"""Rotate the ESP32 test token in smartfarm_test only."""

import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app.security.device_auth import generate_device_token


DEVICE_ID = UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11")


def main() -> int:
    load_dotenv(".env")
    raw_url = os.environ.get("SMARTFARM_MIGRATION_DATABASE_URL")

    if not raw_url:
        print("ERROR: Migration database URL is not configured.", file=sys.stderr)
        return 1

    try:
        url = make_url(raw_url).set(database="smartfarm_test")
    except Exception:
        print("ERROR: Invalid database URL configuration.", file=sys.stderr)
        return 1

    if url.database != "smartfarm_test":
        print("ERROR: Refusing unexpected database.", file=sys.stderr)
        return 1

    print("Target database: smartfarm_test")
    print(f"Device ID: {DEVICE_ID}")
    print("This will revoke existing credentials for this test device")
    print("and create one replacement credential.")
    if input("Type ROTATE to proceed: ").strip() != "ROTATE":
        print("Cancelled; no database changes made.")
        return 0

    token, token_hash = generate_device_token()
    credential_id = uuid4()
    engine = create_engine(url, pool_pre_ping=True)

    try:
        with engine.begin() as conn:
            db_name, role = conn.execute(
                text("SELECT current_database(), current_user")
            ).one()

            if db_name != "smartfarm_test":
                raise RuntimeError("Unexpected database")
            if role != "smartfarm_owner":
                raise RuntimeError("Unexpected database role")

            device = conn.execute(
                text("""
                    SELECT d.tenant_id
                    FROM public.devices AS d
                    JOIN public.tenants AS t ON t.id = d.tenant_id
                    WHERE d.id = :device_id
                      AND d.status = 'active'
                      AND t.status = 'active'
                    FOR UPDATE OF d
                """),
                {"device_id": DEVICE_ID},
            ).mappings().first()

            if device is None:
                raise RuntimeError(
                    "Active test device and tenant were not found"
                )

            credential_count = conn.execute(
                text("""
                    SELECT count(*)
                    FROM public.device_credentials
                    WHERE device_id = :device_id
                """),
                {"device_id": DEVICE_ID},
            ).scalar_one()

            if credential_count < 1:
                raise RuntimeError(
                    "No existing credential found; refusing rotation"
                )

            conn.execute(
                text("""
                    UPDATE public.device_credentials
                    SET revoked_at = CURRENT_TIMESTAMP
                    WHERE device_id = :device_id
                      AND revoked_at IS NULL
                """),
                {"device_id": DEVICE_ID},
            )

            conn.execute(
                text("""
                    INSERT INTO public.device_credentials
                        (id, tenant_id, device_id, secret_hash)
                    VALUES
                        (:id, :tenant_id, :device_id, :secret_hash)
                """),
                {
                    "id": credential_id,
                    "tenant_id": device["tenant_id"],
                    "device_id": DEVICE_ID,
                    "secret_hash": token_hash,
                },
            )

        print("\nToken rotation successful.")
        print(f"New credential ID: {credential_id}")
        print("New device token (shown once; store securely):")
        print(token)
        print("Only its SHA-256 hash was stored in the database.")
        print("Do not paste the token into chat or commit it to Git.")
        return 0

    except IntegrityError:
        print(
            "ERROR: Database constraint failed; transaction rolled back.",
            file=sys.stderr,
        )
        return 1
    except RuntimeError as exc:
        print(f"ERROR: {exc}; transaction rolled back.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"ERROR: Rotation failed ({type(exc).__name__}); "
            "transaction rolled back.",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
