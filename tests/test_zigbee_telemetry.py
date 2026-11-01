from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.integrations.zigbee.clusters import NormalizedMeasurement
from app.integrations.zigbee.telemetry import (
    ZigbeeTelemetryError,
    build_telemetry_event,
)


@pytest.fixture
def identifiers():
    return {
        "event_id": uuid4(),
        "device_id": uuid4(),
        "temperature_id": uuid4(),
        "humidity_id": uuid4(),
    }


@pytest.fixture
def measurements():
    return [
        NormalizedMeasurement(
            metric="air_temperature",
            value=28.5,
            unit="Cel",
        ),
        NormalizedMeasurement(
            metric="air_humidity",
            value=72.0,
            unit="%",
        ),
    ]


def test_builds_telemetry_event(identifiers, measurements):
    event = build_telemetry_event(
        event_id=identifiers["event_id"],
        device_id=identifiers["device_id"],
        observed_at=datetime.now(timezone.utc),
        measurements=measurements,
        sensor_ids={
            "air_temperature": identifiers["temperature_id"],
            "air_humidity": identifiers["humidity_id"],
        },
    )

    assert event.event_id == identifiers["event_id"]
    assert event.device_id == identifiers["device_id"]
    assert len(event.readings) == 2
    assert event.readings[0].sensor_id == identifiers["temperature_id"]
    assert event.readings[1].sensor_id == identifiers["humidity_id"]


def test_rejects_unmapped_measurement(identifiers, measurements):
    with pytest.raises(ZigbeeTelemetryError, match="no registered sensor"):
        build_telemetry_event(
            event_id=identifiers["event_id"],
            device_id=identifiers["device_id"],
            observed_at=datetime.now(timezone.utc),
            measurements=measurements,
            sensor_ids={
                "air_temperature": identifiers["temperature_id"],
            },
        )


def test_rejects_empty_measurements(identifiers):
    with pytest.raises(ZigbeeTelemetryError, match="at least one"):
        build_telemetry_event(
            event_id=identifiers["event_id"],
            device_id=identifiers["device_id"],
            observed_at=datetime.now(timezone.utc),
            measurements=[],
            sensor_ids={},
        )


def test_rejects_duplicate_metrics(identifiers, measurements):
    duplicated = [measurements[0], measurements[0]]

    with pytest.raises(ZigbeeTelemetryError, match="duplicate measurement"):
        build_telemetry_event(
            event_id=identifiers["event_id"],
            device_id=identifiers["device_id"],
            observed_at=datetime.now(timezone.utc),
            measurements=duplicated,
            sensor_ids={
                "air_temperature": identifiers["temperature_id"],
            },
        )


def test_rejects_duplicate_sensor_ids(identifiers, measurements):
    with pytest.raises(ZigbeeTelemetryError, match="sensor_id values"):
        build_telemetry_event(
            event_id=identifiers["event_id"],
            device_id=identifiers["device_id"],
            observed_at=datetime.now(timezone.utc),
            measurements=measurements,
            sensor_ids={
                "air_temperature": identifiers["temperature_id"],
                "air_humidity": identifiers["temperature_id"],
            },
        )


def test_rejects_naive_datetime(identifiers, measurements):
    with pytest.raises(ZigbeeTelemetryError, match="timezone"):
        build_telemetry_event(
            event_id=identifiers["event_id"],
            device_id=identifiers["device_id"],
            observed_at=datetime(2026, 10, 30, 10, 0, 0),
            measurements=measurements,
            sensor_ids={
                "air_temperature": identifiers["temperature_id"],
                "air_humidity": identifiers["humidity_id"],
            },
        )
