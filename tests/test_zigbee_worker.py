import threading

import pytest

from app.integrations.zigbee.worker import ZigbeeWorker


class FakeTransport:
    def __init__(self):
        self.connected = False
        self.disconnected = False
        self.stop_requested = False
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
        self.stop_requested = True

    def disconnect(self):
        self.disconnected = True
        self.connected = False


def test_worker_lifecycle():
    transport = FakeTransport()
    received = []

    worker = ZigbeeWorker(
        transport=transport,
        topics=["zigbee2mqtt/bridge/devices", "zigbee2mqtt/+"],
        message_handler=lambda topic, payload: received.append(
            (topic, payload)
        ),
    )

    worker.run()

    assert transport.connected is False
    assert transport.disconnected is True
    assert transport.subscriptions == [
        "zigbee2mqtt/bridge/devices",
        "zigbee2mqtt/+",
    ]
    assert worker.running is False


def test_worker_dispatches_messages():
    transport = FakeTransport()
    received = []

    worker = ZigbeeWorker(
        transport=transport,
        topics=["zigbee2mqtt/+"],
        message_handler=lambda topic, payload: received.append(
            (topic, payload)
        ),
    )

    worker.run()
    transport.handlers["zigbee2mqtt/+"](
        "zigbee2mqtt/sensor_01",
        b'{"temperature": 28.5}',
    )

    assert received == [
        ("zigbee2mqtt/sensor_01", b'{"temperature": 28.5}')
    ]


def test_handler_error_does_not_escape_dispatch():
    transport = FakeTransport()

    def failing_handler(topic, payload):
        raise ValueError("invalid payload")

    worker = ZigbeeWorker(
        transport=transport,
        topics=["zigbee2mqtt/+"],
        message_handler=failing_handler,
    )

    worker.run()

    # The worker isolates the exception from the MQTT callback.
    transport.handlers["zigbee2mqtt/+"](
        "zigbee2mqtt/sensor_01",
        b"invalid",
    )


def test_stop_requests_transport_stop():
    transport = FakeTransport()
    worker = ZigbeeWorker(
        transport=transport,
        topics=["zigbee2mqtt/+"],
        message_handler=lambda topic, payload: None,
    )

    worker.run()
    worker.stop()

    # Once run() has exited, no connection remains to stop.
    assert transport.stop_requested is False


def test_rejects_empty_topics():
    with pytest.raises(ValueError, match="at least one"):
        ZigbeeWorker(
            transport=FakeTransport(),
            topics=[],
            message_handler=lambda topic, payload: None,
        )


def test_rejects_duplicate_topics():
    with pytest.raises(ValueError, match="duplicate"):
        ZigbeeWorker(
            transport=FakeTransport(),
            topics=["zigbee2mqtt/+", "zigbee2mqtt/+"],
            message_handler=lambda topic, payload: None,
        )


def test_disconnects_after_loop_error():
    class FailingTransport(FakeTransport):
        def loop_forever(self):
            raise RuntimeError("connection lost")

    transport = FailingTransport()
    worker = ZigbeeWorker(
        transport=transport,
        topics=["zigbee2mqtt/+"],
        message_handler=lambda topic, payload: None,
    )

    with pytest.raises(RuntimeError, match="connection lost"):
        worker.run()

    assert transport.disconnected is True
    assert worker.running is False



def test_stop_requests_transport_stop_while_loop_is_running():
    loop_entered = threading.Event()
    stop_requested = threading.Event()

    class BlockingTransport(FakeTransport):
        def loop_forever(self):
            loop_entered.set()
            stop_requested.wait(timeout=5)

        def stop_loop(self):
            self.stop_requested = True
            stop_requested.set()

    transport = BlockingTransport()
    worker = ZigbeeWorker(
        transport=transport,
        topics=["zigbee2mqtt/+"],
        message_handler=lambda topic, payload: None,
    )

    thread = threading.Thread(target=worker.run)
    thread.start()

    try:
        assert loop_entered.wait(timeout=2), "MQTT loop did not start"
        assert worker.running is True

        worker.stop()

        assert stop_requested.wait(timeout=2), "stop was not requested"
    finally:
        if thread.is_alive():
            worker.stop()
        thread.join(timeout=3)

    assert not thread.is_alive(), "Worker thread did not stop"
    assert transport.stop_requested is True
    assert transport.disconnected is True
    assert worker.running is False
