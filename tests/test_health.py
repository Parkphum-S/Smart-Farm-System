import asyncio
import httpx

from app.main import app


def test_health_live() -> None:
    async def request() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    asyncio.run(request())


def test_api_v1_root_not_found() -> None:
    async def request() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/v1")
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}

    asyncio.run(request())
