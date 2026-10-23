"""Real PostgreSQL concurrency tests for command idempotency.

All test writes are isolated to smartfarm_test.
Production database URLs are never used for test connections.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.schemas.commands import CommandCreate
from app.services.commands import CommandConflict, create_command


WORKERS = 8


def _test_url(variable: str, expected_source_db: str):
    raw = dotenv_values(".env").get(variable)
    if not raw:
        pytest.fail(f"Required environment setting {variable} is missing")

    url = make_url(raw)
    if url.database != expected_source_db:
        pytest.fail(
            f"Unsafe source database for {variable}: {url.database!r}"
        )

    return url.set(database="smartfarm_test")


@pytest.fixture(scope="module")
def postgres_engines():
    # Construct isolated engines. Never import the application's global engine.
    app_url = _test_url("SMARTFARM_DATABASE_URL", "smartfarm")
    owner_url = _test_url("SMARTFARM_MIGRATION_DATABASE_URL", "smartfarm")

    app_engine = create_engine(app_url, pool_pre_ping=True)
    owner_engine = create_engine(owner_url, pool_pre_ping=True)

    try:
        with app_engine.connect() as conn:
            database, role = conn.execute(
                text("SELECT current_database(), current_user")
            ).one()
            if (database, role) != ("smartfarm_test", "smartfarm_app"):
                pytest.fail(
                    "Unsafe runtime connection: "
                    f"database={database!r}, role={role!r}"
                )

        with owner_engine.connect() as conn:
            database, role = conn.execute(
                text("SELECT current_database(), current_user")
            ).one()
            if (database, role) != ("smartfarm_test", "smartfarm_owner"):
                pytest.fail(
                    "Unsafe fixture connection: "
                    f"database={database!r}, role={role!r}"
                )

            revision = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            if revision != "0003_commands":
                pytest.fail(f"Unexpected test migration: {revision!r}")

        yield app_engine, owner_engine
    finally:
        app_engine.dispose()
        owner_engine.dispose()


@pytest.fixture
def command_context(postgres_engines):
    app_engine, owner_engine = postgres_engines
    RuntimeSession = sessionmaker(
        bind=app_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    tenant_id = uuid4()
    device_id = uuid4()
    second_device_id = uuid4()
    user_id = uuid4()

    # Seed only uniquely identified fixture rows with the owner role.
    with owner_engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO tenants (id, name, status)
                VALUES (:id, :name, 'active')
            """),
            {"id": tenant_id, "name": f"Command concurrency {tenant_id}"},
        )
        conn.execute(
            text("""
                INSERT INTO devices (
                    id, tenant_id, farm_id, device_code,
                    device_type, name, status
                )
                VALUES (
                    :id, :tenant_id, NULL, :device_code,
                    'relay_controller', 'Concurrency test device', 'active'
                )
            """),
            {
                "id": device_id,
                "tenant_id": tenant_id,
                "device_code": f"cmd-test-{device_id}",
            },
        )
        conn.execute(
            text("""
                INSERT INTO devices (
                    id, tenant_id, farm_id, device_code,
                    device_type, name, status
                )
                VALUES (
                    :id, :tenant_id, NULL, :device_code,
                    'relay_controller', 'Second concurrency test device',
                    'active'
                )
            """),
            {
                "id": second_device_id,
                "tenant_id": tenant_id,
                "device_code": f"cmd-test-{second_device_id}",
            },
        )
        conn.execute(
            text("""
                INSERT INTO users (id, email, display_name, status)
                VALUES (:id, :email, 'Command concurrency test', 'active')
            """),
            {
                "id": user_id,
                "email": f"{user_id}@example.invalid",
            },
        )

    context = {
        "sessions": RuntimeSession,
        "owner_engine": owner_engine,
        "tenant_id": tenant_id,
        "device_id": device_id,
        "second_device_id": second_device_id,
        "user_id": user_id,
    }

    try:
        yield context
    finally:
        # Remove only records belonging to this fixture's generated UUIDs.
        with owner_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM command_events WHERE tenant_id = :id"),
                {"id": tenant_id},
            )
            conn.execute(
                text("DELETE FROM commands WHERE tenant_id = :id"),
                {"id": tenant_id},
            )
            conn.execute(
                text("DELETE FROM devices WHERE tenant_id = :id"),
                {"id": tenant_id},
            )
            conn.execute(
                text("DELETE FROM tenants WHERE id = :id"),
                {"id": tenant_id},
            )
            conn.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": user_id},
            )


