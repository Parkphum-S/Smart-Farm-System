
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
DEVICE_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
OTHER_DEVICE_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
SENSOR_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
CREATED_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)

USER = AuthenticatedUser(
    id="sensor-test-user",
    email="sensor-test@example.invalid",
    display_name="Sensor Test",
)

SENSOR_ROW = {
    "id": SENSOR_ID,
    "tenant_id": TENANT_ID,
    "device_id": DEVICE_ID,
    "sensor_code": "TEMP-001",
    "measurement_type": "temperature",
    "unit": "°C",
    "status": "active",
    "created_at": CREATED_AT,
}


def result(*, first=None, one=None, all_rows=None, scalar=None):
    value = Mock()
    value.first.return_value = first
    value.mappings.return_value.first.return_value = first
    value.mappings.return_value.one.return_value = (
        one if one is not None else SENSOR_ROW
    )
    value.mappings.return_value.all.return_value = (
        all_rows if all_rows is not None else [SENSOR_ROW]
    )
    value.scalar_one.return_value = scalar
    return value


@pytest.fixture
def sensor_client(monkeypatch):
    db = Mock()
    db.begin.return_value.__enter__ = Mock(return_value=db)
    db.begin.return_value.__exit__ = Mock(return_value=False)
    db.execute.return_value = result(first=SENSOR_ROW)

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
        method="GET",
        tenant_id=TENANT_ID,
        device_id=DEVICE_ID,
        sensor_id=SENSOR_ID,
        token="test-token",
        json=None,
        query=None,
    ):
        path = (
            f"/api/v1/tenants/{tenant_id}"
            f"/devices/{device_id}/sensors"
        )
        if sensor_id is not None:
            path += f"/{sensor_id}"

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
                method,
                path,
                headers=headers,
                json=json,
                params=query,
            )

    yield db, request
    app.dependency_overrides.pop(get_db, None)


def test_missing_bearer_token_returns_401(sensor_client):
    db, request = sensor_client

    response = asyncio.run(request(token=None))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    db.begin.assert_not_called()


def test_tenant_without_membership_returns_403(
    sensor_client,
    monkeypatch,
):
    _, request = sensor_client
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


@pytest.mark.parametrize("role", ["owner", "operator", "viewer"])
def test_all_authorized_roles_can_list_sensors(
    sensor_client,
    monkeypatch,
    role,
):
    db, request = sensor_client
    monkeypatch.setattr(
        dependencies,
        "authorize_tenant",
        Mock(return_value=role),
    )

    response = asyncio.run(request(sensor_id=None))

    assert response.status_code == 200
    assert response.json()[0]["id"] == str(SENSOR_ID)

    sql = str(db.execute.call_args.args[0])
    params = db.execute.call_args.args[1]

    assert "FROM sensors" in sql
    assert "tenant_id = :tenant_id" in sql
    assert "device_id = :device_id" in sql
    assert params["tenant_id"] == TENANT_ID
    assert params["device_id"] == DEVICE_ID


def test_list_sensors_applies_filters_and_pagination(sensor_client):
    db, request = sensor_client

    response = asyncio.run(
        request(
            sensor_id=None,
            query={
                "status": "active",
                "measurement_type": "temperature",
                "limit": 25,
                "offset": 10,
            },
        )
    )

    assert response.status_code == 200

    sql = str(db.execute.call_args.args[0])
    params = db.execute.call_args.args[1]

    assert "status = :status" in sql
    assert "measurement_type = :measurement_type" in sql
    assert "ORDER BY sensor_code, id" in sql
    assert params["status"] == "active"
    assert params["measurement_type"] == "temperature"
    assert params["limit"] == 25
    assert params["offset"] == 10


def test_list_sensors_rejects_blank_measurement_type(sensor_client):
    db, request = sensor_client

    response = asyncio.run(
        request(
            sensor_id=None,
            query={"measurement_type": "   "},
        )
    )

    assert response.status_code == 422
    db.execute.assert_not_called()


@pytest.mark.parametrize(
    "query",
    [
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
        {"status": "unknown"},
    ],
)
def test_list_sensors_rejects_invalid_query_parameters(
    sensor_client,
    query,
):
    db, request = sensor_client

    response = asyncio.run(
        request(sensor_id=None, query=query)
    )

    assert response.status_code == 422
    db.execute.assert_not_called()


def test_list_sensors_returns_empty_list(sensor_client):
    db, request = sensor_client
    db.execute.return_value = result(all_rows=[])

    response = asyncio.run(request(sensor_id=None))

    assert response.status_code == 200
    assert response.json() == []


def test_get_sensor_returns_tenant_device_scoped_resource(sensor_client):
    db, request = sensor_client

    response = asyncio.run(request())

    assert response.status_code == 200
    assert response.json()["id"] == str(SENSOR_ID)
    assert response.json()["sensor_code"] == "TEMP-001"

    sql = str(db.execute.call_args.args[0])
    params = db.execute.call_args.args[1]

    assert "tenant_id = :tenant_id" in sql
    assert "device_id = :device_id" in sql
    assert "id = :sensor_id" in sql
    assert params == {
        "tenant_id": TENANT_ID,
        "device_id": DEVICE_ID,
        "sensor_id": SENSOR_ID,
    }


