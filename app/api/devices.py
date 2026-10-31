"""Tenant-scoped device endpoints."""

import json
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_tenant_role
from app.db.session import get_db
from app.schemas.device import (
    DeviceCreate, DeviceResponse, DeviceUpdate, DeviceZoneAssignment,
)


router = APIRouter(tags=["devices"])


@router.get(
    "/tenants/{tenant_id}/devices",
    response_model=list[DeviceResponse],
)
def list_devices(
    tenant_id: UUID,
    _role: Annotated[
        str,
        Depends(require_tenant_role("owner", "operator", "viewer")),
    ],
    db: Session = Depends(get_db),
) -> list[DeviceResponse]:
    """List devices belonging to an authorized tenant."""
    try:
        with db.begin():
            rows = (
                db.execute(
                    text(
                        """
                        SELECT
                            id,
                            device_code,
                            device_type,
                            name,
                            status,
                            farm_id,
                            zone_id,
                            platform,
                            protocol,
                            vendor,
                            capabilities,
                            last_seen_at,
                            created_at,
                            updated_at
                        FROM devices
                        WHERE tenant_id = :tenant_id
                        ORDER BY name, id
                        """
                    ),
                    {"tenant_id": tenant_id},
                )
                .mappings()
                .all()
            )
    except DBAPIError:
        raise HTTPException(
            status_code=503,
            detail="Device data temporarily unavailable",
        ) from None

    public_fields = {
        "id",
        "device_code",
        "device_type",
        "name",
        "status",
        "farm_id",
        "zone_id",
        "platform",
        "protocol",
        "vendor",
        "capabilities",
        "last_seen_at",
        "created_at",
        "updated_at",
    }

    return [
        DeviceResponse.model_validate(
            {key: row[key] for key in public_fields if key in row}
        )
        for row in rows
    ]



@router.post(
    "/tenants/{tenant_id}/devices",
    response_model=DeviceResponse,
    status_code=201,
)
def create_device(
    tenant_id: UUID,
    payload: DeviceCreate,
    _role: Annotated[
        str,
        Depends(require_tenant_role("owner", "operator")),
    ],
    db: Session = Depends(get_db),
) -> DeviceResponse:
    """Register a device without creating or exposing device credentials."""
    values = payload.model_dump()
    values["device_code"] = values["device_code"].strip()
    values["device_type"] = values["device_type"].strip()
    values["name"] = values["name"].strip()
    for key in ("platform", "protocol", "vendor"):
        if values[key] is not None:
            values[key] = values[key].strip() or None
    if not values["device_code"] or not values["device_type"] or not values["name"]:
        raise HTTPException(status_code=422, detail="Device fields cannot be blank")

    try:
        values["capabilities"] = json.dumps(
            values["capabilities"], allow_nan=False
        )
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="capabilities must contain valid JSON values",
        ) from None

    try:
        with db.begin():
            if values["farm_id"] is not None:
                farm = db.execute(
                    text("""
                        SELECT id FROM farms
                        WHERE tenant_id = :tenant_id AND id = :farm_id
                    """),
                    {"tenant_id": tenant_id, "farm_id": values["farm_id"]},
                ).first()
                if farm is None:
                    raise HTTPException(status_code=409, detail="Farm not found in this tenant")

            row = db.execute(
                text("""
                    INSERT INTO devices (
                        id, tenant_id, farm_id, device_code,
                        device_type, name, status,
                        platform, protocol, vendor, capabilities
                    )
                    VALUES (
                        :id, :tenant_id, :farm_id, :device_code,
                        :device_type, :name, :status,
                        :platform, :protocol, :vendor,
                        CAST(:capabilities AS jsonb)
                    )
                    RETURNING id, device_code, device_type, name, status,
                              farm_id, zone_id, platform, protocol, vendor,
                              capabilities, last_seen_at, created_at, updated_at
                """),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    **values,
                },
            ).mappings().one()
    except HTTPException:
        raise
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Device code already exists or device references are invalid",
        ) from None
    except DBAPIError:
        raise HTTPException(
            status_code=503,
            detail="Device data temporarily unavailable",
        ) from None

    return DeviceResponse.model_validate(dict(row))


