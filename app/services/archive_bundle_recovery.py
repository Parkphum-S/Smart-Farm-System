"""Read-only validation for complete telemetry archive bundles."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.archive_recovery import inspect_orphan_archive


BUNDLE_FORMAT_VERSION = 1
EXPECTED_FILES = {
    "events": "events.jsonl",
    "readings": "readings.jsonl",
}


def _reject_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream, parse_constant=_reject_constant)


def _aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def inspect_telemetry_bundle(bundle_dir: str | Path) -> dict[str, Any]:
    """Inspect a bundle without creating, modifying, or deleting files."""
    root = Path(bundle_dir)
    manifest_path = root / "bundle.manifest.json"

    result: dict[str, Any] = {
        "bundle": root.name,
        "status": "NOT_CHECKED",
        "manifest_exists": manifest_path.is_file(),
        "files": {},
        "errors": [],
    }

    if not root.is_dir():
        result["status"] = "BUNDLE_NOT_FOUND"
        result["errors"].append("Bundle directory does not exist")
        return result

    if not manifest_path.is_file():
        result["status"] = "INCOMPLETE_BUNDLE"
        result["errors"].append("Bundle completion manifest is missing")
        return result

    try:
        manifest = _read_json(manifest_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        result["status"] = "INVALID_BUNDLE_MANIFEST"
        result["errors"].append(f"Cannot read bundle manifest: {exc}")
        return result

    if not isinstance(manifest, dict):
        result["status"] = "INVALID_BUNDLE_MANIFEST"
        result["errors"].append("Bundle manifest must be a JSON object")
        return result

    errors: list[str] = []

    version = manifest.get("format_version")
    if type(version) is not int or version != BUNDLE_FORMAT_VERSION:
        errors.append("Unsupported or invalid bundle format_version")

    if manifest.get("status") != "complete":
        errors.append("Bundle status is not complete")

    created_at = _aware_datetime(manifest.get("created_at"))
    if created_at is None:
        errors.append(
            "Bundle created_at must be a timezone-aware timestamp"
        )

    interval = manifest.get("interval")
    if not isinstance(interval, dict):
        errors.append("Bundle interval must be an object")
    else:
        start = _aware_datetime(interval.get("start_at"))
        end = _aware_datetime(interval.get("end_at"))
        if start is None or end is None:
            errors.append("Bundle interval timestamps must be timezone-aware")
        elif start >= end:
            errors.append("Bundle interval start_at must precede end_at")
        if interval.get("semantics") != "[start_at, end_at)":
            errors.append("Unsupported bundle interval semantics")

    file_manifests = manifest.get("files")
    if not isinstance(file_manifests, dict):
        errors.append("Bundle files must be an object")
        file_manifests = {}

    for key, filename in EXPECTED_FILES.items():
        data_path = root / filename
        inspection = inspect_orphan_archive(data_path)
        result["files"][key] = inspection

        if inspection["status"] != "VALID_MANIFEST":
            errors.append(
                f"{key}: archive inspection status is "
                f"{inspection['status']}"
            )

        embedded = file_manifests.get(key)
        if not isinstance(embedded, dict):
            errors.append(f"{key}: bundle manifest entry is missing")
            continue

        sidecar_path = root / f"{Path(filename).stem}.manifest.json"
        try:
            sidecar = _read_json(sidecar_path)
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            errors.append(f"{key}: cannot read file manifest: {exc}")
            continue

        if not isinstance(sidecar, dict):
            errors.append(f"{key}: file manifest must be an object")
            continue

        if embedded != sidecar:
            errors.append(
                f"{key}: bundle manifest entry does not match file manifest"
            )

    extra_keys = set(file_manifests) - set(EXPECTED_FILES)
    if extra_keys:
        errors.append(
            f"Unexpected bundle file entries: {', '.join(sorted(extra_keys))}"
        )

    result["errors"] = errors
    result["status"] = "VALID_BUNDLE" if not errors else "REVIEW_REQUIRED"
    return result
