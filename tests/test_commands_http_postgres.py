"""HTTP integration tests for command tenant isolation and device auth."""

import asyncio
import hashlib
import os
from uuid import uuid4

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.db.session import get_db
from app.main import app
from app.security.device_auth import generate_device_token
from app.security.user_auth import hash_password, hash_session_token


@pytest.fixture(scope="module")
def postgres_engines():
    values = dotenv_values(".env")
    raw_url = values.get("SMARTFARM_MIGRATION_DATABASE_URL")
    assert raw_url, "Migration database URL is not configured"

    source_url = make_url(raw_url)
    assert source_url.database == "smartfarm", (
        "Unexpected migration DB source; refusing to run"
    )

    runtime_raw_url = values.get("SMARTFARM_DATABASE_URL")
    assert runtime_raw_url, "Runtime database URL is not configured"
    runtime_source_url = make_url(runtime_raw_url)
    assert runtime_source_url.database == "smartfarm", (
        "Unexpected runtime DB source; refusing to run"
    )

    runtime_url = runtime_source_url.set(database="smartfarm_test")
    runtime_engine = create_engine(runtime_url, pool_pre_ping=True)
    RuntimeSession = __import__(
        "sqlalchemy.orm", fromlist=["sessionmaker"]
    ).sessionmaker(
        bind=runtime_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    owner_url = source_url.set(database="smartfarm_test")
    owner_engine = create_engine(owner_url, pool_pre_ping=True)
    previous_overrides = app.dependency_overrides.copy()

    def override_get_db():
        db = RuntimeSession()
        try:
            yield db
        finally:
            db.close()

    try:
        with runtime_engine.connect() as conn:
            database, role = conn.execute(
                text("SELECT current_database(), current_user")
            ).one()
            assert (database, role) == ("smartfarm_test", "smartfarm_app"), (
                f"Unsafe runtime connection: database={database!r}, "
                f"role={role!r}"
            )

        app.dependency_overrides[get_db] = override_get_db

        with owner_engine.connect() as conn:
            database, role = conn.execute(
                text("SELECT current_database(), current_user")
            ).one()
            assert (database, role) == (
                "smartfarm_test",
                "smartfarm_owner",
            ), (
                f"Unsafe fixture connection: database={database!r}, "
                f"role={role!r}"
            )
            revision = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == "0004_zones", (
                f"Unexpected test migration: {revision!r}"
            )

        yield owner_engine
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        owner_engine.dispose()
        runtime_engine.dispose()


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

        def get(self, url, **kwargs):
            return self.request("GET", url, **kwargs)

        def post(self, url, **kwargs):
            return self.request("POST", url, **kwargs)

    return SyncASGIClient()


@pytest.fixture
def command_world(postgres_engines):
    owner_engine = postgres_engines
    suffix = uuid4().hex
    tenant_a = uuid4()
    tenant_b = uuid4()
    device_a = uuid4()
    device_a2 = uuid4()
    device_b = uuid4()
    owner_id = uuid4()
    operator_id = uuid4()
    viewer_id = uuid4()
    outsider_id = uuid4()

    users = [
        (owner_id, f"cmd-owner-{suffix}@example.test"),
        (operator_id, f"cmd-operator-{suffix}@example.test"),
        (viewer_id, f"cmd-viewer-{suffix}@example.test"),
        (outsider_id, f"cmd-outsider-{suffix}@example.test"),
    ]

    # Device tokens are only returned to the test client; only hashes are stored.
    token_a, hash_a = generate_device_token()
    token_a2, hash_a2 = generate_device_token()
    token_b, hash_b = generate_device_token()

    tenant_ids = [tenant_a, tenant_b]
    device_ids = [device_a, device_a2, device_b]
    user_ids = [row[0] for row in users]

    try:
        with owner_engine.begin() as conn:
            for tenant_id, name in (
                (tenant_a, f"HTTP command tenant A {suffix}"),
                (tenant_b, f"HTTP command tenant B {suffix}"),
            ):
                conn.execute(
                    text("""
                        INSERT INTO tenants (id, name, status)
                        VALUES (:id, :name, 'active')
                    """),
                    {"id": tenant_id, "name": name},
                )

            for device_id, tenant_id, code in (
                (device_a, tenant_a, f"a-{suffix}"),
                (device_a2, tenant_a, f"a2-{suffix}"),
                (device_b, tenant_b, f"b-{suffix}"),
            ):
                conn.execute(
                    text("""
                        INSERT INTO devices (
                            id, tenant_id, farm_id, device_code,
                            device_type, name, status
                        )
                        VALUES (
                            :id, :tenant_id, NULL, :code,
                            'relay_controller', 'HTTP integration device',
                            'active'
                        )
                    """),
                    {
                        "id": device_id,
                        "tenant_id": tenant_id,
                        "code": code,
                    },
                )

            for user_id, email in users:
                conn.execute(
                    text("""
                        INSERT INTO users (id, email, display_name, status)
                        VALUES (:id, :email, 'Command HTTP test', 'active')
                    """),
                    {"id": user_id, "email": email},
                )
                conn.execute(
                    text("""
                        INSERT INTO user_credentials (user_id, password_hash)
                        VALUES (:id, :password_hash)
                    """),
                    {
                        "id": user_id,
                        "password_hash": hash_password(
                            f"Test-Password-{user_id.hex}!"
                        ),
                    },
                )

            for user_id, role in (
                (owner_id, "owner"),
                (operator_id, "operator"),
                (viewer_id, "viewer"),
            ):
                conn.execute(
                    text("""
                        INSERT INTO tenant_memberships (
                            tenant_id, user_id, role, status
                        )
                        VALUES (:tenant_id, :user_id, :role, 'active')
                    """),
                    {
                        "tenant_id": tenant_a,
                        "user_id": user_id,
                        "role": role,
                    },
                )

            for device_id, tenant_id, secret_hash in (
                (device_a, tenant_a, hash_a),
                (device_a2, tenant_a, hash_a2),
                (device_b, tenant_b, hash_b),
            ):
                conn.execute(
                    text("""
                        INSERT INTO device_credentials (
                            id, tenant_id, device_id, secret_hash
                        )
                        VALUES (:id, :tenant_id, :device_id, :secret_hash)
                    """),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "device_id": device_id,
                        "secret_hash": secret_hash,
                    },
                )

        yield {
            "owner_engine": owner_engine,
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "device_a": device_a,
            "device_a2": device_a2,
            "device_b": device_b,
            "owner_id": owner_id,
            "operator_id": operator_id,
            "viewer_id": viewer_id,
            "outsider_id": outsider_id,
            "tokens": {
                "device_a": token_a,
                "device_a2": token_a2,
                "device_b": token_b,
            },
            "emails": {user_id: email for user_id, email in users},
            "passwords": {
                user_id: f"Test-Password-{user_id.hex}!"
                for user_id, _ in users
            },
        }
    finally:
        # Remove only rows generated by this fixture.
        with owner_engine.begin() as conn:
            conn.execute(
                text("""
                    DELETE FROM command_events
                    WHERE tenant_id = ANY(:tenant_ids)
                """),
                {"tenant_ids": tenant_ids},
            )
            conn.execute(
                text("""
                    DELETE FROM commands
                    WHERE tenant_id = ANY(:tenant_ids)
                """),
                {"tenant_ids": tenant_ids},
            )
            conn.execute(
                text("""
                    DELETE FROM device_credentials
                    WHERE device_id = ANY(:device_ids)
                """),
                {"device_ids": device_ids},
            )
            conn.execute(
                text("""
                    DELETE FROM tenant_memberships
                    WHERE tenant_id = ANY(:tenant_ids)
                       OR user_id = ANY(:user_ids)
                """),
                {"tenant_ids": tenant_ids, "user_ids": user_ids},
            )
            conn.execute(
                text("""
                    DELETE FROM user_sessions
                    WHERE user_id = ANY(:user_ids)
                """),
                {"user_ids": user_ids},
            )
            conn.execute(
                text("DELETE FROM user_credentials WHERE user_id = ANY(:ids)"),
                {"ids": user_ids},
            )
            conn.execute(
                text("DELETE FROM devices WHERE id = ANY(:ids)"),
                {"ids": device_ids},
            )
            conn.execute(
                text("DELETE FROM tenants WHERE id = ANY(:ids)"),
                {"ids": tenant_ids},
            )
            conn.execute(
                text("DELETE FROM users WHERE id = ANY(:ids)"),
                {"ids": user_ids},
            )


