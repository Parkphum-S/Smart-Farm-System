import asyncio
from unittest.mock import Mock

import httpx
from sqlalchemy.exc import OperationalError

from app.db.session import get_db
from app.main import app


def _get_ready(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as http:
            return await http.get("/health/ready")

    try:
        return asyncio.run(request())
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_ready_returns_200_when_database_responds():
    db = Mock()

    response = _get_ready(db)

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    db.execute.assert_called_once()


def test_ready_returns_503_without_leaking_error_details():
    db = Mock()
    db.execute.side_effect = OperationalError(
        "SELECT 1", {}, RuntimeError("secret-db-detail")
    )

    response = _get_ready(db)

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert "secret-db-detail" not in response.text
