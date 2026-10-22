import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.db.session import SessionLocal, engine
from app.schemas.telemetry import SensorReading, TelemetryEvent
from app.security.device_auth import DeviceIdentity
from app.services.telemetry import EventConflict, ingest_telemetry
from app.services.archive_reader import iter_events, iter_readings
from app.services.archive_bundle import export_telemetry_bundle


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

def test_archive_reader_streams_events_and_readings_read_only(farm_device_sensor):
    _, identity, make_event = farm_device_sensor
    event = make_event(values=[25.5, 26.0])

    with SessionLocal.begin() as db:
        ingested = ingest_telemetry(db, identity, event)

    start_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    end_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as conn:
        with conn.begin():
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            assert conn.exec_driver_sql(
                "SHOW transaction_read_only"
            ).scalar_one() == "on"

            events = [
                row for row in iter_events(conn, start_at, end_at, batch_size=1)
                if row["id"] == ingested.event_record_id
            ]
            readings = [
                row for row in iter_readings(conn, start_at, end_at, batch_size=1)
                if row["telemetry_event_id"] == ingested.event_record_id
            ]

    assert len(events) == 1
    assert events[0]["event_id"] == event.event_id
    assert len(readings) == 2
    assert {float(row["value"]) for row in readings} == {25.5, 26.0}


def test_archive_reader_uses_half_open_event_interval(farm_device_sensor):
    owner, identity, make_event = farm_device_sensor

    events = [
        make_event(values=[25.5, 26.0]),
        make_event(values=[27.0, 28.0]),
        make_event(values=[29.0, 30.0]),
    ]
    ingested = []

    for event in events:
        with SessionLocal.begin() as db:
            ingested.append(ingest_telemetry(db, identity, event))

    start_at = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    middle_at = datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)
    end_at = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)

    timestamps = [start_at, middle_at, end_at]

    with owner.begin() as conn:
        for result, received_at in zip(ingested, timestamps):
            conn.execute(
                text("""
                    UPDATE telemetry_events
                    SET received_at = :received_at
                    WHERE id = :event_record_id
                      AND tenant_id = :tenant_id
                """),
                {
                    "received_at": received_at,
                    "event_record_id": result.event_record_id,
                    "tenant_id": identity.tenant_id,
                },
            )

    expected_event_ids = {
        ingested[0].event_record_id,
        ingested[1].event_record_id,
    }

    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as conn:
        with conn.begin():
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")

            assert conn.exec_driver_sql(
                "SHOW transaction_read_only"
            ).scalar_one() == "on"

            selected_events = list(
                iter_events(conn, start_at, end_at, batch_size=1)
            )
            selected_readings = list(
                iter_readings(conn, start_at, end_at, batch_size=1)
            )

    assert {row["id"] for row in selected_events} == expected_event_ids
    assert len(selected_events) == 2

    assert {
        row["telemetry_event_id"] for row in selected_readings
    } == expected_event_ids
    assert len(selected_readings) == 4



def test_archive_bundle_exports_events_and_readings_postgres(
    farm_device_sensor, tmp_path
):
    import json

    _, identity, make_event = farm_device_sensor
    event = make_event(values=[24.5, 25.0])

    with SessionLocal.begin() as db:
        ingested = ingest_telemetry(db, identity, event)

    start_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    end_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    with engine.connect() as conn:
        assert conn.exec_driver_sql(
            "SELECT current_database()"
        ).scalar_one() == "smartfarm_test"
        # SELECT triggers SQLAlchemy autobegin; end that transaction
        # before the exporter starts its own repeatable-read transaction.
        conn.rollback()

        result = export_telemetry_bundle(
            conn,
            tmp_path,
            start_at,
            end_at,
            batch_size=1,
        )

        # The export must not leave an open transaction or change
        # the connection's original isolation level.
        assert not conn.in_transaction()
        assert conn.get_isolation_level() == "READ COMMITTED"

    bundle_dir = Path(result["bundle_dir"])
    manifest_path = bundle_dir / "bundle.manifest.json"
    assert manifest_path.is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "complete"
    assert manifest["interval"]["semantics"] == "[start_at, end_at)"

    event_rows = [
        json.loads(line)
        for line in (bundle_dir / "events.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line
    ]
    reading_rows = [
        json.loads(line)
        for line in (bundle_dir / "readings.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line
    ]

    matching_events = [
        row for row in event_rows
        if row["id"] == str(ingested.event_record_id)
    ]
    matching_readings = [
        row for row in reading_rows
        if row["telemetry_event_id"] == str(ingested.event_record_id)
    ]

    assert len(matching_events) == 1
    assert len(matching_readings) == 2
    assert manifest["files"]["events"]["record_count"] == len(event_rows)
    assert manifest["files"]["readings"]["record_count"] == len(reading_rows)
