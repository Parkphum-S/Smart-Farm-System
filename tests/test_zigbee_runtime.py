import json
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.integrations.zigbee.runtime import build_zigbee_runtime


DISCOVERY = json.dumps([
    {
        "friendly_name": "greenhouse_sensor",
        "ieee_address": "0x00124b0001abcdef",
        "definition": {
            "model": "TS0601",
            "vendor": "Test Vendor",
        },
        "endpoints": {
            "1": {"clusters": ["msTemperatureMeasurement"]}
        },
    }
]).encode()


class FakeTransport:
    def __init__(self):
        self.connected = False
        self.disconnected = False
        self.subscriptions = []
        self.handlers = {}

    def connect(self):
        self.connected = True

    def subscribe(self, topic, handler):
        self.subscriptions.append(topic)
        self.handlers[topic] = handler

    def loop_forever(self):
        pass

    def stop_loop(self):
        pass

    def disconnect(self):
        self.disconnected = True
        self.connected = False


class FakeSession:
    pass


class SessionContext:
    def __init__(self):
        self.session = FakeSession()
        self.exited_with = None
        self.entered = False

    @contextmanager
    def begin(self):
        self.entered = True
        try:
            yield self.session
        except Exception as exc:
            self.exited_with = exc
            raise


def make_runtime():
    transport = FakeTransport()
    transaction = SessionContext()
    runtime = build_zigbee_runtime(
        transport=transport,
        session_factory=transaction.begin,
        base_topic="/zigbee2mqtt/",
    )
    return runtime, transport, transaction


def publish_discovery(transport):
    transport.handlers["zigbee2mqtt/bridge/devices"](
        "zigbee2mqtt/bridge/devices",
        DISCOVERY,
    )


def test_runtime_wires_router_and_worker():
    runtime, transport, _ = make_runtime()

    assert runtime.router.devices == ()
    runtime.worker.run()

    assert transport.subscriptions == [
        "zigbee2mqtt/bridge/devices",
        "zigbee2mqtt/+",
    ]
    assert transport.disconnected is True


def test_discovery_updates_router_without_database_registration():
    runtime, transport, transaction = make_runtime()
    runtime.worker.run()

    publish_discovery(transport)

    assert len(runtime.router.devices) == 1
    assert runtime.router.devices[0].ieee_address == "00124b0001abcdef"
    assert transaction.entered is False


def test_state_message_uses_transaction_and_registered_telemetry(
    monkeypatch,
):
    import app.integrations.zigbee.runtime as runtime_module

    runtime, transport, transaction = make_runtime()
    calls = []

    def fake_process(db, **kwargs):
        calls.append((db, kwargs))

    monkeypatch.setattr(
        runtime_module,
        "process_registered_measurements",
        fake_process,
    )

    runtime.worker.run()
    publish_discovery(transport)

    transport.handlers["zigbee2mqtt/+"](
        "zigbee2mqtt/greenhouse_sensor",
        b'{"temperature": 28.5, "humidity": 70}',
    )

    assert transaction.entered is True
    assert transaction.exited_with is None
    assert len(calls) == 1

    db, kwargs = calls[0]
    assert db is transaction.session
    assert kwargs["ieee_address"] == "00124b0001abcdef"
    assert kwargs["event_id"].version == 4
    assert isinstance(kwargs["event_id"], UUID)
    assert kwargs["observed_at"].tzinfo == timezone.utc
    assert isinstance(kwargs["observed_at"], datetime)
    assert [
        (item.metric, item.value, item.unit)
        for item in kwargs["measurements"]
    ] == [
        ("air_temperature", 28.5, "Cel"),
        ("air_humidity", 70.0, "%"),
    ]


def test_processing_failure_is_isolated_and_transaction_rolls_back(
    monkeypatch,
):
    import app.integrations.zigbee.runtime as runtime_module

    runtime, transport, transaction = make_runtime()

    def fail_processing(db, **kwargs):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(
        runtime_module,
        "process_registered_measurements",
        fail_processing,
    )

    runtime.worker.run()
    publish_discovery(transport)

    # Worker dispatch must contain callback exceptions.
    transport.handlers["zigbee2mqtt/+"](
        "zigbee2mqtt/greenhouse_sensor",
        b'{"temperature": 28.5}',
    )

    assert transaction.entered is True
    assert isinstance(transaction.exited_with, RuntimeError)
    assert str(transaction.exited_with) == "simulated database failure"


def test_runtime_rejects_empty_base_topic():
    with pytest.raises(ValueError, match="base_topic"):
        build_zigbee_runtime(
            transport=FakeTransport(),
            session_factory=lambda: None,
            base_topic=" / ",
        )
