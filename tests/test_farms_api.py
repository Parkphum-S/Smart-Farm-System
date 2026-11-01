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
FARM_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
USER = AuthenticatedUser(
    id="test-user-id",
    email="farm-test@example.invalid",
    display_name="Farm Test",
)
CREATED_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)

FARM_ROW = {
    "id": FARM_ID,
    "name": "North Farm",
    "timezone": "Asia/Bangkok",
    "latitude": None,
    "longitude": None,
    "created_at": CREATED_AT,
    "updated_at": CREATED_AT,
}


@pytest.fixture
def farm_client(monkeypatch):
    db = Mock()
    db.begin.return_value.__enter__ = Mock(return_value=db)
    db.begin.return_value.__exit__ = Mock(return_value=False)
    db.execute.return_value.mappings.return_value.all.return_value = [
        FARM_ROW
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
        tenant_id=TENANT_ID,
        farm_id=None,
        json=None,
    ):
        transport = httpx.ASGITransport(app=app)
        path = f"/api/v1/tenants/{tenant_id}/farms"
        if farm_id is not None:
            path += f"/{farm_id}"
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            headers = (
                {"Authorization": f"Bearer {token}"}
                if token is not None
                else {}
            )
            return await client.request(
                method, path, headers=headers, json=json
            )

    yield db, request
    app.dependency_overrides.pop(get_db, None)


def test_missing_bearer_token_returns_401(farm_client):
    db, request = farm_client

    response = asyncio.run(request(token=None))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    db.begin.assert_not_called()


@pytest.mark.parametrize("role", ["owner", "operator", "viewer"])
def test_allowed_tenant_roles_can_list_farms(
    farm_client,
    monkeypatch,
    role,
):
    db, request = farm_client
    monkeypatch.setattr(
        dependencies,
        "authorize_tenant",
        Mock(return_value=role),
    )

    response = asyncio.run(request())

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(FARM_ID),
            "name": "North Farm",
            "timezone": "Asia/Bangkok",
            "latitude": None,
            "longitude": None,
            "created_at": "2026-10-01T00:00:00Z",
            "updated_at": "2026-10-01T00:00:00Z",
        }
    ]

    sql = str(db.execute.call_args.args[0])
    assert "WHERE tenant_id = :tenant_id" in sql
    assert db.execute.call_args.kwargs == {}
    assert db.execute.call_args.args[1] == {"tenant_id": TENANT_ID}


def test_tenant_without_membership_returns_403(
    farm_client,
    monkeypatch,
):
    _, request = farm_client
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


def test_database_error_returns_safe_503(farm_client):
    from sqlalchemy.exc import OperationalError

    db, request = farm_client
    db.execute.side_effect = OperationalError(
        "SELECT",
        {},
        RuntimeError("private database detail"),
    )

    response = asyncio.run(request())

    assert response.status_code == 503
    assert "private database detail" not in response.text


def test_create_farm_returns_created_resource(farm_client):
    db, request = farm_client
    db.execute.return_value.mappings.return_value.one.return_value = FARM_ROW

    response = asyncio.run(
        request(
            method="POST",
            json={"name": "North Farm", "timezone": "Asia/Bangkok"},
        )
    )

    assert response.status_code == 201, response.text
    assert response.json()["id"] == str(FARM_ID)
    assert response.json()["name"] == "North Farm"

    sql = str(db.execute.call_args.args[0])
    params = db.execute.call_args.args[1]
    assert "INSERT INTO farms" in sql
    assert params["tenant_id"] == TENANT_ID
    assert params["name"] == "North Farm"
    assert params["timezone"] == "Asia/Bangkok"
    assert params["latitude"] is None
    assert params["longitude"] is None


def test_create_farm_trims_name_and_defaults_timezone(farm_client):
    db, request = farm_client
    db.execute.return_value.mappings.return_value.one.return_value = {
        **FARM_ROW,
        "name": "New Farm",
        "timezone": "UTC",
    }

    response = asyncio.run(
        request(method="POST", json={"name": "  New Farm  "})
    )

    assert response.status_code == 201, response.text
    params = db.execute.call_args.args[1]
    assert params["name"] == "New Farm"
    assert params["timezone"] == "UTC"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "   "},
        {"name": "Farm", "timezone": "Not/A_Real_Timezone"},
        {"name": "Farm", "unexpected": "field"},
        {"name": "Farm", "latitude": 13.7},
        {"name": "Farm", "latitude": 91, "longitude": 100},
        {"name": "Farm", "latitude": 13.7, "longitude": 181},
    ],
)
def test_create_farm_rejects_invalid_payload(farm_client, payload):
    db, request = farm_client

    response = asyncio.run(request(method="POST", json=payload))

    assert response.status_code == 422
    db.execute.assert_not_called()


def test_update_farm_returns_updated_resource(farm_client):
    db, request = farm_client
    updated = {**FARM_ROW, "name": "Updated Farm"}
    db.execute.return_value.mappings.return_value.first.return_value = updated

    response = asyncio.run(
        request(
            method="PATCH",
            farm_id=FARM_ID,
            json={"name": "Updated Farm"},
        )
    )

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Updated Farm"

    sql = str(db.execute.call_args.args[0])
    params = db.execute.call_args.args[1]
    assert "UPDATE farms" in sql
    assert "WHERE tenant_id = :tenant_id AND id = :farm_id" in sql
    assert params["tenant_id"] == TENANT_ID
    assert params["farm_id"] == FARM_ID
    assert params["name"] == "Updated Farm"


