import threading
import time
from types import SimpleNamespace

import pytest

from app.integrations.zigbee.mqtt_paho import (
    PahoMQTTConfig,
    PahoMQTTTransport,
)


class FakeClient:
    def __init__(self):
        self.on_connect = None
        self.on_disconnect = None
        self.on_subscribe = None
        self.on_message = None
        self.subscribe_reason_codes = [0]
        self.subscribe_ack_delay = 0.01
        self.subscriptions = []
        self._next_mid = 0
        self._ack_threads = []
        self.connected_args = None
        self.username = None
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False
        self.result = 0

    def reconnect_delay_set(self, **kwargs):
        self.reconnect_delay = kwargs

    def username_pw_set(self, username, password):
        self.username = (username, password)

    def connect(self, host, port, keepalive):
        self.connected_args = (host, port, keepalive)

    def loop_start(self):
        self.loop_started = True
        self.on_connect(self, None, {}, 0, None)

    def subscribe(self, topic, qos):
        self.subscriptions.append((topic, qos))
        self._next_mid += 1
        mid = self._next_mid

        if (
            int(self.result) == 0
            and self.on_subscribe is not None
            and self.subscribe_ack_delay is not None
        ):
            def acknowledge():
                time.sleep(self.subscribe_ack_delay)
                self.on_subscribe(
                    self,
                    None,
                    mid,
                    self.subscribe_reason_codes,
                    None,
                )

            thread = threading.Thread(target=acknowledge, daemon=True)
            self._ack_threads.append(thread)
            thread.start()

        return self.result, mid

    def wait_for_acks(self):
        for thread in self._ack_threads:
            thread.join(timeout=2)
            assert not thread.is_alive()
        self._ack_threads.clear()

    def disconnect(self):
        self.disconnected = True
        if self.on_disconnect is not None:
            self.on_disconnect(self, None, {}, 0, None)

    def loop_stop(self):
        self.loop_stopped = True

    def publish_message(self, topic, payload):
        message = SimpleNamespace(topic=topic, payload=payload)
        self.on_message(self, None, message)


def make_transport(client=None, **overrides):
    config = PahoMQTTConfig(
        host="127.0.0.1",
        **overrides,
    )
    client = client or FakeClient()
    transport = PahoMQTTTransport(
        config,
        client_factory=lambda: client,
    )
    return transport, client


def test_connect_and_subscribe():
    transport, client = make_transport()

    transport.connect()
    transport.subscribe("zigbee2mqtt/+", lambda topic, payload: None)

    assert client.connected_args == ("127.0.0.1", 1883, 60)
    assert client.loop_started is True
    assert client.subscriptions == [("zigbee2mqtt/+", 1)]

    transport.disconnect()
    assert client.disconnected is True
    assert client.loop_stopped is True


def test_message_dispatch():
    transport, client = make_transport()
    received = []

    transport.connect()
    transport.subscribe(
        "zigbee2mqtt/sensor",
        lambda topic, payload: received.append((topic, payload)),
    )

    client.publish_message("zigbee2mqtt/sensor", b'{"temperature": 28}')

    assert received == [
        ("zigbee2mqtt/sensor", b'{"temperature": 28}')
    ]

    transport.disconnect()


def test_handler_error_does_not_escape_mqtt_callback():
    transport, client = make_transport()

    transport.connect()
    transport.subscribe(
        "zigbee2mqtt/sensor",
        lambda topic, payload: (_ for _ in ()).throw(
            RuntimeError("handler error")
        ),
    )

    client.publish_message("zigbee2mqtt/sensor", b"{}")
    transport.disconnect()


def test_resubscribe_after_reconnect():
    transport, client = make_transport()

    transport.connect()
    transport.subscribe("zigbee2mqtt/+", lambda topic, payload: None)

    client.subscriptions.clear()
    client.on_connect(client, None, {}, 0, None)

    assert client.subscriptions == [("zigbee2mqtt/+", 1)]

    transport.disconnect()


def test_connect_rejection_raises():
    client = FakeClient()

    def rejected_loop_start():
        client.loop_started = True
        client.on_connect(client, None, {}, 5, None)

    client.loop_start = rejected_loop_start

    transport, _ = make_transport(client)

    with pytest.raises(ConnectionError, match="rejected"):
        transport.connect()

    assert client.disconnected is True


def test_loop_stops_when_requested():
    transport, client = make_transport()
    transport.connect()

    thread = threading.Thread(target=transport.loop_forever)
    thread.start()

    transport.stop_loop()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert client.disconnected is True

    transport.disconnect()


def test_config_validation():
    with pytest.raises(ValueError, match="QoS"):
        PahoMQTTConfig(host="localhost", qos=3)

    with pytest.raises(ValueError, match="username"):
        PahoMQTTConfig(host="localhost", password="secret")


