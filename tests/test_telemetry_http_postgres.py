import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.db.session import engine
from app.main import app
from app.security.device_auth import generate_device_token


@pytest.fixture(scope="module")
def owner_engine():
    load_dotenv(".env")
    url = make_url(os.environ["SMARTFARM_MIGRATION_DATABASE_URL"])
    assert url.database == "smartfarm"
    test_engine = create_engine(
        url.set(database="smartfarm_test"),
        pool_pre_ping=True,
    )
    try:
        yield test_engine
    finally:
        test_engine.dispose()


@pytest.fixture(autouse=True)
def require_test_database():
    with engine.connect() as conn:
        database, role = conn.execute(
            text("SELECT current_database(), current_user")
        ).one()
    assert database == "smartfarm_test"
    assert role == "smartfarm_app"


@pytest.fixture
def device_setup(owner_engine):
    tenant_id, device_id, sensor_id, credential_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    token, token_hash = generate_device_token()

    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tenants (id, name, status) "
                "VALUES (:id, 'HTTP Integration Test', 'active')"
            ),
            {"id": tenant_id},
        )
        conn.execute(
            text(
                "INSERT INTO devices "
                "(id, tenant_id, device_code, device_type, name, status) "
                "VALUES (:id, :tenant, :code, 'test', 'HTTP Device', 'active')"
            ),
            {
                "id": device_id,
                "tenant": tenant_id,
                "code": str(device_id),
            },
        )
        conn.execute(
            text(
                "INSERT INTO sensors "
                "(id, tenant_id, device_id, sensor_code, "
                "measurement_type, unit, status) "
                "VALUES (:id, :tenant, :device, :code, "
                "'temperature', 'C', 'active')"
            ),
            {
                "id": sensor_id,
                "tenant": tenant_id,
                "device": device_id,
                "code": str(sensor_id),
            },
        )
        conn.execute(
            text(
                "INSERT INTO device_credentials "
                "(id, tenant_id, device_id, secret_hash) "
                "VALUES (:id, :tenant, :device, :hash)"
            ),
            {
                "id": credential_id,
                "tenant": tenant_id,
                "device": device_id,
                "hash": token_hash,
            },
        )

    payload = {
        "event_id": str(uuid4()),
        "device_id": str(device_id),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "readings": [
            {
                "sensor_id": str(sensor_id),
                "metric": "temperature",
                "value": 25.5,
                "unit": "C",
            }
        ],
    }

    yield {
        "tenant_id": tenant_id,
        "device_id": device_id,
        "credential_id": credential_id,
        "sensor_id": sensor_id,
        "token": token,
        "payload": payload,
        "owner": owner_engine,
    }

    with owner_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM sensor_readings WHERE tenant_id = :id"),
            {"id": tenant_id},
        )
        conn.execute(
            text("DELETE FROM telemetry_events WHERE tenant_id = :id"),
            {"id": tenant_id},
        )
        conn.execute(
            text("DELETE FROM device_credentials WHERE tenant_id = :id"),
            {"id": tenant_id},
        )
        conn.execute(
            text("DELETE FROM sensors WHERE tenant_id = :id"),
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


@pytest.fixture
def http_client():
    import asyncio

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


def send(client, setup, payload=None):
    return client.post(
        "/api/v1/telemetry",
        json=payload if payload is not None else setup["payload"],
        headers={"Authorization": f"Bearer {setup['token']}"},
    )


def test_real_credential_persists_and_deduplicates(
    device_setup, http_client
):
    setup = device_setup
    first = send(http_client, setup)
    second = send(http_client, setup)

    assert first.status_code == 202, first.text
    assert first.json()["duplicate"] is False
    assert second.status_code == 202, second.text
    assert second.json()["duplicate"] is True

    with setup["owner"].connect() as conn:
        assert conn.execute(
            text(
                "SELECT count(*) FROM telemetry_events "
                "WHERE device_id = :device AND event_id = :event"
            ),
            {
                "device": setup["device_id"],
                "event": setup["payload"]["event_id"],
            },
        ).scalar_one() == 1


def test_revoked_credential_is_rejected(device_setup, http_client):
    setup = device_setup
    with setup["owner"].begin() as conn:
        conn.execute(
            text(
                "UPDATE device_credentials SET revoked_at = CURRENT_TIMESTAMP "
                "WHERE id = :id"
            ),
            {"id": setup["credential_id"]},
        )

    response = send(http_client, setup)
    assert response.status_code == 401


def test_inactive_tenant_is_rejected(device_setup, http_client):
    setup = device_setup
    with setup["owner"].begin() as conn:
        conn.execute(
            text("UPDATE tenants SET status = 'suspended' WHERE id = :id"),
            {"id": setup["tenant_id"]},
        )

    response = send(http_client, setup)
    assert response.status_code == 401


def test_conflicting_event_id_returns_409(device_setup, http_client):
    setup = device_setup
    first = send(http_client, setup)
    assert first.status_code == 202, first.text

    changed = {
        **setup["payload"],
        "readings": [
            {
                **setup["payload"]["readings"][0],
                "value": 26.5,
            }
        ],
    }
    response = send(http_client, setup, changed)
    assert response.status_code == 409


def test_database_failure_rolls_back_event(device_setup, http_client):
    setup = device_setup
    payload = {
        **setup["payload"],
        "readings": [
            {
                **setup["payload"]["readings"][0],
                "value": 1e30,
            }
        ],
    }

    response = send(http_client, setup, payload)
    assert response.status_code == 503, response.text
    assert "database" not in response.text.lower()

    with setup["owner"].connect() as conn:
        assert conn.execute(
            text(
                "SELECT count(*) FROM telemetry_events "
                "WHERE device_id = :device AND event_id = :event"
            ),
            {
                "device": setup["device_id"],
                "event": payload["event_id"],
            },
        ).scalar_one() == 0
