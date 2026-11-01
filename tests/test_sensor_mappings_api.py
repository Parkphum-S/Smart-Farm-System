"""Tests for tenant-scoped sensor endpoint mapping API."""

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
DEVICE_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
SENSOR_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
MAPPING_ID = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
CREATED_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)

USER = AuthenticatedUser(
    id="mapping-test-user",
    email="mapping-test@example.invalid",
    display_name="Mapping Test",
)

MAPPING_ROW = {
    "id": MAPPING_ID,
    "tenant_id": TENANT_ID,
    "device_id": DEVICE_ID,
    "sensor_id": SENSOR_ID,
    "adapter_type": "zigbee",
    "endpoint_key": "endpoint-1",
    "mapping_status": "active",
    "created_at": CREATED_AT,
    "updated_at": CREATED_AT,
}


def result(*, first=None, one=None, all_rows=None):
    value = Mock()
    value.first.return_value = first
    value.mappings.return_value.first.return_value = first
    value.mappings.return_value.one.return_value = (
        one if one is not None else MAPPING_ROW
    )
    value.mappings.return_value.all.return_value = (
        all_rows if all_rows is not None else [MAPPING_ROW]
    )
    return value


@pytest.fixture
def mapping_client(monkeypatch):
    db = Mock()
    db.begin.return_value.__enter__ = Mock(return_value=db)
    db.begin.return_value.__exit__ = Mock(return_value=False)
    db.execute.return_value = result(first={"status": "active"})

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
        device_id=DEVICE_ID,
        mapping_id=MAPPING_ID,
        token="test-token",
        json=None,
        query=None,
    ):
        path = (
            f"/api/v1/tenants/{tenant_id}/devices/{device_id}"
            "/sensor-mappings"
        )
        if mapping_id is not None:
            path += f"/{mapping_id}"

        headers = (
            {"Authorization": f"Bearer {token}"}
            if token is not None else {}
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.request(
                method, path, headers=headers, json=json, params=query
            )

    yield db, request
    app.dependency_overrides.pop(get_db, None)


def test_missing_token_returns_401(mapping_client):
    db, request = mapping_client
    response = asyncio.run(request(token=None))
    assert response.status_code == 401
    db.begin.assert_not_called()


@pytest.mark.parametrize("role", ["owner", "operator", "viewer"])
def test_all_roles_can_list_mappings(mapping_client, monkeypatch, role):
    db, request = mapping_client
    monkeypatch.setattr(
        dependencies, "authorize_tenant", Mock(return_value=role)
    )
    response = asyncio.run(request(mapping_id=None))
    assert response.status_code == 200
    assert response.json()[0]["id"] == str(MAPPING_ID)
    sql = str(db.execute.call_args.args[0])
    params = db.execute.call_args.args[1]
    assert "FROM sensor_endpoint_mappings" in sql
    assert "tenant_id = :tenant_id" in sql
    assert "device_id = :device_id" in sql
    assert params["tenant_id"] == TENANT_ID
    assert params["device_id"] == DEVICE_ID


def test_list_mapping_filters_and_pagination(mapping_client):
    db, request = mapping_client
    response = asyncio.run(request(
        mapping_id=None,
        query={"status": "active", "adapter_type": " ZIGBEE ", "limit": 20, "offset": 5},
    ))
    assert response.status_code == 200
    params = db.execute.call_args.args[1]
    assert params["mapping_status"] == "active"
    assert params["adapter_type"] == "zigbee"
    assert params["limit"] == 20
    assert params["offset"] == 5


def test_list_mappings_empty(mapping_client):
    db, request = mapping_client
    db.execute.return_value = result(all_rows=[])
    response = asyncio.run(request(mapping_id=None))
    assert response.status_code == 200
    assert response.json() == []


def test_get_mapping_is_tenant_device_scoped(mapping_client):
    db, request = mapping_client
    db.execute.return_value = result(first=MAPPING_ROW)
    response = asyncio.run(request())
    assert response.status_code == 200
    assert response.json()["endpoint_key"] == "endpoint-1"
    sql = str(db.execute.call_args.args[0])
    params = db.execute.call_args.args[1]
    assert "tenant_id = :tenant_id" in sql
    assert "device_id = :device_id" in sql
    assert "id = :mapping_id" in sql
    assert params["mapping_id"] == MAPPING_ID


def test_get_mapping_not_found(mapping_client):
    db, request = mapping_client
    db.execute.return_value = result(first=None)
    response = asyncio.run(request())
    assert response.status_code == 404


def test_create_mapping_success_and_normalizes_values(mapping_client):
    db, request = mapping_client
    db.execute.side_effect = [
        result(first={"status": "active"}),
        result(one=MAPPING_ROW),
    ]
    response = asyncio.run(request(
        method="POST",
        mapping_id=None,
        json={
            "sensor_id": str(SENSOR_ID),
            "adapter_type": " ZIGBEE ",
            "endpoint_key": " endpoint-1 ",
        },
    ))
    assert response.status_code == 201
    assert db.execute.call_count == 2
    assert "FOR SHARE" in str(db.execute.call_args_list[0].args[0])
    insert_sql = str(db.execute.call_args_list[1].args[0])
    params = db.execute.call_args_list[1].args[1]
    assert "INSERT INTO sensor_endpoint_mappings" in insert_sql
    assert params["tenant_id"] == TENANT_ID
    assert params["device_id"] == DEVICE_ID
    assert params["adapter_type"] == "zigbee"
    assert params["endpoint_key"] == "endpoint-1"


def test_create_mapping_rejects_sensor_outside_device(mapping_client):
    db, request = mapping_client
    db.execute.return_value = result(first=None)
    response = asyncio.run(request(
        method="POST",
        mapping_id=None,
        json={
            "sensor_id": str(SENSOR_ID),
            "adapter_type": "zigbee",
            "endpoint_key": "endpoint-1",
        },
    ))
    assert response.status_code == 404
    db.execute.assert_called_once()


def test_active_mapping_requires_active_sensor(mapping_client):
    db, request = mapping_client
    db.execute.return_value = result(first={"status": "disabled"})
    response = asyncio.run(request(
        method="POST",
        mapping_id=None,
        json={
            "sensor_id": str(SENSOR_ID),
            "adapter_type": "zigbee",
            "endpoint_key": "endpoint-1",
            "mapping_status": "active",
        },
    ))
    assert response.status_code == 409
    db.execute.assert_called_once()


def test_create_duplicate_mapping_returns_409(mapping_client):
    db, request = mapping_client
    db.execute.side_effect = [
        result(first={"status": "active"}),
        IntegrityError("INSERT", {}, RuntimeError("unique violation")),
    ]
    response = asyncio.run(request(
        method="POST",
        mapping_id=None,
        json={
            "sensor_id": str(SENSOR_ID),
            "adapter_type": "zigbee",
            "endpoint_key": "endpoint-1",
        },
    ))
    assert response.status_code == 409


@pytest.mark.parametrize("role", ["owner", "operator"])
def test_owner_and_operator_can_update_mapping(mapping_client, monkeypatch, role):
    db, request = mapping_client
    monkeypatch.setattr(
        dependencies, "authorize_tenant", Mock(return_value=role)
    )
    updated = {**MAPPING_ROW, "mapping_status": "disabled"}
    db.execute.side_effect = [
        result(first=MAPPING_ROW),
        result(first={"status": "active"}),
        result(one=updated),
    ]
    response = asyncio.run(request(
        method="PATCH", json={"mapping_status": "disabled"}
    ))
    assert response.status_code == 200
    assert response.json()["mapping_status"] == "disabled"
    assert "FOR UPDATE" in str(db.execute.call_args_list[0].args[0])


def test_update_mapping_not_found(mapping_client):
    db, request = mapping_client
    db.execute.return_value = result(first=None)
    response = asyncio.run(request(method="PATCH", json={"endpoint_key": "x"}))
    assert response.status_code == 404
    db.execute.assert_called_once()


def test_viewer_cannot_create_or_update_mapping(mapping_client, monkeypatch):
    db, request = mapping_client
    monkeypatch.setattr(
        dependencies,
        "authorize_tenant",
        Mock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
    )
    create = asyncio.run(request(
        method="POST",
        mapping_id=None,
        json={
            "sensor_id": str(SENSOR_ID),
            "adapter_type": "zigbee",
            "endpoint_key": "endpoint-1",
        },
    ))
    update = asyncio.run(request(method="PATCH", json={"mapping_status": "disabled"}))
    assert create.status_code == 403
    assert update.status_code == 403
    db.execute.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"sensor_id": str(SENSOR_ID), "adapter_type": " ", "endpoint_key": "x"},
        {"sensor_id": str(SENSOR_ID), "adapter_type": "zigbee", "endpoint_key": " "},
        {"sensor_id": str(SENSOR_ID), "adapter_type": "zigbee", "endpoint_key": "x", "extra": 1},
        {"sensor_id": str(SENSOR_ID), "adapter_type": "zigbee", "endpoint_key": "x", "mapping_status": "unknown"},
    ],
)
def test_create_rejects_invalid_payload(mapping_client, payload):
    db, request = mapping_client
    response = asyncio.run(request(method="POST", mapping_id=None, json=payload))
    assert response.status_code == 422
    db.execute.assert_not_called()


@pytest.mark.parametrize("payload", [{}, {"endpoint_key": None}, {"mapping_status": None}, {"extra": "x"}])
def test_update_rejects_invalid_payload(mapping_client, payload):
    db, request = mapping_client
    response = asyncio.run(request(method="PATCH", json=payload))
    assert response.status_code == 422
    db.execute.assert_not_called()


def test_mapping_has_no_delete_route(mapping_client):
    db, request = mapping_client
    response = asyncio.run(request(method="DELETE"))
    assert response.status_code == 405
    db.execute.assert_not_called()


def test_database_error_returns_safe_503(mapping_client):
    db, request = mapping_client
    db.execute.side_effect = OperationalError("SELECT", {}, RuntimeError("db down"))
    response = asyncio.run(request(mapping_id=None))
    assert response.status_code == 503
    assert "db down" not in response.text
