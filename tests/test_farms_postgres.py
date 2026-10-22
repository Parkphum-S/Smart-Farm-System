import asyncio
import os
from uuid import uuid4

import httpx
import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.db.session import engine
from app.main import app
from app.security.user_auth import hash_password


@pytest.fixture(scope="module")
def owner_engine():
    load_dotenv(".env")
    raw_url = os.environ.get("SMARTFARM_MIGRATION_DATABASE_URL")
    assert raw_url, "Migration database URL is not configured"

    url = make_url(raw_url)
    assert url.database == "smartfarm", "Unexpected migration DB target"

    test_engine = create_engine(
        url.set(database="smartfarm_test"),
        pool_pre_ping=True,
    )
    try:
        with test_engine.connect() as conn:
            assert conn.execute(
                text("SELECT current_database()")
            ).scalar_one() == "smartfarm_test"
        yield test_engine
    finally:
        test_engine.dispose()


@pytest.fixture(autouse=True)
def require_test_database():
    with engine.connect() as conn:
        database, role = conn.execute(
            text("SELECT current_database(), current_user")
        ).one()

    assert database == "smartfarm_test", f"Unsafe test database: {database}"
    assert role == "smartfarm_app", f"Unexpected runtime role: {role}"


@pytest.fixture
def farm_records(owner_engine):
    user_id = uuid4()
    tenant_a = uuid4()
    tenant_b = uuid4()
    farm_a = uuid4()
    farm_b = uuid4()
    email = f"farm-test-{user_id.hex}@example.test"
    password = "Farm-Integration-Test-42!"

    with owner_engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO users (id, email, display_name, status)
                VALUES (:id, :email, :name, 'active')
            """),
            {
                "id": user_id,
                "email": email,
                "name": "Farm Integration Test",
            },
        )
        conn.execute(
            text("""
                INSERT INTO user_credentials (user_id, password_hash)
                VALUES (:id, :password_hash)
            """),
            {
                "id": user_id,
                "password_hash": hash_password(password),
            },
        )
        conn.execute(
            text("""
                INSERT INTO tenants (id, name, status)
                VALUES
                    (:tenant_a, 'Farm Test Tenant A', 'active'),
                    (:tenant_b, 'Farm Test Tenant B', 'active')
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
                    (:farm_a, :tenant_a, 'Tenant A Farm', 'Asia/Bangkok'),
                    (:farm_b, :tenant_b, 'Tenant B Farm', 'Asia/Bangkok')
            """),
            {
                "farm_a": farm_a,
                "tenant_a": tenant_a,
                "farm_b": farm_b,
                "tenant_b": tenant_b,
            },
        )

    records = {
        "owner_engine": owner_engine,
        "user_id": user_id,
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "farm_a": farm_a,
        "farm_b": farm_b,
        "email": email,
        "password": password,
    }
    yield records

    with owner_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM farms WHERE id IN (:farm_a, :farm_b)"),
            {"farm_a": farm_a, "farm_b": farm_b},
        )
        conn.execute(
            text("DELETE FROM tenant_memberships WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        conn.execute(
            text("DELETE FROM tenants WHERE id IN (:tenant_a, :tenant_b)"),
            {"tenant_a": tenant_a, "tenant_b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM user_sessions WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        conn.execute(
            text("DELETE FROM user_credentials WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        conn.execute(
            text("DELETE FROM users WHERE id = :user_id"),
            {"user_id": user_id},
        )


@pytest.fixture
def http_client():
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

        def post(self, url, **kwargs):
            return self.request("POST", url, **kwargs)

        def get(self, url, **kwargs):
            return self.request("GET", url, **kwargs)

    return SyncASGIClient()


def login(client, records):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": records["email"],
            "password": records["password"],
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_postgres_lists_only_farms_for_authorized_tenant(
    http_client,
    farm_records,
):
    headers = login(http_client, farm_records)

    response = http_client.get(
        f"/api/v1/tenants/{farm_records['tenant_a']}/farms",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(farm_records["farm_a"])
    assert body[0]["name"] == "Tenant A Farm"
    assert set(body[0]) == {
        "id",
        "name",
        "timezone",
        "created_at",
        "updated_at",
    }
    assert str(farm_records["farm_b"]) not in response.text
    assert "Tenant B Farm" not in response.text


def test_postgres_rejects_tenant_without_membership(
    http_client,
    farm_records,
):
    headers = login(http_client, farm_records)

    response = http_client.get(
        f"/api/v1/tenants/{farm_records['tenant_b']}/farms",
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient tenant permissions"
