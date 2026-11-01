import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import UUID

import httpx
import pytest

from app.api import dependencies, weather
from app.db.session import get_db
from app.main import app
from app.services.user_auth import AuthenticatedUser


TENANT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
FARM_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")

USER = AuthenticatedUser(
    id="weather-test-user-id",
    email="weather-test@example.invalid",
    display_name="Weather Test",
)

FARM_ROW = {
    "id": FARM_ID,
    "latitude": 13.7563,
    "longitude": 100.5018,
}

WEATHER_PAYLOAD = {
    "main": {
        "temp": 31.5,
        "feels_like": 35.2,
        "humidity": 68,
        "pressure": 1008,
    },
    "wind": {"speed": 2.4, "deg": 180},
    "weather": [{"description": "มีเมฆบางส่วน", "icon": "02d"}],
    "dt": 1793500000,
}


@pytest.fixture
def weather_client(monkeypatch):
    db = Mock()
    db.begin.return_value.__enter__ = Mock(return_value=db)
    db.begin.return_value.__exit__ = Mock(return_value=False)

    result = Mock()
    result.mappings.return_value.first.return_value = FARM_ROW
    db.execute.return_value = result

    def override_get_db():
        yield db

    monkeypatch.setattr(
        dependencies, "authenticate_session", Mock(return_value=USER)
    )
    monkeypatch.setattr(
        dependencies, "authorize_tenant", Mock(return_value="owner")
    )
    monkeypatch.setattr(weather.settings, "openweather_api_key", "test-key")
    weather._cache.clear()
    weather._air_cache.clear()
    app.dependency_overrides[get_db] = override_get_db

    async def request(token="test-token", endpoint="weather"):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            headers = (
                {"Authorization": f"Bearer {token}"}
                if token is not None else {}
            )
            return await client.get(
                f"/api/v1/tenants/{TENANT_ID}/farms/{FARM_ID}/{endpoint}",
                headers=headers,
            )

    yield db, request
    app.dependency_overrides.pop(get_db, None)
    weather._cache.clear()
    weather._air_cache.clear()


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    calls = []

    def __init__(self, *, timeout):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, *, params):
        self.calls.append((url, params))
        if url.endswith("/air_pollution"):
            return FakeResponse({
                "list": [{
                    "main": {"aqi": 2},
                    "components": {"pm2_5": 12.34},
                    "dt": 1793500000,
                }]
            })
        return FakeResponse(WEATHER_PAYLOAD)


def test_weather_returns_current_conditions_for_selected_farm(
    weather_client, monkeypatch
):
    db, request = weather_client
    FakeClient.calls = []
    monkeypatch.setattr(weather.httpx, "Client", FakeClient)

    response = asyncio.run(request())

    assert response.status_code == 200
    body = response.json()
    assert body["temperature"] == 31.5
    assert body["feels_like"] == 35.2
    assert body["humidity"] == 68
    assert body["pressure"] == 1008
    assert body["wind_speed"] == 2.4
    assert body["wind_deg"] == 180
    assert body["description"] == "มีเมฆบางส่วน"
    assert body["icon"] == "02d"
    assert body["source"] == "OpenWeatherMap"
    assert body["observed_at"].endswith("+00:00")

    sql = str(db.execute.call_args.args[0])
    assert "FROM farms" in sql
    assert "tenant_id = :tenant_id" in sql
    assert db.execute.call_args.args[1] == {
        "tenant_id": TENANT_ID,
        "farm_id": FARM_ID,
    }

    assert len(FakeClient.calls) == 1
    url, params = FakeClient.calls[0]
    assert url == "https://api.openweathermap.org/data/2.5/weather"
    assert params == {
        "lat": FARM_ROW["latitude"],
        "lon": FARM_ROW["longitude"],
        "units": "metric",
        "lang": "th",
        "appid": "test-key",
    }


def test_weather_uses_cache_for_repeated_requests(
    weather_client, monkeypatch
):
    _, request = weather_client
    FakeClient.calls = []
    monkeypatch.setattr(weather.httpx, "Client", FakeClient)

    first = asyncio.run(request())
    second = asyncio.run(request())

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert len(FakeClient.calls) == 1


def test_weather_without_farm_coordinates_returns_409(
    weather_client, monkeypatch
):
    db, request = weather_client
    result = Mock()
    result.mappings.return_value.first.return_value = {
        **FARM_ROW, "latitude": None, "longitude": None
    }
    db.execute.return_value = result
    upstream = Mock()
    monkeypatch.setattr(weather.httpx, "Client", upstream)

    response = asyncio.run(request())

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Farm coordinates are not configured"
    )
    upstream.assert_not_called()


