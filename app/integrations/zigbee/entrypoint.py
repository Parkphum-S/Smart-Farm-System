"""Standalone entrypoint for the Smart Farm Zigbee MQTT worker."""

import logging
import signal
from typing import Callable

from app.core.config import Settings
from app.integrations.zigbee.mqtt_paho import (
    PahoMQTTConfig,
    PahoMQTTTransport,
)
from app.integrations.zigbee.runtime import build_zigbee_runtime


logger = logging.getLogger(__name__)


def run_worker(
    *,
    app_settings: Settings | None = None,
    session_factory: Callable | None = None,
    transport_factory: Callable = PahoMQTTTransport,
    signal_api=signal,
) -> None:
    """Build and run the independent Zigbee worker.

    Database imports are delayed until runtime startup so importing this
    module does not require a configured database.
    """
    if session_factory is None:
        # Importing the DB session loads .env before Settings is instantiated.
        from app.db.session import SessionLocal

        session_factory = SessionLocal.begin

    if app_settings is None:
        app_settings = Settings()

    if not app_settings.zigbee_mqtt_host:
        raise RuntimeError("SMARTFARM_ZIGBEE_MQTT_HOST is not configured")

    mqtt_config = PahoMQTTConfig(
        host=app_settings.zigbee_mqtt_host,
        port=app_settings.zigbee_mqtt_port,
        keepalive=app_settings.zigbee_mqtt_keepalive,
        client_id=app_settings.zigbee_mqtt_client_id,
        username=app_settings.zigbee_mqtt_username,
        password=app_settings.zigbee_mqtt_password,
        qos=app_settings.zigbee_mqtt_qos,
        connect_timeout=app_settings.zigbee_mqtt_connect_timeout,
        subscribe_timeout=app_settings.zigbee_mqtt_subscribe_timeout,
    )

    transport = transport_factory(mqtt_config)
    runtime = build_zigbee_runtime(
        transport=transport,
        session_factory=session_factory,
        base_topic=app_settings.zigbee_base_topic,
    )

    previous_handlers = {}

    def request_stop(signum, frame):
        logger.info("Received signal %s; stopping Zigbee worker", signum)
        runtime.worker.stop()

    try:
        for sig in (signal_api.SIGTERM, signal_api.SIGINT):
            previous_handlers[sig] = signal_api.getsignal(sig)
            signal_api.signal(sig, request_stop)

        logger.info("Starting Smart Farm Zigbee MQTT worker")
        runtime.worker.run()
    finally:
        for sig, previous in previous_handlers.items():
            signal_api.signal(sig, previous)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run_worker()


if __name__ == "__main__":
    main()
