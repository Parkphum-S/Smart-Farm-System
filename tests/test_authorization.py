from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.services.authorization import authorize_tenant


def session_with_role(role):
    db = Mock()
    result = Mock()
    result.mappings.return_value.first.return_value = (
        {"role": role} if role is not None else None
    )
    db.execute.return_value = result
    return db


def test_authorize_tenant_allows_matching_role():
    db = session_with_role("owner")
    assert authorize_tenant(db, "user-1", "tenant-1", {"owner"}) == "owner"


def test_authorize_tenant_rejects_role_not_allowed():
    db = session_with_role("viewer")
    with pytest.raises(HTTPException) as exc:
        authorize_tenant(db, "user-1", "tenant-1", {"owner"})
    assert exc.value.status_code == 403


def test_authorize_tenant_rejects_missing_membership():
    db = session_with_role(None)
    with pytest.raises(HTTPException) as exc:
        authorize_tenant(db, "user-1", "tenant-1", {"viewer"})
    assert exc.value.status_code == 403
