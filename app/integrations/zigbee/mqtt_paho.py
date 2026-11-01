"""Paho MQTT transport implementation for Zigbee integrations."""

import logging
import threading
from dataclasses import dataclass
from typing import Callable

from app.integrations.zigbee.transport import MessageHandler


logger = logging.getLogger(__name__)


def _topic_matches_filter(topic_filter: str, topic: str) -> bool:
    """Match an MQTT topic against a subscription filter."""
    if not topic or topic.startswith("$") and not topic_filter.startswith("$"):
        return False

    filters = topic_filter.split("/")
    levels = topic.split("/")

    for index, level_filter in enumerate(filters):
        if level_filter == "#":
            return index == len(filters) - 1

        if index >= len(levels):
            return False

        if level_filter == "+":
            continue

        if level_filter != levels[index]:
            return False

    return len(filters) == len(levels)


@dataclass(frozen=True)
class PahoMQTTConfig:
    host: str
    port: int = 1883
    keepalive: int = 60
    client_id: str = "smartfarm-zigbee"
    username: str | None = None
    password: str | None = None
    qos: int = 1
    connect_timeout: float = 15.0
    subscribe_timeout: float = 10.0

    def __post_init__(self):
        if not self.host.strip():
            raise ValueError("MQTT host is required")
        if not 1 <= self.port <= 65535:
            raise ValueError("invalid MQTT port")
        if self.keepalive < 1:
            raise ValueError("keepalive must be positive")
        if not 0 <= self.qos <= 2:
            raise ValueError("MQTT QoS must be 0, 1 or 2")
        if self.connect_timeout <= 0:
            raise ValueError("connect_timeout must be positive")
        if self.subscribe_timeout <= 0:
            raise ValueError("subscribe_timeout must be positive")
        if self.password is not None and self.username is None:
            raise ValueError("MQTT username is required when password is set")


