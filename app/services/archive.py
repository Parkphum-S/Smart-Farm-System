"""Streaming, export-only helpers for telemetry archive files."""

import ctypes
import errno
import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("Archive datetimes must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        # Preserve decimal precision; consumers should interpret this as decimal text.
        return str(value)
    raise TypeError(f"Unsupported archive value type: {type(value).__name__}")


def _fsync_directory(directory: Path) -> None:
    """Request persistence of directory-entry changes."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(directory, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _publish_exclusive(temporary_path: Path, destination: Path) -> None:
    """Atomically publish a file without replacing an existing destination."""
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = libc.renameat2
    except AttributeError as exc:
        raise OSError(
            errno.ENOSYS,
            "renameat2 is not available on this system",
        ) from exc

    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int

    at_fdcwd = -100
    rename_noreplace = 1
    result = renameat2(
        at_fdcwd,
        os.fsencode(temporary_path),
        at_fdcwd,
        os.fsencode(destination),
        rename_noreplace,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(
            error_number,
            os.strerror(error_number),
            str(destination),
        )


def write_jsonl_archive(
    output_dir: str | Path,
    archive_name: str,
    records: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Stream records to JSONL and write a SHA-256 manifest.

    The caller must provide a consistent, complete record set.
    Existing output files are never overwritten.
    """
    if (
        not archive_name
        or Path(archive_name).name != archive_name
        or archive_name in {".", ".."}
    ):
        raise ValueError("archive_name must be a plain filename stem")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    data_path = output_dir / f"{archive_name}.jsonl"
    manifest_path = output_dir / f"{archive_name}.manifest.json"

    if data_path.exists() or manifest_path.exists():
        raise FileExistsError("Archive output already exists")

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{archive_name}.",
        suffix=".jsonl.tmp",
        dir=output_dir,
    )
    temporary_path = Path(temporary_name)
    digest = hashlib.sha256()
    count = 0
    size_bytes = 0

    try:
        with os.fdopen(fd, "wb") as stream:
            for record in records:
                line = (
                    json.dumps(
                        record,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                        default=_json_default,
                    )
                    + "\n"
                ).encode("utf-8")
                stream.write(line)
                digest.update(line)
                count += 1
                size_bytes += len(line)

            stream.flush()
            os.fsync(stream.fileno())

        manifest = {
            "format_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "file": data_path.name,
            "record_count": count,
            "sha256": digest.hexdigest(),
            "size_bytes": size_bytes,
        }
        manifest_bytes = (
            json.dumps(
                manifest,
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")

        # Publish data first; never overwrite an existing file.
        _publish_exclusive(temporary_path, data_path)
        _fsync_directory(output_dir)

        # Publish the manifest exclusively. If this fails, leave the data
        # file in place for explicit recovery rather than deleting it blindly.
        fd_manifest, manifest_temp_name = tempfile.mkstemp(
            prefix=f".{archive_name}.",
            suffix=".manifest.tmp",
            dir=output_dir,
        )
        manifest_temp = Path(manifest_temp_name)
        try:
            with os.fdopen(fd_manifest, "wb") as stream:
                stream.write(manifest_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            _publish_exclusive(manifest_temp, manifest_path)
            _fsync_directory(output_dir)
        finally:
            manifest_temp.unlink(missing_ok=True)

        return manifest
    finally:
        temporary_path.unlink(missing_ok=True)
