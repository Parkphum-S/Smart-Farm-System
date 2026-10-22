import hashlib
import json

from app.services.archive_recovery import inspect_orphan_archive


def test_valid_orphan_is_inspected_without_modification(tmp_path):
    path = tmp_path / "batch.jsonl"
    data = b'{"event_id":"a"}\n{"event_id":"b"}\n'
    path.write_bytes(data)
    original = path.read_bytes()

    result = inspect_orphan_archive(path)

    assert result["status"] == "VALID_JSONL_NO_MANIFEST"
    assert result["record_count"] == 2
    assert result["size_bytes"] == len(data)
    assert result["sha256"] == hashlib.sha256(data).hexdigest()
    assert result["manifest_exists"] is False
    assert path.read_bytes() == original
    assert not (tmp_path / "batch.manifest.json").exists()


def test_invalid_json_is_reported(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_bytes(b'{"ok":true}\n{broken}\n')

    result = inspect_orphan_archive(path)

    assert result["status"] == "INVALID_JSONL_NO_MANIFEST"
    assert result["record_count"] == 1
    assert any("invalid JSON" in error for error in result["errors"])


def test_missing_final_newline_is_reported(tmp_path):
    path = tmp_path / "partial.jsonl"
    path.write_bytes(b'{"ok":true}')

    result = inspect_orphan_archive(path)

    assert result["status"] == "INVALID_JSONL_NO_MANIFEST"
    assert result["record_count"] == 1
    assert any("missing newline" in error for error in result["errors"])


def test_empty_orphan_is_valid(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_bytes(b"")

    result = inspect_orphan_archive(path)

    assert result["status"] == "VALID_JSONL_NO_MANIFEST"
    assert result["record_count"] == 0
    assert result["size_bytes"] == 0
    assert result["sha256"] == hashlib.sha256(b"").hexdigest()


def test_existing_manifest_is_never_modified(tmp_path):
    path = tmp_path / "batch.jsonl"
    manifest = tmp_path / "batch.manifest.json"
    path.write_bytes(b'{"ok":true}\n')
    original_manifest = b'{"existing":"keep"}\n'
    manifest.write_bytes(original_manifest)

    result = inspect_orphan_archive(path)

    assert result["status"] == "MANIFEST_PRESENT_REVIEW_REQUIRED"
    assert result["manifest_exists"] is True
    assert manifest.read_bytes() == original_manifest


def test_missing_file_is_reported(tmp_path):
    result = inspect_orphan_archive(tmp_path / "missing.jsonl")

    assert result["status"] == "FILE_NOT_FOUND"


def test_read_error_marks_partial_result(tmp_path, monkeypatch):
    path = tmp_path / "read-error.jsonl"
    path.write_bytes(b'{"ok":true}\n')

    class FailingStream:
        def __init__(self):
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def readline(self):
            self.calls += 1
            if self.calls == 1:
                return b'{"ok":true}\n'
            raise OSError("simulated read failure")

    original_open = type(path).open
    stream = FailingStream()

    def patched_open(self, *args, **kwargs):
        if self == path:
            return stream
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(type(path), "open", patched_open)

    result = inspect_orphan_archive(path)

    assert result["status"] == "READ_ERROR"
    assert result["record_count"] == 1
