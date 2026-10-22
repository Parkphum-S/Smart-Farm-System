import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.auth import LoginRequest, LoginResponse, UserResponse
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
