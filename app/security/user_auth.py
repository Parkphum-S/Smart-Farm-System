import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)


_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a password using Argon2id."""
    if not password:
        raise ValueError("Password must not be empty")
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Verify a password without exposing hash verification errors."""
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def generate_session_token() -> tuple[str, str]:
    """Return the raw session token and its SHA-256 hash."""
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return token, token_hash


def hash_session_token(token: str) -> str:
    """Hash a session token for database lookup."""
    if not token:
        raise ValueError("Session token must not be empty")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
