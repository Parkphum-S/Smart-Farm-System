"""User login and database-backed session management."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.security.user_auth import (
    generate_session_token,
    hash_session_token,
    verify_password,
)

SESSION_LIFETIME = timedelta(hours=12)
MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION = timedelta(minutes=15)


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str
    display_name: str


@dataclass(frozen=True)
class LoginResult:
    user: AuthenticatedUser | None
    access_token: str | None
    expires_in: int


def login(db: Session, email: str, password: str) -> LoginResult:
    """Attempt login. Caller owns the transaction, including failed attempts."""
    row = db.execute(
        text("""
            SELECT u.id, u.email, u.display_name, u.status,
                   c.password_hash, c.failed_attempts, c.locked_until
            FROM users AS u
            JOIN user_credentials AS c ON c.user_id = u.id
            WHERE lower(u.email) = lower(:email)
            FOR UPDATE OF c
        """),
        {"email": email.strip().lower()},
    ).mappings().first()

    if row is None:
        return LoginResult(None, None, 0)

    if row["status"] != "active":
        return LoginResult(None, None, 0)

    now = db.execute(
        text("SELECT CURRENT_TIMESTAMP")
    ).scalar_one()

    locked_until = row["locked_until"]
    failed_attempts = row["failed_attempts"]

    if locked_until is not None:
        if locked_until > now:
            return LoginResult(None, None, 0)

        # A lock that has expired starts a fresh failure-count window.
        failed_attempts = 0
        db.execute(
            text("""
                UPDATE user_credentials
                SET failed_attempts = 0, locked_until = NULL
                WHERE user_id = :user_id
            """),
            {"user_id": row["id"]},
        )

    if not verify_password(row["password_hash"], password):
        attempts = failed_attempts + 1
        lock_until = (
            now + LOCK_DURATION
            if attempts >= MAX_FAILED_ATTEMPTS
            else None
        )
        db.execute(
            text("""
                UPDATE user_credentials
                SET failed_attempts = :attempts,
                    locked_until = :locked_until
                WHERE user_id = :user_id
            """),
            {
                "attempts": attempts,
                "locked_until": lock_until,
                "user_id": row["id"],
            },
        )
        return LoginResult(None, None, 0)

    db.execute(
        text("""
            UPDATE user_credentials
            SET failed_attempts = 0, locked_until = NULL
            WHERE user_id = :user_id
        """),
        {"user_id": row["id"]},
    )

    access_token, token_hash = generate_session_token()
    expires_at = now + SESSION_LIFETIME

    db.execute(
        text("""
            INSERT INTO user_sessions (id, user_id, token_hash, expires_at)
            VALUES (:id, :user_id, :token_hash, :expires_at)
        """),
        {
            "id": uuid4(),
            "user_id": row["id"],
            "token_hash": token_hash,
            "expires_at": expires_at,
        },
    )

    user = AuthenticatedUser(
        id=str(row["id"]),
        email=row["email"],
        display_name=row["display_name"],
    )
    return LoginResult(user, access_token, int(SESSION_LIFETIME.total_seconds()))


def authenticate_session(db: Session, token: str) -> AuthenticatedUser | None:
    """Return an active user only for a valid, non-expired session."""
    if not isinstance(token, str) or not token:
        return None

    token_hash = hash_session_token(token)
    row = db.execute(
        text("""
            SELECT u.id, u.email, u.display_name
            FROM user_sessions AS s
            JOIN users AS u ON u.id = s.user_id
            WHERE s.token_hash = :token_hash
              AND s.revoked_at IS NULL
              AND s.expires_at > CURRENT_TIMESTAMP
              AND u.status = 'active'
        """),
        {"token_hash": token_hash},
    ).mappings().first()

    if row is None:
        return None

    db.execute(
        text("""
            UPDATE user_sessions
            SET last_used_at = CURRENT_TIMESTAMP
            WHERE token_hash = :token_hash
              AND revoked_at IS NULL
              AND expires_at > CURRENT_TIMESTAMP
        """),
        {"token_hash": token_hash},
    )

    return AuthenticatedUser(
        id=str(row["id"]),
        email=row["email"],
        display_name=row["display_name"],
    )


def logout(db: Session, token: str) -> None:
    """Revoke the session matching this token; repeated logout is harmless."""
    if not isinstance(token, str) or not token:
        return

    token_hash = hash_session_token(token)
    db.execute(
        text("""
            UPDATE user_sessions
            SET revoked_at = CURRENT_TIMESTAMP
            WHERE token_hash = :token_hash
              AND revoked_at IS NULL
        """),
        {"token_hash": token_hash},
    )
