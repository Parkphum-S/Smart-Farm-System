import re

import pytest

from unittest.mock import Mock
from uuid import UUID, uuid4

from app.security.device_auth import (
    DeviceIdentity,
    authenticate_device,
    generate_device_token,
    hash_device_token,
    verify_device_token,
)


def test_generated_token_has_expected_format_and_hash() -> None:
    token, stored_hash = generate_device_token()

    assert re.fullmatch(r"sfdev_[A-Za-z0-9_-]{43}", token)
    assert re.fullmatch(r"[0-9a-f]{64}", stored_hash)
    assert token not in stored_hash


def test_valid_token_is_verified() -> None:
    token, stored_hash = generate_device_token()

    assert verify_device_token(token, stored_hash)


def test_wrong_token_is_rejected() -> None:
    _, stored_hash = generate_device_token()
    another_token, _ = generate_device_token()

    assert not verify_device_token(another_token, stored_hash)


def test_malformed_token_is_rejected() -> None:
    _, stored_hash = generate_device_token()

    assert not verify_device_token("not-a-device-token", stored_hash)


def test_malformed_stored_hash_is_rejected() -> None:
    token, _ = generate_device_token()

    assert not verify_device_token(token, "not-a-hash")


def test_malformed_token_cannot_be_hashed() -> None:
    with pytest.raises(ValueError, match="Invalid device token format"):
        hash_device_token("invalid")


def test_authenticate_device_returns_credential_id() -> None:
    token, _ = generate_device_token()
    tenant_id = uuid4()
    device_id = uuid4()
    credential_id = uuid4()

    db = Mock()
    db.execute.return_value.mappings.return_value.first.return_value = {
        "tenant_id": tenant_id,
        "device_id": device_id,
        "credential_id": credential_id,
    }

    identity = authenticate_device(db, token)

    assert identity == DeviceIdentity(
        tenant_id=tenant_id,
        device_id=device_id,
        credential_id=credential_id,
    )
    db.execute.assert_called_once()


def test_authenticate_device_returns_none_when_not_found() -> None:
    token, _ = generate_device_token()

    db = Mock()
    db.execute.return_value.mappings.return_value.first.return_value = None

    assert authenticate_device(db, token) is None
    db.execute.assert_called_once()


def test_authenticate_device_rejects_malformed_token_without_query() -> None:
    db = Mock()

    assert authenticate_device(db, "invalid-token") is None
    db.execute.assert_not_called()


def test_device_identity_keeps_legacy_constructor_compatibility() -> None:
    identity = DeviceIdentity(
        tenant_id=UUID(int=1),
        device_id=UUID(int=2),
    )

    assert identity.credential_id is None