@router.patch(
    "/tenants/{tenant_id}/devices/{device_id}",
    response_model=DeviceResponse,
)
def update_device(
    tenant_id: UUID,
    device_id: UUID,
    payload: DeviceUpdate,
    _role: Annotated[
        str,
        Depends(require_tenant_role("owner", "operator")),
    ],
    db: Session = Depends(get_db),
) -> DeviceResponse:
    """Update editable fields without changing device identity or credentials."""
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="No fields to update")

    for key in ("device_type", "name"):
        if key in changes:
            if changes[key] is None or not changes[key].strip():
                raise HTTPException(status_code=422, detail=f"{key} cannot be blank")
            changes[key] = changes[key].strip()

    for key in ("platform", "protocol", "vendor"):
        if key in changes and changes[key] is not None:
            changes[key] = changes[key].strip() or None

    if "capabilities" in changes:
        if changes["capabilities"] is None:
            raise HTTPException(status_code=422, detail="capabilities cannot be null")
        try:
            changes["capabilities"] = json.dumps(
                changes["capabilities"], allow_nan=False
            )
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="capabilities must contain valid JSON values",
            ) from None

    if any(
        value is None
        for key, value in changes.items()
        if key not in {"farm_id", "platform", "protocol", "vendor"}
    ):
        raise HTTPException(status_code=422, detail="Invalid update value")


    allowed_columns = {
        "device_type", "name", "farm_id", "status", "zone_id",
        "platform", "protocol", "vendor", "capabilities",
    }
    if not set(changes).issubset(allowed_columns):
        raise HTTPException(status_code=422, detail="Unsupported update field")

    try:
        with db.begin():
            current = db.execute(
                text("""
                    SELECT farm_id FROM devices
                    WHERE tenant_id = :tenant_id AND id = :device_id
                    FOR UPDATE
                """),
                {"tenant_id": tenant_id, "device_id": device_id},
            ).mappings().first()

            if current is None:
                row = None
            else:
                if (
                    "farm_id" in changes
                    and current["farm_id"] != changes["farm_id"]
                ):
                    changes["zone_id"] = None

                if changes.get("farm_id") is not None:
                    farm = db.execute(
                        text("""
                            SELECT id FROM farms
                            WHERE tenant_id = :tenant_id AND id = :farm_id
                        """),
                        {
                            "tenant_id": tenant_id,
                            "farm_id": changes["farm_id"],
                        },
                    ).first()
                    if farm is None:
                        raise HTTPException(
                            status_code=409,
                            detail="Farm not found in this tenant",
                        )

                assignments = ", ".join(
                    f"{key} = CAST(:{key} AS jsonb)" if key == "capabilities"
                    else f"{key} = :{key}"
                    for key in changes
                )

                row = db.execute(
                    text(f"""
                        UPDATE devices
                        SET {assignments}, updated_at = CURRENT_TIMESTAMP
                        WHERE tenant_id = :tenant_id AND id = :device_id
                        RETURNING id, device_code, device_type, name, status,
                                  farm_id, zone_id, platform, protocol, vendor,
                                  capabilities, last_seen_at, created_at, updated_at
                    """),
                    {
                        **changes,
                        "tenant_id": tenant_id,
                        "device_id": device_id,
                    },
                ).mappings().first()
    except HTTPException:
        raise
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Device update conflicts with related records",
        ) from None
    except DBAPIError:
        raise HTTPException(
            status_code=503,
            detail="Device data temporarily unavailable",
        ) from None

    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return DeviceResponse.model_validate(dict(row))


@router.patch(
    "/tenants/{tenant_id}/devices/{device_id}/zone",
    response_model=DeviceResponse,
)
def assign_device_zone(
    tenant_id: UUID,
    device_id: UUID,
    payload: DeviceZoneAssignment,
    _role: Annotated[
        str,
        Depends(require_tenant_role("owner", "operator")),
    ],
    db: Session = Depends(get_db),
) -> DeviceResponse:
    """Assign, move, or unassign a device zone within its existing farm."""
    try:
        with db.begin():
            device = (
                db.execute(
                    text(
                        """
                        SELECT id, farm_id
                        FROM devices
                        WHERE tenant_id = :tenant_id AND id = :device_id
                        FOR UPDATE
                        """
                    ),
                    {"tenant_id": tenant_id, "device_id": device_id},
                )
                .mappings()
                .first()
            )
            if device is None:
                raise HTTPException(status_code=404, detail="Device not found")

            if payload.zone_id is not None:
                if device["farm_id"] is None:
                    raise HTTPException(
                        status_code=409,
                        detail="Assign the device to a farm before assigning a zone",
                    )

                zone = (
                    db.execute(
                        text(
                            """
                            SELECT id
                            FROM zones
                            WHERE tenant_id = :tenant_id
                              AND farm_id = :farm_id
                              AND id = :zone_id
                            """
                        ),
                        {
                            "tenant_id": tenant_id,
                            "farm_id": device["farm_id"],
                            "zone_id": payload.zone_id,
                        },
                    )
                    .mappings()
                    .first()
                )
                if zone is None:
                    raise HTTPException(
                        status_code=409,
                        detail="Zone must belong to the device's farm and tenant",
                    )

            updated = (
                db.execute(
                    text(
                        """
                        UPDATE devices
                        SET zone_id = :zone_id,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE tenant_id = :tenant_id AND id = :device_id
                        RETURNING
                            id, device_code, device_type, name, status,
                            farm_id, zone_id, platform, protocol, vendor,
                            capabilities, last_seen_at, created_at, updated_at
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "device_id": device_id,
                        "zone_id": payload.zone_id,
                    },
                )
                .mappings()
                .one()
            )
    except HTTPException:
        raise
    except DBAPIError:
        raise HTTPException(
            status_code=503,
            detail="Device zone assignment temporarily unavailable",
        ) from None

    return DeviceResponse.model_validate(dict(updated))
