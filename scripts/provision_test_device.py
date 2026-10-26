"""Provision the ESP32 test device in smartfarm_test only."""

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

SENSORS = [
    {
        "id": UUID("123e4567-e89b-12d3-a456-426614174001"),
        "sensor_code": "temperature",
        "measurement_type": "temperature",
        "unit": "celsius",
    },
    {
        "id": UUID("123e4567-e89b-12d3-a456-426614174002"),
        "sensor_code": "humidity",
        "measurement_type": "humidity",
        "unit": "percent",
    },
    {
        "id": UUID("123e4567-e89b-12d3-a456-426614174003"),
        "sensor_code": "soil_moisture",
        "measurement_type": "soil_moisture",
        "unit": "percent",
    },
]


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

    tenant_id = uuid4()
    credential_id = uuid4()
    device_code = "ESP32-TEST-001"
    tenant_name = "Smart Farm Test"

    print("Target database: smartfarm_test")
    print(f"Tenant name: {tenant_name}")
    print(f"Device code: {device_code}")
    print(f"Device ID: {DEVICE_ID}")
    print("Sensors: temperature, humidity, soil_moisture")
    print()
    print("This operation will create a tenant, device, 3 sensors,")
    print("and a device credential in smartfarm_test.")
    print("It will not modify firmware or the .env file.")
    confirmation = input("Type CREATE to proceed: ").strip()
    if confirmation != "CREATE":
        print("Cancelled; no database changes made.")
        return 0

    token, token_hash = generate_device_token()
    engine = create_engine(url, pool_pre_ping=True)

    try:
        with engine.begin() as conn:
            db_name = conn.execute(
                text("SELECT current_database()")
            ).scalar_one()

            if db_name != "smartfarm_test":
                raise RuntimeError("Unexpected database")

            existing_device = conn.execute(
                text("""
                    SELECT 1 FROM public.devices
                    WHERE id = :device_id
                """),
                {"device_id": DEVICE_ID},
            ).first()

            existing_sensors = conn.execute(
                text("""
                    SELECT id FROM public.sensors
                    WHERE id = ANY(CAST(:sensor_ids AS uuid[]))
                """),
                {"sensor_ids": [str(sensor["id"]) for sensor in SENSORS]},
            ).fetchall()

            existing_code = conn.execute(
                text("""
                    SELECT 1 FROM public.devices
                    WHERE device_code = :device_code
                """),
                {"device_code": device_code},
            ).first()

            if existing_device or existing_sensors or existing_code:
                raise RuntimeError(
                    "Device UUID, sensor UUID, or device code already exists"
                )

            conn.execute(
                text("""
                    INSERT INTO public.tenants (id, name, status)
                    VALUES (:id, :name, 'active')
                """),
                {"id": tenant_id, "name": tenant_name},
            )

            conn.execute(
                text("""
                    INSERT INTO public.devices
                        (id, tenant_id, device_code, device_type, name, status)
                    VALUES
                        (:id, :tenant_id, :device_code, 'esp32',
                         'ESP32 Test Device', 'active')
                """),
                {
                    "id": DEVICE_ID,
                    "tenant_id": tenant_id,
                    "device_code": device_code,
                },
            )

            for sensor in SENSORS:
                conn.execute(
                    text("""
                        INSERT INTO public.sensors
                            (id, tenant_id, device_id, sensor_code,
                             measurement_type, unit, status)
                        VALUES
                            (:id, :tenant_id, :device_id, :sensor_code,
                             :measurement_type, :unit, 'active')
                    """),
                    {
                        **sensor,
                        "tenant_id": tenant_id,
                        "device_id": DEVICE_ID,
                    },
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
                    "tenant_id": tenant_id,
                    "device_id": DEVICE_ID,
                    "secret_hash": token_hash,
                },
            )

        print("\nProvisioning successful.")
        print(f"Tenant ID: {tenant_id}")
        print(f"Device ID: {DEVICE_ID}")
        print("Device token (shown once; store it securely):")
        print(token)
        print("\nOnly the token hash was stored in the database.")
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
            f"ERROR: Provisioning failed ({type(exc).__name__}); "
            "transaction rolled back.",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
