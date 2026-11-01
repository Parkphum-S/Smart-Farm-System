from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.integrations.zigbee import entrypoint


class FakeSignal:
    SIGTERM = 15
    SIGINT = 2

    def __init__(self):
        self.handlers = {
            self.SIGTERM: "old-term",
            self.SIGINT: "old-int",
        }
        self.installed = {}
        self.calls = []

    def getsignal(self, sig):
        return self.handlers[sig]

    def signal(self, sig, handler):
        self.calls.append((sig, handler))
        if callable(handler):
            self.installed[sig] = handler
        self.handlers[sig] = handler


class FakeWorker:
    def __init__(self, run_error=None):
        self.run_error = run_error
        self.run_called = False
        self.stop_called = False

    def run(self):
        self.run_called = True
        if self.run_error:
            raise self.run_error

    def stop(self):
        self.stop_called = True


def configured_settings(**overrides):
    values = {
        "zigbee_mqtt_host": "127.0.0.1",
        "zigbee_mqtt_port": 1884,
        "zigbee_mqtt_keepalive": 45,
        "zigbee_mqtt_client_id": "test-zigbee",
        "zigbee_mqtt_username": "test-user",
        "zigbee_mqtt_password": "test-password",
        "zigbee_mqtt_qos": 2,
        "zigbee_mqtt_connect_timeout": 8.0,
        "zigbee_mqtt_subscribe_timeout": 6.0,
        "zigbee_base_topic": "farm/zigbee",
    }
    values.update(overrides)
    return Settings(**values)


def test_run_worker_builds_runtime_with_config_and_transaction_factory(
    monkeypatch,
):
    signal_api = FakeSignal()
    session_factory = object()
    captured = {}

    class FakeTransport:
        def __init__(self, config):
            captured["config"] = config

    worker = FakeWorker()

    def fake_build_runtime(**kwargs):
        captured["runtime_kwargs"] = kwargs
        return SimpleNamespace(worker=worker)

    monkeypatch.setattr(
        entrypoint,
        "build_zigbee_runtime",
        fake_build_runtime,
    )

    entrypoint.run_worker(
        app_settings=configured_settings(),
        session_factory=session_factory,
        transport_factory=FakeTransport,
        signal_api=signal_api,
    )

    config = captured["config"]
    assert config.host == "127.0.0.1"
    assert config.port == 1884
    assert config.keepalive == 45
    assert config.client_id == "test-zigbee"
    assert config.username == "test-user"
    assert config.password == "test-password"
    assert config.qos == 2
    assert config.connect_timeout == 8.0
    assert config.subscribe_timeout == 6.0

    runtime_kwargs = captured["runtime_kwargs"]
    assert runtime_kwargs["session_factory"] is session_factory
    assert runtime_kwargs["base_topic"] == "farm/zigbee"
    assert isinstance(runtime_kwargs["transport"], FakeTransport)
    assert worker.run_called
    assert signal_api.handlers[signal_api.SIGTERM] == "old-term"
    assert signal_api.handlers[signal_api.SIGINT] == "old-int"


def test_run_worker_requires_mqtt_host_before_startup():
    with pytest.raises(
        RuntimeError,
        match="SMARTFARM_ZIGBEE_MQTT_HOST",
    ):
        entrypoint.run_worker(
            app_settings=Settings(zigbee_mqtt_host=None),
            session_factory=object(),
            transport_factory=lambda config: object(),
            signal_api=FakeSignal(),
        )


def test_run_worker_restores_signal_handlers_when_worker_fails(
    monkeypatch,
):
    signal_api = FakeSignal()
    worker = FakeWorker(run_error=RuntimeError("worker failed"))

    monkeypatch.setattr(
        entrypoint,
        "build_zigbee_runtime",
        lambda **kwargs: SimpleNamespace(worker=worker),
    )

    with pytest.raises(RuntimeError, match="worker failed"):
        entrypoint.run_worker(
            app_settings=configured_settings(),
            session_factory=object(),
            transport_factory=lambda config: object(),
            signal_api=signal_api,
        )

    assert worker.run_called
    assert signal_api.handlers[signal_api.SIGTERM] == "old-term"
    assert signal_api.handlers[signal_api.SIGINT] == "old-int"


def test_signal_handler_requests_worker_stop(monkeypatch):
    signal_api = FakeSignal()
    worker = FakeWorker()
    captured = {}

    monkeypatch.setattr(
        entrypoint,
        "build_zigbee_runtime",
        lambda **kwargs: SimpleNamespace(worker=worker),
    )

    entrypoint.run_worker(
        app_settings=configured_settings(),
        session_factory=object(),
        transport_factory=lambda config: object(),
        signal_api=signal_api,
    )

    term_handler = signal_api.installed[signal_api.SIGTERM]
    term_handler(signal_api.SIGTERM, None)

    assert worker.stop_called