def login(http_client, world, user_id):
    response = http_client.post(
        "/api/v1/auth/login",
        json={
            "email": world["emails"][user_id],
            "password": world["passwords"][user_id],
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_payload(key=None):
    return {
        "command_type": "relay.set",
        "parameters": {"relay": 1, "state": "on"},
        "idempotency_key": key or f"http-{uuid4().hex}",
        "expires_in_seconds": 60,
    }


def create_command(http_client, headers, tenant_id, device_id, key=None):
    return http_client.post(
        f"/api/v1/tenants/{tenant_id}/devices/{device_id}/commands",
        headers=headers,
        json=create_payload(key),
    )


def test_command_create_requires_valid_user_session(http_client, command_world):
    world = command_world
    path = (
        f"/api/v1/tenants/{world['tenant_a']}/devices/"
        f"{world['device_a']}/commands"
    )
    payload = create_payload()

    assert http_client.post(path, json=payload).status_code == 401
    assert http_client.post(
        path,
        headers={"Authorization": "Bearer invalid-session-token"},
        json=payload,
    ).status_code == 401


def test_owner_and_operator_can_create_but_viewer_cannot(
    http_client, command_world
):
    world = command_world
    owner_headers = login(http_client, world, world["owner_id"])
    operator_headers = login(http_client, world, world["operator_id"])
    viewer_headers = login(http_client, world, world["viewer_id"])

    owner_response = create_command(
        http_client, owner_headers, world["tenant_a"], world["device_a"]
    )
    assert owner_response.status_code == 201, owner_response.text

    operator_response = create_command(
        http_client, operator_headers, world["tenant_a"], world["device_a"]
    )
    assert operator_response.status_code == 201, operator_response.text

    viewer_response = create_command(
        http_client, viewer_headers, world["tenant_a"], world["device_a"]
    )
    assert viewer_response.status_code == 403


def test_tenant_a_user_cannot_create_or_list_tenant_b_commands(
    http_client, command_world
):
    world = command_world
    owner_headers = login(http_client, world, world["owner_id"])

    create_b = create_command(
        http_client, owner_headers, world["tenant_b"], world["device_b"]
    )
    assert create_b.status_code == 403

    list_b = http_client.get(
        f"/api/v1/tenants/{world['tenant_b']}/devices/"
        f"{world['device_b']}/commands",
        headers=owner_headers,
    )
    assert list_b.status_code == 403


def test_user_without_membership_cannot_access_tenant_commands(
    http_client, command_world
):
    world = command_world
    outsider_headers = login(http_client, world, world["outsider_id"])

    response = http_client.get(
        f"/api/v1/tenants/{world['tenant_a']}/devices/"
        f"{world['device_a']}/commands",
        headers=outsider_headers,
    )
    assert response.status_code == 403


def test_history_response_excludes_internal_columns(http_client, command_world):
    world = command_world
    owner_headers = login(http_client, world, world["owner_id"])
    created = create_command(
        http_client, owner_headers, world["tenant_a"], world["device_a"]
    )
    assert created.status_code == 201, created.text

    response = http_client.get(
        f"/api/v1/tenants/{world['tenant_a']}/devices/"
        f"{world['device_a']}/commands",
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text
    command = response.json()["commands"][0]

    forbidden_fields = {
        "tenant_id",
        "requested_by_user_id",
        "idempotency_key",
        "request_hash",
    }
    assert forbidden_fields.isdisjoint(command.keys())


def test_device_pending_commands_are_scoped_to_authenticated_device(
    http_client, command_world
):
    world = command_world
    owner_headers = login(http_client, world, world["owner_id"])

    created = create_command(
        http_client, owner_headers, world["tenant_a"], world["device_a"]
    )
    assert created.status_code == 201, created.text
    expected_id = created.json()["command"]["id"]

    response = http_client.get(
        "/api/v1/commands/pending",
        headers={
            "Authorization": f"Bearer {world['tokens']['device_a2']}"
        },
    )
    assert response.status_code == 200, response.text
    assert all(
        row["id"] != expected_id for row in response.json()["commands"]
    )

    own_response = http_client.get(
        "/api/v1/commands/pending",
        headers={
            "Authorization": f"Bearer {world['tokens']['device_a']}"
        },
    )
    assert own_response.status_code == 200, own_response.text
    assert expected_id in {
        row["id"] for row in own_response.json()["commands"]
    }


def test_invalid_and_revoked_device_tokens_are_rejected(
    http_client, command_world
):
    world = command_world

    invalid = http_client.get(
        "/api/v1/commands/pending",
        headers={"Authorization": "Bearer invalid-device-token"},
    )
    assert invalid.status_code == 401

    with world["owner_engine"].begin() as conn:
        conn.execute(
            text("""
                UPDATE device_credentials
                SET revoked_at = CURRENT_TIMESTAMP
                WHERE device_id = :device_id
            """),
            {"device_id": world["device_a"]},
        )

    revoked = http_client.get(
        "/api/v1/commands/pending",
        headers={
            "Authorization": f"Bearer {world['tokens']['device_a']}"
        },
    )
    assert revoked.status_code == 401


def test_device_cannot_report_event_for_another_device_command(
    http_client, command_world
):
    world = command_world
    owner_headers = login(http_client, world, world["owner_id"])
    created = create_command(
        http_client, owner_headers, world["tenant_a"], world["device_a"]
    )
    assert created.status_code == 201, created.text
    command_id = created.json()["command"]["id"]

    response = http_client.post(
        f"/api/v1/commands/{command_id}/events",
        headers={
            "Authorization": f"Bearer {world['tokens']['device_a2']}"
        },
        json={
            "event_id": f"foreign-{uuid4().hex}",
            "event_type": "acknowledged",
            "details": {},
        },
    )
    assert response.status_code == 404


def test_device_cannot_report_event_for_other_tenant_command(
    http_client, command_world
):
    world = command_world
    owner_headers = login(http_client, world, world["owner_id"])
    created = create_command(
        http_client, owner_headers, world["tenant_a"], world["device_a"]
    )
    assert created.status_code == 201, created.text
    command_id = created.json()["command"]["id"]

    response = http_client.post(
        f"/api/v1/commands/{command_id}/events",
        headers={
            "Authorization": f"Bearer {world['tokens']['device_b']}"
        },
        json={
            "event_id": f"foreign-tenant-{uuid4().hex}",
            "event_type": "acknowledged",
            "details": {},
        },
    )
    assert response.status_code == 404
