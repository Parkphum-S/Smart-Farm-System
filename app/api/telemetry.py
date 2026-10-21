import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.telemetry import TelemetryEvent
from app.security.device_auth import authenticate_device
from app.services.telemetry import (
    EventConflict,
    TelemetryRejected,
    ingest_telemetry,
)


logger = logging.getLogger(__name__)
router = APIRouter(tags=["telemetry"])
bearer_scheme = HTTPBearer(auto_error=False)


@router.post(
    "/telemetry",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a telemetry event",
)
def submit_telemetry(
    event: TelemetryEvent,
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
    db: Session = Depends(get_db),
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        with db.begin():
            identity = authenticate_device(
                db,
                credentials.credentials,
            )
            if identity is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid device credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            result = ingest_telemetry(db, identity, event)

    except TelemetryRejected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Telemetry rejected",
        ) from None
    except EventConflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event ID conflicts with an existing event",
        ) from None
    except DBAPIError as exc:
        logger.error(
            "Telemetry storage error: event_id=%s device_id=%s error=%s",
            event.event_id,
            event.device_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telemetry storage temporarily unavailable",
        ) from None

    return {
        "event_id": str(event.event_id),
        "duplicate": result.duplicate,
    }
