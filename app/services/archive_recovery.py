"""Read-only inspection for JSONL archives missing their manifest."""

import hashlib
import json
from pathlib import Path
from typing import Any


def inspect_orphan_archive(data_path: str | Path) -> dict[str, Any]:
    """Inspect a JSONL archive without modifying any files.

    This function never creates a manifest, renames files, or deletes data.
    """
    path = Path(data_path)
    manifest_path = path.with_name(
        f"{path.stem}.manifest.json"
    )

    result: dict[str, Any] = {
        "file": path.name,
        "manifest": manifest_path.name,
        "manifest_exists": manifest_path.exists(),
        "status": "NOT_CHECKED",
        "record_count": 0,
        "size_bytes": 0,
        "sha256": None,
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
                    errors.append(
                        f"Line {line_number}: missing newline"
                    )

                try:
                    text = line.decode("utf-8")
                except UnicodeDecodeError:
                    errors.append(
                        f"Line {line_number}: invalid UTF-8"
                    )
                    continue

                try:
                    def reject_constant(value: str) -> None:
                        raise ValueError(
                            f"Invalid JSON constant: {value}"
                        )

                    record = json.loads(
                        text,
                        parse_constant=reject_constant,
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
        result["errors"].append(str(exc))
        return result

    result["record_count"] = count
    result["size_bytes"] = size
    result["sha256"] = digest.hexdigest()
    result["errors"] = errors

    if manifest_path.exists():
        result["status"] = "MANIFEST_PRESENT_REVIEW_REQUIRED"
    elif errors:
        result["status"] = "INVALID_JSONL_NO_MANIFEST"
    else:
        result["status"] = "VALID_JSONL_NO_MANIFEST"

    return result
