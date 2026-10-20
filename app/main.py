from fastapi import FastAPI

from app.core.config import settings


app = FastAPI(title=settings.app_name)


@app.get("/health/live", tags=["health"])
def health_live() -> dict[str, str]:
    return {"status": "ok"}
