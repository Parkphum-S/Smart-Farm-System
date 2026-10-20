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
