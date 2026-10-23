"""Transactional command lifecycle operations.

The caller owns the database transaction. This service never commits.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.commands import CommandCreate, CommandEventCreate
from app.security.device_auth import DeviceIdentity


class CommandRejected(Exception):
    """The authenticated principal cannot perform the requested operation."""


class CommandConflict(Exception):
    """An idempotency key or event ID was reused inconsistently."""


class CommandNotFound(Exception):
    """The command does not exist for the authenticated device/tenant."""


class CommandExpired(Exception):
    """The command is expired and must not be executed."""


def _request_hash(request: CommandCreate) -> str:
    canonical = json.dumps(
        request.model_dump(mode="json", exclude={"idempotency_key"}),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _event(
    db: Session,
    *,
    tenant_id: UUID,
    command_id: UUID,
    device_id: UUID,
    event_type: str,
    event_id: str,
    actor_type: str,
    actor_user_id: UUID | None = None,
    occurred_at: datetime | None = None,
    details: dict | None = None,
) -> bool:
    inserted = db.execute(
        text("""
            INSERT INTO command_events (
                id, tenant_id, command_id, device_id, event_type,
                event_id, actor_type, actor_user_id, occurred_at, details
            )
            VALUES (
                :id, :tenant_id, :command_id, :device_id, :event_type,
                :event_id, :actor_type, :actor_user_id, :occurred_at,
                CAST(:details AS jsonb)
            )
            ON CONFLICT (device_id, event_id) DO NOTHING
            RETURNING id
        """),
        {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "command_id": command_id,
            "device_id": device_id,
            "event_type": event_type,
            "event_id": event_id,
            "actor_type": actor_type,
            "actor_user_id": actor_user_id,
            "occurred_at": occurred_at,
            "details": json.dumps(details or {}, separators=(",", ":")),
        },
    ).scalar_one_or_none()
    return inserted is not None


def _expire_device_commands(
    db: Session,
    identity: DeviceIdentity,
) -> None:
    rows = db.execute(
        text("""
            UPDATE commands
            SET status = 'expired', updated_at = CURRENT_TIMESTAMP
            WHERE tenant_id = :tenant_id
              AND device_id = :device_id
              AND status IN ('pending', 'sent')
              AND expires_at <= CURRENT_TIMESTAMP
            RETURNING id
        """),
        {
            "tenant_id": identity.tenant_id,
            "device_id": identity.device_id,
        },
    ).scalars().all()

    for command_id in rows:
        _event(
            db,
            tenant_id=identity.tenant_id,
            command_id=command_id,
            device_id=identity.device_id,
            event_type="expired",
            event_id=f"system-expired-{command_id}",
            actor_type="system",
        )


def create_command(
    db: Session,
    *,
    tenant_id: UUID,
    device_id: UUID,
    user_id: UUID,
    request: CommandCreate,
) -> tuple[dict, bool]:
    """Create idempotently; returns (row, was_existing)."""
    digest = _request_hash(request)
    existing = db.execute(
        text("""
            SELECT *
            FROM commands
            WHERE tenant_id = :tenant_id
              AND requested_by_user_id = :user_id
              AND idempotency_key = :key
        """),
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "key": request.idempotency_key,
        },
    ).mappings().first()

    if existing is not None:
        if existing["request_hash"] != digest:
            raise CommandConflict("Idempotency key reused with different request")
        return dict(existing), True

    device = db.execute(
        text("""
            SELECT d.status, t.status AS tenant_status
            FROM devices AS d
            JOIN tenants AS t ON t.id = d.tenant_id
            WHERE d.id = :device_id AND d.tenant_id = :tenant_id
        """),
        {"device_id": device_id, "tenant_id": tenant_id},
    ).mappings().first()

    if (
        device is None
        or device["status"] != "active"
        or device["tenant_status"] != "active"
    ):
        raise CommandRejected("Device or tenant is not active")

    now = datetime.now(timezone.utc)
    command_id = uuid4()
    parameters = request.parameters.model_dump(mode="json")
    expires_at = now + timedelta(seconds=request.expires_in_seconds)

    row = db.execute(
        text("""
            INSERT INTO commands (
                id, tenant_id, device_id, requested_by_user_id,
                command_type, parameters, status, expires_at,
                idempotency_key, request_hash, correlation_id
            )
            VALUES (
                :id, :tenant_id, :device_id, :user_id,
                :command_type, CAST(:parameters AS jsonb), 'pending',
                :expires_at, :key, :request_hash, :correlation_id
            )
            ON CONFLICT (
                tenant_id, requested_by_user_id, idempotency_key
            ) DO NOTHING
            RETURNING *
        """),
        {
            "id": command_id,
            "tenant_id": tenant_id,
            "device_id": device_id,
            "user_id": user_id,
            "command_type": request.command_type,
            "parameters": json.dumps(parameters, separators=(",", ":")),
            "expires_at": expires_at,
            "key": request.idempotency_key,
            "request_hash": digest,
            "correlation_id": request.correlation_id,
        },
    ).mappings().first()

    if row is None:
        # Another request may have inserted the same idempotency key.
        existing = db.execute(
            text("""
                SELECT *
                FROM commands
                WHERE tenant_id = :tenant_id
                  AND requested_by_user_id = :user_id
                  AND idempotency_key = :key
            """),
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "key": request.idempotency_key,
            },
        ).mappings().first()

        if existing is None:
            raise RuntimeError(
                "Command insert conflicted, but the existing command "
                "could not be found"
            )

        if existing["request_hash"] != digest:
            raise CommandConflict(
                "Idempotency key reused with different request"
            )

        return dict(existing), True

    _event(
        db,
        tenant_id=tenant_id,
        command_id=command_id,
        device_id=device_id,
        event_type="created",
        event_id=f"system-created-{command_id}",
        actor_type="user",
        actor_user_id=user_id,
    )
    return dict(row), False


def pending_commands(
    db: Session,
    identity: DeviceIdentity,
    *,
    limit: int = 20,
) -> list[dict]:
    """Atomically claim pending commands and return live commands for retry.

    The caller must wrap this function in a database transaction.
    Device-side command-ID deduplication is still required.
    """
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")

    _expire_device_commands(db, identity)
    rows = db.execute(
        text("""
            SELECT *
            FROM commands
            WHERE tenant_id = :tenant_id
              AND device_id = :device_id
              AND status IN ('pending', 'sent')
              AND expires_at > CURRENT_TIMESTAMP
            ORDER BY created_at, id
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
        """),
        {
            "tenant_id": identity.tenant_id,
            "device_id": identity.device_id,
            "limit": limit,
        },
    ).mappings().all()

    result = []
    for original in rows:
        row = dict(original)
        if row["status"] == "pending":
            updated = db.execute(
                text("""
                    UPDATE commands
                    SET status = 'sent', updated_at = CURRENT_TIMESTAMP
                    WHERE id = :command_id
                      AND tenant_id = :tenant_id
                      AND device_id = :device_id
                      AND status = 'pending'
                      AND expires_at > CURRENT_TIMESTAMP
                    RETURNING *
                """),
                {
                    "command_id": row["id"],
                    "tenant_id": identity.tenant_id,
                    "device_id": identity.device_id,
                },
            ).mappings().first()
            if updated is None:
                continue

            row = dict(updated)
            _event(
                db,
                tenant_id=identity.tenant_id,
                command_id=row["id"],
                device_id=identity.device_id,
                event_type="delivered",
                event_id=f"system-delivered-{row['id']}",
                actor_type="system",
            )
        result.append(row)

    return result


def _validate_event_details(details: dict) -> str:
    """Validate bounded, JSON-safe result details; never accept secret fields."""
    forbidden = ("token", "secret", "password", "authorization", "credential")

    def walk(value, depth=0):
        if depth > 5:
            raise CommandRejected("Event details are too deeply nested")
        if isinstance(value, dict):
            if len(value) > 32:
                raise CommandRejected("Too many event detail fields")
            for key, child in value.items():
                if not isinstance(key, str) or not key.strip():
                    raise CommandRejected("Invalid event detail key")
                if any(word in key.lower() for word in forbidden):
                    raise CommandRejected("Sensitive event detail key rejected")
                walk(child, depth + 1)
        elif isinstance(value, list):
            if len(value) > 32:
                raise CommandRejected("Event detail list is too long")
            for child in value:
                walk(child, depth + 1)
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            raise CommandRejected("Event details must contain JSON scalar values")
        elif isinstance(value, float):
            import math
            if not math.isfinite(value):
                raise CommandRejected("Non-finite event detail number")

    walk(details)
    try:
        encoded = json.dumps(
            details, separators=(",", ":"), sort_keys=True, allow_nan=False
        )
    except (TypeError, ValueError):
        raise CommandRejected("Event details are not valid JSON") from None

    if len(encoded.encode("utf-8")) > 2048:
        raise CommandRejected("Event details exceed size limit")
    return encoded


def record_command_event(
    db: Session,
    identity: DeviceIdentity,
    command_id: UUID,
    event: CommandEventCreate,
) -> tuple[dict, bool]:
    """Record a device event idempotently and enforce forward-only transitions."""
    details_json = _validate_event_details(event.details)
    _expire_device_commands(db, identity)

    row = db.execute(
        text("""
            SELECT *
            FROM commands
            WHERE id = :command_id
              AND tenant_id = :tenant_id
              AND device_id = :device_id
            FOR UPDATE
        """),
        {
            "command_id": command_id,
            "tenant_id": identity.tenant_id,
            "device_id": identity.device_id,
        },
    ).mappings().first()

    if row is None:
        raise CommandNotFound()

    duplicate = db.execute(
        text("""
            SELECT command_id, event_type, details, occurred_at
            FROM command_events
            WHERE device_id = :device_id AND event_id = :event_id
        """),
        {
            "device_id": identity.device_id,
            "event_id": event.event_id,
        },
    ).mappings().first()

    if duplicate is not None:
        same_time = duplicate["occurred_at"] == event.occurred_at
        if (
            duplicate["command_id"] != command_id
            or duplicate["event_type"] != event.event_type
            or duplicate["details"] != event.details
            or not same_time
        ):
            raise CommandConflict("Event ID reused with different content")
        return dict(row), True

    if row["status"] in ("pending", "sent") and db.execute(
        text("""
            SELECT expires_at <= CURRENT_TIMESTAMP
            FROM commands
            WHERE id = :command_id
        """),
        {"command_id": command_id},
    ).scalar_one():
        raise CommandExpired()

    allowed = {
        "sent": {"acknowledged", "failed"},
        "acknowledged": {"succeeded", "failed"},
    }
    if event.event_type not in allowed.get(row["status"], set()):
        raise CommandConflict("Invalid command state transition")

    inserted = _event(
        db,
        tenant_id=identity.tenant_id,
        command_id=command_id,
        device_id=identity.device_id,
        event_type=event.event_type,
        event_id=event.event_id,
        actor_type="device",
        occurred_at=event.occurred_at,
        details=json.loads(details_json),
    )
    if not inserted:
        # Another transaction may have claimed the same device/event key.
        # Do not silently accept it without re-reading and comparing content.
        duplicate = db.execute(
            text("""
                SELECT command_id, event_type, details, occurred_at
                FROM command_events
                WHERE device_id = :device_id AND event_id = :event_id
            """),
            {
                "device_id": identity.device_id,
                "event_id": event.event_id,
            },
        ).mappings().first()
        if (
            duplicate is None
            or duplicate["command_id"] != command_id
            or duplicate["event_type"] != event.event_type
            or duplicate["details"] != event.details
            or duplicate["occurred_at"] != event.occurred_at
        ):
            raise CommandConflict("Event ID already exists")
        return dict(row), True

    summary = (
        json.loads(details_json)
        if event.event_type in ("succeeded", "failed")
        else None
    )
    updated = db.execute(
        text("""
            UPDATE commands
            SET status = :status,
                updated_at = CURRENT_TIMESTAMP,
                result_summary = CASE
                    WHEN :has_summary THEN CAST(:summary AS jsonb)
                    ELSE result_summary
                END
            WHERE id = :command_id
              AND tenant_id = :tenant_id
              AND device_id = :device_id
            RETURNING *
        """),
        {
            "status": event.event_type,
            "has_summary": summary is not None,
            "summary": json.dumps(summary or {}, separators=(",", ":")),
            "command_id": command_id,
            "tenant_id": identity.tenant_id,
            "device_id": identity.device_id,
        },
    ).mappings().one()

    return dict(updated), False
