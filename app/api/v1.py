from fastapi import APIRouter

from app.api.telemetry import router as telemetry_router


router = APIRouter(prefix="/api/v1")
router.include_router(telemetry_router)
