"""Runtime assembly for the independent Zigbee MQTT worker."""

import logging
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from app.integrations.zigbee.clusters import NormalizedMeasurement
from app.integrations.zigbee.discovery import ZigbeeDiscoveredDevice
from app.integrations.zigbee.router import ZigbeeMessageRouter
from app.integrations.zigbee.transport import MQTTTransport
from app.integrations.zigbee.worker import ZigbeeWorker
from app.integrations.zigbee.service import process_registered_measurements


logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True)
class ZigbeeRuntime:
    """Assembled Zigbee runtime components."""

    router: ZigbeeMessageRouter
    worker: ZigbeeWorker


def build_zigbee_runtime(
    *,
    transport: MQTTTransport,
    session_factory: SessionFactory,
    base_topic: str,
) -> ZigbeeRuntime:
    """Build the router and worker without starting external services.

    The supplied session factory must provide a transaction context manager,
    such as SQLAlchemy sessionmaker.begin.

    Discovery never creates registrations. State messages are accepted only
    through existing active IEEE registrations and sensor mappings.
    """
    normalized_topic = base_topic.strip().strip("/")
    if not normalized_topic:
        raise ValueError("base_topic is required")

    def on_discovery(
        devices: tuple[ZigbeeDiscoveredDevice, ...],
    ) -> None:
        logger.info(
            "Zigbee discovery completed: %d devices",
            len(devices),
        )

    def on_state(
        device: ZigbeeDiscoveredDevice,
        measurements: list[NormalizedMeasurement],
    ) -> None:
        received_at = datetime.now(timezone.utc)

        with session_factory() as db:
            process_registered_measurements(
                db,
                ieee_address=device.ieee_address,
                measurements=measurements,
                event_id=uuid4(),
                observed_at=received_at,
            )

        logger.debug(
            "Zigbee telemetry ingested for registered device"
        )

    router = ZigbeeMessageRouter(
        base_topic=normalized_topic,
        on_discovery=on_discovery,
        on_state=on_state,
    )

    worker = ZigbeeWorker(
        transport=transport,
        topics=(
            f"{normalized_topic}/bridge/devices",
            f"{normalized_topic}/+",
        ),
        message_handler=router.handle_message,
    )

    return ZigbeeRuntime(
        router=router,
        worker=worker,
    )
