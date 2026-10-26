from pathlib import Path
import argparse
import os
import re
import stat
import tempfile
import uuid
import sys

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.security.device_auth import generate_device_token, hash_device_token
from app.security.secret_file_recovery import (
    SecretRecoveryRequired,
    install_prepared_secret,
    verify_secret_file,
)

DEVICE_ID = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
TENANT_ID = "00000000-0000-0000-0000-000000000001"
DEVICE_CODE = "esp32_001"
SECRET_PATH = Path("esp32_firmware/secrets.h")


def stop(message):
    raise SystemExit(f"STOP: {message}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Provision a production device token safely."
    )
    parser.add_argument(
        "--recover-two-usable-credentials",
        action="store_true",
        help=(
            "Explicit recovery mode: proceed only when exactly two "
            "usable credentials already exist for the target device."
        ),
    )
    args = parser.parse_args([] if argv is None else argv)
    expected_usable_credentials = (
        2 if args.recover_two_usable_credentials else 1
    )

    # Verify production target without displaying connection details.
    raw = dotenv_values(".env").get("SMARTFARM_MIGRATION_DATABASE_URL")
    if not raw:
        stop("migration database URL missing")

    url = make_url(raw)
    if url.database != "smartfarm" or url.username != "smartfarm_owner":
        stop("unexpected database or role")

    if not SECRET_PATH.is_file():
        stop("secrets.h missing")

    st = SECRET_PATH.stat()
    if stat.S_IMODE(st.st_mode) != 0o600:
        stop("secrets.h must have permission 600")
    if st.st_uid != os.getuid():
        stop("secrets.h must be owned by the current user")

    original = SECRET_PATH.read_bytes()
    try:
        source = original.decode("utf-8")
    except UnicodeDecodeError:
        stop("secrets.h is not valid UTF-8")

    lines = source.splitlines(keepends=True)
    matches = [
        i for i, line in enumerate(lines)
        if re.match(r"^\s*#\s*define\s+DEVICE_API_KEY\b", line)
    ]
    if len(matches) != 1:
        stop("expected exactly one DEVICE_API_KEY definition")

    index = matches[0]
    match = re.fullmatch(
        r'(?P<prefix>\s*#\s*define\s+DEVICE_API_KEY\s+)'
        r'"(?P<value>(?:[^"\\]|\\.)*)"(?P<suffix>\s*(?:\r?\n)?)',
        lines[index],
    )
    if not match:
        stop("unexpected API-key definition format")

    engine = create_engine(url, pool_pre_ping=True)
    temp_path = None
    preserve_temp_for_recovery = False
    try:
        # Transaction remains open while file replacement is prepared.
        with engine.connect() as conn:
            tx = conn.begin()
            try:
                identity = conn.execute(text("""
                    SELECT current_database() AS db,
                           current_user AS role,
                           has_table_privilege(
                               current_user,
                               'public.device_credentials',
                               'INSERT'
                           ) AS can_insert
                """)).mappings().one()

                if identity["db"] != "smartfarm":
                    stop("database identity mismatch")
                if identity["role"] != "smartfarm_owner":
                    stop("database role mismatch")
                if not identity["can_insert"]:
                    stop("INSERT privilege missing")

                device = conn.execute(text("""
                    SELECT d.id::text AS device_id,
                           d.tenant_id::text AS tenant_id,
                           d.device_code,
                           d.status AS device_status,
                           t.status AS tenant_status
                    FROM public.devices d
                    JOIN public.tenants t ON t.id = d.tenant_id
                    WHERE d.id = CAST(:device_id AS uuid)
                    FOR UPDATE OF d
                """), {"device_id": DEVICE_ID}).mappings().one_or_none()

                if device is None:
                    stop("target device not found")
                if device["device_id"] != DEVICE_ID:
                    stop("device ID mismatch")
                if device["tenant_id"] != TENANT_ID:
                    stop("tenant ID mismatch")
                if device["device_code"] != DEVICE_CODE:
                    stop("device code mismatch")
                if device["device_status"] != "active":
                    stop("device is not active")
                if device["tenant_status"] != "active":
                    stop("tenant is not active")
                usable_credentials = conn.execute(text("""
                    SELECT COUNT(*) AS n
                    FROM public.device_credentials
                    WHERE device_id = CAST(:device_id AS uuid)
                      AND tenant_id = CAST(:tenant_id AS uuid)
                      AND revoked_at IS NULL
                      AND (expires_at IS NULL OR expires_at > now())
                """), {
                    "device_id": DEVICE_ID,
                    "tenant_id": TENANT_ID,
                }).mappings().one()["n"]

                if usable_credentials != expected_usable_credentials:
                    if args.recover_two_usable_credentials:
                        stop(
                            "recovery mode requires exactly two existing "
                            "usable credentials; no credential was inserted"
                        )
                    stop(
                        "expected exactly one existing usable credential; "
                        "recovery mode requires explicit authorization"
                    )

                token, secret_hash = generate_device_token()
                if hash_device_token(token) != secret_hash:
                    stop("token hash self-check failed")

                new_line = (
                    match.group("prefix")
                    + '"' + token + '"'
                    + match.group("suffix")
                )
                updated_lines = list(lines)
                updated_lines[index] = new_line
                replacement = "".join(updated_lines).encode("utf-8")

                # Create a same-directory temporary file with restrictive mode.
                fd, temp_name = tempfile.mkstemp(
                    prefix=".secrets.h.", dir=str(SECRET_PATH.parent)
                )
                temp_path = Path(temp_name)
                try:
                    os.fchmod(fd, 0o600)
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(replacement)
                        handle.flush()
                        os.fsync(handle.fileno())
                except Exception:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    raise

                # Insert only the hash. The original credential is not revoked.
                credential_id = uuid.uuid4()
                conn.execute(text("""
                    INSERT INTO public.device_credentials
                        (id, tenant_id, device_id, secret_hash,
                         expires_at, revoked_at)
                    VALUES
                        (:id, CAST(:tenant_id AS uuid),
                         CAST(:device_id AS uuid), :secret_hash,
                         NULL, NULL)
                """), {
                    "id": str(credential_id),
                    "tenant_id": TENANT_ID,
                    "device_id": DEVICE_ID,
                    "secret_hash": secret_hash,
                })

                # Commit DB before replacing secrets.h.
                # If commit fails or is ambiguous, keep the original file and stop.
                try:
                    tx.commit()
                except Exception:
                    # The database outcome may be ambiguous. Preserve the recovery
                    # file and require read-only verification before any retry.
                    preserve_temp_for_recovery = True
                    stop(
                        "commit outcome requires read-only verification; "
                        f"credential ID {credential_id}; "
                        f"recovery file retained as {temp_path.name}; "
                        "do not rerun provisioning yet"
                    )

                # Preserve the old secret until install and verification pass.
                try:
                    backup_path = install_prepared_secret(
                        temp_path, SECRET_PATH
                    )
                    temp_path = None
                except SecretRecoveryRequired as exc:
                    preserve_temp_for_recovery = True
                    recovery_name = (
                        exc.recovery_path.name
                        if exc.recovery_path is not None
                        else "unavailable"
                    )
                    stop(
                        "credential may be committed; secret installation "
                        "or directory sync failed; preserve recovery file "
                        f"{recovery_name}; do not rerun provisioning"
                    )
                except OSError as exc:
                    preserve_temp_for_recovery = True
                    stop(
                        "credential may be committed; backup or installation "
                        f"failed ({type(exc).__name__}); "
                        f"prepared file {temp_path.name}; "
                        "do not rerun provisioning"
                    )

                if not verify_secret_file(
                    SECRET_PATH, secret_hash, hash_device_token
                ):
                    stop(
                        "credential may be committed; secret verification "
                        f"failed; preserve backup {backup_path.name}; "
                        "do not rerun provisioning"
                    )

                # Only remove the previous secret after verification succeeds.
                backup_path.unlink()

                print("Provisioning: PASS")
                print("Database: smartfarm")
                print("Device: esp32_001")
                print("New credential inserted; old credential preserved")
                if args.recover_two_usable_credentials:
                    print("Explicit two-credential recovery mode used")
                print("Database stores only the token hash")
                print("Secret file updated with permission 600")
                print("Token and hash were not displayed")
                print("Firmware was not flashed; relays were not changed")

            except BaseException:
                if tx.is_active:
                    tx.rollback()
                raise
    finally:
        if temp_path is not None and not preserve_temp_for_recovery:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        engine.dispose()


if __name__ == "__main__":
    main(sys.argv[1:])
