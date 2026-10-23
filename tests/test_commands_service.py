from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.schemas.commands import CommandCreate, CommandEventCreate
from app.security.device_auth import DeviceIdentity
from app.services.commands import (
    CommandConflict,
    CommandNotFound,
    CommandRejected,
    pending_commands,
    create_command,
    record_command_event,
)


NOW = datetime.now(timezone.utc)


def result_with(value=None, *, method="first"):
    result = Mock()
    mappings = result.mappings
    getattr(mappings.return_value, method).return_value = value
    return result


def scalar_result(value):
    result = Mock()
    result.scalar_one_or_none.return_value = value
    result.scalar_one.return_value = value
    return result


def expired_result(rows=None):
    result = Mock()
    result.scalars.return_value.all.return_value = rows or []
    return result


def make_identity():
    return DeviceIdentity(tenant_id=uuid4(), device_id=uuid4())


def make_request(**overrides):
    data = {
        "command_type": "relay.set",
        "parameters": {"relay": 1, "state": "off"},
        "idempotency_key": "test-key-001",
        "expires_in_seconds": 60,
    }
    data.update(overrides)
    return CommandCreate(**data)


def make_command(identity, *, status="sent", **overrides):
    row = {
        "id": uuid4(),
        "tenant_id": identity.tenant_id,
        "device_id": identity.device_id,
        "requested_by_user_id": uuid4(),
        "command_type": "relay.set",
        "parameters": {"relay": 1, "state": "off"},
        "status": status,
        "created_at": NOW,
        "expires_at": NOW + timedelta(minutes=1),
        "updated_at": NOW,
        "correlation_id": None,
        "result_summary": None,
        "idempotency_key": "test-key-001",
        "request_hash": "a" * 64,
    }
    row.update(overrides)
    return row


def test_create_command_returns_existing_for_same_request():
    from app.services.commands import _request_hash

    identity = make_identity()
    user_id = uuid4()
    request = make_request()
    row = make_command(
        identity,
        requested_by_user_id=user_id,
        request_hash=_request_hash(request),
    )
    db = Mock()
    db.execute.return_value = result_with(row)

    result, was_existing = create_command(
        db,
        tenant_id=identity.tenant_id,
        device_id=identity.device_id,
        user_id=user_id,
        request=request,
    )

    assert result["id"] == row["id"]
    assert was_existing is True
    db.execute.assert_called_once()


def test_create_command_rejects_reused_key_with_different_request():
    identity = make_identity()
    user_id = uuid4()
    row = make_command(
        identity,
        requested_by_user_id=user_id,
        request_hash="0" * 64,
    )
    db = Mock()
    db.execute.return_value = result_with(row)

    with pytest.raises(CommandConflict):
        create_command(
            db,
            tenant_id=identity.tenant_id,
            device_id=identity.device_id,
            user_id=user_id,
            request=make_request(),
        )

    db.execute.assert_called_once()


@pytest.mark.parametrize(
    "device",
    [
        None,
        {"status": "inactive", "tenant_status": "active"},
        {"status": "active", "tenant_status": "suspended"},
    ],
)
def test_create_command_rejects_missing_or_inactive_device(device):
    identity = make_identity()
    db = Mock()
    db.execute.side_effect = [
        result_with(None),
        result_with(device),
    ]

    with pytest.raises(CommandRejected):
        create_command(
            db,
            tenant_id=identity.tenant_id,
            device_id=identity.device_id,
            user_id=uuid4(),
            request=make_request(),
        )

    assert db.execute.call_count == 2