@pytest.mark.parametrize("role", ["owner", "operator", "viewer"])
def test_all_authorized_roles_can_get_sensor(
    sensor_client,
    monkeypatch,
    role,
):
    _, request = sensor_client
    monkeypatch.setattr(
        dependencies,
        "authorize_tenant",
        Mock(return_value=role),
    )

    response = asyncio.run(request())

    assert response.status_code == 200


def test_get_sensor_not_found_returns_404(sensor_client):
    db, request = sensor_client
    db.execute.return_value = result(first=None)

    response = asyncio.run(request())

    assert response.status_code == 404
    assert response.json()["detail"] == "Sensor not found"


def test_create_sensor_success(sensor_client):
    db, request = sensor_client

    device_result = result(first=(DEVICE_ID,))
    insert_result = result(one=SENSOR_ROW)
    db.execute.side_effect = [device_result, insert_result]

    response = asyncio.run(
        request(
            method="POST",
            sensor_id=None,
            json={
                "sensor_code": " TEMP-001 ",
                "measurement_type": " temperature ",
                "unit": " °C ",
            },
        )
    )

    assert response.status_code == 201
    assert response.json()["sensor_code"] == "TEMP-001"
    assert response.json()["measurement_type"] == "temperature"

    assert db.execute.call_count == 2

    device_sql = str(db.execute.call_args_list[0].args[0])
    assert "FROM devices" in device_sql
    assert "tenant_id = :tenant_id" in device_sql
    assert "id = :device_id" in device_sql

    insert_sql = str(db.execute.call_args_list[1].args[0])
    insert_params = db.execute.call_args_list[1].args[1]

    assert "INSERT INTO sensors" in insert_sql
    assert "RETURNING" in insert_sql
    assert insert_params["tenant_id"] == TENANT_ID
    assert insert_params["device_id"] == DEVICE_ID
    assert insert_params["sensor_code"] == "TEMP-001"
    assert insert_params["measurement_type"] == "temperature"
    assert insert_params["unit"] == "°C"


def test_create_sensor_device_not_found(sensor_client):
    db, request = sensor_client
    db.execute.return_value = result(first=None)

    response = asyncio.run(
        request(
            method="POST",
            sensor_id=None,
            json={
                "sensor_code": "TEMP-002",
                "measurement_type": "temperature",
                "unit": "°C",
            },
        )
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Device not found"
    db.execute.assert_called_once()


def test_create_sensor_duplicate_code_returns_409(sensor_client):
    db, request = sensor_client
    db.execute.side_effect = [
        result(first=(DEVICE_ID,)),
        IntegrityError(
            "INSERT INTO sensors",
            {},
            RuntimeError("uq_sensors_device_code"),
        ),
    ]

    response = asyncio.run(
        request(
            method="POST",
            sensor_id=None,
            json={
                "sensor_code": "TEMP-001",
                "measurement_type": "temperature",
                "unit": "°C",
            },
        )
    )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_create_sensor_invalid_reference_returns_409(sensor_client):
    db, request = sensor_client
    db.execute.side_effect = [
        result(first=(DEVICE_ID,)),
        IntegrityError(
            "INSERT INTO sensors",
            {},
            RuntimeError("foreign key violation"),
        ),
    ]

    response = asyncio.run(
        request(
            method="POST",
            sensor_id=None,
            json={
                "sensor_code": "TEMP-002",
                "measurement_type": "temperature",
                "unit": "°C",
            },
        )
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Sensor references are invalid"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "sensor_code": "   ",
            "measurement_type": "temperature",
            "unit": "°C",
        },
        {
            "sensor_code": "TEMP-001",
            "measurement_type": " ",
            "unit": "°C",
        },
        {
            "sensor_code": "TEMP-001",
            "measurement_type": "temperature",
            "unit": "",
        },
        {
            "sensor_code": "TEMP-001",
            "measurement_type": "temperature",
            "unit": "°C",
            "status": "retired",
        },
    ],
)
def test_create_sensor_rejects_invalid_payload(sensor_client, payload):
    db, request = sensor_client

    response = asyncio.run(
        request(
            method="POST",
            sensor_id=None,
            json=payload,
        )
    )

    assert response.status_code == 422
    db.execute.assert_not_called()


def test_viewer_cannot_create_sensor(sensor_client, monkeypatch):
    db, request = sensor_client
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
        request(
            method="POST",
            sensor_id=None,
            json={
                "sensor_code": "TEMP-003",
                "measurement_type": "temperature",
                "unit": "°C",
            },
        )
    )

    assert response.status_code == 403
    db.execute.assert_not_called()


