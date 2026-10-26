import importlib
from contextlib import contextmanager
from types import SimpleNamespace

import pytest


admin = importlib.import_module("scripts.provision_admin")
sensors = importlib.import_module("scripts.provision_production_sensors")

VALID_URL = "postgresql://smartfarm_owner:fake@localhost/smartfarm"


class Result:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def one(self):
        return self.row


class FakeConnection:
    def __init__(self, db, role):
        self.db = db
        self.role = role
        self.statements = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)

        if "current_database()" in sql:
            if "AS db" in sql:
                return Result({"db": self.db, "role": self.role})
            return Result((self.db, self.role))

        raise AssertionError(
            f"Unexpected SQL executed after identity check: {sql}"
        )


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection
        self.disposed = False
        self.transaction_exited = False

    @contextmanager
    def begin(self):
        try:
            yield self.connection
        except Exception:
            self.transaction_exited = True
            raise
        else:
            self.transaction_exited = True

    def dispose(self):
        self.disposed = True


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://smartfarm_owner:fake@localhost/smartfarm_test",
        "postgresql://smartfarm_app:fake@localhost/smartfarm",
    ],
)
def test_sensors_rejects_wrong_database_or_url_role(monkeypatch, url):
    monkeypatch.setenv("SMARTFARM_MIGRATION_DATABASE_URL", url)
    monkeypatch.setattr(sensors, "dotenv_values", lambda _: {})
    monkeypatch.setattr(
        sensors,
        "create_engine",
        lambda *a, **kw: pytest.fail("Engine must not be created"),
    )

    with pytest.raises(SystemExit, match="unexpected database or role"):
        sensors.main()


@pytest.mark.parametrize("db,role", [
    ("smartfarm_test", "smartfarm_owner"),
    ("smartfarm", "smartfarm_app"),
])
def test_sensors_rejects_wrong_connected_identity_before_device_query(
    monkeypatch, db, role
):
    monkeypatch.setenv("SMARTFARM_MIGRATION_DATABASE_URL", VALID_URL)
    monkeypatch.setattr(sensors, "dotenv_values", lambda _: {})

    conn = FakeConnection(db, role)
    engine = FakeEngine(conn)
    monkeypatch.setattr(sensors, "create_engine", lambda *a, **kw: engine)

    with pytest.raises(RuntimeError, match="connected (database|role) mismatch"):
        sensors.main()

    assert len(conn.statements) == 1
    assert not any("FROM devices" in sql for sql in conn.statements)
    assert engine.transaction_exited
    assert engine.disposed


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://smartfarm_owner:fake@localhost/smartfarm_test",
        "postgresql://smartfarm_app:fake@localhost/smartfarm",
    ],
)
def test_admin_rejects_wrong_database_or_url_role(monkeypatch, url):
    monkeypatch.setattr(
        admin, "dotenv_values",
        lambda _: {"SMARTFARM_MIGRATION_DATABASE_URL": url},
    )
    monkeypatch.setattr(
        admin, "create_engine",
        lambda *a, **kw: pytest.fail("Engine must not be created"),
    )

    assert admin.main() == 1


@pytest.mark.parametrize("db,role", [
    ("smartfarm_test", "smartfarm_owner"),
    ("smartfarm", "smartfarm_app"),
])
def test_admin_rejects_wrong_connected_identity_before_tenant_query(
    monkeypatch, db, role
):
    monkeypatch.setattr(
        admin, "dotenv_values",
        lambda _: {"SMARTFARM_MIGRATION_DATABASE_URL": VALID_URL},
    )
    monkeypatch.setattr("builtins.input", lambda _: "admin@example.com")
    monkeypatch.setattr(admin, "getpass", lambda _: "A-secure-test-password")
    monkeypatch.setattr(admin, "hash_password", lambda _: "fake-hash")

    conn = FakeConnection(db, role)
    engine = FakeEngine(conn)
    monkeypatch.setattr(admin, "create_engine", lambda *a, **kw: engine)

    assert admin.main() == 1

    assert len(conn.statements) == 1
    assert not any("public.tenants" in sql for sql in conn.statements)
    assert engine.transaction_exited
    assert engine.disposed
