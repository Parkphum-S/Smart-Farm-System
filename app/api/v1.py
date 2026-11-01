from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.devices import router as devices_router
from app.api.commands import router as commands_router
from app.api.farms import router as farms_router
from app.api.weather import router as weather_router
from app.api.telemetry import router as telemetry_router
from app.api.zones import router as zones_router
from app.api.sensors import router as sensors_router
from app.api.sensor_mappings import router as sensor_mappings_router


router = APIRouter(prefix="/api/v1")
router.include_router(telemetry_router)
router.include_router(auth_router)
router.include_router(farms_router)
router.include_router(weather_router)
router.include_router(devices_router)
router.include_router(commands_router)
router.include_router(zones_router)
router.include_router(sensors_router)
router.include_router(sensor_mappings_router)
