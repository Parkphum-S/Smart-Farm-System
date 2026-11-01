from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.integrations.zigbee.discovery import ZigbeeDiscoveredDevice
from app.integrations.zigbee.mapping import (
    ZigbeeMappingError,
    ZigbeeSensorBinding,
)
from app.integrations.zigbee import service
from app.security.device_auth import DeviceIdentity


@pytest.fixture
def context():
    identity = DeviceIdentity(
        tenant_id=uuid4(),
        device_id=uuid4(),
    )
    device = ZigbeeDiscoveredDevice(
        friendly_name="sensor_01",
        ieee_address="00124b0000000001",
    )
    temperature_id = uuid4()
    humidity_id = uuid4()

    return {
        "identity": identity,
        "device": device,
        "temperature_id": temperature_id,
        "humidity_id": humidity_id,
        "bindings": [
            ZigbeeSensorBinding(
                metric="air_temperature",
                unit="Cel",
                endpoint_key="temperature",
            ),
            ZigbeeSensorBinding(
                metric="air_humidity",
                unit="%",
                endpoint_key="humidity",
            ),
        ],
    }


def test_processes_and_ingests_state_message(monkeypatch, context):
    resolved_calls = []
    ingested = []

    def fake_resolve(db, *, tenant_id, device_id, bindings):
        resolved_calls.append((tenant_id, device_id, bindings))
        return {
            "air_temperature": context["temperature_id"],
            "air_humidity": context["humidity_id"],
        }

    def fake_ingest(db, identity, event):
        ingested.append((identity, event))
        return "ingested"

    monkeypatch.setattr(service, "resolve_sensor_bindings", fake_resolve)
    monkeypatch.setattr(service, "ingest_telemetry", fake_ingest)

    result = service.process_state_message(
        object(),
        identity=context["identity"],
        topic="zigbee2mqtt/sensor_01",
        payload={"temperature": 28.5, "humidity": 72},
        devices_by_friendly_name={"sensor_01": context["device"]},
        bindings=context["bindings"],
        event_id=uuid4(),
        observed_at=datetime.now(timezone.utc),
    )

    assert result == "ingested"
    assert len(resolved_calls) == 1
    assert resolved_calls[0][0] == context["identity"].tenant_id
    assert resolved_calls[0][1] == context["identity"].device_id

    identity, event = ingested[0]
    assert identity == context["identity"]
    assert event.device_id == context["identity"].device_id
    assert len(event.readings) == 2


def test_rejects_missing_configured_binding(monkeypatch, context):
    def unexpected_resolve(*args, **kwargs):
        pytest.fail("mapping resolver must not run")

    monkeypatch.setattr(service, "resolve_sensor_bindings", unexpected_resolve)

    with pytest.raises(ZigbeeMappingError, match="missing configured"):
        service.process_state_message(
            object(),
            identity=context["identity"],
            topic="zigbee2mqtt/sensor_01",
            payload={"temperature": 28.5},
            devices_by_friendly_name={"sensor_01": context["device"]},
            bindings=[],
            event_id=uuid4(),
            observed_at=datetime.now(timezone.utc),
        )


def test_rejects_duplicate_configured_metric(context):
    duplicate_bindings = context["bindings"] + [
        ZigbeeSensorBinding(
            metric="air_temperature",
            unit="Cel",
            endpoint_key="temperature_2",
        )
    ]

    with pytest.raises(service.ZigbeeServiceError, match="duplicate configured"):
        service.process_state_message(
            object(),
            identity=context["identity"],
            topic="zigbee2mqtt/sensor_01",
            payload={"temperature": 28.5},
            devices_by_friendly_name={"sensor_01": context["device"]},
            bindings=duplicate_bindings,
            event_id=uuid4(),
            observed_at=datetime.now(timezone.utc),
        )


def test_rejects_state_without_supported_measurements(context):
    with pytest.raises(service.ZigbeeServiceError, match="no supported"):
        service.process_state_message(
            object(),
            identity=context["identity"],
            topic="zigbee2mqtt/sensor_01",
            payload={"battery": 95, "linkquality": 120},
            devices_by_friendly_name={"sensor_01": context["device"]},
            bindings=context["bindings"],
            event_id=uuid4(),
            observed_at=datetime.now(timezone.utc),
        )



