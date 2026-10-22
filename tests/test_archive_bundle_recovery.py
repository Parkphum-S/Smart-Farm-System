import hashlib
import json

from app.services.archive_bundle_recovery import inspect_telemetry_bundle


def write_json(path, value):
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def create_bundle(root):
    root.mkdir()
    file_manifests = {}

    for name, record in (
        ("events", {"event_id": "event-1"}),
        ("readings", {"reading_id": "reading-1"}),
    ):
        filename = f"{name}.jsonl"
        data = (
            json.dumps(
                record, sort_keys=True, separators=(",", ":")
            )
            + "\n"
        ).encode("utf-8")
        (root / filename).write_bytes(data)

        file_manifest = {
            "format_version": 1,
            "created_at": "2026-10-23T00:00:00+00:00",
            "file": filename,
            "record_count": 1,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        }
        write_json(root / f"{name}.manifest.json", file_manifest)
        file_manifests[name] = file_manifest

    write_json(
        root / "bundle.manifest.json",
        {
            "format_version": 1,
            "status": "complete",
            "created_at": "2026-10-23T00:00:00+00:00",
            "interval": {
                "start_at": "2026-10-22T00:00:00+00:00",
                "end_at": "2026-10-23T00:00:00+00:00",
                "semantics": "[start_at, end_at)",
            },
            "files": file_manifests,
        },
    )


def test_valid_bundle_passes_without_modifying_files(tmp_path):
    bundle = tmp_path / "bundle"
    create_bundle(bundle)
    before = {
        path.name: path.read_bytes()
        for path in bundle.iterdir()
    }

    result = inspect_telemetry_bundle(bundle)

    assert result["status"] == "VALID_BUNDLE"
    assert result["errors"] == []
    assert all(
        item["status"] == "VALID_MANIFEST"
        for item in result["files"].values()
    )
    assert {
        path.name: path.read_bytes()
        for path in bundle.iterdir()
    } == before


def test_modified_jsonl_requires_review(tmp_path):
    bundle = tmp_path / "bundle"
    create_bundle(bundle)
    with (bundle / "events.jsonl").open("ab") as stream:
        stream.write(b'{"event_id":"tampered"}\n')

    result = inspect_telemetry_bundle(bundle)

    assert result["status"] == "REVIEW_REQUIRED"
    assert any("events" in error for error in result["errors"])


def test_missing_sidecar_manifest_requires_review(tmp_path):
    bundle = tmp_path / "bundle"
    create_bundle(bundle)
    (bundle / "readings.manifest.json").unlink()

    result = inspect_telemetry_bundle(bundle)

    assert result["status"] == "REVIEW_REQUIRED"
    assert any("readings" in error for error in result["errors"])


def test_embedded_manifest_mismatch_requires_review(tmp_path):
    bundle = tmp_path / "bundle"
    create_bundle(bundle)

    manifest_path = bundle / "bundle.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["events"]["record_count"] = 999
    write_json(manifest_path, manifest)

    result = inspect_telemetry_bundle(bundle)

    assert result["status"] == "REVIEW_REQUIRED"
    assert any("does not match file manifest" in error
               for error in result["errors"])


def test_missing_bundle_manifest_is_incomplete(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    result = inspect_telemetry_bundle(bundle)

    assert result["status"] == "INCOMPLETE_BUNDLE"
    assert result["manifest_exists"] is False


def test_invalid_interval_requires_review(tmp_path):
    bundle = tmp_path / "bundle"
    create_bundle(bundle)

    manifest_path = bundle / "bundle.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["interval"]["start_at"] = "2026-10-24T00:00:00+00:00"
    write_json(manifest_path, manifest)

    result = inspect_telemetry_bundle(bundle)

    assert result["status"] == "REVIEW_REQUIRED"
    assert any("start_at must precede end_at" in error
               for error in result["errors"])


def test_missing_bundle_created_at_requires_review(tmp_path):
    bundle = tmp_path / "bundle"
    create_bundle(bundle)

    manifest_path = bundle / "bundle.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["created_at"]
    write_json(manifest_path, manifest)

    result = inspect_telemetry_bundle(bundle)

    assert result["status"] == "REVIEW_REQUIRED"
    assert any("created_at" in error for error in result["errors"])


def test_naive_bundle_created_at_requires_review(tmp_path):
    bundle = tmp_path / "bundle"
    create_bundle(bundle)

    manifest_path = bundle / "bundle.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["created_at"] = "2026-10-23T00:00:00"
    write_json(manifest_path, manifest)

    result = inspect_telemetry_bundle(bundle)

    assert result["status"] == "REVIEW_REQUIRED"
    assert any("created_at" in error for error in result["errors"])


def test_unexpected_bundle_manifest_file_entry_requires_review(tmp_path):
    bundle = tmp_path / "bundle"
    create_bundle(bundle)

    manifest_path = bundle / "bundle.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["extra"] = {}
    write_json(manifest_path, manifest)

    result = inspect_telemetry_bundle(bundle)

    assert result["status"] == "REVIEW_REQUIRED"
    assert any("Unexpected bundle file entries" in error
               for error in result["errors"])


def test_unlisted_jsonl_file_does_not_modify_bundle(tmp_path):
    bundle = tmp_path / "bundle"
    create_bundle(bundle)
    extra_path = bundle / "extra.jsonl"
    extra_path.write_text('{"extra":true}\n', encoding="utf-8")
    before = extra_path.read_bytes()

    result = inspect_telemetry_bundle(bundle)

    assert result["status"] == "VALID_BUNDLE"
    assert extra_path.read_bytes() == before
