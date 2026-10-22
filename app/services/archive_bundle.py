"""Create consistent, verifiable telemetry archive bundles."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.services.archive import _fsync_directory, _publish_exclusive
from app.services.archive import write_jsonl_archive
from app.services.archive_reader import iter_events, iter_readings


BUNDLE_FORMAT_VERSION = 1
BUNDLE_MANIFEST_NAME = "bundle.manifest.json"


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _range_label(start_at: datetime, end_at: datetime) -> str:
    start = start_at.strftime("%Y%m%dT%H%M%SZ")
    end = end_at.strftime("%Y%m%dT%H%M%SZ")
    return f"telemetry-{start}-{end}-{uuid4().hex[:12]}"


def _publish_bundle_manifest(
    output_dir: Path, manifest: dict[str, Any]
) -> None:
    destination = output_dir / BUNDLE_MANIFEST_NAME
    if destination.exists():
        raise FileExistsError("Bundle manifest already exists")

    fd, temporary_name = tempfile.mkstemp(
        prefix=".bundle.",
        suffix=".manifest.tmp",
        dir=output_dir,
    )
    temporary_path = Path(temporary_name)
    try:
        payload = (
            json.dumps(
                manifest,
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

        _publish_exclusive(temporary_path, destination)
        _fsync_directory(output_dir)
    finally:
        temporary_path.unlink(missing_ok=True)


def export_telemetry_bundle(
    connection: Connection,
    archive_root: str | Path,
    start_at: datetime,
    end_at: datetime,
    *,
    batch_size: int = 1000,
) -> dict[str, Any]:
    """Export one consistent read-only PostgreSQL snapshot.

    The connection must not already have a transaction. A bundle is complete
    only after the read-only repeatable-read transaction commits and the
    bundle manifest is published. Failed exports are retained for inspection.
    Source records are never modified or deleted.
    """
    start_utc = _utc(start_at, "start_at")
    end_utc = _utc(end_at, "end_at")
    if start_utc >= end_utc:
        raise ValueError("start_at must be earlier than end_at")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if connection.in_transaction():
        raise ValueError("connection must not have an active transaction")

    root = Path(archive_root)
    root.mkdir(parents=True, exist_ok=True)
    bundle_dir = root / _range_label(start_utc, end_utc)
    bundle_dir.mkdir(exist_ok=False)

    # Restore the caller's isolation level before returning the connection.
    original_isolation_level = connection.get_isolation_level()
    transaction = None

    try:
        # Isolation level must be configured before opening the transaction.
        connection.execution_options(isolation_level="REPEATABLE READ")
        transaction = connection.begin()
        connection.execute(text("SET TRANSACTION READ ONLY"))

        events = write_jsonl_archive(
            bundle_dir,
            "events",
            iter_events(
                connection, start_utc, end_utc, batch_size=batch_size
            ),
        )
        readings = write_jsonl_archive(
            bundle_dir,
            "readings",
            iter_readings(
                connection, start_utc, end_utc, batch_size=batch_size
            ),
        )
        transaction.commit()
    except BaseException:
        if transaction is not None and transaction.is_active:
            transaction.rollback()
        raise
    finally:
        if not connection.in_transaction():
            connection.execution_options(
                isolation_level=original_isolation_level
            )

    manifest = {
        "format_version": BUNDLE_FORMAT_VERSION,
        "status": "complete",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "interval": {
            "start_at": start_utc.isoformat(),
            "end_at": end_utc.isoformat(),
            "semantics": "[start_at, end_at)",
        },
        "files": {
            "events": events,
            "readings": readings,
        },
    }
    _publish_bundle_manifest(bundle_dir, manifest)
    return {"bundle_dir": str(bundle_dir), "manifest": manifest}
