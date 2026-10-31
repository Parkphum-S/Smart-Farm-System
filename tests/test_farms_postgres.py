import asyncio
import os
from uuid import uuid4

import httpx
import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.db.session import get_db
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




@pytest.fixture(scope="module")
def app_engine():
    from dotenv import load_dotenv

    load_dotenv(".env")
    raw = os.environ.get("SMARTFARM_DATABASE_URL")
    assert raw, "Runtime database URL is not configured"
    url = make_url(raw)
    assert url.database == "smartfarm", "Unexpected runtime DB target"

    test_engine = create_engine(
        url.set(database="smartfarm_test"),
        pool_pre_ping=True,
    )
    try:
        with test_engine.connect() as conn:
            database, role = conn.execute(
                text("SELECT current_database(), current_user")
            ).one()
        assert database == "smartfarm_test", f"Unsafe test database: {database}"
        assert role == "smartfarm_app", f"Unexpected runtime role: {role}"
        yield test_engine
    finally:
        test_engine.dispose()


@pytest.fixture(autouse=True)
def require_test_database(app_engine):
    with app_engine.connect() as conn:
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
def http_client(app_engine):
    from sqlalchemy.orm import sessionmaker

    TestingSession = sessionmaker(
        bind=app_engine,
        autoflush=False,
        autocommit=False,
    )

    def override_get_db():
        db = TestingSession()
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

            import asyncio
            return asyncio.run(send())

        def post(self, url, **kwargs):
            return self.request("POST", url, **kwargs)

        def get(self, url, **kwargs):
            return self.request("GET", url, **kwargs)

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


