"""Orchestrate Zigbee state parsing, sensor mapping and telemetry ingestion."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.integrations.zigbee.discovery import ZigbeeDiscoveredDevice
from app.integrations.zigbee.mapping import (
    ZigbeeMappingError,
    ZigbeeSensorBinding,
    resolve_sensor_bindings,
)
from app.integrations.zigbee.parser import parse_state_message
from app.integrations.zigbee.telemetry import build_telemetry_event
from app.schemas.telemetry import TelemetryEvent
from app.security.device_auth import DeviceIdentity
from app.services.telemetry import ingest_telemetry


class ZigbeeServiceError(ValueError):
    """A Zigbee state message cannot be ingested safely."""


def process_state_message(
    db: Session,
    *,
    identity: DeviceIdentity,
    topic: str,
    payload: str | bytes | bytearray | dict,
    devices_by_friendly_name: dict[str, ZigbeeDiscoveredDevice],
    bindings: list[ZigbeeSensorBinding],
    event_id: UUID,
    observed_at: datetime,
):
    """Parse and ingest one Zigbee state message.

    The caller must authenticate the gateway and own the DB transaction.
    This service never commits, rolls back, or creates sensor mappings.
    """
    device, measurements = parse_state_message(
        topic,
        payload,
        devices_by_friendly_name,
    )

    if not measurements:
        raise ZigbeeServiceError("state message contains no supported measurements")

    bindings_by_metric: dict[str, ZigbeeSensorBinding] = {}
    for binding in bindings:
        if binding.metric in bindings_by_metric:
            raise ZigbeeServiceError(
                f"duplicate configured binding for metric: {binding.metric}"
            )
        bindings_by_metric[binding.metric] = binding

    measurement_metrics = {measurement.metric for measurement in measurements}
    missing = measurement_metrics - bindings_by_metric.keys()
    if missing:
        raise ZigbeeMappingError(
            "missing configured sensor binding for: "
            + ", ".join(sorted(missing))
        )

    active_bindings = [
        bindings_by_metric[measurement.metric]
        for measurement in measurements
    ]

    sensor_ids = resolve_sensor_bindings(
        db,
        tenant_id=identity.tenant_id,
        device_id=identity.device_id,
        bindings=active_bindings,
    )

    event: TelemetryEvent = build_telemetry_event(
        event_id=event_id,
        device_id=identity.device_id,
        observed_at=observed_at,
        measurements=measurements,
        sensor_ids=sensor_ids,
    )

    return ingest_telemetry(db, identity, event)


def process_registered_measurements(
    db: Session,
    *,
    ieee_address: str,
    measurements: list,
    event_id: UUID,
    observed_at: datetime,
):
    """Resolve a registered Zigbee device and ingest normalized measurements.

    Mapping is loaded from the database for the resolved tenant/device.
    The caller owns the transaction. This function never commits or rolls back.
    """
    from app.integrations.zigbee.mapping import load_sensor_bindings
    from app.integrations.zigbee.registration import resolve_device_identity

    identity = resolve_device_identity(db, ieee_address=ieee_address)

    if not measurements:
        raise ZigbeeServiceError(
            "state message contains no supported measurements"
        )

    bindings = load_sensor_bindings(
        db,
        tenant_id=identity.tenant_id,
        device_id=identity.device_id,
    )

    bindings_by_metric: dict[str, ZigbeeSensorBinding] = {}
    for binding in bindings:
        if binding.metric in bindings_by_metric:
            raise ZigbeeMappingError(
                f"duplicate configured binding for metric: {binding.metric}"
            )
        bindings_by_metric[binding.metric] = binding

    measurement_metrics = {measurement.metric for measurement in measurements}
    missing = measurement_metrics - bindings_by_metric.keys()
    if missing:
        raise ZigbeeMappingError(
            "missing configured sensor binding for: "
            + ", ".join(sorted(missing))
        )

    active_bindings = [
        bindings_by_metric[measurement.metric]
        for measurement in measurements
    ]

    sensor_ids = resolve_sensor_bindings(
        db,
        tenant_id=identity.tenant_id,
        device_id=identity.device_id,
        bindings=active_bindings,
    )

    event: TelemetryEvent = build_telemetry_event(
        event_id=event_id,
        device_id=identity.device_id,
        observed_at=observed_at,
        measurements=measurements,
        sensor_ids=sensor_ids,
    )

    return ingest_telemetry(db, identity, event)
