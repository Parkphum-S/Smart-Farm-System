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
            assert conn.execute(
                text("SELECT current_database()")
            ).scalar_one() == "smartfarm_test"
            assert conn.execute(text("SELECT current_user")).scalar_one() \
                == "smartfarm_owner"
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
        assert database == "smartfarm_test", f"Unsafe database: {database}"
        assert role == "smartfarm_app", f"Unexpected runtime role: {role}"
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
def zone_records(owner_engine):
    user_id = uuid4()
    tenant_a, tenant_b = uuid4(), uuid4()
    farm_a, farm_b = uuid4(), uuid4()
    email = f"zone-test-{user_id.hex}@example.test"
    password = "Zone-Integration-Test-42!"

    with owner_engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO users (id, email, display_name, status)
                VALUES (:id, :email, :name, 'active')
            """),
            {
                "id": user_id,
                "email": email,
                "name": "Zone Integration Test",
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
                    (:tenant_a, 'Zone Test Tenant A', 'active'),
                    (:tenant_b, 'Zone Test Tenant B', 'active')
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
                    (:farm_a, :tenant_a, 'Zone Test Farm A', 'Asia/Bangkok'),
                    (:farm_b, :tenant_b, 'Zone Test Farm B', 'Asia/Bangkok')
            """),
            {
                "farm_a": farm_a,
                "tenant_a": tenant_a,
                "farm_b": farm_b,
                "tenant_b": tenant_b,
            },
        )

    records = {
        "user_id": user_id,
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "farm_a": farm_a,
        "farm_b": farm_b,
        "email": email,
        "password": password,
        "owner_engine": owner_engine,
    }
    yield records

    with owner_engine.begin() as conn:
        # Delete zones first to preserve foreign-key ordering.
        conn.execute(
            text("""
                DELETE FROM zones
                WHERE tenant_id IN (:tenant_a, :tenant_b)
            """),
            {"tenant_a": tenant_a, "tenant_b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM farms WHERE id IN (:a, :b)"),
            {"a": farm_a, "b": farm_b},
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
            text("DELETE FROM tenants WHERE id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
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

        def delete(self, url, **kwargs):
            return self.request("DELETE", url, **kwargs)

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
        json={
            "email": records["email"],
            "password": records["password"],
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def zones_url(records, farm_key="farm_a"):
    return (
        f"/api/v1/tenants/{records['tenant_a']}/farms/"
        f"{records[farm_key]}/zones"
    )


def test_postgres_zone_crud(http_client, zone_records):
    headers = login(http_client, zone_records)
    url = zones_url(zone_records)

    created = http_client.post(
        url,
        headers=headers,
        json={
            "name": "Greenhouse A",
            "description": "North greenhouse",
        },
    )
    assert created.status_code == 201, created.text
    zone = created.json()
    assert zone["name"] == "Greenhouse A"
    assert zone["status"] == "active"
    assert zone["tenant_id"] == str(zone_records["tenant_a"])
    assert zone["farm_id"] == str(zone_records["farm_a"])

    zone_url = f"{url}/{zone['id']}"

    listed = http_client.get(url, headers=headers)
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == zone["id"] for item in listed.json())

    fetched = http_client.get(zone_url, headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["id"] == zone["id"]

    updated = http_client.patch(
        zone_url,
        headers=headers,
        json={"name": "Greenhouse A Updated", "status": "disabled"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Greenhouse A Updated"
    assert updated.json()["status"] == "disabled"

    deleted = http_client.delete(zone_url, headers=headers)
    assert deleted.status_code == 204, deleted.text

    missing = http_client.get(zone_url, headers=headers)
    assert missing.status_code == 404, missing.text


def test_postgres_rejects_duplicate_zone_name(http_client, zone_records):
    headers = login(http_client, zone_records)
    url = zones_url(zone_records)
    payload = {"name": "Duplicate Zone"}

    first = http_client.post(url, headers=headers, json=payload)
    assert first.status_code == 201, first.text

    duplicate = http_client.post(url, headers=headers, json=payload)
    assert duplicate.status_code == 409, duplicate.text


def test_postgres_rejects_tenant_without_membership(
    http_client, zone_records
):
    headers = login(http_client, zone_records)
    response = http_client.get(
        f"/api/v1/tenants/{zone_records['tenant_b']}/farms/"
        f"{zone_records['farm_b']}/zones",
        headers=headers,
    )
    assert response.status_code == 403, response.text


def test_postgres_runtime_zone_privileges(app_engine):
    with app_engine.connect() as conn:
        table_privileges = conn.execute(
            text("""
                SELECT
                    has_table_privilege(current_user, 'zones', 'SELECT'),
                    has_table_privilege(current_user, 'zones', 'INSERT'),
                    has_table_privilege(current_user, 'zones', 'DELETE')
            """)
        ).one()
        update_privileges = conn.execute(
            text("""
                SELECT
                    has_column_privilege(
                        current_user, 'zones', 'name', 'UPDATE'
                    ),
                    has_column_privilege(
                        current_user, 'zones', 'description', 'UPDATE'
                    ),
                    has_column_privilege(
                        current_user, 'zones', 'status', 'UPDATE'
                    ),
                    has_column_privilege(
                        current_user, 'zones', 'tenant_id', 'UPDATE'
                    ),
                    has_column_privilege(
                        current_user, 'zones', 'farm_id', 'UPDATE'
                    ),
                    has_column_privilege(
                        current_user, 'zones', 'id', 'UPDATE'
                    ),
                    has_column_privilege(
                        current_user, 'zones', 'updated_at', 'UPDATE'
                    )
            """)
        ).one()

    assert tuple(table_privileges) == (True, True, True)
    assert tuple(update_privileges) == (
        True, True, True, False, False, False, True
    )


def test_postgres_blocks_cross_tenant_zone_resource_access(
    http_client, zone_records
):
    records = zone_records
    headers = login(http_client, records)

    foreign_zone_id = uuid4()

    # Create a real Zone owned by Tenant B using the owner connection.
    with records["owner_engine"].begin() as conn:
        conn.execute(
            text("""
                INSERT INTO zones (id, tenant_id, farm_id, name)
                VALUES (:id, :tenant_id, :farm_id, :name)
            """),
            {
                "id": foreign_zone_id,
                "tenant_id": records["tenant_b"],
                "farm_id": records["farm_b"],
                "name": "Tenant B Protected Zone",
            },
        )

    tenant_a_path = (
        f"/api/v1/tenants/{records['tenant_a']}/farms/"
        f"{records['farm_a']}/zones/{foreign_zone_id}"
    )
    tenant_b_path = (
        f"/api/v1/tenants/{records['tenant_b']}/farms/"
        f"{records['farm_b']}/zones/{foreign_zone_id}"
    )

    with records["owner_engine"].connect() as conn:
        before = conn.execute(
            text("""
                SELECT tenant_id, farm_id, name, status
                FROM zones
                WHERE id = :zone_id
            """),
            {"zone_id": foreign_zone_id},
        ).one()

    # Tenant A cannot read Tenant B's Zone through Tenant A's path.
    response = http_client.get(
        tenant_a_path,
        headers=headers,
    )
    assert response.status_code == 404, response.text

    # Tenant A cannot update Tenant B's Zone by supplying its ID.
    response = http_client.patch(
        tenant_a_path,
        headers=headers,
        json={"name": "Cross Tenant Modified"},
    )
    assert response.status_code == 404, response.text

    # Tenant A cannot delete Tenant B's Zone by supplying its ID.
    response = http_client.delete(
        tenant_a_path,
        headers=headers,
    )
    assert response.status_code == 404, response.text

    # Direct use of Tenant B's path must fail membership authorization.
    response = http_client.get(
        tenant_b_path,
        headers=headers,
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "Insufficient tenant permissions"

    with records["owner_engine"].connect() as conn:
        after = conn.execute(
            text("""
                SELECT tenant_id, farm_id, name, status
                FROM zones
                WHERE id = :zone_id
            """),
            {"zone_id": foreign_zone_id},
        ).one()

    assert after == before
