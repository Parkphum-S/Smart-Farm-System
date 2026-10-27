"""Tenant-scoped farm endpoints."""
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_tenant_role
from app.db.session import get_db
from app.schemas.farm import FarmCreate, FarmResponse, FarmUpdate


router = APIRouter(tags=["farms"])


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="Farm data temporarily unavailable",
    )


def _referenced_farm(exc: IntegrityError) -> bool:
    """Identify foreign-key failures without exposing database internals."""
    orig = exc.orig
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return sqlstate == "23503"


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
        raise _unavailable() from None

    return [FarmResponse.model_validate(dict(row)) for row in rows]


@router.post(
    "/tenants/{tenant_id}/farms",
    response_model=FarmResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_farm(
    tenant_id: UUID,
    payload: FarmCreate,
    _role: Annotated[
        str, Depends(require_tenant_role("owner", "operator"))
    ],
    db: Session = Depends(get_db),
) -> FarmResponse:
    """Create a farm inside the authorized tenant."""
    try:
        with db.begin():
            row = (
                db.execute(
                    text(
                        """
                        INSERT INTO farms (id, tenant_id, name, timezone)
                        VALUES (:id, :tenant_id, :name, :timezone)
                        RETURNING id, name, timezone, created_at, updated_at
                        """
                    ),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "name": payload.name,
                        "timezone": payload.timezone,
                    },
                )
                .mappings()
                .one()
            )
    except IntegrityError:
        raise _unavailable() from None
    except DBAPIError:
        raise _unavailable() from None

    return FarmResponse.model_validate(dict(row))


@router.patch(
    "/tenants/{tenant_id}/farms/{farm_id}",
    response_model=FarmResponse,
)
def update_farm(
    tenant_id: UUID,
    farm_id: UUID,
    payload: FarmUpdate,
    _role: Annotated[
        str, Depends(require_tenant_role("owner", "operator"))
    ],
    db: Session = Depends(get_db),
) -> FarmResponse:
    """Update only the named farm belonging to the authorized tenant."""
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="No fields to update")
    if any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="Invalid update value")

    assignments = ", ".join(f"{key} = :{key}" for key in changes)
    try:
        with db.begin():
            row = (
                db.execute(
                    text(
                        f"""
                        UPDATE farms
                        SET {assignments}, updated_at = now()
                        WHERE tenant_id = :tenant_id AND id = :farm_id
                        RETURNING id, name, timezone, created_at, updated_at
                        """
                    ),
                    {
                        **changes,
                        "tenant_id": tenant_id,
                        "farm_id": farm_id,
                    },
                )
                .mappings()
                .first()
            )
    except DBAPIError:
        raise _unavailable() from None

    if row is None:
        raise HTTPException(status_code=404, detail="Farm not found")
    return FarmResponse.model_validate(dict(row))


@router.delete(
    "/tenants/{tenant_id}/farms/{farm_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_farm(
    tenant_id: UUID,
    farm_id: UUID,
    _role: Annotated[
        str, Depends(require_tenant_role("owner", "operator"))
    ],
    db: Session = Depends(get_db),
) -> Response:
    """Delete an unreferenced farm; never cascade into related records."""
    try:
        with db.begin():
            result = db.execute(
                text(
                    """
                    DELETE FROM farms
                    WHERE tenant_id = :tenant_id AND id = :farm_id
                    """
                ),
                {"tenant_id": tenant_id, "farm_id": farm_id},
            )
    except IntegrityError as exc:
        if _referenced_farm(exc):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Farm cannot be deleted while zones or devices reference it"
                ),
            ) from None
        raise _unavailable() from None
    except DBAPIError:
        raise _unavailable() from None

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Farm not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
