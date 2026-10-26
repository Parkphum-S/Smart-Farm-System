import os
from uuid import UUID

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

DEVICE_ID = UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11")
TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")

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


def main():
    env = dotenv_values(".env")
    raw_url = (
        os.environ.get("SMARTFARM_MIGRATION_DATABASE_URL")
        or env.get("SMARTFARM_MIGRATION_DATABASE_URL")
    )
    if not raw_url:
        raise SystemExit("STOP: migration database URL is not configured")

    url = make_url(raw_url)
    if url.database != "smartfarm" or url.username != "smartfarm_owner":
        raise SystemExit("STOP: unexpected database or role")

    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            identity = conn.execute(text("""
                SELECT current_database() AS db, current_user AS role
            """)).mappings().one()
            if identity["db"] != "smartfarm":
                raise RuntimeError("STOP: connected database mismatch")
            if identity["role"] != "smartfarm_owner":
                raise RuntimeError("STOP: connected role mismatch")

            device = conn.execute(
                text("""
                    SELECT id, tenant_id, device_code, status
                    FROM devices
                    WHERE id = :device_id
                      AND device_code = 'esp32_001'
                    FOR UPDATE
                """),
                {"device_id": DEVICE_ID},
            ).mappings().one_or_none()

            if (
                device is None
                or device["tenant_id"] != TENANT_ID
                or device["status"] != "active"
            ):
                raise RuntimeError(
                    "STOP: device identity, tenant, or status mismatch"
                )

            ids = [s["id"] for s in SENSORS]
            codes = [s["sensor_code"] for s in SENSORS]

            existing = conn.execute(
                text("""
                    SELECT id, tenant_id, device_id, sensor_code,
                           measurement_type, unit, status
                    FROM sensors
                    WHERE id = ANY(CAST(:ids AS uuid[]))
                       OR (
                           device_id = :device_id
                           AND sensor_code = ANY(CAST(:codes AS text[]))
                       )
                """),
                {
                    "ids": [str(v) for v in ids],
                    "codes": codes,
                    "device_id": DEVICE_ID,
                },
            ).mappings().all()

            expected_by_id = {s["id"]: s for s in SENSORS}
            matched_codes = set()

            for row in existing:
                expected = expected_by_id.get(row["id"])
                if (
                    expected is None
                    or row["tenant_id"] != TENANT_ID
                    or row["device_id"] != DEVICE_ID
                    or row["sensor_code"] != expected["sensor_code"]
                    or row["measurement_type"] != expected["measurement_type"]
                    or row["unit"] != expected["unit"]
                    or row["status"] != "active"
                ):
                    raise RuntimeError(
                        "STOP: conflicting existing Sensor; no changes committed"
                    )
                matched_codes.add(row["sensor_code"])

            for sensor in SENSORS:
                if sensor["sensor_code"] in matched_codes:
                    continue
                conn.execute(
                    text("""
                        INSERT INTO sensors (
                            id, tenant_id, device_id, sensor_code,
                            measurement_type, unit, status
                        )
                        VALUES (
                            :id, :tenant_id, :device_id, :sensor_code,
                            :measurement_type, :unit, 'active'
                        )
                    """),
                    {
                        **sensor,
                        "tenant_id": TENANT_ID,
                        "device_id": DEVICE_ID,
                    },
                )

            verified = conn.execute(
                text("""
                    SELECT id, sensor_code, measurement_type, unit, status
                    FROM sensors
                    WHERE tenant_id = :tenant_id
                      AND device_id = :device_id
                    ORDER BY sensor_code
                """),
                {"tenant_id": TENANT_ID, "device_id": DEVICE_ID},
            ).mappings().all()

            actual = {
                (r["id"], r["sensor_code"], r["measurement_type"],
                 r["unit"], r["status"])
                for r in verified
            }
            expected = {
                (s["id"], s["sensor_code"], s["measurement_type"],
                 s["unit"], "active")
                for s in SENSORS
            }

            if actual != expected:
                raise RuntimeError(
                    "Verification failed; transaction will be rolled back"
                )

        print("Provisioning: PASS")
        print("Database: smartfarm")
        print("Device: esp32_001")
        print("Verified active sensors: 3")
        for sensor in SENSORS:
            print(
                f"- {sensor['sensor_code']}: "
                f"{sensor['measurement_type']} ({sensor['unit']})"
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
