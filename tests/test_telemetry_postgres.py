import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.db.session import SessionLocal, engine
from app.schemas.telemetry import SensorReading, TelemetryEvent
from app.security.device_auth import DeviceIdentity
from app.services.telemetry import EventConflict, ingest_telemetry


@pytest.fixture(scope="module")
def owner_engine():
    from dotenv import load_dotenv

    load_dotenv(".env")
    url = make_url(os.environ["SMARTFARM_MIGRATION_DATABASE_URL"])
    assert url.database == "smartfarm", "Unexpected migration DB target"
    test_url = url.set(database="smartfarm_test")
    db_engine = create_engine(test_url, pool_pre_ping=True)
    try:
        yield db_engine
    finally:
        db_engine.dispose()


@pytest.fixture(autouse=True)
def require_test_database():
    with engine.connect() as conn:
        db, role = conn.execute(
            text("SELECT current_database(), current_user")
        ).one()
    assert db == "smartfarm_test", f"Unsafe test database: {db}"
    assert role == "smartfarm_app", f"Unexpected runtime role: {role}"


@pytest.fixture
def farm_device_sensor(owner_engine):
    tenant_id, device_id, sensor_id = uuid4(), uuid4(), uuid4()
    sensor_id_2 = uuid4()

    with owner_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tenants (id, name, status) "
                 "VALUES (:id, 'Integration Test', 'active')"),
            {"id": tenant_id},
        )
        conn.execute(
            text(
                "INSERT INTO devices "
                "(id, tenant_id, device_code, device_type, name, status) "
                "VALUES (:id, :tenant, :code, 'test', 'Integration Device', 'active')"
            ),
            {"id": device_id, "tenant": tenant_id, "code": str(device_id)},
        )
        conn.execute(
            text(
                "INSERT INTO sensors "
                "(id, tenant_id, device_id, sensor_code, measurement_type, unit, status) "
                "VALUES (:id, :tenant, :device, :code, 'temperature', 'C', 'active')"
            ),
            {
                "id": sensor_id,
                "tenant": tenant_id,
                "device": device_id,
                "code": str(sensor_id),
            },
        )
        conn.execute(
            text(
                "INSERT INTO sensors "
                "(id, tenant_id, device_id, sensor_code, measurement_type, unit, status) "
                "VALUES (:id, :tenant, :device, :code, 'temperature', 'C', 'active')"
            ),
            {
                "id": sensor_id_2,
                "tenant": tenant_id,
                "device": device_id,
                "code": str(sensor_id_2),
            },
        )

    identity = DeviceIdentity(tenant_id=tenant_id, device_id=device_id)

    def make_event(value=25.5, event_id=None, values=None):
        sensor_ids = [sensor_id, sensor_id_2]
        readings = [
            SensorReading(
                sensor_id=sensor_ids[i],
                metric="temperature",
                value=v,
                unit="C",
            )
            for i, v in enumerate(values if values is not None else [value])
        ]
        return TelemetryEvent(
            event_id=event_id or uuid4(),
            device_id=device_id,
            observed_at=datetime.now(timezone.utc),
            readings=readings,
        )

    yield owner_engine, identity, make_event

    with owner_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM sensor_readings WHERE tenant_id = :id"),
            {"id": tenant_id},
        )
        conn.execute(
            text("DELETE FROM telemetry_events WHERE tenant_id = :id"),
            {"id": tenant_id},
        )
        conn.execute(
            text("DELETE FROM sensors WHERE tenant_id = :id"),
            {"id": tenant_id},
        )
        conn.execute(
            text("DELETE FROM devices WHERE tenant_id = :id"),
            {"id": tenant_id},
        )
        conn.execute(
            text("DELETE FROM tenants WHERE id = :id"),
            {"id": tenant_id},
        )


def test_persist_and_idempotent_retry(farm_device_sensor):
    owner, identity, make_event = farm_device_sensor
    event = make_event()

    with SessionLocal.begin() as db:
        first = ingest_telemetry(db, identity, event)

    assert first.duplicate is False

    with SessionLocal.begin() as db:
        retry = ingest_telemetry(db, identity, event)

    assert retry.duplicate is True
    assert retry.event_record_id == first.event_record_id

    with owner.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM telemetry_events WHERE id = :id"),
            {"id": first.event_record_id},
        ).scalar_one() == 1
        assert conn.execute(
            text("SELECT count(*) FROM sensor_readings WHERE telemetry_event_id = :id"),
            {"id": first.event_record_id},
        ).scalar_one() == 1


def test_same_event_id_different_payload_is_rejected(farm_device_sensor):
    _, identity, make_event = farm_device_sensor
    event = make_event()

    with SessionLocal.begin() as db:
        ingest_telemetry(db, identity, event)

    changed = make_event(value=26.5, event_id=event.event_id)
    with pytest.raises(EventConflict):
        with SessionLocal.begin() as db:
            ingest_telemetry(db, identity, changed)


def test_database_error_rolls_back_event_and_readings(farm_device_sensor):
    owner, identity, make_event = farm_device_sensor
    event = make_event(values=[25.5, 1e30])

    with pytest.raises(DBAPIError):
        with SessionLocal.begin() as db:
            ingest_telemetry(db, identity, event)

    with owner.connect() as conn:
        assert conn.execute(
            text(
                "SELECT count(*) FROM telemetry_events "
                "WHERE device_id = :device AND event_id = :event"
            ),
            {"device": identity.device_id, "event": event.event_id},
        ).scalar_one() == 0
        assert conn.execute(
            text("SELECT count(*) FROM sensor_readings WHERE tenant_id = :tenant"),
            {"tenant": identity.tenant_id},
        ).scalar_one() == 0
