import os
from uuid import uuid4

import pytest
from dotenv import load_dotenv
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db.session import engine
from app.services.authorization import authorize_tenant


@pytest.fixture(scope="module")
def owner_engine():
    load_dotenv(".env")
    raw_url = os.environ.get("SMARTFARM_MIGRATION_DATABASE_URL")
    assert raw_url, "Migration database URL is not configured"
    url = make_url(raw_url)
    assert url.database == "smartfarm", "Unexpected migration URL target"
    test_engine = create_engine(url.set(database="smartfarm_test"), pool_pre_ping=True)
    with test_engine.connect() as conn:
        assert conn.execute(text("SELECT current_database()")).scalar_one() == "smartfarm_test"
    yield test_engine
    test_engine.dispose()


@pytest.fixture(autouse=True)
def require_test_database():
    with engine.connect() as conn:
        db, role = conn.execute(text("SELECT current_database(), current_user")).one()
    assert db == "smartfarm_test", f"Unsafe test database: {db}"
    assert role == "smartfarm_app", f"Unexpected runtime role: {role}"


@pytest.fixture
def authorization_records(owner_engine):
    user_id = uuid4()
    tenant_id = uuid4()
    email = f"authorization-test-{user_id.hex}@example.test"
    with owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, email, display_name, status) VALUES (:id, :email, :name, :status)"), {"id": user_id, "email": email, "name": "Authorization Test", "status": "active"})
        conn.execute(text("INSERT INTO tenants (id, name, status) VALUES (:id, :name, :status)"), {"id": tenant_id, "name": "Authorization Test Tenant", "status": "active"})
        conn.execute(text("INSERT INTO tenant_memberships (tenant_id, user_id, role, status) VALUES (:tenant_id, :user_id, :role, :status)"), {"tenant_id": tenant_id, "user_id": user_id, "role": "owner", "status": "active"})
    yield {"user_id": str(user_id), "tenant_id": str(tenant_id), "owner_engine": owner_engine}
    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tenant_id AND user_id = :user_id"), {"tenant_id": tenant_id, "user_id": user_id})
        conn.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tenant_id"), {"tenant_id": tenant_id})


def test_postgres_allows_active_owner(authorization_records):
    with Session(engine) as db:
        role = authorize_tenant(db, authorization_records["user_id"], authorization_records["tenant_id"], {"owner"})
    assert role == "owner"


def test_postgres_rejects_insufficient_role(authorization_records):
    with authorization_records["owner_engine"].begin() as conn:
        conn.execute(text("UPDATE tenant_memberships SET role = :role WHERE tenant_id = :tenant_id AND user_id = :user_id"), {"role": "viewer", "tenant_id": authorization_records["tenant_id"], "user_id": authorization_records["user_id"]})
    with Session(engine) as db, pytest.raises(HTTPException) as exc:
        authorize_tenant(db, authorization_records["user_id"], authorization_records["tenant_id"], {"owner"})
    assert exc.value.status_code == 403


def test_postgres_rejects_suspended_membership(authorization_records):
    with authorization_records["owner_engine"].begin() as conn:
        conn.execute(text("UPDATE tenant_memberships SET status = :status WHERE tenant_id = :tenant_id AND user_id = :user_id"), {"status": "suspended", "tenant_id": authorization_records["tenant_id"], "user_id": authorization_records["user_id"]})
    with Session(engine) as db, pytest.raises(HTTPException) as exc:
        authorize_tenant(db, authorization_records["user_id"], authorization_records["tenant_id"], {"owner"})
    assert exc.value.status_code == 403


def test_postgres_rejects_suspended_tenant(authorization_records):
    with authorization_records["owner_engine"].begin() as conn:
        conn.execute(text("UPDATE tenants SET status = :status WHERE id = :tenant_id"), {"status": "suspended", "tenant_id": authorization_records["tenant_id"]})
    with Session(engine) as db, pytest.raises(HTTPException) as exc:
        authorize_tenant(db, authorization_records["user_id"], authorization_records["tenant_id"], {"owner"})
    assert exc.value.status_code == 403


def test_postgres_rejects_missing_membership(authorization_records):
    with authorization_records["owner_engine"].begin() as conn:
        conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tenant_id AND user_id = :user_id"), {"tenant_id": authorization_records["tenant_id"], "user_id": authorization_records["user_id"]})
    with Session(engine) as db, pytest.raises(HTTPException) as exc:
        authorize_tenant(db, authorization_records["user_id"], authorization_records["tenant_id"], {"owner"})
    assert exc.value.status_code == 403
