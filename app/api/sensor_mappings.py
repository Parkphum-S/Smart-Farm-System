"""Tenant-scoped sensor endpoint mapping endpoints."""

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_tenant_role
from app.db.session import get_db
from app.schemas.sensor_mapping import (
    SensorMappingCreate,
    SensorMappingResponse,
    SensorMappingUpdate,
)


router = APIRouter(tags=["sensor-mappings"])
MAPPING_COLUMNS = (
    "id, tenant_id, device_id, sensor_id, adapter_type, endpoint_key, "
    "mapping_status, created_at, updated_at"
)


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="Sensor mapping data temporarily unavailable",
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Sensor mapping not found")


def _response(row) -> SensorMappingResponse:
    return SensorMappingResponse.model_validate(dict(row))


def _validate_sensor(db, tenant_id, device_id, sensor_id, mapping_status):
    sensor = db.execute(
        text("""
            SELECT status
            FROM sensors
            WHERE tenant_id = :tenant_id
              AND device_id = :device_id
              AND id = :sensor_id
            FOR SHARE
        """),
        {
            "tenant_id": tenant_id,
            "device_id": device_id,
            "sensor_id": sensor_id,
        },
    ).mappings().first()

    if sensor is None:
        raise HTTPException(status_code=404, detail="Sensor not found")

    if mapping_status == "active" and sensor["status"] != "active":
        raise HTTPException(
            status_code=409,
            detail="Active mappings require an active sensor",
        )


@router.post(
    "/tenants/{tenant_id}/devices/{device_id}/sensor-mappings",
    response_model=SensorMappingResponse,
    status_code=201,
)
def create_sensor_mapping(
    tenant_id: UUID,
    device_id: UUID,
    payload: SensorMappingCreate,
    _role: Annotated[str, Depends(require_tenant_role("owner", "operator"))],
    db: Session = Depends(get_db),
) -> SensorMappingResponse:
    try:
        with db.begin():
            _validate_sensor(
                db,
                tenant_id,
                device_id,
                payload.sensor_id,
                payload.mapping_status,
            )

            row = db.execute(
                text(f"""
                    INSERT INTO sensor_endpoint_mappings (
                        id, tenant_id, device_id, sensor_id,
                        adapter_type, endpoint_key, mapping_status
                    )
                    VALUES (
                        :id, :tenant_id, :device_id, :sensor_id,
                        :adapter_type, :endpoint_key, :mapping_status
                    )
                    RETURNING {MAPPING_COLUMNS}
                """),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "device_id": device_id,
                    **payload.model_dump(),
                },
            ).mappings().one()

    except HTTPException:
        raise
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Sensor mapping conflicts with an existing mapping or reference",
        ) from None
    except DBAPIError:
        raise _unavailable() from None

    return _response(row)


@router.get(
    "/tenants/{tenant_id}/devices/{device_id}/sensor-mappings",
    response_model=list[SensorMappingResponse],
)
def list_sensor_mappings(
    tenant_id: UUID,
    device_id: UUID,
    _role: Annotated[
        str, Depends(require_tenant_role("owner", "operator", "viewer"))
    ],
    mapping_status: Annotated[str | None, Query(alias="status")] = None,
    adapter_type: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> list[SensorMappingResponse]:
    query = f"""
        SELECT {MAPPING_COLUMNS}
        FROM sensor_endpoint_mappings
        WHERE tenant_id = :tenant_id AND device_id = :device_id
    """
    params = {
        "tenant_id": tenant_id,
        "device_id": device_id,
        "limit": limit,
        "offset": offset,
    }

    if mapping_status is not None:
        if mapping_status not in ("active", "disabled"):
            raise HTTPException(status_code=422, detail="Invalid mapping status")
        query += " AND mapping_status = :mapping_status"
        params["mapping_status"] = mapping_status

    if adapter_type is not None:
        adapter_type = adapter_type.strip().lower()
        if not adapter_type:
            raise HTTPException(status_code=422, detail="adapter_type cannot be blank")
        query += " AND adapter_type = :adapter_type"
        params["adapter_type"] = adapter_type

    query += " ORDER BY adapter_type, endpoint_key, id LIMIT :limit OFFSET :offset"

    try:
        with db.begin():
            rows = db.execute(text(query), params).mappings().all()
    except DBAPIError:
        raise _unavailable() from None

    return [_response(row) for row in rows]


@router.get(
    "/tenants/{tenant_id}/devices/{device_id}/sensor-mappings/{mapping_id}",
    response_model=SensorMappingResponse,
)
def get_sensor_mapping(
    tenant_id: UUID,
    device_id: UUID,
    mapping_id: UUID,
    _role: Annotated[
        str, Depends(require_tenant_role("owner", "operator", "viewer"))
    ],
    db: Session = Depends(get_db),
) -> SensorMappingResponse:
    try:
        with db.begin():
            row = db.execute(
                text(f"""
                    SELECT {MAPPING_COLUMNS}
                    FROM sensor_endpoint_mappings
                    WHERE tenant_id = :tenant_id
                      AND device_id = :device_id
                      AND id = :mapping_id
                """),
                {
                    "tenant_id": tenant_id,
                    "device_id": device_id,
                    "mapping_id": mapping_id,
                },
            ).mappings().first()
    except DBAPIError:
        raise _unavailable() from None

    if row is None:
        raise _not_found()

    return _response(row)


@router.patch(
    "/tenants/{tenant_id}/devices/{device_id}/sensor-mappings/{mapping_id}",
    response_model=SensorMappingResponse,
)
def update_sensor_mapping(
    tenant_id: UUID,
    device_id: UUID,
    mapping_id: UUID,
    payload: SensorMappingUpdate,
    _role: Annotated[str, Depends(require_tenant_role("owner", "operator"))],
    db: Session = Depends(get_db),
) -> SensorMappingResponse:
    changes = payload.model_dump(exclude_unset=True)

    if not changes:
        raise HTTPException(status_code=422, detail="No fields to update")

    if any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="Update values cannot be null")

    try:
        with db.begin():
            current = db.execute(
                text(f"""
                    SELECT {MAPPING_COLUMNS}
                    FROM sensor_endpoint_mappings
                    WHERE tenant_id = :tenant_id
                      AND device_id = :device_id
                      AND id = :mapping_id
                    FOR UPDATE
                """),
                {
                    "tenant_id": tenant_id,
                    "device_id": device_id,
                    "mapping_id": mapping_id,
                },
            ).mappings().first()

            if current is None:
                raise _not_found()

            sensor_id = changes.get("sensor_id", current["sensor_id"])
            mapping_status = changes.get(
                "mapping_status", current["mapping_status"]
            )
            _validate_sensor(
                db, tenant_id, device_id, sensor_id, mapping_status
            )

            assignments = ", ".join(
                f"{key} = :{key}" for key in changes
            )
            assignments += ", updated_at = now()"

            row = db.execute(
                text(f"""
                    UPDATE sensor_endpoint_mappings
                    SET {assignments}
                    WHERE tenant_id = :tenant_id
                      AND device_id = :device_id
                      AND id = :mapping_id
                    RETURNING {MAPPING_COLUMNS}
                """),
                {
                    **changes,
                    "tenant_id": tenant_id,
                    "device_id": device_id,
                    "mapping_id": mapping_id,
                },
            ).mappings().one()

    except HTTPException:
        raise
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Sensor mapping conflicts with an existing mapping or reference",
        ) from None
    except DBAPIError:
        raise _unavailable() from None

    return _response(row)
