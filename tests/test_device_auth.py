import re

import pytest

from app.security.device_auth import (
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
