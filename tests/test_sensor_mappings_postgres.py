"""PostgreSQL integration tests for sensor endpoint mappings."""

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
    assert url.database == "smartfarm"

    engine = create_engine(
        url.set(database="smartfarm_test"), pool_pre_ping=True
    )
    try:
        with engine.connect() as conn:
            database, role = conn.execute(
                text("SELECT current_database(), current_user")
            ).one()
            assert (database, role) == ("smartfarm_test", "smartfarm_owner")
            revisions = set(conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars().all())
            expected_revisions = {
                "0013_zigbee_device_registrations",
                "0015_farm_weather_coordinates",
            }
            assert revisions == expected_revisions, (
                f"Unexpected test migrations: {revisions!r}"
            )
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def app_engine():
    load_dotenv(".env")
    raw = os.environ.get("SMARTFARM_DATABASE_URL")
    assert raw, "Runtime database URL is not configured"
    url = make_url(raw)
    assert url.database == "smartfarm"

    engine = create_engine(
        url.set(database="smartfarm_test"), pool_pre_ping=True
    )
    try:
        with engine.connect() as conn:
            database, role = conn.execute(
                text("SELECT current_database(), current_user")
            ).one()
        assert (database, role) == ("smartfarm_test", "smartfarm_app")
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def require_test_database(app_engine):
    with app_engine.connect() as conn:
        database, role = conn.execute(
            text("SELECT current_database(), current_user")
        ).one()
    assert (database, role) == ("smartfarm_test", "smartfarm_app")


@pytest.fixture
def mapping_records(owner_engine):
    user_id = uuid4()
    tenant_id, farm_id, device_id = uuid4(), uuid4(), uuid4()
    email = f"sensor-mapping-{user_id.hex}@example.test"
    password = "Sensor-Mapping-Integration-Test-42!"

    with owner_engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO users (id, email, display_name, status)
                VALUES (:id, :email, 'Sensor Mapping Test', 'active')
            """),
            {"id": user_id, "email": email},
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
                VALUES (:id, 'Sensor Mapping Test Tenant', 'active')
            """),
            {"id": tenant_id},
        )
        conn.execute(
            text("""
                INSERT INTO tenant_memberships
                    (tenant_id, user_id, role, status)
                VALUES (:tenant_id, :user_id, 'owner', 'active')
            """),
            {"tenant_id": tenant_id, "user_id": user_id},
        )
        conn.execute(
            text("""
                INSERT INTO farms (id, tenant_id, name, timezone)
                VALUES (:id, :tenant_id, 'Sensor Mapping Test Farm',
                        'Asia/Bangkok')
            """),
            {"id": farm_id, "tenant_id": tenant_id},
        )
        conn.execute(
            text("""
                INSERT INTO devices (
                    id, tenant_id, farm_id, device_code, device_type,
                    name, status, created_at, updated_at
                )
                VALUES (
                    :id, :tenant_id, :farm_id, :code, 'sensor',
                    'Sensor Mapping Test Device', 'active',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """),
            {
                "id": device_id,
                "tenant_id": tenant_id,
                "farm_id": farm_id,
                "code": f"mapping-{device_id.hex}",
            },
        )

    records = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "farm_id": farm_id,
        "device_id": device_id,
        "email": email,
        "password": password,
    }
    yield records

    with owner_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM sensor_endpoint_mappings WHERE device_id = :id"),
            {"id": device_id},
        )
        conn.execute(
            text("DELETE FROM sensors WHERE device_id = :id"),
            {"id": device_id},
        )
        conn.execute(
            text("DELETE FROM devices WHERE id = :id"),
            {"id": device_id},
        )
        conn.execute(
            text("DELETE FROM farms WHERE id = :id"),
            {"id": farm_id},
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
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        conn.execute(
            text("DELETE FROM tenants WHERE id = :id"),
            {"id": tenant_id},
        )


@pytest.fixture
def mapping_http_client(app_engine):
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

    async def send(method, url, **kwargs):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.request(method, url, **kwargs)

    class Client:
        def request(self, method, url, **kwargs):
            return asyncio.run(send(method, url, **kwargs))

        def get(self, url, **kwargs):
            return self.request("GET", url, **kwargs)

        def post(self, url, **kwargs):
            return self.request("POST", url, **kwargs)

        def patch(self, url, **kwargs):
            return self.request("PATCH", url, **kwargs)

    try:
        yield Client()
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous


def test_postgres_sensor_mapping_runtime_crud(
    mapping_http_client, mapping_records
):
    client = mapping_http_client
    records = mapping_records

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": records["email"],
            "password": records["password"],
        },
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    base_url = (
        f"/api/v1/tenants/{records['tenant_id']}/devices/"
        f"{records['device_id']}"
    )

    sensor_response = client.post(
        f"{base_url}/sensors",
        headers=headers,
        json={
            "sensor_code": f"mapping-sensor-{uuid4().hex}",
            "measurement_type": "temperature",
            "unit": "C",
        },
    )
    assert sensor_response.status_code == 201, sensor_response.text
    sensor_id = sensor_response.json()["id"]

    mapping_url = f"{base_url}/sensor-mappings"
    created = client.post(
        mapping_url,
        headers=headers,
        json={
            "sensor_id": sensor_id,
            "adapter_type": " TEST_ADAPTER ",
            "endpoint_key": " endpoint-01 ",
        },
    )
    assert created.status_code == 201, created.text

    mapping = created.json()
    mapping_id = mapping["id"]
    assert mapping["sensor_id"] == sensor_id
    assert mapping["adapter_type"] == "test_adapter"
    assert mapping["endpoint_key"] == "endpoint-01"
    assert mapping["mapping_status"] == "active"

    listed = client.get(mapping_url, headers=headers)
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == mapping_id for item in listed.json())

    fetched = client.get(f"{mapping_url}/{mapping_id}", headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["id"] == mapping_id

    updated = client.patch(
        f"{mapping_url}/{mapping_id}",
        headers=headers,
        json={"mapping_status": "disabled"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["mapping_status"] == "disabled"

    filtered = client.get(
        mapping_url,
        headers=headers,
        params={"status": "disabled", "adapter_type": "test_adapter"},
    )
    assert filtered.status_code == 200, filtered.text
    assert [item["id"] for item in filtered.json()] == [mapping_id]
