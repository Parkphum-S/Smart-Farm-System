"""Provider-neutral MQTT transport contract for Zigbee integrations."""

from collections.abc import Callable
from typing import Protocol


MessageHandler = Callable[[str, bytes], None]


class MQTTTransport(Protocol):
    """Minimal synchronous MQTT transport interface."""

    def connect(self) -> None:
        """Connect to the configured MQTT broker."""

    def subscribe(self, topic: str, handler: MessageHandler) -> None:
        """Subscribe to a topic and dispatch received messages."""

    def loop_forever(self) -> None:
        """Process incoming messages until stopped or disconnected."""

    def stop_loop(self) -> None:
        """Request the network loop to stop."""

    def disconnect(self) -> None:
        """Close the broker connection."""
