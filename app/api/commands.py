"""Tenant-authorized command API and device command endpoints."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.dependencies import get_authenticated_user, require_tenant_role
from app.db.session import get_db
from app.schemas.commands import CommandCreate, CommandEventCreate, CommandResponse
from app.security.device_auth import authenticate_device
from app.services.commands import (
    CommandConflict,
    CommandExpired,
    CommandNotFound,
    CommandRejected,
    create_command,
    pending_commands,
    record_command_event,
)
from app.services.user_auth import AuthenticatedUser

logger = logging.getLogger(__name__)
router = APIRouter(tags=["commands"])
bearer_scheme = HTTPBearer(auto_error=False)


def _require_device_credentials(credentials):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Device authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials


def _device_identity(credentials, db):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Device authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    identity = authenticate_device(db, credentials.credentials)
    if identity is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid device credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return identity


def _command_response(row: dict) -> CommandResponse:
    # Never expose internal database columns through the public API.
    allowed = {
        "id",
        "device_id",
        "command_type",
        "parameters",
        "status",
        "created_at",
        "expires_at",
        "updated_at",
        "correlation_id",
        "result_summary",
    }
    return CommandResponse.model_validate(
        {key: row[key] for key in allowed if key in row}
    )


def _database_unavailable(operation: str) -> HTTPException:
    logger.warning("Command API database error: operation=%s", operation)
    return HTTPException(
        status_code=503,
        detail="Command service temporarily unavailable",
    )


@router.post(
    "/tenants/{tenant_id}/devices/{device_id}/commands",
    summary="Create a relay command",
)
def submit_command(
    tenant_id: UUID,
    device_id: UUID,
    request: CommandCreate,
    response: Response,
    role: Annotated[
        str, Depends(require_tenant_role("owner", "operator"))
    ],
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    db: Session = Depends(get_db),
) -> dict:
    del role
    try:
        user_id = UUID(str(user.id))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(
            status_code=401,
            detail="Invalid session identity",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    try:
        with db.begin():
            row, duplicate = create_command(
                db,
                tenant_id=tenant_id,
                device_id=device_id,
                user_id=user_id,
                request=request,
            )
    except CommandConflict:
        raise HTTPException(
            status_code=409,
            detail="Idempotency key conflicts with an existing command",
        ) from None
    except CommandRejected:
        raise HTTPException(
            status_code=403,
            detail="Command rejected for this device",
        ) from None
    except DBAPIError:
        raise _database_unavailable("create") from None

    response.status_code = status.HTTP_200_OK if duplicate else status.HTTP_201_CREATED
    return {"command": _command_response(row), "duplicate": duplicate}


@router.get("/commands/pending", summary="Poll commands for the authenticated device")
def get_pending_commands(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    db: Session = Depends(get_db),
) -> dict:
    _require_device_credentials(credentials)
    try:
        with db.begin():
            identity = _device_identity(credentials, db)
            rows = pending_commands(db, identity, limit=limit)
    except HTTPException:
        raise
    except DBAPIError:
        raise _database_unavailable("poll") from None

    return {"commands": [_command_response(row) for row in rows]}


@router.post(
    "/commands/{command_id}/events",
    summary="Report a command event from the authenticated device",
)
def submit_command_event(
    command_id: UUID,
    event: CommandEventCreate,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    db: Session = Depends(get_db),
) -> dict:
    _require_device_credentials(credentials)
    try:
        with db.begin():
            identity = _device_identity(credentials, db)
            row, duplicate = record_command_event(
                db, identity, command_id, event
            )
    except HTTPException:
        raise
    except CommandNotFound:
        raise HTTPException(
            status_code=404,
            detail="Command not found for this device",
        ) from None
    except CommandExpired:
        raise HTTPException(
            status_code=409,
            detail="Command has expired",
        ) from None
    except CommandConflict:
        raise HTTPException(
            status_code=409,
            detail="Command event conflicts with existing state",
        ) from None
    except CommandRejected:
        raise HTTPException(
            status_code=422,
            detail="Command event details rejected",
        ) from None
    except DBAPIError:
        raise _database_unavailable("event") from None

    return {"command": _command_response(row), "duplicate": duplicate}


@router.get(
    "/tenants/{tenant_id}/devices/{device_id}/commands",
    summary="List command history for a device",
)
def list_device_commands(
    tenant_id: UUID,
    device_id: UUID,
    role: Annotated[
        str, Depends(require_tenant_role("owner", "operator", "viewer"))
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    db: Session = Depends(get_db),
) -> dict:
    del role
    try:
        with db.begin():
            rows = (
                db.execute(
                    text("""
                        SELECT *
                        FROM commands
                        WHERE tenant_id = :tenant_id
                          AND device_id = :device_id
                        ORDER BY created_at DESC, id DESC
                        LIMIT :limit
                    """),
                    {
                        "tenant_id": tenant_id,
                        "device_id": device_id,
                        "limit": limit,
                    },
                )
                .mappings()
                .all()
            )
    except DBAPIError:
        raise _database_unavailable("history") from None

    return {"commands": [_command_response(dict(row)) for row in rows]}
