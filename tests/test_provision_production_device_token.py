import importlib
import os
import re
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


provision = importlib.import_module(
    "scripts.provision_production_device_token"
)


class FakeTransaction:
    def __init__(self, fail_commit=False):
        self.is_active = True
        self.fail_commit = fail_commit
        self.committed = False
        self.rolled_back = False

    def commit(self):
        if self.fail_commit:
            raise RuntimeError("simulated commit failure")
        self.committed = True
        self.is_active = False

    def rollback(self):
        self.rolled_back = True
        self.is_active = False


class FakeResult:
    def __init__(self, row=None, scalar=None):
        self.row = row
        self.scalar = scalar

    def mappings(self):
        return self

    def one(self):
        return self.row

    def one_or_none(self):
        return self.row

    def scalars(self):
        return self

    def all(self):
        return self.scalar


class FakeConnection:
    def __init__(self, tx, can_insert=True, usable_credentials=1):
        self.tx = tx
        self.can_insert = can_insert
        self.usable_credentials = usable_credentials
        self.insert_count = 0

    def begin(self):
        return self.tx

    def execute(self, statement, params=None):
        sql = str(statement)

        if "current_database()" in sql:
            return FakeResult(row={
                "db": "smartfarm",
                "role": "smartfarm_owner",
                "can_insert": self.can_insert,
            })

        if "FROM public.devices d" in sql:
            return FakeResult(row={
                "device_id": provision.DEVICE_ID,
                "tenant_id": provision.TENANT_ID,
                "device_code": provision.DEVICE_CODE,
                "device_status": "active",
                "tenant_status": "active",
            })

        if "COUNT(*) AS n" in sql:
            return FakeResult(row={"n": self.usable_credentials})

        if "INSERT INTO public.device_credentials" in sql:
            self.insert_count += 1
            return FakeResult()

        raise AssertionError(f"Unexpected SQL statement: {sql}")


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection
        self.disposed = False

    def connect(self):
        connection = self.connection

        class Context:
            def __enter__(self):
                return connection

            def __exit__(self, *args):
                return False

        return Context()

    def dispose(self):
        self.disposed = True


@pytest.fixture
def harness(tmp_path, monkeypatch):
    secret = tmp_path / "secrets.h"
    secret.write_text(
        '#pragma once\n#define DEVICE_API_KEY "sfdev_' + "A" * 43 + '"\n'
    )
    secret.chmod(0o600)

    tx = FakeTransaction()
    conn = FakeConnection(tx)
    engine = FakeEngine(conn)

    monkeypatch.setattr(provision, "SECRET_PATH", secret)
    monkeypatch.setattr(
        provision, "dotenv_values",
        lambda _: {
            "SMARTFARM_MIGRATION_DATABASE_URL":
                "postgresql://smartfarm_owner:fake@localhost/smartfarm"
        },
    )
    monkeypatch.setattr(provision, "create_engine", lambda *a, **k: engine)
    monkeypatch.setattr(
        provision, "generate_device_token",
        lambda: ("sfdev_" + "B" * 43, "fake-hash"),
    )
    monkeypatch.setattr(
        provision, "hash_device_token",
        lambda token: "fake-hash",
    )

    return SimpleNamespace(
        secret=secret,
        tx=tx,
        conn=conn,
        engine=engine,
    )


def test_success_inserts_one_credential_and_installs_secret(harness, capsys):
    provision.main()

    content = harness.secret.read_text()
    match = re.search(
        r'^#define DEVICE_API_KEY "([^"]+)"$',
        content,
        re.MULTILINE,
    )

    assert match is not None
    assert match.group(1) == "sfdev_" + "B" * 43
    assert stat.S_IMODE(harness.secret.stat().st_mode) == 0o600
    assert harness.conn.insert_count == 1
    assert harness.tx.committed
    assert "Provisioning: PASS" in capsys.readouterr().out


def test_commit_failure_keeps_original_secret(harness, monkeypatch):
    harness.tx.fail_commit = True

    original = harness.secret.read_bytes()

    with pytest.raises(SystemExit, match="commit outcome"):
        provision.main()

    assert harness.secret.read_bytes() == original
    assert harness.conn.insert_count == 1
    assert not harness.tx.committed

    recovery_files = list(
        harness.secret.parent.glob(".secrets.h.*")
    )
    assert len(recovery_files) == 1
    assert recovery_files[0].exists()


