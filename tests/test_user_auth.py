from app.security.user_auth import (
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)


def test_password_hash_and_verify():
    password = "temporary-test-password"
    password_hash = hash_password(password)

    assert password_hash.startswith("$argon2id$")
    assert verify_password(password_hash, password)
    assert not verify_password(password_hash, "incorrect-password")


def test_session_token_is_hashed():
    token, token_hash = generate_session_token()

    assert token
    assert len(token_hash) == 64
    assert token_hash == hash_session_token(token)
    assert token != token_hash


def test_different_tokens_have_different_hashes():
    token1, hash1 = generate_session_token()
    token2, hash2 = generate_session_token()

    assert token1 != token2
    assert hash1 != hash2
