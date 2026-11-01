"""Pydantic schemas for tenant-scoped sensor registration."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


SensorStatus = Literal["active", "disabled", "retired"]


class SensorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensor_code: str | None = Field(default=None, min_length=1, max_length=100)
    measurement_type: str = Field(min_length=1, max_length=64)
    unit: str = Field(min_length=1, max_length=32)

    @field_validator("sensor_code")
    @classmethod
    def strip_optional_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Value must not be blank")
        return value

    @field_validator("measurement_type", "unit")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value must not be blank")
        return value


class SensorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measurement_type: str | None = Field(default=None, min_length=1, max_length=64)
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    status: SensorStatus | None = None

    @field_validator("measurement_type", "unit")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Value must not be blank")
        return value


class SensorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    device_id: UUID
    sensor_code: str
    measurement_type: str
    unit: str
    status: SensorStatus
    created_at: datetime
