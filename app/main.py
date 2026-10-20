from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.v1 import router as v1_router
from app.core.config import settings


app = FastAPI(title=settings.app_name)
app.include_router(health_router)
app.include_router(v1_router)
