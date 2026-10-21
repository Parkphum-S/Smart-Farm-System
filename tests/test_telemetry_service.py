from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.schemas.telemetry import SensorReading, TelemetryEvent
from app.security.device_auth import DeviceIdentity
from app.services.telemetry import (
    EventConflict,
    TelemetryRejected,
    ingest_telemetry,
)


def scalar_result(value):
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return result


def mapping_result(value):
    result = Mock()
    result.mappings.return_value.first.return_value = value
    return result


def make_event(device_id, sensor_id):
    return TelemetryEvent(
        event_id=uuid4(),
        device_id=device_id,
        observed_at=datetime.now(timezone.utc),
        readings=[
            SensorReading(
                sensor_id=sensor_id,
                metric="temperature",
                value=25.5,
                unit="C",
            )
        ],
    )


def make_identity(device_id=None):
    return DeviceIdentity(
        tenant_id=uuid4(),
        device_id=device_id or uuid4(),
    )


def active_tenant_and_device():
    return [
        scalar_result("active"),
        scalar_result("active"),
    ]


def active_sensor(sensor_id):
    return mapping_result(
        {"measurement_type": "temperature", "unit": "C"}
    )


def test_rejects_event_from_another_device():
    identity = make_identity()
    event = make_event(uuid4(), uuid4())
    db = Mock()

    with pytest.raises(TelemetryRejected):
        ingest_telemetry(db, identity, event)

    db.execute.assert_not_called()


def test_rejects_inactive_tenant():
    identity = make_identity()
    event = make_event(identity.device_id, uuid4())
    db = Mock()
    db.execute.side_effect = [
        scalar_result("suspended"),
    ]

    with pytest.raises(TelemetryRejected):
        ingest_telemetry(db, identity, event)


def test_rejects_sensor_not_owned_by_device_or_inactive():
    identity = make_identity()
    event = make_event(identity.device_id, uuid4())
    db = Mock()
    db.execute.side_effect = [
        *active_tenant_and_device(),
        mapping_result(None),
    ]

    with pytest.raises(TelemetryRejected):
        ingest_telemetry(db, identity, event)


def test_rejects_sensor_metric_or_unit_mismatch():
    identity = make_identity()
    event = make_event(identity.device_id, uuid4())
    db = Mock()
    db.execute.side_effect = [
        *active_tenant_and_device(),
        mapping_result(
            {"measurement_type": "humidity", "unit": "%"}
        ),
    ]

    with pytest.raises(TelemetryRejected):
        ingest_telemetry(db, identity, event)


def test_persists_valid_event_and_reading():
    identity = make_identity()
    sensor_id = uuid4()
    event = make_event(identity.device_id, sensor_id)
    event_record_id = uuid4()
    db = Mock()

    exists_result = Mock()
    exists_result.scalar_one.return_value = True

    db.execute.side_effect = [
        *active_tenant_and_device(),
        active_sensor(sensor_id),
        scalar_result(event_record_id),
        Mock(),
        exists_result,
    ]

    result = ingest_telemetry(db, identity, event)

    assert result.event_record_id == event_record_id
    assert result.duplicate is False
    assert db.execute.call_count == 6


def test_rejects_reused_event_id_with_different_payload():
    identity = make_identity()
    sensor_id = uuid4()
    event = make_event(identity.device_id, sensor_id)
    db = Mock()

    db.execute.side_effect = [
        *active_tenant_and_device(),
        active_sensor(sensor_id),
        scalar_result(None),
        mapping_result(
            {"id": uuid4(), "payload_hash": "0" * 64}
        ),
    ]

    with pytest.raises(EventConflict):
        ingest_telemetry(db, identity, event)
