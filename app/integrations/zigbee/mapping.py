"""Tenant-scoped Zigbee endpoint-to-sensor mapping resolver."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


class ZigbeeMappingError(ValueError):
    """A Zigbee endpoint cannot be safely resolved to a registered sensor."""


@dataclass(frozen=True)
class ZigbeeSensorBinding:
    """Explicit mapping between a parsed metric and a registered endpoint."""

    metric: str
    unit: str
    endpoint_key: str


def resolve_sensor_bindings(
    db: Session,
    *,
    tenant_id: UUID,
    device_id: UUID,
    bindings: list[ZigbeeSensorBinding],
) -> dict[str, UUID]:
    """Resolve configured endpoint keys to active sensors.

    The caller owns the transaction. No mapping or sensor is created here.
    Every binding must resolve exactly to an active sensor belonging to the
    supplied tenant and device, with the expected metric and unit.
    """
    if not bindings:
        raise ZigbeeMappingError("at least one sensor binding is required")

    metrics: set[str] = set()
    endpoint_keys: set[str] = set()

    for binding in bindings:
        if not binding.metric or not binding.unit:
            raise ZigbeeMappingError("metric and unit are required")
        if not binding.endpoint_key or len(binding.endpoint_key) > 255:
            raise ZigbeeMappingError("invalid endpoint_key")
        if binding.metric in metrics:
            raise ZigbeeMappingError("duplicate metric binding")
        if binding.endpoint_key in endpoint_keys:
            raise ZigbeeMappingError("duplicate endpoint_key binding")

        metrics.add(binding.metric)
        endpoint_keys.add(binding.endpoint_key)

    resolved: dict[str, UUID] = {}

    statement = text("""
        SELECT
            m.sensor_id,
            s.measurement_type,
            s.unit
        FROM sensor_endpoint_mappings AS m
        JOIN sensors AS s
          ON s.id = m.sensor_id
         AND s.tenant_id = m.tenant_id
         AND s.device_id = m.device_id
        WHERE m.tenant_id = :tenant_id
          AND m.device_id = :device_id
          AND m.adapter_type = 'zigbee'
          AND m.endpoint_key = :endpoint_key
          AND m.mapping_status = 'active'
          AND s.status = 'active'
        FOR SHARE OF m, s
    """)

    for binding in bindings:
        row = (
            db.execute(
                statement,
                {
                    "tenant_id": tenant_id,
                    "device_id": device_id,
                    "endpoint_key": binding.endpoint_key,
                },
            )
            .mappings()
            .first()
        )

        if row is None:
            raise ZigbeeMappingError(
                f"No active Zigbee sensor mapping for metric {binding.metric}"
            )

        if (
            row["measurement_type"] != binding.metric
            or row["unit"] != binding.unit
        ):
            raise ZigbeeMappingError(
                f"Sensor mapping metric or unit mismatch for {binding.metric}"
            )

        sensor_id = row["sensor_id"]
        if not isinstance(sensor_id, UUID):
            sensor_id = UUID(str(sensor_id))

        resolved[binding.metric] = sensor_id

    return resolved


def load_sensor_bindings(
    db: Session,
    *,
    tenant_id: UUID,
    device_id: UUID,
) -> list[ZigbeeSensorBinding]:
    """Load all active Zigbee mappings for one tenant-owned device.

    Ambiguous metric mappings are rejected rather than guessed.
    The caller owns the transaction.
    """
    rows = (
        db.execute(
            text("""
                SELECT
                    m.endpoint_key,
                    s.measurement_type,
                    s.unit
                FROM sensor_endpoint_mappings AS m
                JOIN sensors AS s
                  ON s.id = m.sensor_id
                 AND s.tenant_id = m.tenant_id
                 AND s.device_id = m.device_id
                WHERE m.tenant_id = :tenant_id
                  AND m.device_id = :device_id
                  AND m.adapter_type = 'zigbee'
                  AND m.mapping_status = 'active'
                  AND s.status = 'active'
                ORDER BY s.measurement_type, m.endpoint_key
                FOR SHARE OF m, s
            """),
            {
                "tenant_id": tenant_id,
                "device_id": device_id,
            },
        )
        .mappings()
        .all()
    )

    bindings: list[ZigbeeSensorBinding] = []
    seen_metrics: set[str] = set()
    seen_endpoints: set[str] = set()

    for row in rows:
        metric = row["measurement_type"]
        unit = row["unit"]
        endpoint_key = row["endpoint_key"]

        if not metric or not unit or not endpoint_key:
            raise ZigbeeMappingError("active sensor mapping contains empty fields")
        if len(endpoint_key) > 255:
            raise ZigbeeMappingError("invalid endpoint_key")
        if metric in seen_metrics:
            raise ZigbeeMappingError(
                f"ambiguous active Zigbee mapping for metric: {metric}"
            )
        if endpoint_key in seen_endpoints:
            raise ZigbeeMappingError("duplicate active endpoint_key")

        seen_metrics.add(metric)
        seen_endpoints.add(endpoint_key)
        bindings.append(
            ZigbeeSensorBinding(
                metric=metric,
                unit=unit,
                endpoint_key=endpoint_key,
            )
        )

    if not bindings:
        raise ZigbeeMappingError("no active Zigbee sensor mappings for device")

    return bindings
