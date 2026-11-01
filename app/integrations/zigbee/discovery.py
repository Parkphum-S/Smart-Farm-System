"""Parse Zigbee2MQTT bridge device discovery payloads."""

from dataclasses import dataclass
import re
from typing import Any


_IEEE_RE = re.compile(r"^(?:0x)?([0-9a-fA-F]{16})$")


class ZigbeePayloadError(ValueError):
    """Raised when a Zigbee payload is malformed or incomplete."""


def normalize_ieee_address(value: Any) -> str:
    if not isinstance(value, str):
        raise ZigbeePayloadError("ieee_address must be a string")

    match = _IEEE_RE.fullmatch(value.strip())
    if not match:
        raise ZigbeePayloadError("invalid IEEE address")

    return match.group(1).lower()


@dataclass(frozen=True)
class ZigbeeDiscoveredDevice:
    friendly_name: str
    ieee_address: str
    model: str | None = None
    manufacturer: str | None = None
    endpoints: tuple[int, ...] = ()


def parse_bridge_devices(payload: Any) -> list[ZigbeeDiscoveredDevice]:
    """Parse the JSON value published on Zigbee2MQTT bridge/devices."""
    if not isinstance(payload, list):
        raise ZigbeePayloadError("bridge/devices payload must be a list")

    devices: list[ZigbeeDiscoveredDevice] = []
    names: set[str] = set()
    addresses: set[str] = set()

    for item in payload:
        if not isinstance(item, dict):
            raise ZigbeePayloadError("each discovered device must be an object")

        ieee = normalize_ieee_address(item.get("ieee_address"))
        friendly_name = item.get("friendly_name")

        if not isinstance(friendly_name, str) or not friendly_name.strip():
            raise ZigbeePayloadError("friendly_name is required")

        friendly_name = friendly_name.strip()

        if friendly_name in names:
            raise ZigbeePayloadError("duplicate friendly_name")
        if ieee in addresses:
            raise ZigbeePayloadError("duplicate IEEE address")

        definition = item.get("definition")
        if not isinstance(definition, dict):
            definition = {}

        endpoints_value = item.get("endpoints")
        endpoints: tuple[int, ...] = ()

        if isinstance(endpoints_value, dict):
            parsed: set[int] = set()
            for key in endpoints_value:
                try:
                    endpoint = int(key)
                except (TypeError, ValueError) as exc:
                    raise ZigbeePayloadError("invalid endpoint ID") from exc
                if not 1 <= endpoint <= 240:
                    raise ZigbeePayloadError("endpoint ID out of range")
                parsed.add(endpoint)
            endpoints = tuple(sorted(parsed))

        devices.append(
            ZigbeeDiscoveredDevice(
                friendly_name=friendly_name,
                ieee_address=ieee,
                model=(
                    definition.get("model")
                    if isinstance(definition.get("model"), str)
                    else None
                ),
                manufacturer=(
                    definition.get("vendor")
                    if isinstance(definition.get("vendor"), str)
                    else None
                ),
                endpoints=endpoints,
            )
        )

        names.add(friendly_name)
        addresses.add(ieee)

    return devices


def build_friendly_name_index(
    devices: list[ZigbeeDiscoveredDevice],
) -> dict[str, ZigbeeDiscoveredDevice]:
    return {device.friendly_name: device for device in devices}