@pytest.mark.parametrize("role", ["owner", "operator"])
def test_owner_and_operator_can_update_sensor(
    sensor_client,
    monkeypatch,
    role,
):
    db, request = sensor_client
    monkeypatch.setattr(
        dependencies,
        "authorize_tenant",
        Mock(return_value=role),
    )

    updated = {**SENSOR_ROW, "status": "disabled"}
    db.execute.side_effect = [
        result(first={"status": "active"}),
        result(one=updated),
    ]

    response = asyncio.run(
        request(method="PATCH", json={"status": "disabled"})
    )

    assert response.status_code == 200
    assert response.json()["status"] == "disabled"
    assert db.execute.call_count == 2

    lock_sql = str(db.execute.call_args_list[0].args[0])
    update_sql = str(db.execute.call_args_list[1].args[0])

    assert "FOR UPDATE" in lock_sql
    assert "UPDATE sensors" in update_sql
    assert "SET status = :status" in update_sql
    assert db.execute.call_args_list[1].args[1]["status"] == "disabled"


def test_update_sensor_rejects_viewer(sensor_client, monkeypatch):
    db, request = sensor_client
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
        request(method="PATCH", json={"status": "disabled"})
    )

    assert response.status_code == 403
    db.execute.assert_not_called()


def test_update_sensor_rejects_empty_payload(sensor_client):
    db, request = sensor_client

    response = asyncio.run(
        request(method="PATCH", json={})
    )

    assert response.status_code == 422
    db.execute.assert_not_called()


def test_update_sensor_rejects_null_value(sensor_client):
    db, request = sensor_client

    response = asyncio.run(
        request(method="PATCH", json={"unit": None})
    )

    assert response.status_code == 422
    db.execute.assert_not_called()


def test_update_sensor_rejects_extra_fields(sensor_client):
    db, request = sensor_client

    response = asyncio.run(
        request(
            method="PATCH",
            json={
                "status": "disabled",
                "sensor_code": "CHANGED",
            },
        )
    )

    assert response.status_code == 422
    db.execute.assert_not_called()


def test_update_sensor_not_found_returns_404(sensor_client):
    db, request = sensor_client
    db.execute.return_value = result(first=None)

    response = asyncio.run(
        request(method="PATCH", json={"status": "disabled"})
    )

    assert response.status_code == 404
    db.execute.assert_called_once()


def test_retired_sensor_cannot_be_reactivated(sensor_client):
    db, request = sensor_client
    db.execute.return_value = result(first={"status": "retired"})

    response = asyncio.run(
        request(method="PATCH", json={"status": "active"})
    )

    assert response.status_code == 409
    assert "cannot be reactivated" in response.json()["detail"]
    db.execute.assert_called_once()


def test_sensor_metadata_is_immutable_after_readings_exist(sensor_client):
    db, request = sensor_client
    db.execute.side_effect = [
        result(first={"status": "active"}),
        result(scalar=True),
    ]

    response = asyncio.run(
        request(
            method="PATCH",
            json={"measurement_type": "humidity"},
        )
    )

    assert response.status_code == 409
    assert "immutable" in response.json()["detail"]
    assert db.execute.call_count == 2

    assert "FOR UPDATE" in str(db.execute.call_args_list[0].args[0])
    assert "FROM sensor_readings" in str(
        db.execute.call_args_list[1].args[0]
    )


def test_sensor_metadata_can_change_before_readings_exist(sensor_client):
    db, request = sensor_client
    updated = {**SENSOR_ROW, "measurement_type": "humidity"}
    db.execute.side_effect = [
        result(first={"status": "active"}),
        result(scalar=False),
        result(one=updated),
    ]

    response = asyncio.run(
        request(
            method="PATCH",
            json={"measurement_type": "humidity"},
        )
    )

    assert response.status_code == 200
    assert response.json()["measurement_type"] == "humidity"
    assert db.execute.call_count == 3


def test_update_sensor_database_integrity_error_returns_409(sensor_client):
    db, request = sensor_client
    db.execute.side_effect = [
        result(first={"status": "active"}),
        IntegrityError(
            "UPDATE sensors",
            {},
            RuntimeError("constraint violation"),
        ),
    ]

    response = asyncio.run(
        request(method="PATCH", json={"status": "disabled"})
    )

    assert response.status_code == 409
    assert "conflicts" in response.json()["detail"]


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH"])
def test_sensor_database_errors_return_safe_503(sensor_client, method):
    db, request = sensor_client
    db.execute.side_effect = OperationalError(
        "SELECT",
        {},
        RuntimeError("private database detail"),
    )

    if method == "POST":
        response = asyncio.run(
            request(
                method=method,
                sensor_id=None,
                json={
                    "sensor_code": "TEMP-004",
                    "measurement_type": "temperature",
                    "unit": "°C",
                },
            )
        )
    elif method == "PATCH":
        response = asyncio.run(
            request(method=method, json={"status": "disabled"})
        )
    else:
        response = asyncio.run(request(method=method))

    assert response.status_code == 503
    assert "private database detail" not in response.text


def test_sensor_has_no_delete_route():
    from app.api.sensors import router

    delete_routes = [
        route
        for route in router.routes
        if "DELETE" in getattr(route, "methods", set())
    ]

    assert delete_routes == []
