import asyncio

import httpx

from app.main import app


VALID_EVENT = {
    "event_id": "11111111-1111-4111-8111-111111111111",
    "device_id": "22222222-2222-4222-8222-222222222222",
    "observed_at": "2026-10-21T00:00:00Z",
    "readings": [
        {
            "sensor_id": "33333333-3333-4333-8333-333333333333",
            "metric": "air_temperature",
            "value": 28.5,
            "unit": "Cel",
        }
    ],
}


def post_event(payload: dict) -> httpx.Response:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.post("/api/v1/telemetry", json=payload)

    return asyncio.run(request())


def test_missing_authentication_is_rejected() -> None:
    response = post_event(VALID_EVENT)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_invalid_uuid_is_rejected() -> None:
    payload = {**VALID_EVENT, "device_id": "not-a-uuid"}
    assert post_event(payload).status_code == 422


def test_naive_timestamp_is_rejected() -> None:
    payload = {**VALID_EVENT, "observed_at": "2026-10-21T00:00:00"}
    assert post_event(payload).status_code == 422


def test_non_finite_reading_is_rejected() -> None:
    import pytest
    from app.schemas.telemetry import SensorReading

    with pytest.raises(ValueError, match="value must be finite"):
        SensorReading.model_validate({
            "sensor_id": "33333333-3333-4333-8333-333333333333",
            "metric": "air_temperature",
            "value": float("inf"),
            "unit": "Cel",
        })


def test_unknown_field_is_rejected() -> None:
    payload = {**VALID_EVENT, "unexpected": True}
    assert post_event(payload).status_code == 422


def test_empty_readings_are_rejected() -> None:
    payload = {**VALID_EVENT, "readings": []}
    assert post_event(payload).status_code == 422


def test_duplicate_sensor_id_in_readings_is_rejected() -> None:
    reading = VALID_EVENT["readings"][0]
    payload = {
        **VALID_EVENT,
        "readings": [reading, dict(reading)],
    }

    import pytest
    from pydantic import ValidationError
    from app.schemas.telemetry import TelemetryEvent

    with pytest.raises(ValidationError):
        TelemetryEvent.model_validate(payload)
