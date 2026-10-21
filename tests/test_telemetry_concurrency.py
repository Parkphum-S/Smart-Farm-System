import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.db.session import SessionLocal, engine
from app.schemas.telemetry import SensorReading, TelemetryEvent
from app.security.device_auth import DeviceIdentity
from app.services.telemetry import ingest_telemetry


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
def seeded(owner_engine):
    tenant_id, device_id, sensor_id = uuid4(), uuid4(), uuid4()

    with owner_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tenants (id, name, status) "
                 "VALUES (:id, 'Concurrency Test', 'active')"),
            {"id": tenant_id},
        )
        conn.execute(
            text(
                "INSERT INTO devices "
                "(id, tenant_id, device_code, device_type, name, status) "
                "VALUES (:id, :tenant, :code, 'test', 'Concurrency Device', 'active')"
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

    identity = DeviceIdentity(tenant_id=tenant_id, device_id=device_id)

    def make_event(event_id, value=25.5):
        return TelemetryEvent(
            event_id=event_id,
            device_id=device_id,
            observed_at=datetime.now(timezone.utc),
            readings=[
                SensorReading(
                    sensor_id=sensor_id,
                    metric="temperature",
                    value=value,
                    unit="C",
                )
            ],
        )

    yield owner_engine, identity, make_event

    with owner_engine.begin() as conn:
        for table in (
            "sensor_readings",
            "telemetry_events",
            "sensors",
            "devices",
        ):
            conn.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :id"),
                {"id": tenant_id},
            )
        conn.execute(
            text("DELETE FROM tenants WHERE id = :id"),
            {"id": tenant_id},
        )


THREADS = 5


def _ingest_in_thread(identity, event, barrier):
    barrier.wait(timeout=10)
    with SessionLocal.begin() as db:
        return ingest_telemetry(db, identity, event).duplicate


def test_concurrent_same_event_inserts_once(seeded):
    owner, identity, make_event = seeded
    event = make_event(uuid4())
    barrier = Barrier(THREADS)

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = [
            pool.submit(_ingest_in_thread, identity, event, barrier)
            for _ in range(THREADS)
        ]
        results = [f.result(timeout=30) for f in futures]

    assert results.count(False) == 1
    assert results.count(True) == THREADS - 1

    with owner.connect() as conn:
        events = conn.execute(
            text("SELECT count(*) FROM telemetry_events "
                 "WHERE device_id = :d AND event_id = :e"),
            {"d": identity.device_id, "e": event.event_id},
        ).scalar_one()
        readings = conn.execute(
            text("SELECT count(*) FROM sensor_readings "
                 "WHERE tenant_id = :t"),
            {"t": identity.tenant_id},
        ).scalar_one()
    assert events == 1
    assert readings == 1