def test_registered_measurements_resolve_and_ingest(monkeypatch, context):
    from app.integrations.zigbee.clusters import NormalizedMeasurement

    calls = []
    measurements = [
        NormalizedMeasurement("air_temperature", 28.5, "Cel"),
        NormalizedMeasurement("air_humidity", 72.0, "%"),
    ]

    def fake_identity(db, *, ieee_address):
        calls.append(("identity", ieee_address))
        return context["identity"]

    def fake_load(db, *, tenant_id, device_id):
        calls.append(("load", tenant_id, device_id))
        return context["bindings"]

    def fake_resolve(db, *, tenant_id, device_id, bindings):
        calls.append(("resolve", tenant_id, device_id, bindings))
        return {
            "air_temperature": context["temperature_id"],
            "air_humidity": context["humidity_id"],
        }

    def fake_ingest(db, identity, event):
        calls.append(("ingest", identity, event))
        return "ingested"

    monkeypatch.setattr(
        "app.integrations.zigbee.registration.resolve_device_identity",
        fake_identity,
    )
    monkeypatch.setattr(
        "app.integrations.zigbee.mapping.load_sensor_bindings",
        fake_load,
    )
    monkeypatch.setattr(service, "resolve_sensor_bindings", fake_resolve)
    monkeypatch.setattr(service, "ingest_telemetry", fake_ingest)

    event_id = uuid4()
    observed_at = datetime.now(timezone.utc)

    result = service.process_registered_measurements(
        object(),
        ieee_address=context["device"].ieee_address,
        measurements=measurements,
        event_id=event_id,
        observed_at=observed_at,
    )

    assert result == "ingested"
    assert [call[0] for call in calls] == [
        "identity", "load", "resolve", "ingest"
    ]
    assert calls[0][1] == context["device"].ieee_address

    identity, event = calls[-1][1], calls[-1][2]
    assert identity == context["identity"]
    assert event.event_id == event_id
    assert event.device_id == context["identity"].device_id
    assert event.observed_at == observed_at
    assert len(event.readings) == 2


def test_registered_measurements_reject_unregistered_ieee(monkeypatch, context):
    from app.integrations.zigbee.registration import ZigbeeRegistrationError

    def reject_identity(db, *, ieee_address):
        raise ZigbeeRegistrationError("unregistered")

    def unexpected_load(*args, **kwargs):
        pytest.fail("sensor mappings must not load for an unregistered device")

    monkeypatch.setattr(
        "app.integrations.zigbee.registration.resolve_device_identity",
        reject_identity,
    )
    monkeypatch.setattr(
        "app.integrations.zigbee.mapping.load_sensor_bindings",
        unexpected_load,
    )

    with pytest.raises(ZigbeeRegistrationError, match="unregistered"):
        service.process_registered_measurements(
            object(),
            ieee_address=context["device"].ieee_address,
            measurements=[],
            event_id=uuid4(),
            observed_at=datetime.now(timezone.utc),
        )


def test_registered_measurements_reject_missing_metric_mapping(
    monkeypatch, context
):
    from app.integrations.zigbee.clusters import NormalizedMeasurement

    monkeypatch.setattr(
        "app.integrations.zigbee.registration.resolve_device_identity",
        lambda db, *, ieee_address: context["identity"],
    )
    monkeypatch.setattr(
        "app.integrations.zigbee.mapping.load_sensor_bindings",
        lambda db, *, tenant_id, device_id: context["bindings"][:1],
    )

    def unexpected_resolve(*args, **kwargs):
        pytest.fail("resolver must not run when a metric mapping is missing")

    monkeypatch.setattr(service, "resolve_sensor_bindings", unexpected_resolve)

    with pytest.raises(ZigbeeMappingError, match="missing configured"):
        service.process_registered_measurements(
            object(),
            ieee_address=context["device"].ieee_address,
            measurements=[
                NormalizedMeasurement("air_humidity", 70.0, "%")
            ],
            event_id=uuid4(),
            observed_at=datetime.now(timezone.utc),
        )
