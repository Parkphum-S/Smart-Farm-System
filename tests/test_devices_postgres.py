"""PostgreSQL integration tests for tenant-safe device zone assignment."""

import asyncio
import os
from uuid import uuid4

import httpx
import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db.session import get_db
from app.main import app
from app.security.user_auth import hash_password


@pytest.fixture(scope="module")
def owner_engine():
    load_dotenv(".env")
    raw = os.environ.get("SMARTFARM_MIGRATION_DATABASE_URL")
    assert raw, "Migration database URL is not configured"
    url = make_url(raw)
    assert url.database == "smartfarm", "Unexpected migration DB target"

    engine = create_engine(
        url.set(database="smartfarm_test"), pool_pre_ping=True
    )
    try:
        with engine.connect() as conn:
            database, role = conn.execute(
                text("SELECT current_database(), current_user")
            ).one()
            assert database == "smartfarm_test"
            assert role == "smartfarm_owner"
            revision = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision in {
                "0011_device_platform_integration",
                "0012_sensor_registration",
                "0013_zigbee_device_registrations",
            }
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def app_engine():
    load_dotenv(".env")
    raw = os.environ.get("SMARTFARM_DATABASE_URL")
    assert raw, "Runtime database URL is not configured"
    url = make_url(raw)
    assert url.database == "smartfarm", "Unexpected runtime DB target"

    engine = create_engine(
        url.set(database="smartfarm_test"), pool_pre_ping=True
    )
    try:
        with engine.connect() as conn:
            database, role = conn.execute(
                text("SELECT current_database(), current_user")
            ).one()
        assert database == "smartfarm_test"
        assert role == "smartfarm_app"
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def require_test_database(app_engine):
    with app_engine.connect() as conn:
        database, role = conn.execute(
            text("SELECT current_database(), current_user")
        ).one()
    assert database == "smartfarm_test"
    assert role == "smartfarm_app"


