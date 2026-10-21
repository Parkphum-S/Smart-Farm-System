from datetime import datetime
from math import isfinite
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SensorReading(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sensor_id: UUID
    metric: Annotated[str, Field(min_length=1, max_length=64)]
    value: float
    unit: Annotated[str, Field(min_length=1, max_length=32)]

    @field_validator("value")
    @classmethod
    def value_must_be_finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("value must be finite")
        return value


class TelemetryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID
    device_id: UUID
    observed_at: datetime
    readings: Annotated[
        list[SensorReading],
        Field(min_length=1, max_length=100),
    ]

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_include_timezone(
        cls, value: datetime
    ) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value

    @field_validator("readings")
    @classmethod
    def sensor_ids_must_be_unique(cls, readings):
        sensor_ids = [reading.sensor_id for reading in readings]
        if len(sensor_ids) != len(set(sensor_ids)):
            raise ValueError(
                "sensor_id values must be unique within an event"
            )
        return readings
