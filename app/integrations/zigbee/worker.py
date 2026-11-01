"""Independent lifecycle manager for the Zigbee MQTT integration."""

import logging
from collections.abc import Sequence

from app.integrations.zigbee.transport import MQTTTransport, MessageHandler


logger = logging.getLogger(__name__)


class ZigbeeWorker:
    """Run a transport independently from the FastAPI application."""

    def __init__(
        self,
        *,
        transport: MQTTTransport,
        topics: Sequence[str],
        message_handler: MessageHandler,
    ) -> None:
        normalized_topics = tuple(
            topic.strip()
            for topic in topics
            if isinstance(topic, str) and topic.strip()
        )

        if not normalized_topics:
            raise ValueError("at least one MQTT topic is required")

        if len(normalized_topics) != len(set(normalized_topics)):
            raise ValueError("duplicate MQTT topics are not allowed")

        self._transport = transport
        self._topics = normalized_topics
        self._message_handler = message_handler
        self._connected = False
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def _dispatch(self, topic: str, payload: bytes) -> None:
        """Isolate message failures so one bad payload cannot kill the worker."""
        try:
            self._message_handler(topic, payload)
        except Exception:
            logger.exception(
                "Zigbee message handler failed; message discarded"
            )

    def run(self) -> None:
        """Connect, subscribe and process messages until the loop exits."""
        if self._running:
            raise RuntimeError("Zigbee worker is already running")

        self._running = True

        try:
            self._transport.connect()
            self._connected = True

            for topic in self._topics:
                self._transport.subscribe(topic, self._dispatch)

            logger.info("Zigbee MQTT worker started")
            self._transport.loop_forever()

        finally:
            self._running = False

            if self._connected:
                try:
                    self._transport.disconnect()
                finally:
                    self._connected = False

            logger.info("Zigbee MQTT worker stopped")

    def stop(self) -> None:
        """Request a graceful stop of the transport loop."""
        if self._connected:
            self._transport.stop_loop()