def test_weather_without_api_key_returns_503(
    weather_client, monkeypatch
):
    _, request = weather_client
    monkeypatch.setattr(weather.settings, "openweather_api_key", None)
    upstream = Mock()
    monkeypatch.setattr(weather.httpx, "Client", upstream)

    response = asyncio.run(request())

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Weather service is not configured"
    )
    upstream.assert_not_called()


def test_weather_provider_failure_returns_safe_502(
    weather_client, monkeypatch
):
    _, request = weather_client

    class FailingClient(FakeClient):
        def get(self, url, *, params):
            raise httpx.ConnectError("private upstream detail")

    monkeypatch.setattr(weather.httpx, "Client", FailingClient)

    response = asyncio.run(request())

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "Weather provider is temporarily unavailable"
    )
    assert "private upstream detail" not in response.text
    assert "test-key" not in response.text


def test_weather_missing_bearer_token_returns_401(weather_client):
    db, request = weather_client

    response = asyncio.run(request(token=None))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    db.begin.assert_not_called()


def test_weather_unknown_farm_returns_404(weather_client, monkeypatch):
    db, request = weather_client
    result = Mock()
    result.mappings.return_value.first.return_value = None
    db.execute.return_value = result
    upstream = Mock()
    monkeypatch.setattr(weather.httpx, "Client", upstream)

    response = asyncio.run(request())

    assert response.status_code == 404
    assert response.json()["detail"] == "Farm not found"
    upstream.assert_not_called()



def test_air_pollution_returns_pm25_and_openweathermap_aqi(
    weather_client, monkeypatch
):
    _, request = weather_client
    FakeClient.calls = []
    monkeypatch.setattr(weather.httpx, "Client", FakeClient)

    response = asyncio.run(request(endpoint="air-pollution"))

    assert response.status_code == 200
    body = response.json()
    assert body["pm2_5"] == 12.34
    assert body["aqi"] == 2
    assert body["aqi_label"] == "พอใช้"
    assert body["source"] == "OpenWeatherMap"
    assert body["observed_at"].endswith("+00:00")

    assert len(FakeClient.calls) == 1
    url, params = FakeClient.calls[0]
    assert url == (
        "https://api.openweathermap.org/data/2.5/air_pollution"
    )
    assert params == {
        "lat": FARM_ROW["latitude"],
        "lon": FARM_ROW["longitude"],
        "appid": "test-key",
    }


def test_air_pollution_uses_independent_cache(
    weather_client, monkeypatch
):
    _, request = weather_client
    FakeClient.calls = []
    monkeypatch.setattr(weather.httpx, "Client", FakeClient)

    first = asyncio.run(request(endpoint="air-pollution"))
    second = asyncio.run(request(endpoint="air-pollution"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert len(FakeClient.calls) == 1


def test_air_pollution_without_coordinates_returns_409(
    weather_client, monkeypatch
):
    db, request = weather_client
    result = Mock()
    result.mappings.return_value.first.return_value = {
        **FARM_ROW, "latitude": None, "longitude": None
    }
    db.execute.return_value = result
    upstream = Mock()
    monkeypatch.setattr(weather.httpx, "Client", upstream)

    response = asyncio.run(request(endpoint="air-pollution"))

    assert response.status_code == 409
    upstream.assert_not_called()


def test_air_pollution_provider_failure_returns_safe_502(
    weather_client, monkeypatch
):
    _, request = weather_client

    class FailingClient(FakeClient):
        def get(self, url, *, params):
            raise httpx.ConnectError("private upstream detail")

    monkeypatch.setattr(weather.httpx, "Client", FailingClient)
    response = asyncio.run(request(endpoint="air-pollution"))

    assert response.status_code == 502
    assert "private upstream detail" not in response.text
    assert "test-key" not in response.text


def test_air_pollution_rejects_invalid_pm25(
    weather_client, monkeypatch
):
    _, request = weather_client

    class InvalidClient(FakeClient):
        def get(self, url, *, params):
            return FakeResponse({
                "list": [{
                    "main": {"aqi": 2},
                    "components": {"pm2_5": -1},
                    "dt": 1793500000,
                }]
            })

    monkeypatch.setattr(weather.httpx, "Client", InvalidClient)
    response = asyncio.run(request(endpoint="air-pollution"))

    assert response.status_code == 502
