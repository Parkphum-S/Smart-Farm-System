import asyncio
import importlib

import httpx

from app.core.config import settings


def _get_paths(monkeypatch, environment):
    import app.main as main_module

    monkeypatch.setattr(settings, "environment", environment)
    reloaded = importlib.reload(main_module)

    async def request():
        transport = httpx.ASGITransport(app=reloaded.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as http:
            return [
                (await http.get(path)).status_code
                for path in ("/docs", "/redoc", "/openapi.json")
            ]

    try:
        return asyncio.run(request())
    finally:
        monkeypatch.undo()
        importlib.reload(main_module)


def test_docs_are_available_in_development(monkeypatch):
    assert _get_paths(monkeypatch, "development") == [200, 200, 200]


def test_docs_are_disabled_in_production(monkeypatch):
    assert _get_paths(monkeypatch, "production") == [404, 404, 404]
