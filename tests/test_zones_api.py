import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError, OperationalError

from app.api import dependencies
from app.db.session import get_db
from app.main import app
from app.services.user_auth import AuthenticatedUser


TENANT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OTHER_TENANT_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
FARM_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ZONE_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
CREATED_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)

USER = AuthenticatedUser(
    id="zone-test-user",
    email="zone-test@example.invalid",
    display_name="Zone Test",
)

ZONE_ROW = {
    "id": ZONE_ID,
    "tenant_id": TENANT_ID,
    "farm_id": FARM_ID,
    "name": "Greenhouse A",
    "description": "North greenhouse",
    "status": "active",
    "zone_type": "plant",
    "category_details": {},
    "created_at": CREATED_AT,
    "updated_at": CREATED_AT,
}


@pytest.fixture
def zone_client(monkeypatch):
    db = Mock()
    db.begin.return_value.__enter__ = Mock(return_value=db)
    db.begin.return_value.__exit__ = Mock(return_value=False)

    result = Mock()
    result.mappings.return_value.all.return_value = [ZONE_ROW]
    result.mappings.return_value.first.return_value = ZONE_ROW
    result.mappings.return_value.one.return_value = ZONE_ROW
    result.first.return_value = (FARM_ID,)
    result.rowcount = 1
    db.execute.return_value = result

    def override_get_db():
        yield db

    monkeypatch.setattr(
        dependencies, "authenticate_session", Mock(return_value=USER)
    )
    monkeypatch.setattr(
        dependencies, "authorize_tenant", Mock(return_value="owner")
    )
    app.dependency_overrides[get_db] = override_get_db

    async def request(
        method="GET",
        tenant_id=TENANT_ID,
        farm_id=FARM_ID,
        zone_id=ZONE_ID,
        token="test-token",
        json=None,
        query=None,
    ):
        transport = httpx.ASGITransport(app=app)
        path = f"/api/v1/tenants/{tenant_id}/farms/{farm_id}/zones"
        if zone_id is not None:
            path += f"/{zone_id}"
        headers = (
            {"Authorization": f"Bearer {token}"}
            if token is not None
            else {}
        )
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.request(
                method, path, headers=headers, json=json, params=query
            )

    yield db, request
    app.dependency_overrides.pop(get_db, None)


def test_list_zones_returns_tenant_scoped_data(zone_client):
    db, request = zone_client

    response = asyncio.run(request(zone_id=None))

    assert response.status_code == 200
    assert response.json()[0]["id"] == str(ZONE_ID)
    sql = str(db.execute.call_args.args[0])
    params = db.execute.call_args.args[1]
    assert "tenant_id = :tenant_id" in sql
    assert "farm_id = :farm_id" in sql
    assert params["tenant_id"] == TENANT_ID
    assert params["farm_id"] == FARM_ID


@pytest.mark.parametrize("role", ["owner", "operator", "viewer"])
def test_all_authorized_roles_can_read_zones(zone_client, monkeypatch, role):
    _, request = zone_client
    monkeypatch.setattr(
        dependencies, "authorize_tenant", Mock(return_value=role)
    )

    response = asyncio.run(request(zone_id=None))

    assert response.status_code == 200


def test_missing_bearer_token_returns_401(zone_client):
    db, request = zone_client

    response = asyncio.run(request(token=None, zone_id=None))

    assert response.status_code == 401
    db.begin.assert_not_called()


def test_tenant_without_access_returns_403(zone_client, monkeypatch):
    _, request = zone_client
    monkeypatch.setattr(
        dependencies,
        "authorize_tenant",
        Mock(side_effect=HTTPException(
            status_code=403, detail="Insufficient tenant permissions"
        )),
    )

    response = asyncio.run(request(tenant_id=OTHER_TENANT_ID, zone_id=None))

    assert response.status_code == 403


def test_create_zone_returns_created_resource(zone_client):
    db, request = zone_client

    response = asyncio.run(request(
        method="POST",
        zone_id=None,
        json={"name": "Greenhouse A", "description": "North greenhouse"},
    ))

    assert response.status_code == 201
    assert response.json()["name"] == "Greenhouse A"
    assert db.execute.call_count == 2
    insert_sql = str(db.execute.call_args_list[1].args[0])
    assert "INSERT INTO zones" in insert_sql
    insert_params = db.execute.call_args_list[1].args[1]
    assert insert_params["tenant_id"] == TENANT_ID
    assert insert_params["farm_id"] == FARM_ID


