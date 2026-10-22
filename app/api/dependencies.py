"""Reusable authentication and tenant authorization dependencies."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.authorization import VALID_ROLES, authorize_tenant
from app.services.user_auth import AuthenticatedUser, authenticate_session


bearer_scheme = HTTPBearer(auto_error=False)


def get_authenticated_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    db: Session = Depends(get_db),
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        with db.begin():
            user = authenticate_session(db, credentials.credentials)
    except DBAPIError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication temporarily unavailable",
        ) from None

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_tenant_role(*allowed_roles: str) -> Callable:
    roles = set(allowed_roles)
    if not roles or not roles.issubset(VALID_ROLES):
        raise ValueError("allowed_roles must contain valid tenant roles")

    def dependency(
        tenant_id: Annotated[str, Path()],
        user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
        db: Session = Depends(get_db),
    ) -> str:
        try:
            with db.begin():
                return authorize_tenant(db, user.id, tenant_id, roles)
        except HTTPException:
            raise
        except DBAPIError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authorization temporarily unavailable",
            ) from None

    return dependency