def test_replace_failure_keeps_recovery_file(harness, monkeypatch):
    original = harness.secret.read_bytes()

    def fail_replace(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(provision.os, "replace", fail_replace)

    with pytest.raises(SystemExit, match="secret installation"):
        provision.main()

    assert harness.tx.committed
    assert harness.conn.insert_count == 1
    assert harness.secret.read_bytes() == original

    backup_files = list(
        harness.secret.parent.glob(".secrets.h.recovery.*")
    )
    prepared_files = [
        path for path in harness.secret.parent.glob(".secrets.h.*")
        if ".recovery." not in path.name
    ]

    assert len(backup_files) == 1
    assert len(prepared_files) == 1
    assert backup_files[0].read_bytes() == original
    assert prepared_files[0].exists()
    assert harness.secret.read_bytes() == original


def test_missing_insert_permission_stops_before_insert(harness):
    harness.conn.can_insert = False
    original = harness.secret.read_bytes()

    with pytest.raises(SystemExit, match="INSERT privilege missing"):
        provision.main()

    assert harness.conn.insert_count == 0
    assert not harness.tx.committed
    assert harness.secret.read_bytes() == original


def test_normal_mode_rejects_two_usable_credentials(harness):
    harness.conn.usable_credentials = 2
    original = harness.secret.read_bytes()

    with pytest.raises(SystemExit, match="recovery mode requires explicit"):
        provision.main()

    assert harness.conn.insert_count == 0
    assert not harness.tx.committed
    assert harness.secret.read_bytes() == original


def test_recovery_mode_accepts_exactly_two_usable_credentials(
    harness, capsys
):
    harness.conn.usable_credentials = 2

    provision.main(["--recover-two-usable-credentials"])

    output = capsys.readouterr().out
    assert harness.conn.insert_count == 1
    assert harness.tx.committed
    assert "Explicit two-credential recovery mode used" in output
    assert "Token and hash were not displayed" in output


@pytest.mark.parametrize("count", [0, 1, 3, 4])
def test_recovery_mode_rejects_unexpected_credential_count(
    harness, count
):
    harness.conn.usable_credentials = count
    original = harness.secret.read_bytes()

    with pytest.raises(SystemExit, match="requires exactly two"):
        provision.main(["--recover-two-usable-credentials"])

    assert harness.conn.insert_count == 0
    assert not harness.tx.committed
    assert harness.secret.read_bytes() == original


def test_directory_fsync_failure_retains_backup(harness, monkeypatch):
    import app.security.secret_file_recovery as recovery

    real_fsync = recovery.fsync_directory
    calls = {"n": 0}

    def fail_after_replace(directory):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated directory fsync failure")
        return real_fsync(directory)

    monkeypatch.setattr(recovery, "fsync_directory", fail_after_replace)

    with pytest.raises(SystemExit, match="directory sync failed"):
        provision.main()

    assert harness.tx.committed
    assert harness.conn.insert_count == 1
    backups = list(harness.secret.parent.glob(".secrets.h.recovery.*"))
    assert len(backups) == 1
    assert backups[0].read_text().startswith("#pragma once")
    assert harness.secret.exists()


def test_token_hash_verification_failure_retains_backup(harness, monkeypatch):
    real_hash = provision.hash_device_token
    calls = {"n": 0}

    def fail_post_install_verification(token):
        calls["n"] += 1
        if calls["n"] == 2:
            return "deliberately-wrong-hash"
        return real_hash(token)

    monkeypatch.setattr(
        provision, "hash_device_token", fail_post_install_verification
    )

    with pytest.raises(SystemExit, match="secret verification failed"):
        provision.main()

    assert harness.tx.committed
    assert harness.conn.insert_count == 1
    backups = list(harness.secret.parent.glob(".secrets.h.recovery.*"))
    assert len(backups) == 1
    assert backups[0].read_text().startswith("#pragma once")
    assert harness.secret.exists()