@pytest.fixture
def device_records(owner_engine):
    user_id = uuid4()
    tenant_a, tenant_b = uuid4(), uuid4()
    farm_a, farm_b = uuid4(), uuid4()
    zone_a, zone_a2, zone_b = uuid4(), uuid4(), uuid4()
    device_a, device_no_farm, device_b = uuid4(), uuid4(), uuid4()
    email = f"device-zone-{user_id.hex}@example.test"
    password = "Device-Zone-Integration-Test-42!"

    with owner_engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO users (id, email, display_name, status)
                VALUES (:id, :email, :name, 'active')
            """),
            {
                "id": user_id,
                "email": email,
                "name": "Device Zone Integration Test",
            },
        )
        conn.execute(
            text("""
                INSERT INTO user_credentials (user_id, password_hash)
                VALUES (:id, :password_hash)
            """),
            {"id": user_id, "password_hash": hash_password(password)},
        )
        conn.execute(
            text("""
                INSERT INTO tenants (id, name, status)
                VALUES
                    (:tenant_a, 'Device Test Tenant A', 'active'),
                    (:tenant_b, 'Device Test Tenant B', 'active')
            """),
            {"tenant_a": tenant_a, "tenant_b": tenant_b},
        )
        conn.execute(
            text("""
                INSERT INTO tenant_memberships
                    (tenant_id, user_id, role, status)
                VALUES (:tenant_id, :user_id, 'owner', 'active')
            """),
            {"tenant_id": tenant_a, "user_id": user_id},
        )
        conn.execute(
            text("""
                INSERT INTO farms (id, tenant_id, name, timezone)
                VALUES
                    (:farm_a, :tenant_a, 'Device Test Farm A', 'Asia/Bangkok'),
                    (:farm_b, :tenant_b, 'Device Test Farm B', 'Asia/Bangkok')
            """),
            {
                "farm_a": farm_a,
                "tenant_a": tenant_a,
                "farm_b": farm_b,
                "tenant_b": tenant_b,
            },
        )
        conn.execute(
            text("""
                INSERT INTO zones (
                    id, tenant_id, farm_id, name, description, status,
                    zone_type, category_details, created_at, updated_at
                )
                VALUES
                    (:zone_a, :tenant_a, :farm_a, 'Device Zone A', NULL,
                     'active', 'plant', CAST('{}' AS jsonb),
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    (:zone_a2, :tenant_a, :farm_a, 'Device Zone A2', NULL,
                     'active', 'plant', CAST('{}' AS jsonb),
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    (:zone_b, :tenant_b, :farm_b, 'Device Zone B', NULL,
                     'active', 'plant', CAST('{}' AS jsonb),
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """),
            {
                "zone_a": zone_a,
                "zone_a2": zone_a2,
                "zone_b": zone_b,
                "tenant_a": tenant_a,
                "tenant_b": tenant_b,
                "farm_a": farm_a,
                "farm_b": farm_b,
            },
        )
        conn.execute(
            text("""
                INSERT INTO devices (
                    id, tenant_id, farm_id, device_code, device_type,
                    name, status, created_at, updated_at
                )
                VALUES
                    (:device_a, :tenant_a, :farm_a, :code_a, 'sensor',
                     'Device A', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    (:device_no_farm, :tenant_a, NULL, :code_no_farm, 'sensor',
                     'Device No Farm', 'pending',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    (:device_b, :tenant_b, :farm_b, :code_b, 'sensor',
                     'Device B', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """),
            {
                "device_a": device_a,
                "device_no_farm": device_no_farm,
                "device_b": device_b,
                "tenant_a": tenant_a,
                "tenant_b": tenant_b,
                "farm_a": farm_a,
                "farm_b": farm_b,
                "code_a": f"device-{device_a.hex}",
                "code_no_farm": f"device-{device_no_farm.hex}",
                "code_b": f"device-{device_b.hex}",
            },
        )

    records = {
        "user_id": user_id,
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "farm_a": farm_a,
        "farm_b": farm_b,
        "zone_a": zone_a,
        "zone_a2": zone_a2,
        "zone_b": zone_b,
        "device_a": device_a,
        "device_no_farm": device_no_farm,
        "device_b": device_b,
        "email": email,
        "password": password,
    }
    yield records

    with owner_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM devices WHERE id = ANY(:ids)"),
            {"ids": [device_a, device_no_farm, device_b]},
        )
        conn.execute(
            text("DELETE FROM zones WHERE id = ANY(:ids)"),
            {"ids": [zone_a, zone_a2, zone_b]},
        )
        conn.execute(
            text("DELETE FROM farms WHERE id = ANY(:ids)"),
            {"ids": [farm_a, farm_b]},
        )
        conn.execute(
            text("DELETE FROM tenant_memberships WHERE user_id = :id"),
            {"id": user_id},
        )
        conn.execute(
            text("DELETE FROM user_sessions WHERE user_id = :id"),
            {"id": user_id},
        )
        conn.execute(
            text("DELETE FROM user_credentials WHERE user_id = :id"),
            {"id": user_id},
        )
        conn.execute(
            text("DELETE FROM users WHERE id = :id"),
            {"id": user_id},
        )
        conn.execute(
            text("DELETE FROM tenants WHERE id = ANY(:ids)"),
            {"ids": [tenant_a, tenant_b]},
        )


@pytest.fixture
def http_client(app_engine):
    testing_session = sessionmaker(
        bind=app_engine, autoflush=False, expire_on_commit=False
    )

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db

    class SyncASGIClient:
        def request(self, method, url, **kwargs):
            async def send():
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                ) as client:
                    return await client.request(method, url, **kwargs)

            return asyncio.run(send())

        def get(self, url, **kwargs):
            return self.request("GET", url, **kwargs)

        def post(self, url, **kwargs):
            return self.request("POST", url, **kwargs)

        def patch(self, url, **kwargs):
            return self.request("PATCH", url, **kwargs)

    try:
        yield SyncASGIClient()
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous


def login(client, records):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": records["email"], "password": records["password"]},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def device_zone_url(records, device_key="device_a", tenant_key="tenant_a"):
    return (
        f"/api/v1/tenants/{records[tenant_key]}/devices/"
        f"{records[device_key]}/zone"
    )


def test_postgres_assign_and_unassign_device_zone(
    http_client, device_records, owner_engine
):
    headers = login(http_client, device_records)
    url = device_zone_url(device_records)

    assigned = http_client.patch(
        url, headers=headers, json={"zone_id": str(device_records["zone_a"])}
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["zone_id"] == str(device_records["zone_a"])
    assert assigned.json()["farm_id"] == str(device_records["farm_a"])

    moved = http_client.patch(
        url, headers=headers, json={"zone_id": str(device_records["zone_a2"])}
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["zone_id"] == str(device_records["zone_a2"])

    unassigned = http_client.patch(
        url, headers=headers, json={"zone_id": None}
    )
    assert unassigned.status_code == 200, unassigned.text
    assert unassigned.json()["zone_id"] is None

    with owner_engine.connect() as conn:
        stored = conn.execute(
            text("SELECT zone_id FROM devices WHERE id = :id"),
            {"id": device_records["device_a"]},
        ).scalar_one_or_none()
    assert stored is None


def test_postgres_rejects_zone_outside_device_farm(
    http_client, device_records
):
    headers = login(http_client, device_records)
    response = http_client.patch(
        device_zone_url(device_records),
        headers=headers,
        json={"zone_id": str(device_records["zone_b"])},
    )
    assert response.status_code == 409


def test_postgres_rejects_zone_assignment_without_farm(
    http_client, device_records
):
    headers = login(http_client, device_records)
    response = http_client.patch(
        device_zone_url(device_records, "device_no_farm"),
        headers=headers,
        json={"zone_id": str(device_records["zone_a"])},
    )
    assert response.status_code == 409


def test_postgres_hides_device_from_other_tenant(
    http_client, device_records
):
    headers = login(http_client, device_records)
    response = http_client.patch(
        device_zone_url(
            device_records, "device_b", tenant_key="tenant_b"
        ),
        headers=headers,
        json={"zone_id": str(device_records["zone_b"])},
    )
    assert response.status_code in (401, 403, 404)


def test_postgres_device_list_includes_zone_but_not_credentials(
    http_client, device_records
):
    headers = login(http_client, device_records)
    assigned = http_client.patch(
        device_zone_url(device_records),
        headers=headers,
        json={"zone_id": str(device_records["zone_a"])},
    )
    assert assigned.status_code == 200, assigned.text

    response = http_client.get(
        f"/api/v1/tenants/{device_records['tenant_a']}/devices",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    device = next(
        item for item in response.json()
        if item["id"] == str(device_records["device_a"])
    )
    assert device["zone_id"] == str(device_records["zone_a"])
    assert "device_token_hash" not in device
    assert "credentials" not in device


def test_postgres_runtime_role_can_update_only_assignment_columns(
    app_engine,
):
    with app_engine.connect() as conn:
        assert conn.execute(
            text("SELECT has_column_privilege("
                 "current_user, 'public.devices', 'zone_id', 'UPDATE')")
        ).scalar_one()
        assert conn.execute(
            text("SELECT has_column_privilege("
                 "current_user, 'public.devices', 'updated_at', 'UPDATE')")
        ).scalar_one()
        assert not conn.execute(
            text("SELECT has_column_privilege("
                 "current_user, 'public.devices', 'farm_id', 'UPDATE')")
        ).scalar_one()
        assert not conn.execute(
            text("SELECT has_column_privilege("
                 "current_user, 'public.devices', 'tenant_id', 'UPDATE')")
        ).scalar_one()


def test_postgres_zone_fk_restricts_cross_farm_assignment(
    owner_engine, device_records
):
    with owner_engine.begin() as conn:
        with pytest.raises(Exception):
            conn.execute(
                text("""
                    UPDATE devices
                    SET zone_id = :zone_b
                    WHERE id = :device_a
                """),
                {
                    "zone_b": device_records["zone_b"],
                    "device_a": device_records["device_a"],
                },
            )


def test_postgres_create_device(http_client, device_records, owner_engine):
    headers = login(http_client, device_records)
    code = f"new-device-{uuid4().hex}"
    response = http_client.post(
        f"/api/v1/tenants/{device_records['tenant_a']}/devices",
        headers=headers,
        json={
            "device_code": code,
            "device_type": "gateway",
            "name": "New Test Gateway",
            "farm_id": str(device_records["farm_a"]),
            "status": "pending",
            "platform": "ESP32",
            "protocol": "MQTT",
            "vendor": "Espressif",
            "capabilities": {
                "relays": 4,
                "sensors": ["temperature", "humidity"],
            },
        },
    )

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["device_code"] == code
    assert created["name"] == "New Test Gateway"
    assert created["farm_id"] == str(device_records["farm_a"])
    assert created["zone_id"] is None
    assert "device_token_hash" not in created
    assert "credentials" not in created

    try:
        with owner_engine.connect() as conn:
            stored = conn.execute(
                text("""
                    SELECT tenant_id, farm_id, device_code, device_type, name, status,
                           platform, protocol, vendor, capabilities
                    FROM devices WHERE id = :id
                """),
                {"id": created["id"]},
            ).mappings().one()
        assert str(stored["tenant_id"]) == str(device_records["tenant_a"])
        assert str(stored["farm_id"]) == str(device_records["farm_a"])
        assert stored["device_code"] == code
        assert stored["device_type"] == "gateway"
        assert stored["name"] == "New Test Gateway"
        assert stored["status"] == "pending"
        assert stored["platform"] == "ESP32"
        assert stored["protocol"] == "MQTT"
        assert stored["vendor"] == "Espressif"
        assert stored["capabilities"] == {
            "relays": 4,
            "sensors": ["temperature", "humidity"],
        }
    finally:
        with owner_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM devices WHERE device_code = :code"),
                {"code": code},
            )


def test_postgres_create_device_rejects_farm_from_other_tenant(
    http_client, device_records
):
    headers = login(http_client, device_records)
    response = http_client.post(
        f"/api/v1/tenants/{device_records['tenant_a']}/devices",
        headers=headers,
        json={
            "device_code": f"invalid-farm-{uuid4().hex}",
            "device_type": "gateway",
            "name": "Invalid Farm Device",
            "farm_id": str(device_records["farm_b"]),
            "status": "pending",
        },
    )
    assert response.status_code == 409, response.text


def test_postgres_update_device_name_and_status(
    http_client, device_records, owner_engine
):
    headers = login(http_client, device_records)
    response = http_client.patch(
        f"/api/v1/tenants/{device_records['tenant_a']}/devices/"
        f"{device_records['device_a']}",
        headers=headers,
        json={"name": "Updated Device Name", "status": "disabled"},
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["name"] == "Updated Device Name"
    assert updated["status"] == "disabled"
    assert updated["device_code"].startswith("device-")

    with owner_engine.connect() as conn:
        stored = conn.execute(
            text("SELECT name, status FROM devices WHERE id = :id"),
            {"id": device_records["device_a"]},
        ).mappings().one()
    assert stored["name"] == "Updated Device Name"
    assert stored["status"] == "disabled"


def test_postgres_update_device_platform_metadata(
    http_client, device_records, owner_engine
):
    headers = login(http_client, device_records)
    response = http_client.patch(
        f"/api/v1/tenants/{device_records['tenant_a']}/devices/"
        f"{device_records['device_a']}",
        headers=headers,
        json={
            "platform": "ESP8266",
            "protocol": "HTTP",
            "vendor": "Espressif",
            "capabilities": {"relays": 2, "sensors": ["temperature"]},
        },
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["platform"] == "ESP8266"
    assert updated["protocol"] == "HTTP"
    assert updated["vendor"] == "Espressif"
    assert updated["capabilities"] == {
        "relays": 2,
        "sensors": ["temperature"],
    }

    with owner_engine.connect() as conn:
        stored = conn.execute(
            text("""
                SELECT platform, protocol, vendor, capabilities
                FROM devices WHERE id = :id
            """),
            {"id": device_records["device_a"]},
        ).mappings().one()

    assert stored["platform"] == "ESP8266"
    assert stored["protocol"] == "HTTP"
    assert stored["vendor"] == "Espressif"
    assert stored["capabilities"] == {
        "relays": 2,
        "sensors": ["temperature"],
    }


def test_postgres_update_device_cannot_change_other_tenant_device(
    http_client, device_records
):
    headers = login(http_client, device_records)
    response = http_client.patch(
        f"/api/v1/tenants/{device_records['tenant_a']}/devices/"
        f"{device_records['device_b']}",
        headers=headers,
        json={"name": "Should Not Update"},
    )
    assert response.status_code in (403, 404)


def test_postgres_changing_device_farm_to_null_clears_zone(
    http_client, device_records, owner_engine
):
    headers = login(http_client, device_records)
    base_url = (
        f"/api/v1/tenants/{device_records['tenant_a']}/devices/"
        f"{device_records['device_a']}"
    )

    assigned = http_client.patch(
        f"{base_url}/zone",
        headers=headers,
        json={"zone_id": str(device_records["zone_a"])},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["zone_id"] == str(device_records["zone_a"])

    response = http_client.patch(
        base_url,
        headers=headers,
        json={"farm_id": None},
    )

    assert response.status_code == 200, response.text
    assert response.json()["farm_id"] is None
    assert response.json()["zone_id"] is None

    with owner_engine.connect() as conn:
        stored = conn.execute(
            text("SELECT farm_id, zone_id FROM devices WHERE id = :id"),
            {"id": device_records["device_a"]},
        ).mappings().one()

    assert stored["farm_id"] is None
    assert stored["zone_id"] is None


def test_postgres_updating_device_with_same_farm_preserves_zone(
    http_client, device_records, owner_engine
):
    headers = login(http_client, device_records)
    base_url = (
        f"/api/v1/tenants/{device_records['tenant_a']}/devices/"
        f"{device_records['device_a']}"
    )

    assigned = http_client.patch(
        f"{base_url}/zone",
        headers=headers,
        json={"zone_id": str(device_records["zone_a"])},
    )
    assert assigned.status_code == 200, assigned.text

    response = http_client.patch(
        base_url,
        headers=headers,
        json={"farm_id": str(device_records["farm_a"])},
    )

    assert response.status_code == 200, response.text
    assert response.json()["farm_id"] == str(device_records["farm_a"])
    assert response.json()["zone_id"] == str(device_records["zone_a"])

    with owner_engine.connect() as conn:
        stored = conn.execute(
            text("SELECT farm_id, zone_id FROM devices WHERE id = :id"),
            {"id": device_records["device_a"]},
        ).mappings().one()

    assert stored["farm_id"] == device_records["farm_a"]
    assert stored["zone_id"] == device_records["zone_a"]


def test_postgres_update_device_rejects_farm_from_other_tenant(
    http_client, device_records, owner_engine
):
    headers = login(http_client, device_records)
    url = (
        f"/api/v1/tenants/{device_records['tenant_a']}/devices/"
        f"{device_records['device_a']}"
    )

    response = http_client.patch(
        url,
        headers=headers,
        json={"farm_id": str(device_records["farm_b"])},
    )

    assert response.status_code == 409, response.text

    with owner_engine.connect() as conn:
        stored = conn.execute(
            text("SELECT farm_id, zone_id FROM devices WHERE id = :id"),
            {"id": device_records["device_a"]},
        ).mappings().one()

    assert stored["farm_id"] == device_records["farm_a"]
    assert stored["zone_id"] is None


def test_postgres_update_missing_device_returns_404(
    http_client, device_records
):
    headers = login(http_client, device_records)
    missing_device_id = uuid4()

    response = http_client.patch(
        f"/api/v1/tenants/{device_records['tenant_a']}/devices/"
        f"{missing_device_id}",
        headers=headers,
        json={"name": "Missing Device"},
    )

    assert response.status_code == 404, response.text
