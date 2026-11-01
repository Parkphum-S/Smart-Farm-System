import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db.session import SessionLocal
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




@pytest.fixture(scope="module")
def app_engine():
    from dotenv import load_dotenv

    load_dotenv(".env")
    raw = os.environ.get("SMARTFARM_DATABASE_URL")
    assert raw, "Runtime database URL is not configured"
    url = make_url(raw)
    assert url.database == "smartfarm", "Unexpected runtime DB target"

    test_engine = create_engine(
        url.set(database="smartfarm_test"),
        pool_pre_ping=True,
    )
    try:
        with test_engine.connect() as conn:
            database, role = conn.execute(
                text("SELECT current_database(), current_user")
            ).one()
        assert database == "smartfarm_test", f"Unsafe test database: {database}"
        assert role == "smartfarm_app", f"Unexpected runtime role: {role}"
        yield test_engine
    finally:
        test_engine.dispose()


@pytest.fixture(autouse=True)
def require_test_database(app_engine, monkeypatch):
    with app_engine.connect() as conn:
        database, role = conn.execute(
            text("SELECT current_database(), current_user")
        ).one()
    assert database == "smartfarm_test", f"Unsafe test database: {database}"
    assert role == "smartfarm_app", f"Unexpected runtime role: {role}"


    # Route SessionLocal calls in this test module to the guarded test DB.
    monkeypatch.setitem(
        globals(),
        "SessionLocal",
        sessionmaker(bind=app_engine, autoflush=False, autocommit=False),
    )


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


def _ingest_or_conflict(identity, event, barrier):
    barrier.wait(timeout=10)
    try:
        with SessionLocal.begin() as db:
            return ingest_telemetry(db, identity, event).duplicate
    except EventConflict:
        return "conflict"


def test_concurrent_same_id_different_payload_conflicts(seeded):
    owner, identity, make_event = seeded
    event_id = uuid4()
    events = [
        make_event(event_id, value=25.0 + i) for i in range(THREADS)
    ]
    barrier = Barrier(THREADS)

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = [
            pool.submit(_ingest_or_conflict, identity, ev, barrier)
            for ev in events
        ]
        results = [f.result(timeout=30) for f in futures]

    assert results.count(False) == 1
    assert results.count("conflict") == THREADS - 1

    with owner.connect() as conn:
        n_events = conn.execute(
            text("SELECT count(*) FROM telemetry_events "
                 "WHERE device_id = :d AND event_id = :e"),
            {"d": identity.device_id, "e": event_id},
        ).scalar_one()
        n_readings = conn.execute(
            text("SELECT count(*) FROM sensor_readings "
                 "WHERE tenant_id = :t"),
            {"t": identity.tenant_id},
        ).scalar_one()
    assert n_events == 1
    assert n_readings == 1


def test_sensor_metadata_update_waits_for_ingestion_and_is_rejected(seeded):
    owner, identity, make_event = seeded
    event = make_event(uuid4())

    lock_acquired = Event()
    release_ingestion = Event()
    updater_started = Event()
    updater_finished = Event()

    class PausingSession:
        def __init__(self, session):
            self.session = session

        def execute(self, statement, params=None, *args, **kwargs):
            result = self.session.execute(
                statement, params or {}, *args, **kwargs
            )
            sql = str(statement).upper()

            if "FROM SENSORS" in sql and "FOR SHARE" in sql:
                lock_acquired.set()
                if not release_ingestion.wait(timeout=10):
                    raise TimeoutError(
                        "Timed out waiting to release sensor lock"
                    )

            return result

    def ingest():
        with SessionLocal.begin() as db:
            return ingest_telemetry(
                PausingSession(db), identity, event
            ).duplicate

    def update_metadata():
        updater_started.set()
        try:
            with SessionLocal.begin() as db:
                db.execute(
                    text("""
                        SELECT id
                        FROM sensors
                        WHERE id = :sensor_id
                          AND tenant_id = :tenant_id
                          AND device_id = :device_id
                        FOR UPDATE
                    """),
                    {
                        "sensor_id": event.readings[0].sensor_id,
                        "tenant_id": identity.tenant_id,
                        "device_id": identity.device_id,
                    },
                ).first()

                has_readings = db.execute(
                    text("""
                        SELECT EXISTS (
                            SELECT 1
                            FROM sensor_readings
                            WHERE tenant_id = :tenant_id
                              AND device_id = :device_id
                              AND sensor_id = :sensor_id
                        )
                    """),
                    {
                        "tenant_id": identity.tenant_id,
                        "device_id": identity.device_id,
                        "sensor_id": event.readings[0].sensor_id,
                    },
                ).scalar_one()

                if not has_readings:
                    db.execute(
                        text("""
                            UPDATE sensors
                            SET measurement_type = 'humidity',
                                unit = 'percent'
                            WHERE id = :sensor_id
                              AND tenant_id = :tenant_id
                              AND device_id = :device_id
                        """),
                        {
                            "sensor_id": event.readings[0].sensor_id,
                            "tenant_id": identity.tenant_id,
                            "device_id": identity.device_id,
                        },
                    )

                return not has_readings
        finally:
            updater_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        ingest_future = pool.submit(ingest)
        update_future = None

        try:
            assert lock_acquired.wait(timeout=10), (
                "Telemetry did not acquire the expected sensor FOR SHARE lock"
            )

            update_future = pool.submit(update_metadata)
            assert updater_started.wait(timeout=10)

            assert not updater_finished.wait(timeout=0.25), (
                "Metadata update was not blocked by the telemetry sensor lock"
            )
        finally:
            release_ingestion.set()

        assert ingest_future.result(timeout=30) is False
        assert update_future is not None
        assert update_future.result(timeout=30) is False

    with owner.connect() as conn:
        sensor = conn.execute(
            text("""
                SELECT measurement_type, unit
                FROM sensors
                WHERE id = :sensor_id
            """),
            {"sensor_id": event.readings[0].sensor_id},
        ).one()

        reading = conn.execute(
            text("""
                SELECT measurement_type, unit
                FROM sensor_readings
                WHERE tenant_id = :tenant_id
                  AND sensor_id = :sensor_id
            """),
            {
                "tenant_id": identity.tenant_id,
                "sensor_id": event.readings[0].sensor_id,
            },
        ).one()

    assert sensor == ("temperature", "C")
    assert reading == ("temperature", "C")
