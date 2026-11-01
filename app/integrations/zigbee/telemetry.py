"""Build provider-neutral telemetry events from normalized Zigbee measurements."""

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from app.integrations.zigbee.clusters import NormalizedMeasurement
from app.schemas.telemetry import SensorReading, TelemetryEvent


class ZigbeeTelemetryError(ValueError):
    """A Zigbee measurement cannot safely become a telemetry event."""


def build_telemetry_event(
    *,
    event_id: UUID,
    device_id: UUID,
    observed_at: datetime,
    measurements: list[NormalizedMeasurement],
    sensor_ids: Mapping[str, UUID],
) -> TelemetryEvent:
    """Build an event using explicitly resolved sensor IDs.

    Does not access the database, generate identifiers, or commit transactions.
    Every measurement must have exactly one configured sensor mapping.
    """
    if not measurements:
        raise ZigbeeTelemetryError("at least one measurement is required")

    seen_metrics: set[str] = set()
    readings: list[SensorReading] = []

    for measurement in measurements:
        if measurement.metric in seen_metrics:
            raise ZigbeeTelemetryError(
                f"duplicate measurement metric: {measurement.metric}"
            )
        seen_metrics.add(measurement.metric)

        sensor_id = sensor_ids.get(measurement.metric)
        if sensor_id is None:
            raise ZigbeeTelemetryError(
                f"no registered sensor for metric: {measurement.metric}"
            )

        readings.append(
            SensorReading(
                sensor_id=sensor_id,
                metric=measurement.metric,
                value=measurement.value,
                unit=measurement.unit,
            )
        )

    try:
        return TelemetryEvent(
            event_id=event_id,
            device_id=device_id,
            observed_at=observed_at,
            readings=readings,
        )
    except (TypeError, ValueError) as exc:
        raise ZigbeeTelemetryError(
            f"invalid Zigbee telemetry event: {exc}"
        ) from exc