class PahoMQTTTransport:
    """Synchronous transport facade over Paho's background network loop."""

    def __init__(
        self,
        config: PahoMQTTConfig,
        *,
        client_factory: Callable[[], object] | None = None,
    ):
        self._config = config
        self._client_factory = client_factory
        self._client = None

        self._lock = threading.RLock()
        self._connected = threading.Event()
        self._stopped = threading.Event()
        self._connection_error: Exception | None = None
        self._handlers: dict[str, MessageHandler] = {}
        self._pending_subscriptions: dict[
            int, tuple[threading.Event, list, bool]
        ] = {}
        self._loop_started = False

    def _create_client(self):
        if self._client_factory is not None:
            return self._client_factory()

        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise RuntimeError(
                "paho-mqtt is required for PahoMQTTTransport"
            ) from exc

        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self._config.client_id,
        )

    @staticmethod
    def _reason_failed(reason_code) -> bool:
        if hasattr(reason_code, "is_failure"):
            return bool(reason_code.is_failure)
        return int(reason_code) != 0

    def connect(self) -> None:
        if self._client is not None:
            raise RuntimeError("MQTT transport is already initialized")

        client = self._create_client()
        self._client = client

        self._connected.clear()
        self._stopped.clear()
        self._connection_error = None

        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_subscribe = self._on_subscribe
        client.on_message = self._on_message
        client.reconnect_delay_set(min_delay=1, max_delay=30)

        if self._config.username is not None:
            client.username_pw_set(
                self._config.username,
                self._config.password,
            )

        try:
            client.connect(
                self._config.host,
                self._config.port,
                self._config.keepalive,
            )
            client.loop_start()
            self._loop_started = True

            if not self._connected.wait(self._config.connect_timeout):
                raise TimeoutError("MQTT connection timed out")

            if self._connection_error is not None:
                raise ConnectionError(
                    "MQTT broker rejected the connection"
                ) from self._connection_error

        except Exception:
            self.disconnect()
            raise

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if self._reason_failed(reason_code):
            self._connection_error = ConnectionError(str(reason_code))
            self._connected.set()
            logger.error("MQTT connection rejected: %s", reason_code)
            return

        self._connection_error = None
        self._connected.set()
        logger.info("MQTT broker connected")

        with self._lock:
            topics = tuple(self._handlers)

        for topic in topics:
            try:
                self._subscribe_client(topic, wait_for_ack=False)
            except Exception:
                logger.exception(
                    "MQTT resubscribe failed for topic %s",
                    topic,
                )

    def _on_disconnect(
        self,
        client,
        userdata,
        disconnect_flags,
        reason_code,
        properties,
    ):
        self._connected.clear()
        logger.warning(
            "MQTT broker disconnected: %s",
            reason_code,
        )

    def _on_subscribe(
        self,
        client,
        userdata,
        mid,
        reason_code_list,
        properties,
    ):
        reason_codes = list(reason_code_list or [])
        failed = any(self._reason_failed(code) for code in reason_codes)

        with self._lock:
            pending = self._pending_subscriptions.get(mid)
            if pending is None:
                logger.warning("MQTT SUBACK received for unknown message id")
                return

            event, result, wait_for_ack = pending
            result.extend(reason_codes)
            event.set()

            if not wait_for_ack:
                self._pending_subscriptions.pop(mid, None)

        if failed:
            logger.error("MQTT broker rejected a subscription")
        else:
            logger.info("MQTT subscription acknowledged")

    def _subscribe_client(
        self,
        topic: str,
        *,
        wait_for_ack: bool = True,
    ) -> None:
        # Hold the lock across subscribe() and pending registration so that
        # the network callback cannot process SUBACK before its MID is stored.
        with self._lock:
            result, mid = self._client.subscribe(
                topic,
                qos=self._config.qos,
            )
            if int(result) != 0:
                raise RuntimeError(
                    f"MQTT subscribe failed for topic {topic}: {result}"
                )

            event = threading.Event()
            reason_codes = []
            self._pending_subscriptions[mid] = (
                event,
                reason_codes,
                wait_for_ack,
            )

        if not wait_for_ack:
            return

        if not event.wait(self._config.subscribe_timeout):
            with self._lock:
                self._pending_subscriptions.pop(mid, None)
            raise TimeoutError(
                f"MQTT SUBACK timed out for topic {topic}"
            )

        with self._lock:
            self._pending_subscriptions.pop(mid, None)

        if not reason_codes:
            raise RuntimeError(
                f"MQTT SUBACK contained no reason code for topic {topic}"
            )

        if any(self._reason_failed(code) for code in reason_codes):
            raise RuntimeError(
                f"MQTT broker rejected subscription for topic {topic}"
            )

    def subscribe(self, topic: str, handler: MessageHandler) -> None:
        if not topic or not topic.strip():
            raise ValueError("MQTT topic is required")
        if not callable(handler):
            raise TypeError("MQTT message handler must be callable")

        normalized_topic = topic.strip()

        with self._lock:
            if normalized_topic in self._handlers:
                raise ValueError("duplicate MQTT subscription")

            self._handlers[normalized_topic] = handler
            should_subscribe = self._connected.is_set()

        if should_subscribe:
            self._subscribe_client(normalized_topic)

    def _on_message(self, client, userdata, message):
        with self._lock:
            handlers = tuple(
                (topic_filter, handler)
                for topic_filter, handler in self._handlers.items()
                if _topic_matches_filter(topic_filter, message.topic)
            )

        if not handlers:
            logger.warning("MQTT message received for unknown topic")
            return

        for _, handler in handlers:
            try:
                handler(message.topic, bytes(message.payload))
            except Exception:
                logger.exception("MQTT message handler failed")

    def loop_forever(self) -> None:
        if not self._loop_started:
            raise RuntimeError("MQTT transport is not connected")

        self._stopped.wait()

    def stop_loop(self) -> None:
        self._stopped.set()

        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                logger.exception("MQTT disconnect during stop failed")

    def disconnect(self) -> None:
        client = self._client
        if client is None:
            return

        self._stopped.set()

        try:
            client.disconnect()
        except Exception:
            logger.exception("MQTT disconnect failed")
        finally:
            if self._loop_started:
                try:
                    client.loop_stop()
                except Exception:
                    logger.exception("MQTT network loop stop failed")

            self._loop_started = False
            self._connected.clear()
            self._client = None
