"""Weather endpoint using the selected farm's stored coordinates."""
from datetime import datetime, timezone
from math import isfinite
from threading import Lock
from time import monotonic
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.dependencies import require_tenant_role
from app.core.config import settings
from app.db.session import get_db


router = APIRouter(tags=["weather"])

_CACHE_TTL_SECONDS = 600
_CACHE_MAX_ITEMS = 256
_cache: dict[tuple[str, float, float], tuple[float, dict]] = {}
_cache_lock = Lock()


def _get_cached(key):
    now = monotonic()
    with _cache_lock:
        item = _cache.get(key)
        if item is None:
            return None
        expires, value = item
        if expires <= now:
            _cache.pop(key, None)
            return None
        return dict(value)


def _store_cached(key, value):
    now = monotonic()
    with _cache_lock:
        expired = [k for k, (expiry, _) in _cache.items() if expiry <= now]
        for old_key in expired:
            _cache.pop(old_key, None)
        if len(_cache) >= _CACHE_MAX_ITEMS and key not in _cache:
            oldest = min(_cache, key=lambda k: _cache[k][0])
            _cache.pop(oldest, None)
        _cache[key] = (now + _CACHE_TTL_SECONDS, dict(value))


_AIR_CACHE_TTL_SECONDS = 600
_air_cache: dict[tuple[str, float, float], tuple[float, dict]] = {}


def _get_air_cached(key):
    now = monotonic()
    with _cache_lock:
        item = _air_cache.get(key)
        if item is None:
            return None
        expires, value = item
        if expires <= now:
            _air_cache.pop(key, None)
            return None
        return dict(value)


def _store_air_cached(key, value):
    now = monotonic()
    with _cache_lock:
        expired = [
            k for k, (expiry, _) in _air_cache.items()
            if expiry <= now
        ]
        for old_key in expired:
            _air_cache.pop(old_key, None)
        if len(_air_cache) >= _CACHE_MAX_ITEMS and key not in _air_cache:
            oldest = min(_air_cache, key=lambda k: _air_cache[k][0])
            _air_cache.pop(oldest, None)
        _air_cache[key] = (now + _AIR_CACHE_TTL_SECONDS, dict(value))


@router.get("/tenants/{tenant_id}/farms/{farm_id}/air-pollution")
def get_farm_air_pollution(
    tenant_id: UUID,
    farm_id: UUID,
    _role: Annotated[
        str, Depends(require_tenant_role("owner", "operator", "viewer"))
    ],
    db: Session = Depends(get_db),
) -> dict:
    """Return current air pollution measurements for the selected farm."""
    try:
        with db.begin():
            farm = (
                db.execute(
                    text("""
                        SELECT id, latitude, longitude
                        FROM farms
                        WHERE tenant_id = :tenant_id AND id = :farm_id
                    """),
                    {"tenant_id": tenant_id, "farm_id": farm_id},
                )
                .mappings()
                .first()
            )
    except DBAPIError:
        raise HTTPException(
            status_code=503, detail="Farm data temporarily unavailable"
        ) from None

    if farm is None:
        raise HTTPException(status_code=404, detail="Farm not found")

    latitude, longitude = farm["latitude"], farm["longitude"]
    if latitude is None or longitude is None:
        raise HTTPException(
            status_code=409,
            detail="Farm coordinates are not configured",
        )
    if not settings.openweather_api_key:
        raise HTTPException(
            status_code=503,
            detail="Air pollution service is not configured",
        )

    cache_key = (str(farm_id), float(latitude), float(longitude))
    cached = _get_air_cached(cache_key)
    if cached is not None:
        return cached

    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.get(
                "https://api.openweathermap.org/data/2.5/air_pollution",
                params={
                    "lat": latitude,
                    "lon": longitude,
                    "appid": settings.openweather_api_key,
                },
            )
            response.raise_for_status()
            payload = response.json()

        item = payload["list"][0]
        components = item["components"]
        pm2_5 = float(components["pm2_5"])
        aqi = int(item["main"]["aqi"])

        if not isfinite(pm2_5) or pm2_5 < 0:
            raise ValueError("Invalid PM2.5 measurement")
        if aqi not in (1, 2, 3, 4, 5):
            raise ValueError("Invalid OpenWeatherMap AQI")

        observed = datetime.fromtimestamp(
            int(item["dt"]), tz=timezone.utc
        ).isoformat()

        aqi_labels = {
            1: "ดี",
            2: "พอใช้",
            3: "ปานกลาง",
            4: "แย่",
            5: "แย่มาก",
        }
        result = {
            "pm2_5": pm2_5,
            "aqi": aqi,
            "aqi_label": aqi_labels[aqi],
            "observed_at": observed,
            "source": "OpenWeatherMap",
        }
    except (
        httpx.HTTPError, KeyError, IndexError, TypeError, ValueError,
        OverflowError,
    ):
        raise HTTPException(
            status_code=502,
            detail="Air pollution provider is temporarily unavailable",
        ) from None

    _store_air_cached(cache_key, result)
    return result


