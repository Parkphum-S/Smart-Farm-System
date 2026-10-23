import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import UUID

import httpx
import pytest

from app.api import commands as commands_api
from app.db.session import get_db
from app.main import app
from app.schemas.commands import CommandResponse
from app.security.device_auth import DeviceIdentity


TENANT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
DEVICE_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
COMMAND_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
CREATED_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)

COMMAND_ROW = {
    "id": COMMAND_ID,
    "tenant_id": TENANT_ID,
    "device_id": DEVICE_ID,
    "requested_by_user_id": UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
    "command_type": "relay.set",
    "parameters": {"relay": 1, "state": "off"},
    "status": "sent",
    "created_at": CREATED_AT,
    "expires_at": datetime(2026, 10, 1, 0, 1, tzinfo=timezone.utc),
    "updated_at": CREATED_AT,
    "correlation_id": None,
    "result_summary": None,
    "idempotency_key": "private-idempotency-key",
    "request_hash": "private-request-hash",
}


@pytest.fixture
def command_client(monkeypatch):
    db = Mock()
    db.begin.return_value.__enter__ = Mock(return_value=db)
    db.begin.return_value.__exit__ = Mock(return_value=False)

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    async def request(method, path, *, token=None, json=None):
        headers = (
            {"Authorization": f"Bearer {token}"}
            if token is not None
            else {}
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(
                method, path, headers=headers, json=json
            )

    yield db, request
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/api/v1/commands/pending", None),
        (
            "POST",
            f"/api/v1/commands/{COMMAND_ID}/events",
            {"event_id": "event-1", "event_type": "acknowledged"},
        ),
    ],
)
def test_missing_device_token_rejected_before_transaction(
    command_client, method, path, payload
):
    db, request = command_client

    response = asyncio.run(
        request(method, path, token=None, json=payload)
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    db.begin.assert_not_called()


def test_invalid_device_token_returns_401(
    command_client, monkeypatch
):
    db, request = command_client
    authenticate = Mock(return_value=None)
    pending = Mock()
    monkeypatch.setattr(commands_api, "authenticate_device", authenticate)
    monkeypatch.setattr(commands_api, "pending_commands", pending)

    response = asyncio.run(
        request("GET", "/api/v1/commands/pending", token="invalid-token")
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    authenticate.assert_called_once()
    pending.assert_not_called()


def test_command_response_excludes_internal_database_fields():
    result = commands_api._command_response(COMMAND_ROW)

    assert isinstance(result, CommandResponse)
    body = result.model_dump(mode="json")
    assert body["id"] == str(COMMAND_ID)
    assert body["device_id"] == str(DEVICE_ID)
    assert body["parameters"] == {"relay": 1, "state": "off"}
    assert "tenant_id" not in body
    assert "requested_by_user_id" not in body
    assert "idempotency_key" not in body
    assert "request_hash" not in body


def test_pending_commands_returns_filtered_response(
    command_client, monkeypatch
):
    db, request = command_client
    identity = DeviceIdentity(tenant_id=TENANT_ID, device_id=DEVICE_ID)
    monkeypatch.setattr(
        commands_api, "authenticate_device", Mock(return_value=identity)
    )
    monkeypatch.setattr(
        commands_api, "pending_commands", Mock(return_value=[COMMAND_ROW])
    )

    response = asyncio.run(
        request("GET", "/api/v1/commands/pending", token="test-device-token")
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["commands"]) == 1
    command = body["commands"][0]
    assert command["id"] == str(COMMAND_ID)
    assert "tenant_id" not in command
    assert "requested_by_user_id" not in command
    assert "idempotency_key" not in command
    assert "request_hash" not in command
