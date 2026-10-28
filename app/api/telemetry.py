import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.dependencies import require_tenant_role
from app.db.session import get_db
from app.schemas.telemetry import TelemetryEvent
from app.schemas.telemetry_read import TelemetryReadingResponse
from app.security.device_auth import authenticate_device
from app.services.telemetry import (
    EventConflict,
    TelemetryRejected,
    ingest_telemetry,
)


logger = logging.getLogger(__name__)
router = APIRouter(tags=["telemetry"])
bearer_scheme = HTTPBearer(auto_error=False)


@router.post(
    "/telemetry",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a telemetry event",
)
def submit_telemetry(
    event: TelemetryEvent,
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
    db: Session = Depends(get_db),
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        with db.begin():
            identity = authenticate_device(
                db,
                credentials.credentials,
            )
            if identity is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid device credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            result = ingest_telemetry(db, identity, event)

    except TelemetryRejected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Telemetry rejected",
        ) from None
    except EventConflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event ID conflicts with an existing event",
        ) from None
    except DBAPIError as exc:
        logger.error(
            "Telemetry storage error: event_id=%s device_id=%s error=%s",
            event.event_id,
            event.device_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telemetry storage temporarily unavailable",
        ) from None

    return {
        "event_id": str(event.event_id),
        "duplicate": result.duplicate,
    }


@router.get(
    "/tenants/{tenant_id}/telemetry/readings",
    response_model=list[TelemetryReadingResponse],
    summary="Read tenant sensor readings",
)
def list_telemetry_readings(
    tenant_id: UUID,
    _role: Annotated[
        str,
        Depends(require_tenant_role("owner", "operator", "viewer")),
    ],
    sensor_id: UUID | None = None,
    metric: Annotated[str | None, Query(max_length=64)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    latest_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    db: Session = Depends(get_db),
) -> list[TelemetryReadingResponse]:
    """Read recent or historical readings for an authorized tenant."""
    for name, value in (("since", since), ("until", until)):
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise HTTPException(
                status_code=422,
                detail=f"{name} must include a timezone",
            )

    if since is not None and until is not None and since >= until:
        raise HTTPException(
            status_code=422,
            detail="since must be earlier than until",
        )

    clauses = ["r.tenant_id = :tenant_id"]
    params: dict[str, object] = {
        "tenant_id": tenant_id,
        "limit": limit,
    }

    if sensor_id is not None:
        clauses.append("r.sensor_id = :sensor_id")
        params["sensor_id"] = sensor_id
    if metric is not None:
        clauses.append("r.measurement_type = :metric")
        params["metric"] = metric
    if since is not None:
        clauses.append("r.measured_at >= :since")
        params["since"] = since
    if until is not None:
        clauses.append("r.measured_at < :until")
        params["until"] = until

    where_sql = " AND ".join(clauses)
    columns_sql = """
        r.id,
        r.sensor_id,
        s.sensor_code,
        r.device_id,
        d.name AS device_name,
        r.measurement_type AS metric,
        r.value,
        r.unit,
        r.quality_status,
        r.measured_at,
        r.received_at
    """

    if latest_only:
        query = text(f"""
            SELECT *
            FROM (
                SELECT DISTINCT ON (r.sensor_id)
                    {columns_sql}
                FROM sensor_readings AS r
                JOIN sensors AS s
                  ON s.id = r.sensor_id
                 AND s.tenant_id = r.tenant_id
                 AND s.device_id = r.device_id
                JOIN devices AS d
                  ON d.id = r.device_id
                 AND d.tenant_id = r.tenant_id
                WHERE {where_sql}
                ORDER BY r.sensor_id, r.measured_at DESC, r.id DESC
            ) AS latest
            ORDER BY measured_at DESC, id DESC
            LIMIT :limit
        """)
    else:
        query = text(f"""
            SELECT {columns_sql}
            FROM sensor_readings AS r
            JOIN sensors AS s
              ON s.id = r.sensor_id
             AND s.tenant_id = r.tenant_id
             AND s.device_id = r.device_id
            JOIN devices AS d
              ON d.id = r.device_id
             AND d.tenant_id = r.tenant_id
            WHERE {where_sql}
            ORDER BY r.measured_at DESC, r.id DESC
            LIMIT :limit
        """)

    try:
        with db.begin():
            rows = db.execute(query, params).mappings().all()
    except DBAPIError as exc:
        logger.error("Telemetry reading query failed: error=%s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telemetry data temporarily unavailable",
        ) from None

    return [
        TelemetryReadingResponse.model_validate(dict(row))
        for row in rows
    ]
