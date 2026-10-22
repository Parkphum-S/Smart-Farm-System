from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

VALID_ROLES = frozenset({"owner", "operator", "viewer"})

def authorize_tenant(db: Session, user_id: str, tenant_id: str, allowed_roles: set[str]) -> str:
    if not allowed_roles or not allowed_roles.issubset(VALID_ROLES):
        raise ValueError("allowed_roles must contain valid tenant roles")

    query = text(
        "SELECT m.role "
        "FROM tenant_memberships AS m "
        "JOIN tenants AS t ON t.id = m.tenant_id "
        "WHERE m.user_id = :user_id "
        "AND m.tenant_id = :tenant_id "
        "AND m.status = :membership_status "
        "AND t.status = :tenant_status"
    )
    row = db.execute(query, {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "membership_status": "active",
        "tenant_status": "active",
    }).mappings().first()

    if row is None or row["role"] not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient tenant permissions",
        )

    return row["role"]
