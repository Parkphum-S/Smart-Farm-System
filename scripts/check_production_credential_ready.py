from pathlib import Path
import re
import sys

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

EXPECTED_DEVICE_ID = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
EXPECTED_TENANT_ID = "00000000-0000-0000-0000-000000000001"
EXPECTED_DEVICE_CODE = "esp32_001"

def stop(message):
    raise SystemExit(f"STOP: {message}")

# Validate connection target without printing the URL or password.
values = dotenv_values(".env")
raw = values.get("SMARTFARM_MIGRATION_DATABASE_URL")
if not raw:
    stop("migration database URL missing")

url = make_url(raw)
if url.database != "smartfarm" or url.username != "smartfarm_owner":
    stop("unexpected production database or role")

# Inspect secret-file structure in memory; never print its contents.
secret_path = Path("esp32_firmware/secrets.h")
if not secret_path.is_file():
    stop("secrets.h missing")

if secret_path.stat().st_mode & 0o777 != 0o600:
    stop("secrets.h must have permission 600")

contents = secret_path.read_text()
macro_lines = [
    line for line in contents.splitlines()
    if re.match(r'^\s*#\s*define\s+DEVICE_API_KEY\b', line)
]
if len(macro_lines) != 1:
    stop("expected exactly one DEVICE_API_KEY definition")

# Check only the exact target device and credential state.
engine = create_engine(url)
try:
    with engine.connect() as conn:
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
            stop("migration role cannot insert credentials")

        device = conn.execute(text("""
            SELECT d.id::text AS device_id,
                   d.tenant_id::text AS tenant_id,
                   d.device_code,
                   d.status AS device_status,
                   t.status AS tenant_status,
                   COUNT(c.id) FILTER (
                       WHERE c.revoked_at IS NULL
                         AND (c.expires_at IS NULL
                              OR c.expires_at > now())
                   ) AS usable_credentials
            FROM public.devices d
            JOIN public.tenants t ON t.id = d.tenant_id
            LEFT JOIN public.device_credentials c
              ON c.device_id = d.id
             AND c.tenant_id = d.tenant_id
            WHERE d.id = CAST(:device_id AS uuid)
            GROUP BY d.id, d.tenant_id, d.device_code,
                     d.status, t.status
        """), {"device_id": EXPECTED_DEVICE_ID}).mappings().one_or_none()

        if device is None:
            stop("expected device not found")
        if device["device_id"] != EXPECTED_DEVICE_ID:
            stop("device ID mismatch")
        if device["tenant_id"] != EXPECTED_TENANT_ID:
            stop("tenant ID mismatch")
        if device["device_code"] != EXPECTED_DEVICE_CODE:
            stop("device code mismatch")
        if device["device_status"] != "active":
            stop("device is not active")
        if device["tenant_status"] != "active":
            stop("tenant is not active")
        if device["usable_credentials"] != 1:
            stop("expected exactly one existing usable credential")

        print("Preflight: PASS")
        print("Database: smartfarm")
        print("Role: smartfarm_owner")
        print("Target device: esp32_001")
        print("Device and tenant: active")
        print("Existing usable credentials: 1 (will be preserved)")
        print("Secret file: permission 600; one API-key definition")
        print("Database writes: none")
        print("Secret-file changes: none")
finally:
    engine.dispose()
