from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.farms import router as farms_router
from app.api.telemetry import router as telemetry_router


router = APIRouter(prefix="/api/v1")
router.include_router(telemetry_router)
router.include_router(auth_router)
router.include_router(farms_router)
