import pytest

from app.integrations.zigbee.clusters import (
    normalize_z2m_state,
    zcl_occupancy,
    zcl_relative_humidity,
    zcl_temperature,
)
from app.integrations.zigbee.discovery import (
    ZigbeePayloadError,
    build_friendly_name_index,
    normalize_ieee_address,
    parse_bridge_devices,
)
from app.integrations.zigbee.parser import parse_state_message


IEEE = "0x00124b0024c12345"


def discovered_devices():
    return parse_bridge_devices([
        {
            "friendly_name": "greenhouse_sensor",
            "ieee_address": IEEE,
            "type": "EndDevice",
            "definition": {
                "model": "Example Sensor",
                "vendor": "Example",
            },
            "endpoints": {"1": {}, "2": {}},
        }
    ])


def test_parse_bridge_devices_and_endpoints():
    devices = discovered_devices()

    assert len(devices) == 1
    assert devices[0].friendly_name == "greenhouse_sensor"
    assert devices[0].ieee_address == "00124b0024c12345"
    assert devices[0].endpoints == (1, 2)
    assert devices[0].model == "Example Sensor"


def test_reject_invalid_ieee_address():
    with pytest.raises(ZigbeePayloadError, match="invalid IEEE"):
        normalize_ieee_address("not-an-ieee-address")


def test_reject_duplicate_discovery_identity():
    with pytest.raises(ZigbeePayloadError, match="duplicate friendly_name"):
        parse_bridge_devices([
            {"friendly_name": "same", "ieee_address": IEEE},
            {"friendly_name": "same", "ieee_address": "0x00124b0024c12346"},
        ])


def test_parse_z2m_state_and_resolve_discovery_identity():
    index = build_friendly_name_index(discovered_devices())

    device, readings = parse_state_message(
        "zigbee2mqtt/greenhouse_sensor",
        '{"temperature": 28.5, "humidity": 72.1, "battery": 95, "linkquality": 88}',
        index,
    )

    assert device.ieee_address == "00124b0024c12345"
    assert [(r.metric, r.value, r.unit) for r in readings] == [
        ("air_temperature", 28.5, "Cel"),
        ("air_humidity", 72.1, "%"),
    ]


def test_parse_state_accepts_bytes():
    index = build_friendly_name_index(discovered_devices())
    device, readings = parse_state_message(
        "zigbee2mqtt/greenhouse_sensor",
        b'{"soil_moisture": 41}',
        index,
    )

    assert device.friendly_name == "greenhouse_sensor"
    assert readings[0].metric == "soil_moisture"
    assert readings[0].value == 41.0


def test_unknown_friendly_name_is_rejected():
    with pytest.raises(ZigbeePayloadError, match="no discovered device"):
        parse_state_message("zigbee2mqtt/unknown", "{}", {})


def test_state_ieee_must_match_discovery():
    index = build_friendly_name_index(discovered_devices())

    with pytest.raises(ZigbeePayloadError, match="does not match"):
        parse_state_message(
            "zigbee2mqtt/greenhouse_sensor",
            {"ieee_address": "0x00124b0024c12346"},
            index,
        )


def test_malformed_json_is_rejected():
    with pytest.raises(ZigbeePayloadError, match="malformed JSON"):
        parse_state_message(
            "zigbee2mqtt/greenhouse_sensor",
            "{bad json",
            build_friendly_name_index(discovered_devices()),
        )


def test_non_measurement_fields_are_not_telemetry():
    readings = normalize_z2m_state({
        "battery": 99,
        "linkquality": 100,
        "occupancy": True,
        "action": "single",
        "state": "ON",
    })

    assert readings == []


def test_invalid_numeric_state_values_are_ignored():
    readings = normalize_z2m_state({
        "temperature": float("nan"),
        "humidity": "70",
        "soil_moisture": True,
    })

    assert readings == []


def test_zcl_temperature_scaling():
    assert zcl_temperature(2850) == 28.5


def test_zcl_humidity_scaling():
    assert zcl_relative_humidity(7210) == 72.1


def test_zcl_occupancy_bit():
    assert zcl_occupancy(0) is False
    assert zcl_occupancy(1) is True
    assert zcl_occupancy(3) is True


@pytest.mark.parametrize("value", [0x8000, -30000, float("inf"), "2850"])
def test_invalid_zcl_temperature(value):
    with pytest.raises(ValueError):
        zcl_temperature(value)


@pytest.mark.parametrize("value", [0xFFFF, -1, 10001, float("nan")])
def test_invalid_zcl_humidity(value):
    with pytest.raises(ValueError):
        zcl_relative_humidity(value)
