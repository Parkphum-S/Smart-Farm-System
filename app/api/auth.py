import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.auth import LoginRequest, LoginResponse, TenantAccessResponse, UserResponse
from app.services.user_auth import (
    AuthenticatedUser,
    authenticate_session,
    login,
    logout,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["authentication"])
bearer_scheme = HTTPBearer(auto_error=False)


def _user_response(user: AuthenticatedUser) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
    )


def _require_bearer(
    credentials: HTTPAuthorizationCredentials | None,
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


@router.post("/login", response_model=LoginResponse)
def login_user(payload: LoginRequest, db: Session = Depends(get_db)):
    try:
        with db.begin():
            result = login(db, str(payload.email), payload.password)
    except DBAPIError as exc:
        logger.error("Login storage error: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="Authentication temporarily unavailable",
        ) from None

    if result.user is None or result.access_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return LoginResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        user=_user_response(result.user),
    )


@router.get("/me", response_model=UserResponse)
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    token = _require_bearer(credentials)
    try:
        with db.begin():
            user = authenticate_session(db, token)
    except DBAPIError as exc:
        logger.error("Session lookup error: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="Authentication temporarily unavailable",
        ) from None

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _user_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    token = _require_bearer(credentials)
    try:
        with db.begin():
            logout(db, token)
    except DBAPIError as exc:
        logger.error("Logout storage error: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="Authentication temporarily unavailable",
        ) from None



@router.get("/tenants", response_model=list[TenantAccessResponse])
def list_current_user_tenants(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    token = _require_bearer(credentials)
    try:
        with db.begin():
            user = authenticate_session(db, token)
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired session",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            rows = db.execute(
                text("""
                    SELECT t.id, t.name, m.role
                    FROM tenant_memberships AS m
                    JOIN tenants AS t ON t.id = m.tenant_id
                    WHERE m.user_id = :user_id
                      AND m.status = 'active'
                      AND t.status = 'active'
                    ORDER BY t.name, t.id
                """),
                {"user_id": user.id},
            ).mappings().all()
    except HTTPException:
        raise
    except DBAPIError:
        logger.error("Tenant listing storage error")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tenant listing temporarily unavailable",
        ) from None

    return [
        TenantAccessResponse(
            id=str(row["id"]),
            name=row["name"],
            role=row["role"],
        )
        for row in rows
    ]