@router.get("/tenants/{tenant_id}/farms/{farm_id}/weather")
def get_farm_weather(
    tenant_id: UUID,
    farm_id: UUID,
    _role: Annotated[
        str, Depends(require_tenant_role("owner", "operator", "viewer"))
    ],
    db: Session = Depends(get_db),
) -> dict:
    """Return current weather for the authorized farm."""
    try:
        with db.begin():
            farm = (
                db.execute(
                    text("""
                        SELECT id, latitude, longitude
                        FROM farms
                        WHERE tenant_id = :tenant_id AND id = :farm_id
                    """),
                    {"tenant_id": tenant_id, "farm_id": farm_id},
                )
                .mappings()
                .first()
            )
    except DBAPIError:
        raise HTTPException(
            status_code=503, detail="Farm data temporarily unavailable"
        ) from None

    if farm is None:
        raise HTTPException(status_code=404, detail="Farm not found")
    latitude, longitude = farm["latitude"], farm["longitude"]
    if latitude is None or longitude is None:
        raise HTTPException(
            status_code=409,
            detail="Farm coordinates are not configured",
        )
    if not settings.openweather_api_key:
        raise HTTPException(
            status_code=503,
            detail="Weather service is not configured",
        )

    cache_key = (str(farm_id), float(latitude), float(longitude))
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={
                    "lat": latitude,
                    "lon": longitude,
                    "units": "metric",
                    "lang": "th",
                    "appid": settings.openweather_api_key,
                },
            )
            response.raise_for_status()
            payload = response.json()

        main = payload["main"]
        wind = payload.get("wind", {})
        weather = payload["weather"][0]
        temperature = float(main["temp"])
        feels_like = float(main["feels_like"])
        humidity = int(main["humidity"])
        pressure = int(main["pressure"])
        wind_speed = float(wind.get("speed", 0))
        wind_deg = wind.get("deg")
        if not all(isfinite(v) for v in (
            temperature, feels_like, wind_speed
        )):
            raise ValueError("Non-finite weather value")
        if not 0 <= humidity <= 100 or pressure <= 0:
            raise ValueError("Invalid weather measurement")
        if wind_deg is not None:
            wind_deg = int(wind_deg)
            if not 0 <= wind_deg <= 360:
                raise ValueError("Invalid wind direction")
        observed = datetime.fromtimestamp(
            int(payload["dt"]), tz=timezone.utc
        ).isoformat()
        result = {
            "temperature": temperature,
            "feels_like": feels_like,
            "humidity": humidity,
            "pressure": pressure,
            "wind_speed": wind_speed,
            "wind_deg": wind_deg,
            "description": str(weather["description"]),
            "icon": str(weather["icon"]),
            "observed_at": observed,
            "source": "OpenWeatherMap",
        }
    except (
        httpx.HTTPError, KeyError, IndexError, TypeError, ValueError,
        OverflowError,
    ):
        raise HTTPException(
            status_code=502,
            detail="Weather provider is temporarily unavailable",
        ) from None

    _store_cached(cache_key, result)
    return result
