"""Tenant-scoped farm endpoints."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.dependencies import require_tenant_role
from app.db.session import get_db
from app.schemas.farm import FarmResponse


router = APIRouter(tags=["farms"])


@router.get(
    "/tenants/{tenant_id}/farms",
    response_model=list[FarmResponse],
)
def list_farms(
    tenant_id: UUID,
    _role: Annotated[
        str,
        Depends(require_tenant_role("owner", "operator", "viewer")),
    ],
    db: Session = Depends(get_db),
) -> list[FarmResponse]:
    """List farms belonging to an authorized tenant."""
    try:
        with db.begin():
            rows = (
                db.execute(
                    text(
                        """
                        SELECT id, name, timezone, created_at, updated_at
                        FROM farms
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
            detail="Farm data temporarily unavailable",
        ) from None

    return [FarmResponse.model_validate(dict(row)) for row in rows]
