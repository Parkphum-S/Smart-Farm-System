"""Route Zigbee2MQTT discovery and device-state messages."""

from collections.abc import Callable

from app.integrations.zigbee.clusters import NormalizedMeasurement
from app.integrations.zigbee.discovery import (
    ZigbeeDiscoveredDevice,
    build_friendly_name_index,
    parse_bridge_devices,
)
from app.integrations.zigbee.parser import (
    decode_json_payload,
    parse_state_message,
)


DiscoveryHandler = Callable[[tuple[ZigbeeDiscoveredDevice, ...]], None]
StateHandler = Callable[
    [ZigbeeDiscoveredDevice, list[NormalizedMeasurement]], None
]


class ZigbeeRoutingError(ValueError):
    """Raised when an MQTT message cannot be routed safely."""


class ZigbeeMessageRouter:
    """Route discovery and state messages without owning database sessions."""

    def __init__(
        self,
        *,
        base_topic: str,
        on_discovery: DiscoveryHandler,
        on_state: StateHandler,
    ) -> None:
        normalized = base_topic.strip().strip("/")
        if not normalized:
            raise ValueError("base_topic is required")

        self._base_topic = normalized
        self._discovery_topic = f"{normalized}/bridge/devices"
        self._on_discovery = on_discovery
        self._on_state = on_state
        self._devices_by_friendly_name: dict[
            str, ZigbeeDiscoveredDevice
        ] = {}

    @property
    def devices(self) -> tuple[ZigbeeDiscoveredDevice, ...]:
        return tuple(self._devices_by_friendly_name.values())

    def handle_message(self, topic: str, payload: bytes) -> None:
        """Dispatch one MQTT message to the matching application callback."""
        if not isinstance(topic, str) or not topic:
            raise ZigbeeRoutingError("invalid MQTT topic")

        if topic == self._discovery_topic:
            decoded_payload = decode_json_payload(payload)
            devices = tuple(parse_bridge_devices(decoded_payload))
            index = build_friendly_name_index(devices)

            # Replace the index only after the complete discovery payload
            # has been parsed and validated successfully.
            self._devices_by_friendly_name = index
            self._on_discovery(devices)
            return

        prefix = f"{self._base_topic}/"
        if not topic.startswith(prefix):
            raise ZigbeeRoutingError("topic is outside the configured base")

        relative_topic = topic[len(prefix):]
        if not relative_topic or "/" in relative_topic:
            raise ZigbeeRoutingError("unsupported Zigbee MQTT topic")

        if not self._devices_by_friendly_name:
            raise ZigbeeRoutingError("discovery has not completed")

        device, state = parse_state_message(
            topic,
            payload,
            self._devices_by_friendly_name,
        )
        self._on_state(device, state)
