import hashlib
import json
from pathlib import Path

import pytest

from app.services.archive import write_jsonl_archive


def test_write_jsonl_archive_creates_data_and_manifest(tmp_path: Path):
    records = [
        {"event_id": "event-1", "value": 25.5},
        {"event_id": "event-2", "value": 26.0},
    ]

    manifest = write_jsonl_archive(tmp_path, "batch-001", records)

    data_path = tmp_path / "batch-001.jsonl"
    manifest_path = tmp_path / "batch-001.manifest.json"
    data = data_path.read_bytes()

    assert [json.loads(line) for line in data.splitlines()] == records
    assert manifest_path.exists()
    assert manifest["record_count"] == 2
    assert manifest["sha256"] == hashlib.sha256(data).hexdigest()
    assert manifest["size_bytes"] == len(data)

    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved_manifest == manifest


def test_empty_archive_is_valid(tmp_path: Path):
    manifest = write_jsonl_archive(tmp_path, "empty-batch", [])

    assert manifest["record_count"] == 0
    assert manifest["sha256"] == hashlib.sha256(b"").hexdigest()
    assert (tmp_path / "empty-batch.jsonl").read_bytes() == b""


def test_existing_archive_is_never_overwritten(tmp_path: Path):
    data_path = tmp_path / "batch-002.jsonl"
    data_path.write_text("preserve me\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_jsonl_archive(tmp_path, "batch-002", [{"value": 1}])

    assert data_path.read_text(encoding="utf-8") == "preserve me\n"


@pytest.mark.parametrize("name", ["../escape", "subdir/batch", "", ".", ".."])
def test_archive_name_rejects_path_traversal(tmp_path: Path, name: str):
    with pytest.raises(ValueError):
        write_jsonl_archive(tmp_path, name, [])


def test_non_json_value_fails_without_publishing_data(tmp_path: Path):
    with pytest.raises((TypeError, ValueError)):
        write_jsonl_archive(tmp_path, "bad-batch", [{"value": object()}])

    assert not (tmp_path / "bad-batch.jsonl").exists()
    assert not (tmp_path / "bad-batch.manifest.json").exists()


def test_naive_datetime_is_rejected_without_publishing_files(tmp_path: Path):
    from datetime import datetime

    with pytest.raises(ValueError, match="timezone-aware"):
        write_jsonl_archive(
            tmp_path,
            "naive-time",
            [{"observed_at": datetime(2026, 1, 1, 12, 0, 0)}],
        )

    assert not (tmp_path / "naive-time.jsonl").exists()
    assert not (tmp_path / "naive-time.manifest.json").exists()


def test_aware_datetime_is_normalized_to_utc(tmp_path: Path):
    from datetime import datetime, timezone, timedelta

    write_jsonl_archive(
        tmp_path,
        "aware-time",
        [{
            "observed_at": datetime(
                2026, 1, 1, 19, 0, 0,
                tzinfo=timezone(timedelta(hours=7)),
            )
        }],
    )

    record = json.loads(
        (tmp_path / "aware-time.jsonl").read_text(encoding="utf-8")
    )
    assert record["observed_at"] == "2026-01-01T12:00:00+00:00"


def test_decimal_is_preserved_as_exact_text(tmp_path: Path):
    from decimal import Decimal

    write_jsonl_archive(
        tmp_path,
        "decimal-value",
        [{"value": Decimal("1234567890.12345678")}],
    )

    record = json.loads(
        (tmp_path / "decimal-value.jsonl").read_text(encoding="utf-8")
    )
    assert record["value"] == "1234567890.12345678"


def test_records_are_consumed_lazily(tmp_path: Path):
    consumed = []

    def records():
        for number in range(3):
            consumed.append(number)
            yield {"number": number}

    iterator = records()
    write_jsonl_archive(tmp_path, "lazy-batch", iterator)

    assert consumed == [0, 1, 2]
    assert [
        json.loads(line)
        for line in (tmp_path / "lazy-batch.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ] == [{"number": 0}, {"number": 1}, {"number": 2}]


def test_iterator_failure_does_not_publish_partial_archive(
    tmp_path: Path,
):
    def records():
        yield {"number": 1}
        raise RuntimeError("simulated source failure")

    with pytest.raises(RuntimeError, match="simulated source failure"):
        write_jsonl_archive(tmp_path, "interrupted-batch", records())

    assert not (tmp_path / "interrupted-batch.jsonl").exists()
    assert not (tmp_path / "interrupted-batch.manifest.json").exists()
    assert list(tmp_path.glob(".interrupted-batch.*.jsonl.tmp")) == []


def test_manifest_publication_failure_leaves_data_for_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import app.services.archive as archive_module

    original_publish = archive_module._publish_exclusive

    def fail_manifest_publication(
        temporary_path: Path,
        destination: Path,
    ) -> None:
        if destination.name.endswith(".manifest.json"):
            raise OSError("simulated manifest publication failure")
        original_publish(temporary_path, destination)

    monkeypatch.setattr(
        archive_module,
        "_publish_exclusive",
        fail_manifest_publication,
    )

    with pytest.raises(OSError, match="manifest publication failure"):
        archive_module.write_jsonl_archive(
            tmp_path,
            "manifest-failure",
            [{"number": 1}],
        )

    # Data is retained intentionally; recovery must be explicit.
    assert (tmp_path / "manifest-failure.jsonl").exists()
    assert not (tmp_path / "manifest-failure.manifest.json").exists()
    assert list(tmp_path.glob(".manifest-failure.*.jsonl.tmp")) == []
    assert list(tmp_path.glob(".manifest-failure.*.manifest.tmp")) == []


def test_publish_exclusive_atomically_moves_file(tmp_path: Path):
    from app.services.archive import _publish_exclusive

    temporary_path = tmp_path / ".archive.jsonl.tmp"
    destination = tmp_path / "archive.jsonl"
    temporary_path.write_bytes(b"archive contents")

    _publish_exclusive(temporary_path, destination)

    assert destination.read_bytes() == b"archive contents"
    assert not temporary_path.exists()


def test_publish_exclusive_does_not_replace_existing_file(tmp_path: Path):
    from app.services.archive import _publish_exclusive

    temporary_path = tmp_path / ".archive.jsonl.tmp"
    destination = tmp_path / "archive.jsonl"
    temporary_path.write_bytes(b"new contents")
    destination.write_bytes(b"original contents")

    with pytest.raises(FileExistsError):
        _publish_exclusive(temporary_path, destination)

    assert destination.read_bytes() == b"original contents"
    assert temporary_path.read_bytes() == b"new contents"


def test_publish_exclusive_reports_unsupported_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import ctypes
    import errno
    import app.services.archive as archive_module

    temporary_path = tmp_path / ".archive.jsonl.tmp"
    destination = tmp_path / "archive.jsonl"
    temporary_path.write_bytes(b"archive contents")

    class FakeRenameat2:
        argtypes = None
        restype = None

        def __call__(self, *args):
            ctypes.set_errno(errno.ENOSYS)
            return -1

    class FakeLibC:
        renameat2 = FakeRenameat2()

    monkeypatch.setattr(
        archive_module.ctypes,
        "CDLL",
        lambda *args, **kwargs: FakeLibC(),
    )

    with pytest.raises(OSError) as exc_info:
        archive_module._publish_exclusive(temporary_path, destination)

    assert exc_info.value.errno == errno.ENOSYS
    assert temporary_path.read_bytes() == b"archive contents"
    assert not destination.exists()


def test_directory_fsync_failure_preserves_published_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import errno
    import app.services.archive as archive_module

    def fail_directory_fsync(directory: Path) -> None:
        raise OSError(errno.EIO, "simulated directory fsync failure")

    monkeypatch.setattr(
        archive_module,
        "_fsync_directory",
        fail_directory_fsync,
    )

    with pytest.raises(OSError, match="directory fsync failure"):
        archive_module.write_jsonl_archive(
            tmp_path,
            "directory-fsync-failure",
            [{"number": 1}],
        )

    data_path = tmp_path / "directory-fsync-failure.jsonl"
    manifest_path = tmp_path / "directory-fsync-failure.manifest.json"

    assert data_path.exists()
    assert not manifest_path.exists()
    assert data_path.read_text(encoding="utf-8") == '{"number":1}\n'
    assert list(tmp_path.glob(".directory-fsync-failure.*.jsonl.tmp")) == []
