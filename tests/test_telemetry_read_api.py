import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

from app.api import dependencies
from app.db.session import get_db
from app.main import app
from app.services.user_auth import AuthenticatedUser


TENANT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
SENSOR_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
DEVICE_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
READING_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
MEASURED_AT = datetime(2026, 10, 26, tzinfo=timezone.utc)

USER = AuthenticatedUser(
    id="telemetry-read-user",
    email="telemetry-read@example.invalid",
    display_name="Telemetry Read Test",
)

READING_ROW = {
    "id": READING_ID,
    "sensor_id": SENSOR_ID,
    "sensor_code": "TEMP-01",
    "device_id": DEVICE_ID,
    "device_name": "North Gateway",
    "metric": "air_temperature",
    "value": 28.5,
    "unit": "Cel",
    "quality_status": "valid",
    "measured_at": MEASURED_AT,
    "received_at": MEASURED_AT,
}


@pytest.fixture
def reading_client(monkeypatch):
    db = Mock()
    db.begin.return_value.__enter__ = Mock(return_value=db)
    db.begin.return_value.__exit__ = Mock(return_value=False)
    db.execute.return_value.mappings.return_value.all.return_value = [
        READING_ROW
    ]

    def override_get_db():
        yield db

    monkeypatch.setattr(
        dependencies,
        "authenticate_session",
        Mock(return_value=USER),
    )
    monkeypatch.setattr(
        dependencies,
        "authorize_tenant",
        Mock(return_value="owner"),
    )
    app.dependency_overrides[get_db] = override_get_db

    async def request(token="test-token", params=None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            headers = (
                {"Authorization": f"Bearer {token}"}
                if token is not None
                else {}
            )
            return await client.get(
                f"/api/v1/tenants/{TENANT_ID}/telemetry/readings",
                headers=headers,
                params=params,
            )

    yield db, request
    app.dependency_overrides.pop(get_db, None)


def test_readings_require_login(reading_client):
    db, request = reading_client

    response = asyncio.run(request(token=None))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    db.execute.assert_not_called()


def test_authorized_tenant_can_read_sensor_history(reading_client):
    db, request = reading_client

    response = asyncio.run(request(params={"metric": "air_temperature"}))

    assert response.status_code == 200
    assert response.json() == [{
        "id": str(READING_ID),
        "sensor_id": str(SENSOR_ID),
        "sensor_code": "TEMP-01",
        "device_id": str(DEVICE_ID),
        "device_name": "North Gateway",
        "metric": "air_temperature",
        "value": 28.5,
        "unit": "Cel",
        "quality_status": "valid",
        "measured_at": "2026-10-26T00:00:00Z",
        "received_at": "2026-10-26T00:00:00Z",
    }]

    sql, params = db.execute.call_args.args
    assert "FROM sensor_readings AS r" in str(sql)
    assert "r.tenant_id = :tenant_id" in str(sql)
    assert params["tenant_id"] == TENANT_ID
    assert params["metric"] == "air_temperature"


def test_latest_only_query_returns_one_row_per_sensor(reading_client):
    db, request = reading_client

    response = asyncio.run(request(params={"latest_only": "true"}))

    assert response.status_code == 200
    sql = str(db.execute.call_args.args[0])
    assert "DISTINCT ON (r.sensor_id)" in sql
    assert "ORDER BY r.sensor_id, r.measured_at DESC, r.id DESC" in sql


def test_tenant_without_membership_cannot_read_readings(
    reading_client,
    monkeypatch,
):
    _, request = reading_client
    monkeypatch.setattr(
        dependencies,
        "authorize_tenant",
        Mock(side_effect=HTTPException(
            status_code=403,
            detail="Insufficient tenant permissions",
        )),
    )

    response = asyncio.run(request())

    assert response.status_code == 403


@pytest.mark.parametrize(
    "params",
    [
        {
            "since": "2026-10-27T00:00:00Z",
            "until": "2026-10-26T00:00:00Z",
        },
        {"since": "2026-10-26T00:00:00"},
    ],
)
def test_invalid_time_range_is_rejected(reading_client, params):
    db, request = reading_client

    response = asyncio.run(request(params=params))

    assert response.status_code == 422
    db.execute.assert_not_called()


def test_database_error_returns_safe_503(reading_client):
    db, request = reading_client
    db.execute.side_effect = OperationalError(
        "query", {}, RuntimeError("database details")
    )

    response = asyncio.run(request())

    assert response.status_code == 503
    assert "database details" not in response.text