def make_request(key, state="off"):
    return CommandCreate(
        command_type="relay.set",
        parameters={"relay": 1, "state": state},
        idempotency_key=key,
        expires_in_seconds=60,
    )


def run_concurrently(context, requests, device_ids=None):
    barrier = Barrier(len(requests))
    if device_ids is None:
        device_ids = [context["device_id"]] * len(requests)
    if len(device_ids) != len(requests):
        raise ValueError("Each request must have one device ID")

    def worker(item):
        request, device_id = item
        # Every worker owns a separate session and transaction.
        with context["sessions"]() as db:
            barrier.wait(timeout=15)
            try:
                with db.begin():
                    row, was_existing = create_command(
                        db,
                        tenant_id=context["tenant_id"],
                        device_id=device_id,
                        user_id=context["user_id"],
                        request=request,
                    )
                return {
                    "outcome": "ok",
                    "id": row["id"],
                    "existing": was_existing,
                    "state": row["parameters"]["state"],
                }
            except CommandConflict:
                return {"outcome": "conflict"}

    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        return list(pool.map(worker, zip(requests, device_ids)))


def database_counts(context, key):
    with context["owner_engine"].connect() as conn:
        command_rows = conn.execute(
            text("""
                SELECT id, parameters, request_hash
                FROM commands
                WHERE tenant_id = :tenant_id
                  AND requested_by_user_id = :user_id
                  AND idempotency_key = :key
            """),
            {
                "tenant_id": context["tenant_id"],
                "user_id": context["user_id"],
                "key": key,
            },
        ).mappings().all()

        event_rows = conn.execute(
            text("""
                SELECT event_type, count(*) AS n
                FROM command_events
                WHERE tenant_id = :tenant_id
                  AND command_id IN (
                      SELECT id FROM commands
                      WHERE tenant_id = :tenant_id
                        AND requested_by_user_id = :user_id
                        AND idempotency_key = :key
                  )
                GROUP BY event_type
            """),
            {
                "tenant_id": context["tenant_id"],
                "user_id": context["user_id"],
                "key": key,
            },
        ).mappings().all()

    return command_rows, {
        row["event_type"]: row["n"] for row in event_rows
    }


def test_concurrent_identical_requests_create_one_command_and_event(
    command_context,
):
    key = f"same-{uuid4()}"
    requests = [make_request(key, "off") for _ in range(WORKERS)]

    results = run_concurrently(command_context, requests)

    assert all(result["outcome"] == "ok" for result in results)
    assert len({result["id"] for result in results}) == 1
    assert sum(not result["existing"] for result in results) == 1
    assert sum(result["existing"] for result in results) == WORKERS - 1

    commands, events = database_counts(command_context, key)
    assert len(commands) == 1
    assert events == {"created": 1}


def test_concurrent_different_payloads_with_same_key_conflict(
    command_context,
):
    key = f"different-{uuid4()}"
    requests = [
        make_request(key, "off"),
        make_request(key, "on"),
    ]

    results = run_concurrently(command_context, requests)

    assert sum(result["outcome"] == "ok" for result in results) == 1
    assert sum(result["outcome"] == "conflict" for result in results) == 1

    commands, events = database_counts(command_context, key)
    assert len(commands) == 1
    assert commands[0]["parameters"]["state"] in {"on", "off"}
    assert events == {"created": 1}


def test_concurrent_same_key_and_payload_for_different_devices_conflict(
    command_context,
):
    key = f"different-device-{uuid4()}"
    request = make_request(key, "off")
    device_ids = [
        command_context["device_id"],
        command_context["second_device_id"],
    ]

    results = run_concurrently(
        command_context,
        [request, request],
        device_ids=device_ids,
    )

    assert sum(result["outcome"] == "ok" for result in results) == 1
    assert sum(result["outcome"] == "conflict" for result in results) == 1

    commands, events = database_counts(command_context, key)
    assert len(commands) == 1
    assert events == {"created": 1}
