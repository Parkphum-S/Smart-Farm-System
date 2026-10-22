"""Read-only inspection for JSONL archives and their manifests."""

import hashlib
import json
from pathlib import Path
from typing import Any


def _reject_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def _inspect_manifest(
    manifest_path: Path,
    data_path: Path,
    record_count: int,
    size_bytes: int,
    sha256: str,
) -> list[str]:
    """Validate a manifest against a fully inspected JSONL file."""
    errors: list[str] = []

    try:
        with manifest_path.open("r", encoding="utf-8") as stream:
            manifest = json.load(stream, parse_constant=_reject_constant)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return [f"Manifest cannot be read as valid JSON: {exc}"]

    if not isinstance(manifest, dict):
        return ["Manifest JSON value is not an object"]

    expected = {
        "format_version": 1,
        "file": data_path.name,
        "record_count": record_count,
        "size_bytes": size_bytes,
        "sha256": sha256,
    }

    for key, expected_value in expected.items():
        actual_value = manifest.get(key)
        if key in {"format_version", "record_count", "size_bytes"}:
            if type(actual_value) is not int:
                errors.append(f"Manifest field {key} must be an integer")
                continue
        if actual_value != expected_value:
            errors.append(
                f"Manifest field {key} does not match JSONL"
            )

    created_at = manifest.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        errors.append("Manifest field created_at must be a non-empty string")

    return errors


def inspect_orphan_archive(data_path: str | Path) -> dict[str, Any]:
    """Inspect a JSONL archive without modifying any files.

    This function never creates a manifest, renames files, or deletes data.
    """
    path = Path(data_path)
    manifest_path = path.with_name(f"{path.stem}.manifest.json")

    result: dict[str, Any] = {
        "file": path.name,
        "manifest": manifest_path.name,
        "manifest_exists": manifest_path.exists(),
        "status": "NOT_CHECKED",
        "record_count": 0,
        "size_bytes": 0,
        "sha256": None,
        "partial_result": False,
        "errors": [],
    }

    if not path.is_file():
        result["status"] = "FILE_NOT_FOUND"
        result["errors"].append("JSONL file does not exist")
        return result

    digest = hashlib.sha256()
    count = 0
    size = 0
    errors: list[str] = []

    try:
        with path.open("rb") as stream:
            line_number = 0

            while True:
                line = stream.readline()
                if not line:
                    break

                line_number += 1
                size += len(line)
                digest.update(line)

                if not line.endswith(b"\n"):
                    errors.append(f"Line {line_number}: missing newline")

                try:
                    text = line.decode("utf-8")
                except UnicodeDecodeError:
                    errors.append(f"Line {line_number}: invalid UTF-8")
                    continue

                try:
                    record = json.loads(
                        text,
                        parse_constant=_reject_constant,
                    )
                except (json.JSONDecodeError, ValueError) as exc:
                    errors.append(
                        f"Line {line_number}: invalid JSON ({exc})"
                    )
                    continue

                if not isinstance(record, dict):
                    errors.append(
                        f"Line {line_number}: JSON value is not an object"
                    )
                    continue

                count += 1

    except OSError as exc:
        result["status"] = "READ_ERROR"
        result["record_count"] = count
        result["size_bytes"] = size
        result["sha256"] = None
        result["partial_result"] = True
        result["errors"].append(str(exc))
        return result

    sha256 = digest.hexdigest()
    result["record_count"] = count
    result["size_bytes"] = size
    result["sha256"] = sha256
    result["errors"] = errors

    if errors:
        result["status"] = (
            "INVALID_JSONL_MANIFEST_PRESENT"
            if manifest_path.exists()
            else "INVALID_JSONL_NO_MANIFEST"
        )
        return result

    if manifest_path.exists():
        manifest_errors = _inspect_manifest(
            manifest_path,
            path,
            count,
            size,
            sha256,
        )
        result["errors"] = manifest_errors
        result["status"] = (
            "MANIFEST_PRESENT_REVIEW_REQUIRED"
            if manifest_errors
            else "VALID_MANIFEST"
        )
    else:
        result["status"] = "VALID_JSONL_NO_MANIFEST"

    return result
