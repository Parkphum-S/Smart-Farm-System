"""Tenant-scoped device endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.dependencies import require_tenant_role
from app.db.session import get_db
from app.schemas.device import DeviceResponse


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
