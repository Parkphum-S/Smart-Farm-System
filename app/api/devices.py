"""Tenant-scoped device endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.dependencies import require_tenant_role
from app.db.session import get_db
from app.schemas.device import DeviceResponse, DeviceZoneAssignment


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
                            farm_id, zone_id, last_seen_at, created_at, updated_at
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
