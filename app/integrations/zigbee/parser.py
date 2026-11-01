"""Parse Zigbee2MQTT state messages with discovery identity resolution."""

import json
from typing import Any

from app.integrations.zigbee.clusters import (
    NormalizedMeasurement,
    normalize_z2m_state,
)
from app.integrations.zigbee.discovery import (
    ZigbeeDiscoveredDevice,
    ZigbeePayloadError,
    normalize_ieee_address,
)


def decode_json_payload(payload: str | bytes | bytearray | dict) -> Any:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ZigbeePayloadError("payload must be UTF-8") from exc
    if not isinstance(payload, str):
        raise ZigbeePayloadError("payload must be JSON text or an object")
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ZigbeePayloadError("malformed JSON payload") from exc


def parse_state_message(
    topic: str,
    payload: str | bytes | bytearray | dict,
    devices_by_friendly_name: dict[str, ZigbeeDiscoveredDevice],
) -> tuple[ZigbeeDiscoveredDevice, list[NormalizedMeasurement]]:
    """Resolve a Zigbee2MQTT state topic against bridge/devices discovery.

    Expected topic: <base_topic>/<friendly_name>.
    The caller supplies the configured base topic separately.
    """
    if not isinstance(topic, str) or not topic.strip():
        raise ZigbeePayloadError("topic is required")

    friendly_name = topic.strip().rsplit("/", 1)[-1]
    device = devices_by_friendly_name.get(friendly_name)
    if device is None:
        raise ZigbeePayloadError("state topic has no discovered device")

    state = decode_json_payload(payload)
    if not isinstance(state, dict):
        raise ZigbeePayloadError("state payload must be an object")

    # If the payload includes an IEEE address, it must agree with discovery.
    supplied_ieee = state.get("ieee_address")
    if supplied_ieee is not None:
        if normalize_ieee_address(supplied_ieee) != device.ieee_address:
            raise ZigbeePayloadError("state IEEE address does not match discovery")

    return device, normalize_z2m_state(state)
