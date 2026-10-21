from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.v1 import router as v1_router
from app.core.config import settings


_is_production = settings.environment.lower() == "production"

app = FastAPI(
    title=settings.app_name,
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)
app.include_router(health_router)
app.include_router(v1_router)
