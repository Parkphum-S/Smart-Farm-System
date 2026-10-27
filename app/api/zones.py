"""Tenant-scoped zone endpoints."""

import json
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_tenant_role
from app.db.session import get_db
from app.schemas.zone import ZoneCreate, ZoneResponse, ZoneUpdate


router = APIRouter(tags=["zones"])


def _unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="Zone data temporarily unavailable")


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Zone not found")


def _duplicate(exc: IntegrityError) -> bool:
    return "uq_zones_tenant_farm_name" in str(exc.orig)


@router.get(
    "/tenants/{tenant_id}/farms/{farm_id}/zones",
    response_model=list[ZoneResponse],
)
def list_zones(
    tenant_id: UUID,
    farm_id: UUID,
    _role: Annotated[
        str, Depends(require_tenant_role("owner", "operator", "viewer"))
    ],
    q: Annotated[str | None, Query(max_length=120)] = None,
    db: Session = Depends(get_db),
) -> list[ZoneResponse]:
    query = (
        "SELECT id, tenant_id, farm_id, name, description, "
        "status, zone_type, category_details, created_at, updated_at FROM zones "
        "WHERE tenant_id = :tenant_id AND farm_id = :farm_id"
    )
    params = {
        "tenant_id": tenant_id,
        "farm_id": farm_id,
    }

    if q is not None:
        query += " AND name ILIKE :pattern"
        params["pattern"] = f"%{q}%"

    query += " ORDER BY name, id"

    try:
        with db.begin():
            rows = db.execute(text(query), params).mappings().all()
    except DBAPIError:
        raise _unavailable() from None
    return [ZoneResponse.model_validate(dict(row)) for row in rows]


@router.post(
    "/tenants/{tenant_id}/farms/{farm_id}/zones",
    response_model=ZoneResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_zone(
    tenant_id: UUID,
    farm_id: UUID,
    payload: ZoneCreate,
    _role: Annotated[str, Depends(require_tenant_role("owner", "operator"))],
    db: Session = Depends(get_db),
) -> ZoneResponse:
    try:
        with db.begin():
            farm = db.execute(
                text(
                    "SELECT id FROM farms "
                    "WHERE tenant_id = :tenant_id AND id = :farm_id"
                ),
                {"tenant_id": tenant_id, "farm_id": farm_id},
            ).first()
            if farm is None:
                raise HTTPException(status_code=404, detail="Farm not found")

            row = db.execute(
                text(
                    "INSERT INTO zones "
                    "(id, tenant_id, farm_id, name, description, status, "
                    "zone_type, category_details) "
                    "VALUES (:id, :tenant_id, :farm_id, :name, "
                    ":description, :status, :zone_type, "
                    "CAST(:category_details AS jsonb)) "
                    "RETURNING id, tenant_id, farm_id, name, description, "
                    "status, zone_type, category_details, created_at, updated_at"
                ),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "farm_id": farm_id,
                    "name": payload.name,
                    "description": payload.description,
                    "status": payload.status,
                    "zone_type": payload.zone_type,
                    "category_details": json.dumps(
                        payload.category_details, ensure_ascii=False
                    ),
                },
            ).mappings().one()
    except IntegrityError as exc:
        if _duplicate(exc):
            raise HTTPException(
                status_code=409, detail="A zone with this name already exists"
            ) from None
        raise _unavailable() from None
    except DBAPIError:
        raise _unavailable() from None
    return ZoneResponse.model_validate(dict(row))


@router.get(
    "/tenants/{tenant_id}/farms/{farm_id}/zones/{zone_id}",
    response_model=ZoneResponse,
)
def get_zone(
    tenant_id: UUID,
    farm_id: UUID,
    zone_id: UUID,
    _role: Annotated[
        str, Depends(require_tenant_role("owner", "operator", "viewer"))
    ],
    db: Session = Depends(get_db),
) -> ZoneResponse:
    try:
        with db.begin():
            row = db.execute(
                text(
                    "SELECT id, tenant_id, farm_id, name, description, "
                    "status, zone_type, category_details, created_at, updated_at FROM zones "
                    "WHERE tenant_id = :tenant_id AND farm_id = :farm_id "
                    "AND id = :zone_id"
                ),
                {
                    "tenant_id": tenant_id,
                    "farm_id": farm_id,
                    "zone_id": zone_id,
                },
            ).mappings().first()
    except DBAPIError:
        raise _unavailable() from None
    if row is None:
        raise _not_found()
    return ZoneResponse.model_validate(dict(row))


@router.patch(
    "/tenants/{tenant_id}/farms/{farm_id}/zones/{zone_id}",
    response_model=ZoneResponse,
)
def update_zone(
    tenant_id: UUID,
    farm_id: UUID,
    zone_id: UUID,
    payload: ZoneUpdate,
    _role: Annotated[str, Depends(require_tenant_role("owner", "operator"))],
    db: Session = Depends(get_db),
) -> ZoneResponse:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="No fields to update")
    if any(
        value is None for key, value in changes.items() if key != "description"
    ):
        raise HTTPException(status_code=422, detail="Invalid update value")

    if "category_details" in changes:
        if changes["category_details"] is None:
            raise HTTPException(status_code=422, detail="Invalid update value")
        changes["category_details"] = json.dumps(
            changes["category_details"], ensure_ascii=False
        )

    assignments = ", ".join(
        (
            f"{key} = CAST(:{key} AS jsonb)"
            if key == "category_details"
            else f"{key} = :{key}"
        )
        for key in changes
    )
    try:
        with db.begin():
            row = db.execute(
                text(
                    f"UPDATE zones SET {assignments}, updated_at = now() "
                    "WHERE tenant_id = :tenant_id AND farm_id = :farm_id "
                    "AND id = :zone_id "
                    "RETURNING id, tenant_id, farm_id, name, description, "
                    "status, zone_type, category_details, created_at, updated_at"
                ),
                {
                    **changes,
                    "tenant_id": tenant_id,
                    "farm_id": farm_id,
                    "zone_id": zone_id,
                },
            ).mappings().first()
    except IntegrityError as exc:
        if _duplicate(exc):
            raise HTTPException(
                status_code=409, detail="A zone with this name already exists"
            ) from None
        raise _unavailable() from None
    except DBAPIError:
        raise _unavailable() from None
    if row is None:
        raise _not_found()
    return ZoneResponse.model_validate(dict(row))


@router.delete(
    "/tenants/{tenant_id}/farms/{farm_id}/zones/{zone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_zone(
    tenant_id: UUID,
    farm_id: UUID,
    zone_id: UUID,
    _role: Annotated[str, Depends(require_tenant_role("owner", "operator"))],
    db: Session = Depends(get_db),
) -> Response:
    try:
        with db.begin():
            result = db.execute(
                text(
                    "DELETE FROM zones WHERE tenant_id = :tenant_id "
                    "AND farm_id = :farm_id AND id = :zone_id"
                ),
                {
                    "tenant_id": tenant_id,
                    "farm_id": farm_id,
                    "zone_id": zone_id,
                },
            )
    except DBAPIError:
        raise _unavailable() from None
    if result.rowcount == 0:
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
