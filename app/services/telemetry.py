"""Transactional telemetry ingestion service. Not wired to the API yet."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.telemetry import TelemetryEvent
from app.security.device_auth import DeviceIdentity


class TelemetryRejected(Exception):
    """The event does not match the authenticated device or its sensors."""


class EventConflict(Exception):
    """An existing event ID was reused with a different payload."""


@dataclass(frozen=True)
class IngestResult:
    event_record_id: object
    duplicate: bool


def ingest_telemetry(
    db: Session,
    identity: DeviceIdentity,
    event: TelemetryEvent,
) -> IngestResult:
    """Validate and persist an event inside the caller's transaction.

    The caller must commit on success and roll back on any exception.
    This function does not commit or open a transaction itself.
    """
    if event.device_id != identity.device_id:
        raise TelemetryRejected("Device identity does not match event")

    observed_at = event.observed_at.astimezone(timezone.utc)
    payload = event.model_dump(mode="json")
    canonical_payload = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    payload_hash = hashlib.sha256(
        canonical_payload.encode("utf-8")
    ).hexdigest()

    tenant = db.execute(
        text("""
            SELECT status
            FROM tenants
            WHERE id = :tenant_id
        """),
        {"tenant_id": identity.tenant_id},
    ).scalar_one_or_none()

    if tenant != "active":
        raise TelemetryRejected("Tenant is not active")

    device = db.execute(
        text("""
            SELECT status
            FROM devices
            WHERE id = :device_id
              AND tenant_id = :tenant_id
        """),
        {
            "device_id": identity.device_id,
            "tenant_id": identity.tenant_id,
        },
    ).scalar_one_or_none()

    if device != "active":
        raise TelemetryRejected("Device is not active")

    checked_sensors = set()

    for reading in event.readings:
        sensor_id = reading.sensor_id

        sensor = db.execute(
            text("""
                SELECT measurement_type, unit
                FROM sensors
                WHERE id = :sensor_id
                  AND tenant_id = :tenant_id
                  AND device_id = :device_id
                  AND status = 'active'
            """),
            {
                "sensor_id": sensor_id,
                "tenant_id": identity.tenant_id,
                "device_id": identity.device_id,
            },
        ).mappings().first()

        if sensor is None:
            raise TelemetryRejected(
                "Sensor is not active or does not belong to device"
            )

        if (
            sensor["measurement_type"] != reading.metric
            or sensor["unit"] != reading.unit
        ):
            raise TelemetryRejected(
                "Reading metric or unit does not match sensor"
            )

        checked_sensors.add(sensor_id)

    event_record_id = uuid4()

    inserted_id = db.execute(
        text("""
            INSERT INTO telemetry_events (
                id, tenant_id, device_id, event_id,
                observed_at, schema_version, payload, payload_hash
            )
            VALUES (
                :id, :tenant_id, :device_id, :event_id,
                :observed_at, 1, CAST(:payload AS jsonb), :payload_hash
            )
            ON CONFLICT (device_id, event_id) DO NOTHING
            RETURNING id
        """),
        {
            "id": event_record_id,
            "tenant_id": identity.tenant_id,
            "device_id": identity.device_id,
            "event_id": event.event_id,
            "observed_at": observed_at,
            "payload": canonical_payload,
            "payload_hash": payload_hash,
        },
    ).scalar_one_or_none()

    if inserted_id is None:
        existing = db.execute(
            text("""
                SELECT id, payload_hash
                FROM telemetry_events
                WHERE device_id = :device_id
                  AND event_id = :event_id
            """),
            {
                "device_id": identity.device_id,
                "event_id": event.event_id,
            },
        ).mappings().first()

        if existing is None:
            raise EventConflict("Could not resolve duplicate event")

        if existing["payload_hash"] != payload_hash:
            raise EventConflict(
                "Event ID already exists with a different payload"
            )

        return IngestResult(
            event_record_id=existing["id"],
            duplicate=True,
        )

    for reading in event.readings:
        db.execute(
            text("""
                INSERT INTO sensor_readings (
                    id, tenant_id, telemetry_event_id, device_id,
                    sensor_id, measured_at, measurement_type,
                    value, unit, quality_status
                )
                SELECT
                    :id, :tenant_id, :event_record_id, :device_id,
                    s.id, :measured_at, s.measurement_type,
                    :value, s.unit, 'valid'
                FROM sensors AS s
                WHERE s.id = :sensor_id
                  AND s.tenant_id = :tenant_id
                  AND s.device_id = :device_id
                  AND s.status = 'active'
            """),
            {
                "id": uuid4(),
                "tenant_id": identity.tenant_id,
                "event_record_id": inserted_id,
                "device_id": identity.device_id,
                "sensor_id": reading.sensor_id,
                "measured_at": observed_at,
                "value": reading.value,
            },
        )

        if not db.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM sensor_readings
                    WHERE telemetry_event_id = :event_record_id
                      AND sensor_id = :sensor_id
                )
            """),
            {
                "event_record_id": inserted_id,
                "sensor_id": reading.sensor_id,
            },
        ).scalar_one():
            raise TelemetryRejected(
                "Sensor became unavailable during ingestion"
            )

    return IngestResult(
        event_record_id=inserted_id,
        duplicate=False,
    )