def test_create_command_inserts_pending_command_and_created_event():
    from app.services.commands import _request_hash

    identity = make_identity()
    user_id = uuid4()
    request = make_request()
    command_id = uuid4()
    inserted_row = make_command(
        identity,
        id=command_id,
        requested_by_user_id=user_id,
        status="pending",
        request_hash=_request_hash(request),
    )

    db = Mock()
    db.execute.side_effect = [
        result_with(None),
        result_with(
            {"status": "active", "tenant_status": "active"}
        ),
        result_with(inserted_row, method="first"),
        scalar_result(uuid4()),
    ]

    result, was_existing = create_command(
        db,
        tenant_id=identity.tenant_id,
        device_id=identity.device_id,
        user_id=user_id,
        request=request,
    )

    assert result["id"] == command_id
    assert result["status"] == "pending"
    assert was_existing is False
    assert db.execute.call_count == 4


@pytest.mark.parametrize("limit", [0, -1, 51])
def test_pending_commands_rejects_invalid_limit(limit):
    db = Mock()

    with pytest.raises(ValueError):
        pending_commands(db, make_identity(), limit=limit)

    db.execute.assert_not_called()


def test_pending_commands_claims_pending_command_as_sent():
    identity = make_identity()
    row = make_command(identity, status="pending")
    updated_row = {**row, "status": "sent"}

    db = Mock()
    db.execute.side_effect = [
        expired_result(),
        result_with([row], method="all"),
        result_with(updated_row),
        scalar_result(uuid4()),
    ]

    result = pending_commands(db, identity)

    assert len(result) == 1
    assert result[0]["status"] == "sent"
    assert db.execute.call_count == 4


def test_pending_commands_retries_live_sent_command_without_redelivering():
    identity = make_identity()
    row = make_command(identity, status="sent")
    db = Mock()
    db.execute.side_effect = [
        expired_result(),
        result_with([row], method="all"),
    ]

    result = pending_commands(db, identity)

    assert result == [row]
    assert db.execute.call_count == 2


def test_pending_commands_skips_command_that_cannot_be_updated():
    identity = make_identity()
    row = make_command(identity, status="pending")
    db = Mock()
    db.execute.side_effect = [
        expired_result(),
        result_with([row], method="all"),
        result_with(None),
    ]

    result = pending_commands(db, identity)

    assert result == []
    assert db.execute.call_count == 3


def test_record_command_event_rejects_unknown_command():
    identity = make_identity()
    event = CommandEventCreate(
        event_id="event-unknown",
        event_type="acknowledged",
    )
    db = Mock()
    db.execute.side_effect = [
        expired_result(),
        result_with(None),
    ]

    with pytest.raises(CommandNotFound):
        record_command_event(db, identity, uuid4(), event)

    assert db.execute.call_count == 2


@pytest.mark.parametrize(
    "details",
    [
        {"access_token": "do-not-store"},
        {"nested": {"password_hash": "secret"}},
        {"items": list(range(33))},
        {"value": float("nan")},
        {"value": object()},
        {"value": "x" * 2100},
    ],
)
def test_record_command_event_rejects_unsafe_details(details):
    identity = make_identity()
    event = CommandEventCreate(
        event_id="event-unsafe",
        event_type="acknowledged",
        details=details,
    )
    db = Mock()

    with pytest.raises(CommandRejected):
        record_command_event(db, identity, uuid4(), event)

    db.execute.assert_not_called()


def test_record_command_event_rejects_invalid_state_transition():
    identity = make_identity()
    row = make_command(identity, status="pending")
    event = CommandEventCreate(
        event_id="event-invalid-transition",
        event_type="succeeded",
    )
    db = Mock()
    db.execute.side_effect = [
        expired_result(),
        result_with(row),
        result_with(None),
        scalar_result(False),
    ]

    with pytest.raises(CommandConflict):
        record_command_event(db, identity, row["id"], event)

    assert db.execute.call_count == 4


def test_record_command_event_records_success_and_result_summary():
    identity = make_identity()
    row = make_command(identity, status="acknowledged")
    event = CommandEventCreate(
        event_id="event-success",
        event_type="succeeded",
        details={"relay": 1, "state": "off"},
    )
    updated_row = {
        **row,
        "status": "succeeded",
        "result_summary": {"relay": 1, "state": "off"},
    }

    db = Mock()
    db.execute.side_effect = [
        expired_result(),
        result_with(row),
        result_with(None),
        scalar_result(uuid4()),
        result_with(updated_row, method="one"),
    ]

    result, was_duplicate = record_command_event(
        db, identity, row["id"], event
    )

    assert result["status"] == "succeeded"
    assert result["result_summary"] == {"relay": 1, "state": "off"}
    assert was_duplicate is False
    assert db.execute.call_count == 5


