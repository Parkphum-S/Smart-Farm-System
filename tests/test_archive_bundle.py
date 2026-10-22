import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services import archive_bundle


class FakeTransaction:
    def __init__(self, connection):
        self.connection = connection
        self.is_active = True
        self.committed = False
        self.rolled_back = False

    def commit(self):
        if self.connection.fail_commit:
            raise OSError("simulated commit failure")
        self.committed = True
        self.is_active = False
        self.connection.active = False

    def rollback(self):
        self.rolled_back = True
        self.is_active = False
        self.connection.active = False


class FakeConnection:
    def __init__(self, already_in_transaction=False, fail_commit=False):
        self.active = already_in_transaction
        self.fail_commit = fail_commit
        self.statements = []
        self.transaction = None
        self.options = {}
        self.options_history = []
        self.isolation_level = "READ COMMITTED"

    def in_transaction(self):
        return self.active

    def get_isolation_level(self):
        return self.isolation_level

    def execution_options(self, **options):
        self.options.update(options)
        self.options_history.append(dict(options))
        if "isolation_level" in options:
            self.isolation_level = options["isolation_level"]
        return self

    def begin(self):
        self.active = True
        self.transaction = FakeTransaction(self)
        return self.transaction

    def execute(self, statement):
        self.statements.append(str(statement))
        return None


def fake_readers(monkeypatch):
    monkeypatch.setattr(
        archive_bundle,
        "iter_events",
        lambda connection, start_at, end_at, *, batch_size:
            iter([{"id": "event-1"}]),
    )
    monkeypatch.setattr(
        archive_bundle,
        "iter_readings",
        lambda connection, start_at, end_at, *, batch_size:
            iter([{"id": "reading-1"}, {"id": "reading-2"}]),
    )


def test_bundle_manifest_is_published_after_snapshot_commit(
    tmp_path, monkeypatch
):
    fake_readers(monkeypatch)
    connection = FakeConnection()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)

    result = archive_bundle.export_telemetry_bundle(
        connection, tmp_path, start, end, batch_size=2
    )

    bundle_dir = tmp_path / result["bundle_dir"].split("/")[-1]
    manifest = json.loads(
        (bundle_dir / "bundle.manifest.json").read_text(encoding="utf-8")
    )

    assert any(
        item.get("isolation_level") == "REPEATABLE READ"
        for item in connection.options_history
    )
    assert connection.isolation_level == "READ COMMITTED"
    assert connection.transaction.committed
    assert not connection.transaction.rolled_back
    assert any("SET TRANSACTION READ ONLY" in s for s in connection.statements)
    assert manifest["status"] == "complete"
    assert manifest["interval"]["semantics"] == "[start_at, end_at)"
    assert manifest["files"]["events"]["record_count"] == 1
    assert manifest["files"]["readings"]["record_count"] == 2
    assert (bundle_dir / "events.jsonl").is_file()
    assert (bundle_dir / "readings.jsonl").is_file()


def test_commit_failure_rolls_back_and_does_not_publish_bundle_manifest(
    tmp_path, monkeypatch
):
    fake_readers(monkeypatch)
    connection = FakeConnection(fail_commit=True)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)

    with pytest.raises(OSError, match="simulated commit failure"):
        archive_bundle.export_telemetry_bundle(
            connection, tmp_path, start, end
        )

    bundle_dirs = list(tmp_path.glob("telemetry-*"))
    assert len(bundle_dirs) == 1
    assert connection.transaction.rolled_back
    assert not (bundle_dirs[0] / "bundle.manifest.json").exists()
    assert connection.isolation_level == "READ COMMITTED"
    assert any(
        item.get("isolation_level") == "REPEATABLE READ"
        for item in connection.options_history
    )


def test_success_restores_original_isolation_level(tmp_path, monkeypatch):
    fake_readers(monkeypatch)
    connection = FakeConnection()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)

    archive_bundle.export_telemetry_bundle(
        connection, tmp_path, start, end
    )

    assert connection.isolation_level == "READ COMMITTED"


def test_reader_failure_rolls_back_and_does_not_publish_bundle_manifest(
    tmp_path, monkeypatch
):
    def fail_readings(connection, start_at, end_at, *, batch_size):
        raise OSError("simulated reader failure")

    monkeypatch.setattr(
        archive_bundle,
        "iter_events",
        lambda connection, start_at, end_at, *, batch_size:
            iter([{"id": "event-1"}]),
    )
    monkeypatch.setattr(archive_bundle, "iter_readings", fail_readings)

    connection = FakeConnection()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)

    with pytest.raises(OSError, match="simulated reader failure"):
        archive_bundle.export_telemetry_bundle(
            connection, tmp_path, start, end
        )

    bundle_dirs = list(tmp_path.glob("telemetry-*"))
    assert len(bundle_dirs) == 1
    assert connection.transaction.rolled_back
    assert (bundle_dirs[0] / "events.jsonl").exists()
    assert not (bundle_dirs[0] / "bundle.manifest.json").exists()


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (
            datetime(2026, 1, 1),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
        ),
        (
            datetime(2026, 1, 2, tzinfo=timezone.utc),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    ],
)
def test_invalid_interval_is_rejected_before_creating_bundle(
    tmp_path, start, end
):
    with pytest.raises(ValueError):
        archive_bundle.export_telemetry_bundle(
            FakeConnection(), tmp_path, start, end
        )
    assert list(tmp_path.iterdir()) == []


def test_active_transaction_is_rejected_before_creating_bundle(tmp_path):
    connection = FakeConnection(already_in_transaction=True)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)

    with pytest.raises(ValueError, match="active transaction"):
        archive_bundle.export_telemetry_bundle(
            connection, tmp_path, start, end
        )

    assert list(tmp_path.iterdir()) == []


def test_manifest_publish_failure_leaves_bundle_without_completion_marker(
    tmp_path, monkeypatch
):
    fake_readers(monkeypatch)
    connection = FakeConnection()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)

    def fail_publish(output_dir, manifest):
        raise OSError("simulated manifest publish failure")

    monkeypatch.setattr(
        archive_bundle, "_publish_bundle_manifest", fail_publish
    )

    with pytest.raises(OSError, match="simulated manifest publish failure"):
        archive_bundle.export_telemetry_bundle(
            connection, tmp_path, start, end
        )

    bundle_dirs = list(tmp_path.glob("telemetry-*"))
    assert len(bundle_dirs) == 1
    assert (bundle_dirs[0] / "events.jsonl").is_file()
    assert (bundle_dirs[0] / "readings.jsonl").is_file()
    assert not (bundle_dirs[0] / "bundle.manifest.json").exists()
    assert connection.transaction.committed
    assert not connection.in_transaction()
    assert connection.isolation_level == "READ COMMITTED"
