"""Read-only, streaming queries for telemetry archive exports."""

from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection


EVENTS_SQL = text("""
    SELECT id, tenant_id, device_id, event_id, observed_at, received_at,
           schema_version, payload, payload_hash
    FROM telemetry_events
    WHERE received_at >= :start_at
      AND received_at < :end_at
    ORDER BY received_at, id
""")

READINGS_SQL = text("""
    SELECT r.id, r.tenant_id, r.telemetry_event_id, r.device_id,
           r.sensor_id, r.measured_at, r.received_at,
           r.measurement_type, r.value, r.unit, r.quality_status
    FROM sensor_readings AS r
    JOIN telemetry_events AS e
      ON e.tenant_id = r.tenant_id
     AND e.id = r.telemetry_event_id
     AND e.device_id = r.device_id
    WHERE e.received_at >= :start_at
      AND e.received_at < :end_at
    ORDER BY e.received_at, e.id, r.id
""")


def _validate_range(start_at: datetime, end_at: datetime) -> tuple[datetime, datetime]:
    for name, value in (("start_at", start_at), ("end_at", end_at)):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must be timezone-aware")

    start_utc = start_at.astimezone(timezone.utc)
    end_utc = end_at.astimezone(timezone.utc)
    if start_utc >= end_utc:
        raise ValueError("start_at must be earlier than end_at")

    return start_utc, end_utc


def _stream_query(
    connection: Connection,
    statement,
    start_at: datetime,
    end_at: datetime,
    batch_size: int,
) -> Iterator[dict[str, Any]]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    result = connection.execution_options(
        stream_results=True,
        yield_per=batch_size,
    ).execute(statement, {"start_at": start_at, "end_at": end_at})

    try:
        for partition in result.partitions(batch_size):
            for row in partition:
                yield dict(row._mapping)
    finally:
        result.close()



def iter_events(
    connection: Connection,
    start_at: datetime,
    end_at: datetime,
    *,
    batch_size: int = 1000,
) -> Iterator[dict[str, Any]]:
    """Yield event records in a half-open received_at interval."""
    start_utc, end_utc = _validate_range(start_at, end_at)
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    return _stream_query(
        connection, EVENTS_SQL, start_utc, end_utc, batch_size
    )


def iter_readings(
    connection: Connection,
    start_at: datetime,
    end_at: datetime,
    *,
    batch_size: int = 1000,
) -> Iterator[dict[str, Any]]:
    """Yield readings belonging to events in the same received_at interval."""
    start_utc, end_utc = _validate_range(start_at, end_at)
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    return _stream_query(
        connection, READINGS_SQL, start_utc, end_utc, batch_size
    )