def test_record_command_event_accepts_identical_duplicate():
    identity = make_identity()
    row = make_command(identity, status="sent")
    occurred_at = NOW
    details = {"relay": 1}
    event = CommandEventCreate(
        event_id="event-duplicate",
        event_type="acknowledged",
        occurred_at=occurred_at,
        details=details,
    )
    duplicate = {
        "command_id": row["id"],
        "event_type": "acknowledged",
        "details": details,
        "occurred_at": occurred_at,
    }

    db = Mock()
    db.execute.side_effect = [
        expired_result(),
        result_with(row),
        result_with(duplicate),
    ]

    result, was_duplicate = record_command_event(
        db, identity, row["id"], event
    )

    assert result["id"] == row["id"]
    assert was_duplicate is True
    assert db.execute.call_count == 3


def test_record_command_event_rejects_duplicate_event_id_with_different_data():
    identity = make_identity()
    row = make_command(identity, status="sent")
    event = CommandEventCreate(
        event_id="event-conflict",
        event_type="acknowledged",
        details={"relay": 1},
    )
    duplicate = {
        "command_id": row["id"],
        "event_type": "acknowledged",
        "details": {"relay": 2},
        "occurred_at": None,
    }

    db = Mock()
    db.execute.side_effect = [
        expired_result(),
        result_with(row),
        result_with(duplicate),
    ]

    with pytest.raises(CommandConflict):
        record_command_event(db, identity, row["id"], event)

    assert db.execute.call_count == 3


def test_create_command_conflict_returns_existing_for_same_hash():
    from app.services.commands import _request_hash

    identity = make_identity()
    user_id = uuid4()
    request = make_request()
    existing = make_command(
        identity,
        requested_by_user_id=user_id,
        request_hash=_request_hash(request),
    )

    db = Mock()
    db.execute.side_effect = [
        result_with(None),  # Initial idempotency lookup
        result_with({"status": "active", "tenant_status": "active"}),
        result_with(None),  # INSERT ... DO NOTHING RETURNING *
        result_with(existing),  # Read the winning request's command
    ]

    result, was_existing = create_command(
        db,
        tenant_id=identity.tenant_id,
        device_id=identity.device_id,
        user_id=user_id,
        request=request,
    )

    assert result["id"] == existing["id"]
    assert was_existing is True
    assert db.execute.call_count == 4


def test_create_command_conflict_rejects_different_hash():
    identity = make_identity()
    user_id = uuid4()
    request = make_request()
    existing = make_command(
        identity,
        requested_by_user_id=user_id,
        request_hash="0" * 64,
    )

    db = Mock()
    db.execute.side_effect = [
        result_with(None),
        result_with({"status": "active", "tenant_status": "active"}),
        result_with(None),
        result_with(existing),
    ]

    with pytest.raises(CommandConflict):
        create_command(
            db,
            tenant_id=identity.tenant_id,
            device_id=identity.device_id,
            user_id=user_id,
            request=request,
        )

    assert db.execute.call_count == 4


def test_create_command_conflict_without_existing_row_fails_closed():
    identity = make_identity()
    user_id = uuid4()
    request = make_request()

    db = Mock()
    db.execute.side_effect = [
        result_with(None),
        result_with({"status": "active", "tenant_status": "active"}),
        result_with(None),
        result_with(None),
    ]

    with pytest.raises(RuntimeError, match="could not be found"):
        create_command(
            db,
            tenant_id=identity.tenant_id,
            device_id=identity.device_id,
            user_id=user_id,
            request=request,
        )

    assert db.execute.call_count == 4
