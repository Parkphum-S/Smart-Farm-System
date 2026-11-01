import json

import pytest

from app.integrations.zigbee.router import (
    ZigbeeMessageRouter,
    ZigbeeRoutingError,
)


def discovery_payload():
    return json.dumps([
        {
            "friendly_name": "greenhouse_sensor",
            "ieee_address": "0x00124b0001abcdef",
            "definition": {
                "model": "TS0601",
                "vendor": "Test Vendor",
            },
            "endpoints": {"1": {"clusters": ["msTemperatureMeasurement"]}},
        }
    ]).encode()


def make_router(discoveries=None, states=None):
    discoveries = discoveries if discoveries is not None else []
    states = states if states is not None else []

    router = ZigbeeMessageRouter(
        base_topic="zigbee2mqtt",
        on_discovery=discoveries.append,
        on_state=lambda device, state: states.append((device, state)),
    )
    return router, discoveries, states


def test_routes_discovery_and_builds_device_index():
    router, discoveries, states = make_router()

    router.handle_message(
        "zigbee2mqtt/bridge/devices",
        discovery_payload(),
    )

    assert len(discoveries) == 1
    assert len(router.devices) == 1
    assert router.devices[0].friendly_name == "greenhouse_sensor"
    assert router.devices[0].ieee_address == "00124b0001abcdef"
    assert states == []


def test_routes_state_after_discovery():
    router, discoveries, states = make_router()
    router.handle_message(
        "zigbee2mqtt/bridge/devices",
        discovery_payload(),
    )

    router.handle_message(
        "zigbee2mqtt/greenhouse_sensor",
        b'{"temperature": 28.5, "humidity": 70}',
    )

    assert len(states) == 1
    device, state = states[0]
    assert device.friendly_name == "greenhouse_sensor"
    assert [
        (item.metric, item.value, item.unit)
        for item in state
    ] == [
        ("air_temperature", 28.5, "Cel"),
        ("air_humidity", 70.0, "%"),
    ]


def test_rejects_state_before_discovery():
    router, _, _ = make_router()

    with pytest.raises(ZigbeeRoutingError, match="discovery"):
        router.handle_message(
            "zigbee2mqtt/greenhouse_sensor",
            b'{"temperature": 28.5}',
        )


def test_rejects_topics_outside_base():
    router, _, _ = make_router()

    with pytest.raises(ZigbeeRoutingError, match="outside"):
        router.handle_message(
            "other/greenhouse_sensor",
            b"{}",
        )


@pytest.mark.parametrize(
    "topic",
    [
        "zigbee2mqtt/",
        "zigbee2mqtt/bridge/state",
        "zigbee2mqtt/bridge",
        "zigbee2mqtt/bridge/devices/extra",
    ],
)
def test_rejects_unsupported_topics(topic):
    router, _, _ = make_router()

    with pytest.raises(ZigbeeRoutingError):
        router.handle_message(topic, b"{}")


def test_rejects_unknown_friendly_name():
    router, _, _ = make_router()
    router.handle_message(
        "zigbee2mqtt/bridge/devices",
        discovery_payload(),
    )

    with pytest.raises(Exception):
        router.handle_message(
            "zigbee2mqtt/unknown_sensor",
            b'{"temperature": 28.5}',
        )


def test_invalid_discovery_does_not_replace_existing_index():
    router, discoveries, _ = make_router()
    router.handle_message(
        "zigbee2mqtt/bridge/devices",
        discovery_payload(),
    )

    with pytest.raises(Exception):
        router.handle_message(
            "zigbee2mqtt/bridge/devices",
            b"invalid-json",
        )

    assert len(router.devices) == 1
    assert router.devices[0].friendly_name == "greenhouse_sensor"
    assert len(discoveries) == 1


def test_normalizes_base_topic():
    router = ZigbeeMessageRouter(
        base_topic="/zigbee2mqtt/",
        on_discovery=lambda devices: None,
        on_state=lambda device, state: None,
    )

    with pytest.raises(ZigbeeRoutingError, match="outside"):
        router.handle_message("other/sensor", b"{}")


def test_rejects_empty_base_topic():
    with pytest.raises(ValueError, match="base_topic"):
        ZigbeeMessageRouter(
            base_topic=" / ",
            on_discovery=lambda devices: None,
            on_state=lambda device, state: None,
        )