def test_duplicate_subscription_rejected():
    transport, _ = make_transport()
    transport.connect()

    handler = lambda topic, payload: None
    transport.subscribe("zigbee2mqtt/+", handler)

    with pytest.raises(ValueError, match="duplicate"):
        transport.subscribe("zigbee2mqtt/+", handler)

    transport.disconnect()


def test_plus_filter_dispatches_concrete_topic():
    transport, client = make_transport()
    received = []

    transport.connect()
    transport.subscribe(
        "zigbee2mqtt/+",
        lambda topic, payload: received.append((topic, payload)),
    )

    client.publish_message(
        "zigbee2mqtt/greenhouse_sensor",
        b'{"temperature": 28}',
    )

    assert received == [
        ("zigbee2mqtt/greenhouse_sensor", b'{"temperature": 28}')
    ]
    transport.disconnect()


def test_hash_filter_dispatches_nested_topic():
    transport, client = make_transport()
    received = []

    transport.connect()
    transport.subscribe(
        "zigbee2mqtt/#",
        lambda topic, payload: received.append(topic),
    )

    client.publish_message("zigbee2mqtt/bridge/devices", b"[]")

    assert received == ["zigbee2mqtt/bridge/devices"]
    transport.disconnect()


def test_plus_filter_does_not_match_multiple_levels():
    transport, client = make_transport()
    received = []

    transport.connect()
    transport.subscribe(
        "zigbee2mqtt/+",
        lambda topic, payload: received.append(topic),
    )

    client.publish_message("zigbee2mqtt/bridge/devices", b"[]")

    assert received == []
    transport.disconnect()


def test_system_topic_not_matched_by_generic_hash():
    transport, client = make_transport()
    received = []

    transport.connect()
    transport.subscribe(
        "#",
        lambda topic, payload: received.append(topic),
    )

    client.publish_message("$SYS/broker/uptime", b"100")

    assert received == []
    transport.disconnect()



def test_disconnect_callback_clears_connected_state():
    transport, client = make_transport()
    transport.connect()

    assert transport._connected.is_set()

    client.on_disconnect(client, None, {}, 1, None)

    assert not transport._connected.is_set()

    transport.disconnect()


def test_reconnect_restores_connection_and_subscriptions():
    transport, client = make_transport()
    transport.connect()
    transport.subscribe("zigbee2mqtt/+", lambda topic, payload: None)

    client.subscriptions.clear()
    client.on_disconnect(client, None, {}, 1, None)

    assert not transport._connected.is_set()

    client.on_connect(client, None, {}, 0, None)

    assert transport._connected.is_set()
    assert client.subscriptions == [("zigbee2mqtt/+", 1)]
    client.wait_for_acks()

    transport.disconnect()


def test_resubscribe_failure_does_not_escape_connect_callback():
    transport, client = make_transport()
    transport.connect()
    transport.subscribe("zigbee2mqtt/+", lambda topic, payload: None)

    client.subscriptions.clear()
    client.result = 1
    client.on_disconnect(client, None, {}, 1, None)

    # A reconnect callback must contain subscription failures.
    client.on_connect(client, None, {}, 0, None)

    assert transport._connected.is_set()
    assert client.subscriptions == [("zigbee2mqtt/+", 1)]
    client.wait_for_acks()

    transport.disconnect()



def test_subscribe_waits_for_successful_suback():
    transport, client = make_transport()
    transport.connect()

    transport.subscribe("zigbee2mqtt/+", lambda topic, payload: None)

    assert client.subscriptions == [("zigbee2mqtt/+", 1)]
    assert transport._pending_subscriptions == {}

    transport.disconnect()


def test_subscribe_rejected_by_broker_raises():
    client = FakeClient()
    client.subscribe_reason_codes = [128]
    transport, _ = make_transport(client)

    transport.connect()

    with pytest.raises(RuntimeError, match="rejected"):
        transport.subscribe("zigbee2mqtt/+", lambda topic, payload: None)

    transport.disconnect()


def test_subscribe_suback_timeout_raises():
    client = FakeClient()
    client.subscribe_ack_delay = None
    transport, _ = make_transport(
        client,
        subscribe_timeout=0.02,
    )

    transport.connect()

    with pytest.raises(TimeoutError, match="SUBACK timed out"):
        transport.subscribe("zigbee2mqtt/+", lambda topic, payload: None)

    assert transport._pending_subscriptions == {}
    transport.disconnect()


def test_subscribe_immediate_error_raises_without_waiting_for_suback():
    client = FakeClient()
    client.result = 4
    transport, _ = make_transport(client)

    transport.connect()

    with pytest.raises(RuntimeError, match="subscribe failed"):
        transport.subscribe("zigbee2mqtt/+", lambda topic, payload: None)

    assert transport._pending_subscriptions == {}
    transport.disconnect()


def test_config_rejects_non_positive_subscribe_timeout():
    with pytest.raises(ValueError, match="subscribe_timeout"):
        PahoMQTTConfig(host="localhost", subscribe_timeout=0)
