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
from app.security.user_auth import hash_password, hash_session_token


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
def auth_user(owner_engine):
    user_id = uuid4()
    email = f"auth-test-{user_id.hex}@example.test"
    password = "Integration-Test-Password-42!"
    password_hash = hash_password(password)

    with owner_engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO users (id, email, display_name, status)
                VALUES (:id, :email, 'Authentication Test', 'active')
            """),
            {"id": user_id, "email": email},
        )
        conn.execute(
            text("""
                INSERT INTO user_credentials (user_id, password_hash)
                VALUES (:id, :password_hash)
            """),
            {"id": user_id, "password_hash": password_hash},
        )

    yield {
        "id": user_id,
        "email": email,
        "password": password,
        "owner": owner_engine,
    }

    with owner_engine.begin() as conn:
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


def login(client, user, password=None):
    return client.post(
        "/api/v1/auth/login",
        json={
            "email": user["email"],
            "password": password if password is not None else user["password"],
        },
    )


def test_login_me_logout_and_token_hash_storage(http_client, auth_user):
    response = login(http_client, auth_user)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 12 * 60 * 60
    assert body["user"]["email"] == auth_user["email"]
    assert body["user"]["id"] == str(auth_user["id"])
    assert body["access_token"]

    token = body["access_token"]
    with auth_user["owner"].connect() as conn:
        row = conn.execute(
            text("""
                SELECT token_hash, expires_at
                FROM user_sessions
                WHERE user_id = :user_id
            """),
            {"user_id": auth_user["id"]},
        ).one()

    assert row.token_hash == hash_session_token(token)
    assert row.token_hash != token

    me = http_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == auth_user["email"]

    logout_response = http_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert logout_response.status_code == 204

    me_after_logout = http_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_after_logout.status_code == 401


def test_wrong_password_increments_failed_attempts(http_client, auth_user):
    response = login(http_client, auth_user, "Definitely-Wrong-Password")
    assert response.status_code == 401

    with auth_user["owner"].connect() as conn:
        attempts, locked_until = conn.execute(
            text("""
                SELECT failed_attempts, locked_until
                FROM user_credentials
                WHERE user_id = :id
            """),
            {"id": auth_user["id"]},
        ).one()

    assert attempts == 1
    assert locked_until is None


def test_fifth_wrong_password_locks_account(http_client, auth_user):
    for _ in range(5):
        response = login(http_client, auth_user, "Definitely-Wrong-Password")
        assert response.status_code == 401

    with auth_user["owner"].connect() as conn:
        attempts, locked_until = conn.execute(
            text("""
                SELECT failed_attempts, locked_until
                FROM user_credentials
                WHERE user_id = :id
            """),
            {"id": auth_user["id"]},
        ).one()

    assert attempts == 5
    assert locked_until is not None

    # Correct password must not bypass an active lock.
    assert login(http_client, auth_user).status_code == 401


def test_expired_lock_starts_a_fresh_failure_count(http_client, auth_user):
    with auth_user["owner"].begin() as conn:
        conn.execute(
            text("""
                UPDATE user_credentials
                SET failed_attempts = 5,
                    locked_until = CURRENT_TIMESTAMP - INTERVAL '1 second'
                WHERE user_id = :id
            """),
            {"id": auth_user["id"]},
        )

    response = login(http_client, auth_user, "Definitely-Wrong-Password")
    assert response.status_code == 401

    with auth_user["owner"].connect() as conn:
        attempts, locked_until = conn.execute(
            text("""
                SELECT failed_attempts, locked_until
                FROM user_credentials
                WHERE user_id = :id
            """),
            {"id": auth_user["id"]},
        ).one()

    assert attempts == 1
    assert locked_until is None


def test_expired_session_is_rejected(http_client, auth_user):
    response = login(http_client, auth_user)
    assert response.status_code == 200
    token = response.json()["access_token"]

    with auth_user["owner"].begin() as conn:
        conn.execute(
            text("""
                UPDATE user_sessions
                SET expires_at = CURRENT_TIMESTAMP - INTERVAL '1 second'
                WHERE token_hash = :token_hash
            """),
            {"token_hash": hash_session_token(token)},
        )

    me = http_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 401


def test_me_requires_bearer_token(http_client):
    response = http_client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


def test_disabled_user_cannot_login(http_client, auth_user):
    with auth_user["owner"].begin() as conn:
        conn.execute(
            text("UPDATE users SET status = 'disabled' WHERE id = :id"),
            {"id": auth_user["id"]},
        )

    response = login(http_client, auth_user)
    assert response.status_code == 401