@pytest.mark.parametrize("payload", [
    {}, {"name": None}, {"timezone": None},
    {"latitude": 13.7}, {"longitude": 100.5},
])
def test_update_farm_rejects_empty_or_null_fields(farm_client, payload):
    db, request = farm_client

    response = asyncio.run(
        request(method="PATCH", farm_id=FARM_ID, json=payload)
    )

    assert response.status_code == 422
    db.execute.assert_not_called()


def test_create_farm_accepts_coordinate_pair(farm_client):
    db, request = farm_client
    db.execute.return_value.mappings.return_value.one.return_value = {
        **FARM_ROW, "latitude": 13.7563, "longitude": 100.5018
    }
    response = asyncio.run(request(
        method="POST",
        json={
            "name": "Bangkok Farm",
            "latitude": 13.7563,
            "longitude": 100.5018,
        },
    ))
    assert response.status_code == 201, response.text
    params = db.execute.call_args.args[1]
    assert params["latitude"] == 13.7563
    assert params["longitude"] == 100.5018


def test_update_farm_accepts_coordinate_pair(farm_client):
    db, request = farm_client
    db.execute.return_value.mappings.return_value.first.return_value = {
        **FARM_ROW, "latitude": 13.7, "longitude": 100.5
    }
    response = asyncio.run(request(
        method="PATCH",
        farm_id=FARM_ID,
        json={"latitude": 13.7, "longitude": 100.5},
    ))
    assert response.status_code == 200, response.text
    params = db.execute.call_args.args[1]
    assert params["latitude"] == 13.7
    assert params["longitude"] == 100.5


def test_update_farm_can_clear_both_coordinates(farm_client):
    db, request = farm_client
    db.execute.return_value.mappings.return_value.first.return_value = FARM_ROW
    response = asyncio.run(request(
        method="PATCH",
        farm_id=FARM_ID,
        json={"latitude": None, "longitude": None},
    ))
    assert response.status_code == 200, response.text
    params = db.execute.call_args.args[1]
    assert params["latitude"] is None
    assert params["longitude"] is None


def test_update_farm_missing_resource_returns_404(farm_client):
    db, request = farm_client
    db.execute.return_value.mappings.return_value.first.return_value = None

    response = asyncio.run(
        request(method="PATCH", farm_id=FARM_ID, json={"name": "Missing"})
    )

    assert response.status_code == 404


def test_update_farm_rejects_unknown_fields(farm_client):
    db, request = farm_client

    response = asyncio.run(
        request(
            method="PATCH",
            farm_id=FARM_ID,
            json={"tenant_id": str(TENANT_ID)},
        )
    )

    assert response.status_code == 422
    db.execute.assert_not_called()


def test_delete_farm_returns_204_and_scopes_query(farm_client):
    db, request = farm_client
    db.execute.return_value.rowcount = 1

    response = asyncio.run(request(method="DELETE", farm_id=FARM_ID))

    assert response.status_code == 204
    sql = str(db.execute.call_args.args[0])
    params = db.execute.call_args.args[1]
    assert "DELETE FROM farms" in sql
    assert "WHERE tenant_id = :tenant_id AND id = :farm_id" in sql
    assert params == {"tenant_id": TENANT_ID, "farm_id": FARM_ID}


def test_delete_farm_missing_resource_returns_404(farm_client):
    db, request = farm_client
    db.execute.return_value.rowcount = 0

    response = asyncio.run(request(method="DELETE", farm_id=FARM_ID))

    assert response.status_code == 404


def test_delete_farm_with_references_returns_safe_409(farm_client):
    from sqlalchemy.exc import IntegrityError

    db, request = farm_client
    db.execute.side_effect = IntegrityError(
        "DELETE FROM farms",
        {},
        RuntimeError("foreign key violation"),
    )
    db.execute.side_effect.orig.sqlstate = "23503"

    response = asyncio.run(request(method="DELETE", farm_id=FARM_ID))

    assert response.status_code == 409
    assert "foreign key violation" not in response.text


def test_create_farm_database_error_returns_safe_503(farm_client):
    from sqlalchemy.exc import OperationalError

    db, request = farm_client
    db.execute.side_effect = OperationalError(
        "INSERT INTO farms", {}, RuntimeError("private database detail")
    )

    response = asyncio.run(
        request(method="POST", json={"name": "New Farm"})
    )

    assert response.status_code == 503
    assert "private database detail" not in response.text


def test_update_farm_database_error_returns_safe_503(farm_client):
    from sqlalchemy.exc import OperationalError

    db, request = farm_client
    db.execute.side_effect = OperationalError(
        "UPDATE farms", {}, RuntimeError("private database detail")
    )

    response = asyncio.run(
        request(method="PATCH", farm_id=FARM_ID, json={"name": "Changed"})
    )

    assert response.status_code == 503
    assert "private database detail" not in response.text
