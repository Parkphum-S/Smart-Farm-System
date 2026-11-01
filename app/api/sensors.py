"""Tenant-scoped sensor registration and metadata endpoints."""

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_tenant_role
from app.db.session import get_db
from app.schemas.sensor import SensorCreate, SensorResponse, SensorStatus, SensorUpdate


router = APIRouter(tags=["sensors"])
SENSOR_COLUMNS = (
    "id, tenant_id, device_id, sensor_code, measurement_type, unit, status, created_at"
)


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="Sensor data temporarily unavailable",
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Sensor not found")


def _response(row) -> SensorResponse:
    return SensorResponse.model_validate(dict(row))


@router.post(
    "/tenants/{tenant_id}/devices/{device_id}/sensors",
    response_model=SensorResponse,
    status_code=201,
)
def create_sensor(
    tenant_id: UUID,
    device_id: UUID,
    payload: SensorCreate,
    _role: Annotated[str, Depends(require_tenant_role("owner", "operator"))],
    db: Session = Depends(get_db),
) -> SensorResponse:
    sensor_code = payload.sensor_code
    if sensor_code is None:
        prefixes = {
            "temperature": "TEMP",
            "humidity": "HUM",
            "soil_moisture": "SOIL",
        }
        prefix = prefixes.get(payload.measurement_type, "SEN")
        sensor_code = f"{prefix}-{uuid4().hex[:8].upper()}"

    try:
        with db.begin():
            device = db.execute(
                text("""
                    SELECT id FROM devices
                    WHERE tenant_id = :tenant_id AND id = :device_id
                """),
                {"tenant_id": tenant_id, "device_id": device_id},
            ).first()

            if device is None:
                raise HTTPException(status_code=404, detail="Device not found")

            row = db.execute(
                text(f"""
                    INSERT INTO sensors (
                        id, tenant_id, device_id, sensor_code,
                        measurement_type, unit, status
                    )
                    VALUES (
                        :id, :tenant_id, :device_id, :sensor_code,
                        :measurement_type, :unit, 'active'
                    )
                    RETURNING {SENSOR_COLUMNS}
                """),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "device_id": device_id,
                    "sensor_code": sensor_code,
                    "measurement_type": payload.measurement_type,
                    "unit": payload.unit,
                },
            ).mappings().one()

    except HTTPException:
        raise
    except IntegrityError as exc:
        if "uq_sensors_device_code" in str(exc.orig):
            raise HTTPException(
                status_code=409,
                detail="Sensor code already exists for this device",
            ) from None
        raise HTTPException(
            status_code=409,
            detail="Sensor references are invalid",
        ) from None
    except DBAPIError:
        raise _unavailable() from None

    return _response(row)


@router.get(
    "/tenants/{tenant_id}/devices/{device_id}/sensors",
    response_model=list[SensorResponse],
)
def list_sensors(
    tenant_id: UUID,
    device_id: UUID,
    _role: Annotated[
        str, Depends(require_tenant_role("owner", "operator", "viewer"))
    ],
    sensor_status: Annotated[SensorStatus | None, Query(alias="status")] = None,
    measurement_type: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> list[SensorResponse]:
    query = f"""
        SELECT {SENSOR_COLUMNS}
        FROM sensors
        WHERE tenant_id = :tenant_id AND device_id = :device_id
    """
    params = {
        "tenant_id": tenant_id,
        "device_id": device_id,
        "limit": limit,
        "offset": offset,
    }

    if sensor_status is not None:
        query += " AND status = :status"
        params["status"] = sensor_status

    if measurement_type is not None:
        value = measurement_type.strip()
        if not value:
            raise HTTPException(
                status_code=422,
                detail="measurement_type cannot be blank",
            )
        query += " AND measurement_type = :measurement_type"
        params["measurement_type"] = value

    query += " ORDER BY sensor_code, id LIMIT :limit OFFSET :offset"

    try:
        with db.begin():
            rows = db.execute(text(query), params).mappings().all()
    except DBAPIError:
        raise _unavailable() from None

    return [_response(row) for row in rows]


@router.get(
    "/tenants/{tenant_id}/devices/{device_id}/sensors/{sensor_id}",
    response_model=SensorResponse,
)
def get_sensor(
    tenant_id: UUID,
    device_id: UUID,
    sensor_id: UUID,
    _role: Annotated[
        str, Depends(require_tenant_role("owner", "operator", "viewer"))
    ],
    db: Session = Depends(get_db),
) -> SensorResponse:
    try:
        with db.begin():
            row = db.execute(
                text(f"""
                    SELECT {SENSOR_COLUMNS}
                    FROM sensors
                    WHERE tenant_id = :tenant_id
                      AND device_id = :device_id
                      AND id = :sensor_id
                """),
                {
                    "tenant_id": tenant_id,
                    "device_id": device_id,
                    "sensor_id": sensor_id,
                },
            ).mappings().first()
    except DBAPIError:
        raise _unavailable() from None

    if row is None:
        raise _not_found()

    return _response(row)


@router.patch(
    "/tenants/{tenant_id}/devices/{device_id}/sensors/{sensor_id}",
    response_model=SensorResponse,
)
def update_sensor(
    tenant_id: UUID,
    device_id: UUID,
    sensor_id: UUID,
    payload: SensorUpdate,
    _role: Annotated[str, Depends(require_tenant_role("owner", "operator"))],
    db: Session = Depends(get_db),
) -> SensorResponse:
    changes = payload.model_dump(exclude_unset=True)

    if not changes:
        raise HTTPException(status_code=422, detail="No fields to update")

    if any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="Update values cannot be null")

    try:
        with db.begin():
            current = db.execute(
                text("""
                    SELECT status
                    FROM sensors
                    WHERE tenant_id = :tenant_id
                      AND device_id = :device_id
                      AND id = :sensor_id
                    FOR UPDATE
                """),
                {
                    "tenant_id": tenant_id,
                    "device_id": device_id,
                    "sensor_id": sensor_id,
                },
            ).mappings().first()

            if current is None:
                raise _not_found()

            requested_status = changes.get("status")
            if (
                current["status"] == "retired"
                and requested_status not in (None, "retired")
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Retired sensors cannot be reactivated",
                )

            if "measurement_type" in changes or "unit" in changes:
                has_readings = db.execute(
                    text("""
                        SELECT EXISTS (
                            SELECT 1
                            FROM sensor_readings
                            WHERE tenant_id = :tenant_id
                              AND device_id = :device_id
                              AND sensor_id = :sensor_id
                        )
                    """),
                    {
                        "tenant_id": tenant_id,
                        "device_id": device_id,
                        "sensor_id": sensor_id,
                    },
                ).scalar_one()

                if has_readings:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Measurement type and unit are immutable "
                            "after readings exist"
                        ),
                    )

            assignments = ", ".join(
                f"{key} = :{key}" for key in changes
            )

            row = db.execute(
                text(f"""
                    UPDATE sensors
                    SET {assignments}
                    WHERE tenant_id = :tenant_id
                      AND device_id = :device_id
                      AND id = :sensor_id
                    RETURNING {SENSOR_COLUMNS}
                """),
                {
                    **changes,
                    "tenant_id": tenant_id,
                    "device_id": device_id,
                    "sensor_id": sensor_id,
                },
            ).mappings().one()

    except HTTPException:
        raise
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Sensor update conflicts with related records",
        ) from None
    except DBAPIError:
        raise _unavailable() from None

    return _response(row)
