import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_TOKEN_PATTERN = re.compile(r"sfdev_[A-Za-z0-9_-]{43}\Z")
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class DeviceIdentity:
    tenant_id: UUID
    device_id: UUID


def generate_device_token() -> tuple[str, str]:
    token = "sfdev_" + secrets.token_urlsafe(32)
    return token, hash_device_token(token)


def hash_device_token(token: str) -> str:
    if not isinstance(token, str) or not _TOKEN_PATTERN.fullmatch(token):
        raise ValueError("Invalid device token format")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_device_token(token: str, stored_hash: str) -> bool:
    if not isinstance(stored_hash, str):
        return False
    if not _HASH_PATTERN.fullmatch(stored_hash):
        return False
    try:
        candidate = hash_device_token(token)
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(candidate, stored_hash)


def authenticate_device(
    db: Session,
    token: str,
) -> DeviceIdentity | None:
    try:
        token_hash = hash_device_token(token)
    except (TypeError, ValueError):
        return None

    statement = text(
        "SELECT d.tenant_id, d.id AS device_id "
        "FROM device_credentials AS c "
        "JOIN devices AS d "
        "ON d.tenant_id = c.tenant_id AND d.id = c.device_id "
        "JOIN tenants AS t ON t.id = d.tenant_id "
        "WHERE c.secret_hash = :secret_hash "
        "AND c.revoked_at IS NULL "
        "AND (c.expires_at IS NULL "
        "OR c.expires_at > CURRENT_TIMESTAMP) "
        "AND d.status = 'active' "
        "AND t.status = 'active' "
        "LIMIT 1"
    )

    row = db.execute(
        statement,
        {"secret_hash": token_hash},
    ).mappings().first()

    if row is None:
        return None

    return DeviceIdentity(
        tenant_id=row["tenant_id"],
        device_id=row["device_id"],
    )
