import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException

from app.api import dependencies
from app.db.session import get_db
from app.main import app
from app.services.user_auth import AuthenticatedUser


TENANT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
DEVICE_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
FARM_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
CREATED_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)

USER = AuthenticatedUser(
    id="device-test-user-id",
    email="device-test@example.invalid",
    display_name="Device Test",
)

DEVICE_ROW = {
    "id": DEVICE_ID,
    "device_code": "GW-001",
    "device_type": "gateway",
    "name": "North Gateway",
    "status": "active",
    "farm_id": FARM_ID,
    "last_seen_at": CREATED_AT,
    "created_at": CREATED_AT,
    "updated_at": CREATED_AT,
}


@pytest.fixture
def device_client(monkeypatch):
    db = Mock()
    db.begin.return_value.__enter__ = Mock(return_value=db)
    db.begin.return_value.__exit__ = Mock(return_value=False)
    db.execute.return_value.mappings.return_value.all.return_value = [
        DEVICE_ROW
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

    async def request(token="test-token"):
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
                f"/api/v1/tenants/{TENANT_ID}/devices",
                headers=headers,
            )

    yield db, request
    app.dependency_overrides.pop(get_db, None)


def test_missing_bearer_token_returns_401(device_client):
    db, request = device_client

    response = asyncio.run(request(token=None))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    db.begin.assert_not_called()


@pytest.mark.parametrize("role", ["owner", "operator", "viewer"])
def test_allowed_tenant_roles_can_list_devices(
    device_client,
    monkeypatch,
    role,
):
    db, request = device_client
    monkeypatch.setattr(
        dependencies,
        "authorize_tenant",
        Mock(return_value=role),
    )

    response = asyncio.run(request())

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(DEVICE_ID),
            "device_code": "GW-001",
            "device_type": "gateway",
            "name": "North Gateway",
            "status": "active",
            "farm_id": str(FARM_ID),
            "last_seen_at": "2026-10-01T00:00:00Z",
            "created_at": "2026-10-01T00:00:00Z",
            "updated_at": "2026-10-01T00:00:00Z",
        }
    ]

    sql = str(db.execute.call_args.args[0])
    assert "FROM devices" in sql
    assert "WHERE tenant_id = :tenant_id" in sql
    assert db.execute.call_args.args[1] == {"tenant_id": TENANT_ID}


def test_tenant_without_membership_returns_403(
    device_client,
    monkeypatch,
):
    _, request = device_client
    monkeypatch.setattr(
        dependencies,
        "authorize_tenant",
        Mock(
            side_effect=HTTPException(
                status_code=403,
                detail="Insufficient tenant permissions",
            )
        ),
    )

    response = asyncio.run(request())

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient tenant permissions"


def test_device_response_does_not_expose_credentials(device_client):
    db, request = device_client
    db.execute.return_value.mappings.return_value.all.return_value = [
        {
            **DEVICE_ROW,
            "secret_hash": "must-not-be-returned",
            "credential_token": "must-not-be-returned",
        }
    ]

    response = asyncio.run(request())

    assert response.status_code == 200
    assert "secret_hash" not in response.text
    assert "credential_token" not in response.text


def test_database_error_returns_safe_503(device_client):
    from sqlalchemy.exc import OperationalError

    db, request = device_client
    db.execute.side_effect = OperationalError(
        "SELECT",
        {},
        RuntimeError("private database detail"),
    )

    response = asyncio.run(request())

    assert response.status_code == 503
    assert "private database detail" not in response.text


def test_tenant_with_no_devices_returns_empty_list(device_client):
    db, request = device_client
    db.execute.return_value.mappings.return_value.all.return_value = []

    response = asyncio.run(request())

    assert response.status_code == 200
    assert response.json() == []
