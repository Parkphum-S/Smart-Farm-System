from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

from app.api import dependencies


def test_missing_bearer_returns_401():
    db = Mock()
    with pytest.raises(HTTPException) as exc:
        dependencies.get_authenticated_user(None, db)
    assert exc.value.status_code == 401
    assert exc.value.headers["WWW-Authenticate"] == "Bearer"
    db.begin.assert_not_called()


def test_invalid_session_returns_401(monkeypatch):
    db = Mock()
    db.begin.return_value.__enter__ = Mock(return_value=db)
    db.begin.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(dependencies, "authenticate_session", Mock(return_value=None))

    credentials = Mock(scheme="Bearer", credentials="invalid")
    with pytest.raises(HTTPException) as exc:
        dependencies.get_authenticated_user(credentials, db)

    assert exc.value.status_code == 401
    assert exc.value.headers["WWW-Authenticate"] == "Bearer"


def test_valid_session_returns_user(monkeypatch):
    db = Mock()
    db.begin.return_value.__enter__ = Mock(return_value=db)
    db.begin.return_value.__exit__ = Mock(return_value=False)
    user = Mock(id="user-1")
    authenticate = Mock(return_value=user)
    monkeypatch.setattr(dependencies, "authenticate_session", authenticate)

    credentials = Mock(scheme="Bearer", credentials="valid-token")
    assert dependencies.get_authenticated_user(credentials, db) is user
    authenticate.assert_called_once_with(db, "valid-token")


def test_invalid_allowed_role_raises_value_error():
    with pytest.raises(ValueError):
        dependencies.require_tenant_role("admin")


def test_tenant_role_dependency_returns_authorized_role(monkeypatch):
    user = Mock(id="user-1")
    db = Mock()
    db.begin.return_value.__enter__ = Mock(return_value=db)
    db.begin.return_value.__exit__ = Mock(return_value=False)
    authorize = Mock(return_value="owner")
    monkeypatch.setattr(dependencies, "authorize_tenant", authorize)

    dependency = dependencies.require_tenant_role("owner")
    result = dependency(tenant_id="tenant-1", user=user, db=db)

    assert result == "owner"
    authorize.assert_called_once_with(db, "user-1", "tenant-1", {"owner"})


def test_insufficient_tenant_role_propagates_403(monkeypatch):
    db = Mock()
    db.begin.return_value.__enter__ = Mock(return_value=db)
    db.begin.return_value.__exit__ = Mock(return_value=False)
    denied = HTTPException(status_code=403, detail="Insufficient tenant permissions")
    monkeypatch.setattr(dependencies, "authorize_tenant", Mock(side_effect=denied))

    dependency = dependencies.require_tenant_role("owner")
    with pytest.raises(HTTPException) as exc:
        dependency(tenant_id="tenant-1", user=Mock(id="user-1"), db=db)

    assert exc.value.status_code == 403


def test_database_error_returns_503(monkeypatch):
    db = Mock()
    db.begin.side_effect = OperationalError("query", {}, RuntimeError("database unavailable"))
    monkeypatch.setattr(dependencies, "authenticate_session", Mock())

    credentials = Mock(scheme="Bearer", credentials="valid-token")
    with pytest.raises(HTTPException) as exc:
        dependencies.get_authenticated_user(credentials, db)

    assert exc.value.status_code == 503
