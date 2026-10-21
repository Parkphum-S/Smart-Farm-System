import asyncio
from unittest.mock import Mock
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

from app.api import telemetry as telemetry_api
from app.db.session import get_db
from app.main import app
from app.security.device_auth import DeviceIdentity
from app.services.telemetry import EventConflict, IngestResult, TelemetryRejected


VALID_EVENT = {
    "event_id": "11111111-1111-4111-8111-111111111111",
    "device_id": "22222222-2222-4222-8222-222222222222",
    "observed_at": "2026-10-21T00:00:00Z",
    "readings": [
        {
            "sensor_id": "33333333-3333-4333-8333-333333333333",
            "metric": "air_temperature",
            "value": 28.5,
            "unit": "Cel",
        }
    ],
}


@pytest.fixture
def client():
    db = Mock()
    db.begin.return_value.__enter__ = Mock(return_value=db)
    db.begin.return_value.__exit__ = Mock(return_value=False)

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    async def request(payload, headers=None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as http:
            return await http.post(
                "/api/v1/telemetry",
                json=payload,
                headers=headers or {},
            )

    yield db, request
    app.dependency_overrides.pop(get_db, None)


def test_missing_bearer_token_returns_401(client, monkeypatch):
    db, request = client
    response = asyncio.run(request(VALID_EVENT))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    db.begin.assert_not_called()


def test_invalid_device_token_returns_401(client, monkeypatch):
    db, request = client
    monkeypatch.setattr(
        telemetry_api,
        "authenticate_device",
        Mock(return_value=None),
    )

    response = asyncio.run(
        request(VALID_EVENT, {"Authorization": "Bearer invalid"})
    )

    assert response.status_code == 401
    db.begin.assert_called_once()


def test_valid_event_is_accepted(client, monkeypatch):
    db, request = client
    identity = DeviceIdentity(
        tenant_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        device_id=UUID(VALID_EVENT["device_id"]),
    )
    monkeypatch.setattr(
        telemetry_api,
        "authenticate_device",
        Mock(return_value=identity),
    )
    monkeypatch.setattr(
        telemetry_api,
        "ingest_telemetry",
        Mock(return_value=IngestResult(UUID(int=1), False)),
    )

    response = asyncio.run(
        request(VALID_EVENT, {"Authorization": "Bearer test-token"})
    )

    assert response.status_code == 202
    assert response.json() == {
        "event_id": VALID_EVENT["event_id"],
        "duplicate": False,
    }


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (TelemetryRejected("rejected"), 403),
        (EventConflict("conflict"), 409),
        (
            OperationalError("insert", {}, RuntimeError("database")),
            503,
        ),
    ],
)
def test_ingestion_errors_return_safe_status(
    client,
    monkeypatch,
    error,
    expected_status,
):
    _, request = client
    identity = DeviceIdentity(
        tenant_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        device_id=UUID(VALID_EVENT["device_id"]),
    )
    monkeypatch.setattr(
        telemetry_api,
        "authenticate_device",
        Mock(return_value=identity),
    )
    monkeypatch.setattr(
        telemetry_api,
        "ingest_telemetry",
        Mock(side_effect=error),
    )

    response = asyncio.run(
        request(VALID_EVENT, {"Authorization": "Bearer test-token"})
    )

    assert response.status_code == expected_status
    assert "database" not in response.text
