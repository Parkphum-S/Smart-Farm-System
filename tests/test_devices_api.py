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
    "zone_id": None,
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

    async def request(
        token="test-token",
        method="GET",
        device_id=DEVICE_ID,
        json=None,
    ):
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
            path = f"/api/v1/tenants/{TENANT_ID}/devices"
            if method.upper() == "PATCH":
                path += f"/{device_id}/zone"
            return await client.request(
                method,
                path,
                headers=headers,
                json=json,
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
            "zone_id": None,
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


ZONE_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
OTHER_ZONE_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")


def _configure_patch_db(db, *, device=DEVICE_ROW, zone_id=ZONE_ID):
    """Configure mock query results for the PATCH endpoint."""
    device_result = Mock()
    device_result.mappings.return_value.first.return_value = device

    update_result = Mock()
    update_result.mappings.return_value.one.return_value = {
        **DEVICE_ROW,
        "zone_id": zone_id,
    }

    if zone_id is None:
        # Unassignment skips the zone lookup and updates directly.
        db.execute.side_effect = [device_result, update_result]
    else:
        zone_result = Mock()
        zone_result.mappings.return_value.first.return_value = {
            "id": zone_id
        }
        db.execute.side_effect = [
            device_result,
            zone_result,
            update_result,
        ]


def test_assign_device_zone_success(device_client):
    db, request = device_client
    _configure_patch_db(db)

    response = asyncio.run(
        request(method="PATCH", json={"zone_id": str(ZONE_ID)})
    )

    assert response.status_code == 200
    assert response.json()["zone_id"] == str(ZONE_ID)
    assert db.execute.call_count == 3
    update_sql = str(db.execute.call_args_list[2].args[0])
    assert "UPDATE devices" in update_sql
    assert "SET zone_id = :zone_id" in update_sql
    assert db.execute.call_args_list[2].args[1]["zone_id"] == ZONE_ID


def test_unassign_device_zone_success(device_client):
    db, request = device_client
    _configure_patch_db(db, zone_id=None)

    response = asyncio.run(
        request(method="PATCH", json={"zone_id": None})
    )

    assert response.status_code == 200
    assert response.json()["zone_id"] is None
    assert db.execute.call_count == 2
    update_sql = str(db.execute.call_args_list[1].args[0])
    assert "UPDATE devices" in update_sql
    assert db.execute.call_args_list[1].args[1]["zone_id"] is None


def test_assign_zone_rejected_when_device_has_no_farm(device_client):
    db, request = device_client
    device_without_farm = {**DEVICE_ROW, "farm_id": None}
    _configure_patch_db(db, device=device_without_farm)

    response = asyncio.run(
        request(method="PATCH", json={"zone_id": str(ZONE_ID)})
    )

    assert response.status_code == 409
    assert "farm" in response.json()["detail"].lower()
    db.execute.assert_called_once()


def test_assign_zone_rejected_when_zone_not_in_device_farm(device_client):
    db, request = device_client

    device_result = Mock()
    device_result.mappings.return_value.first.return_value = DEVICE_ROW

    missing_zone_result = Mock()
    missing_zone_result.mappings.return_value.first.return_value = None

    db.execute.side_effect = [device_result, missing_zone_result]

    response = asyncio.run(
        request(method="PATCH", json={"zone_id": str(OTHER_ZONE_ID)})
    )

    assert response.status_code == 409
    assert db.execute.call_count == 2
    assert "UPDATE devices" not in str(db.execute.call_args_list[-1].args[0])


def test_assign_zone_device_not_found(device_client):
    db, request = device_client
    device_result = Mock()
    device_result.mappings.return_value.first.return_value = None
    db.execute.return_value = device_result

    response = asyncio.run(
        request(
            method="PATCH",
            device_id=OTHER_ZONE_ID,
            json={"zone_id": str(ZONE_ID)},
        )
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Device not found"
    db.execute.assert_called_once()


@pytest.mark.parametrize("role", ["owner", "operator"])
def test_owner_and_operator_can_assign_device_zone(
    device_client, monkeypatch, role
):
    db, request = device_client
    _configure_patch_db(db)
    monkeypatch.setattr(
        dependencies, "authorize_tenant", Mock(return_value=role)
    )

    response = asyncio.run(
        request(method="PATCH", json={"zone_id": str(ZONE_ID)})
    )

    assert response.status_code == 200


def test_viewer_cannot_assign_device_zone(device_client, monkeypatch):
    db, request = device_client
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

    response = asyncio.run(
        request(method="PATCH", json={"zone_id": str(ZONE_ID)})
    )

    assert response.status_code == 403
    db.execute.assert_not_called()


def test_missing_token_cannot_assign_device_zone(device_client):
    db, request = device_client

    response = asyncio.run(
        request(
            token=None,
            method="PATCH",
            json={"zone_id": str(ZONE_ID)},
        )
    )

    assert response.status_code == 401
    db.execute.assert_not_called()


def test_patch_database_error_returns_safe_503(device_client):
    from sqlalchemy.exc import OperationalError

    db, request = device_client
    db.execute.side_effect = OperationalError(
        "SELECT",
        {},
        RuntimeError("private database detail"),
    )

    response = asyncio.run(
        request(method="PATCH", json={"zone_id": str(ZONE_ID)})
    )

    assert response.status_code == 503
    assert "private database detail" not in response.text


def test_patch_rejects_unexpected_payload_fields(device_client):
    db, request = device_client

    response = asyncio.run(
        request(
            method="PATCH",
            json={
                "zone_id": str(ZONE_ID),
                "farm_id": str(FARM_ID),
            },
        )
    )

    assert response.status_code == 422
    db.execute.assert_not_called()