def test_viewer_cannot_create_zone(zone_client):
    _, request = zone_client
    from app.api.zones import router

    create_route = next(
        route for route in router.routes
        if getattr(route, "path", "").endswith("/zones")
        and "POST" in getattr(route, "methods", set())
    )
    role_dependency = next(
        dependency.call
        for dependency in create_route.dependant.dependencies
        if dependency.name == "_role"
    )

    async def deny_viewer():
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    app.dependency_overrides[role_dependency] = deny_viewer
    try:
        response = asyncio.run(request(
            method="POST",
            zone_id=None,
            json={"name": "Read-only test"},
        ))
    finally:
        app.dependency_overrides.pop(role_dependency, None)

    assert response.status_code == 403


def test_update_zone_returns_updated_resource(zone_client):
    db, request = zone_client
    updated = {**ZONE_ROW, "name": "Greenhouse B"}
    db.execute.return_value.mappings.return_value.first.return_value = updated

    response = asyncio.run(request(
        method="PATCH",
        json={"name": "Greenhouse B"},
    ))

    assert response.status_code == 200
    assert response.json()["name"] == "Greenhouse B"
    sql = str(db.execute.call_args.args[0])
    params = db.execute.call_args.args[1]
    assert "UPDATE zones SET name = :name" in sql
    assert "tenant_id = :tenant_id" in sql
    assert "farm_id = :farm_id" in sql
    assert "id = :zone_id" in sql
    assert params["tenant_id"] == TENANT_ID
    assert params["farm_id"] == FARM_ID
    assert params["zone_id"] == ZONE_ID


def test_update_zone_rejects_empty_payload(zone_client):
    _, request = zone_client

    response = asyncio.run(request(method="PATCH", json={}))

    assert response.status_code == 422


def test_update_zone_duplicate_name_returns_409(zone_client):
    db, request = zone_client
    db.execute.side_effect = IntegrityError(
        "UPDATE zones",
        {},
        RuntimeError("uq_zones_tenant_farm_name"),
    )

    response = asyncio.run(request(
        method="PATCH",
        json={"name": "Existing zone"},
    ))

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_delete_zone_returns_204_and_scopes_query(zone_client):
    db, request = zone_client

    response = asyncio.run(request(method="DELETE"))

    assert response.status_code == 204
    sql = str(db.execute.call_args.args[0])
    params = db.execute.call_args.args[1]
    assert "tenant_id = :tenant_id" in sql
    assert "farm_id = :farm_id" in sql
    assert "id = :zone_id" in sql
    assert params == {
        "tenant_id": TENANT_ID,
        "farm_id": FARM_ID,
        "zone_id": ZONE_ID,
    }


def test_delete_missing_zone_returns_404(zone_client):
    db, request = zone_client
    db.execute.return_value.rowcount = 0

    response = asyncio.run(request(method="DELETE"))

    assert response.status_code == 404


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_viewer_cannot_modify_or_delete_zone(zone_client, method):
    _, request = zone_client
    from app.api.zones import router

    route = next(
        route for route in router.routes
        if getattr(route, "path", "").endswith("/zones/{zone_id}")
        and method in getattr(route, "methods", set())
    )
    role_dependency = next(
        dependency.call
        for dependency in route.dependant.dependencies
        if dependency.name == "_role"
    )

    async def deny_viewer():
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    app.dependency_overrides[role_dependency] = deny_viewer
    try:
        response = asyncio.run(request(
            method=method,
            json={"name": "Not allowed"} if method == "PATCH" else None,
        ))
    finally:
        app.dependency_overrides.pop(role_dependency, None)

    assert response.status_code == 403


def test_missing_zone_returns_404(zone_client):
    db, request = zone_client
    db.execute.return_value.mappings.return_value.first.return_value = None

    response = asyncio.run(request(method="GET"))

    assert response.status_code == 404


def test_database_error_returns_safe_503(zone_client):
    db, request = zone_client
    db.execute.side_effect = OperationalError(
        "SELECT", {}, RuntimeError("private database detail")
    )

    response = asyncio.run(request(zone_id=None))

    assert response.status_code == 503
    assert "private database detail" not in response.text


def test_blank_zone_name_is_rejected(zone_client):
    _, request = zone_client

    response = asyncio.run(request(
        method="POST",
        zone_id=None,
        json={"name": "   "},
    ))

    assert response.status_code == 422