def test_postgres_create_farm_via_api(http_client, farm_records):
    records = farm_records
    headers = login(http_client, records)
    created_id = None

    try:
        response = http_client.post(
            f"/api/v1/tenants/{records['tenant_a']}/farms",
            headers=headers,
            json={"name": "CRUD Created Farm", "timezone": "Asia/Bangkok"},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        created_id = body["id"]
        assert body["name"] == "CRUD Created Farm"
        assert body["timezone"] == "Asia/Bangkok"

        with records["owner_engine"].connect() as conn:
            row = conn.execute(
                text("""
                    SELECT tenant_id, name, timezone
                    FROM farms WHERE id = :farm_id
                """),
                {"farm_id": created_id},
            ).one()
        assert str(row.tenant_id) == str(records["tenant_a"])
        assert row.name == "CRUD Created Farm"
        assert row.timezone == "Asia/Bangkok"
    finally:
        if created_id:
            with records["owner_engine"].begin() as conn:
                conn.execute(
                    text("DELETE FROM farms WHERE id = :farm_id"),
                    {"farm_id": created_id},
                )


def test_postgres_update_farm_via_api(http_client, farm_records):
    records = farm_records
    headers = login(http_client, records)
    farm_id = records["farm_a"]

    try:
        response = http_client.request(
            "PATCH",
            f"/api/v1/tenants/{records['tenant_a']}/farms/{farm_id}",
            headers=headers,
            json={"name": "CRUD Updated Farm"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "CRUD Updated Farm"

        with records["owner_engine"].connect() as conn:
            name = conn.execute(
                text("SELECT name FROM farms WHERE id = :farm_id"),
                {"farm_id": farm_id},
            ).scalar_one()
        assert name == "CRUD Updated Farm"
    finally:
        with records["owner_engine"].begin() as conn:
            conn.execute(
                text("""
                    UPDATE farms
                    SET name = 'Tenant A Farm'
                    WHERE id = :farm_id AND tenant_id = :tenant_id
                """),
                {"farm_id": farm_id, "tenant_id": records["tenant_a"]},
            )


def test_postgres_delete_farm_via_api(http_client, farm_records):
    records = farm_records
    headers = login(http_client, records)
    created_id = None

    try:
        response = http_client.post(
            f"/api/v1/tenants/{records['tenant_a']}/farms",
            headers=headers,
            json={"name": "CRUD Delete Farm"},
        )
        assert response.status_code == 201, response.text
        created_id = response.json()["id"]

        response = http_client.request(
            "DELETE",
            f"/api/v1/tenants/{records['tenant_a']}/farms/{created_id}",
            headers=headers,
        )
        assert response.status_code == 204, response.text

        with records["owner_engine"].connect() as conn:
            exists = conn.execute(
                text("SELECT EXISTS(SELECT 1 FROM farms WHERE id = :farm_id)"),
                {"farm_id": created_id},
            ).scalar_one()
        assert exists is False
        created_id = None
    finally:
        if created_id:
            with records["owner_engine"].begin() as conn:
                conn.execute(
                    text("DELETE FROM farms WHERE id = :farm_id"),
                    {"farm_id": created_id},
                )


def test_postgres_delete_farm_referenced_by_zone_returns_409(
    http_client, farm_records
):
    records = farm_records
    headers = login(http_client, records)
    created_id = None
    zone_id = uuid4()

    try:
        response = http_client.post(
            f"/api/v1/tenants/{records['tenant_a']}/farms",
            headers=headers,
            json={"name": "CRUD Referenced Farm"},
        )
        assert response.status_code == 201, response.text
        created_id = response.json()["id"]

        with records["owner_engine"].begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO zones (id, tenant_id, farm_id, name)
                    VALUES (:id, :tenant_id, :farm_id, :name)
                """),
                {
                    "id": zone_id,
                    "tenant_id": records["tenant_a"],
                    "farm_id": created_id,
                    "name": "CRUD Reference Zone",
                },
            )

        response = http_client.request(
            "DELETE",
            f"/api/v1/tenants/{records['tenant_a']}/farms/{created_id}",
            headers=headers,
        )
        assert response.status_code == 409, response.text
        assert "foreign key" not in response.text.lower()

    finally:
        with records["owner_engine"].begin() as conn:
            conn.execute(
                text("DELETE FROM zones WHERE id = :zone_id"),
                {"zone_id": zone_id},
            )
            if created_id:
                conn.execute(
                    text("DELETE FROM farms WHERE id = :farm_id"),
                    {"farm_id": created_id},
                )


def test_postgres_uploads_and_reads_farm_image(http_client, farm_records):
    headers = login(http_client, farm_records)
    tenant_id = farm_records["tenant_a"]
    farm_id = farm_records["farm_a"]
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"smartfarm-test-image"

    upload = http_client.post(
        f"/api/v1/tenants/{tenant_id}/farms/{farm_id}/image",
        headers=headers,
        files={"image": ("farm.png", image_bytes, "image/png")},
    )
    assert upload.status_code == 204, upload.text

    response = http_client.get(
        f"/api/v1/tenants/{tenant_id}/farms/{farm_id}/image",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.content == image_bytes
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_postgres_farm_without_image_returns_404(http_client, farm_records):
    headers = login(http_client, farm_records)

    response = http_client.get(
        f"/api/v1/tenants/{farm_records['tenant_a']}/farms/"
        f"{farm_records['farm_a']}/image",
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Farm image not found"


def test_postgres_rejects_empty_farm_image(http_client, farm_records):
    headers = login(http_client, farm_records)

    response = http_client.post(
        f"/api/v1/tenants/{farm_records['tenant_a']}/farms/"
        f"{farm_records['farm_a']}/image",
        headers=headers,
        files={"image": ("empty.png", b"", "image/png")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Image file is empty"


def test_postgres_rejects_farm_image_with_fake_png_signature(
    http_client, farm_records
):
    headers = login(http_client, farm_records)

    response = http_client.post(
        f"/api/v1/tenants/{farm_records['tenant_a']}/farms/"
        f"{farm_records['farm_a']}/image",
        headers=headers,
        files={"image": ("farm.png", b"not-a-real-png", "image/png")},
    )

    assert response.status_code == 415


def test_postgres_rejects_unsupported_farm_image(http_client, farm_records):
    headers = login(http_client, farm_records)

    response = http_client.post(
        f"/api/v1/tenants/{farm_records['tenant_a']}/farms/"
        f"{farm_records['farm_a']}/image",
        headers=headers,
        files={"image": ("farm.gif", b"GIF89a-invalid", "image/gif")},
    )
    assert response.status_code == 415


def test_postgres_rejects_farm_image_over_5_mib(http_client, farm_records):
    headers = login(http_client, farm_records)

    response = http_client.post(
        f"/api/v1/tenants/{farm_records['tenant_a']}/farms/"
        f"{farm_records['farm_a']}/image",
        headers=headers,
        files={
            "image": (
                "farm.png",
                b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024),
                "image/png",
            )
        },
    )
    assert response.status_code == 413


def test_postgres_cannot_upload_image_to_another_tenant(
    http_client, farm_records
):
    headers = login(http_client, farm_records)

    response = http_client.post(
        f"/api/v1/tenants/{farm_records['tenant_b']}/farms/"
        f"{farm_records['farm_b']}/image",
        headers=headers,
        files={
            "image": (
                "farm.png",
                b"\x89PNG\r\n\x1a\n" + b"smartfarm-test-image",
                "image/png",
            )
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient tenant permissions"


def test_postgres_runtime_farm_privileges(app_engine):
    with app_engine.connect() as conn:
        identity = conn.execute(
            text("""
                SELECT current_database(), current_user,
                       rolsuper, rolcreatedb, rolcreaterole
                FROM pg_roles
                WHERE rolname = current_user
            """)
        ).one()

        table_privileges = conn.execute(
            text("""
                SELECT
                    has_table_privilege(current_user, 'farms', 'SELECT'),
                    has_table_privilege(current_user, 'farms', 'INSERT'),
                    has_table_privilege(current_user, 'farms', 'DELETE')
            """)
        ).one()

        update_privileges = conn.execute(
            text("""
                SELECT
                    has_column_privilege(
                        current_user, 'farms', 'name', 'UPDATE'
                    ),
                    has_column_privilege(
                        current_user, 'farms', 'timezone', 'UPDATE'
                    ),
                    has_column_privilege(
                        current_user, 'farms', 'updated_at', 'UPDATE'
                    ),
                    has_column_privilege(
                        current_user, 'farms', 'tenant_id', 'UPDATE'
                    ),
                    has_column_privilege(
                        current_user, 'farms', 'id', 'UPDATE'
                    ),
                    has_column_privilege(
                        current_user, 'farms', 'image_content', 'UPDATE'
                    ),
                    has_column_privilege(
                        current_user, 'farms', 'image_content_type', 'UPDATE'
                    )
            """)
        ).one()

    assert identity == (
        "smartfarm_test",
        "smartfarm_app",
        False,
        False,
        False,
    )
    assert tuple(table_privileges) == (True, True, True)
    assert tuple(update_privileges) == (
        True, True, True, False, False, True, True
    )


def test_postgres_blocks_cross_tenant_farm_resource_access(
    http_client, farm_records
):
    records = farm_records
    headers = login(http_client, records)

    foreign_farm_id = records["farm_b"]
    tenant_a_path = (
        f"/api/v1/tenants/{records['tenant_a']}/farms/{foreign_farm_id}"
    )
    tenant_b_image_path = (
        f"/api/v1/tenants/{records['tenant_b']}/farms/"
        f"{foreign_farm_id}/image"
    )

    with records["owner_engine"].connect() as conn:
        before = conn.execute(
            text("""
                SELECT tenant_id, name, timezone
                FROM farms
                WHERE id = :farm_id
            """),
            {"farm_id": foreign_farm_id},
        ).one()

    # Tenant A cannot read Tenant B's farm image through Tenant A's path.
    response = http_client.get(
        f"{tenant_a_path}/image",
        headers=headers,
    )
    assert response.status_code == 404, response.text

    # Tenant A cannot update Tenant B's farm by supplying its ID.
    response = http_client.request(
        "PATCH",
        tenant_a_path,
        headers=headers,
        json={"name": "Cross Tenant Modified"},
    )
    assert response.status_code == 404, response.text

    # Tenant A cannot delete Tenant B's farm by supplying its ID.
    response = http_client.request(
        "DELETE",
        tenant_a_path,
        headers=headers,
    )
    assert response.status_code == 404, response.text

    # Direct use of Tenant B's path must fail membership authorization.
    response = http_client.get(
        tenant_b_image_path,
        headers=headers,
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "Insufficient tenant permissions"

    with records["owner_engine"].connect() as conn:
        after = conn.execute(
            text("""
                SELECT tenant_id, name, timezone
                FROM farms
                WHERE id = :farm_id
            """),
            {"farm_id": foreign_farm_id},
        ).one()

    assert after == before
