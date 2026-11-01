"""Schemas for tenant-scoped sensor endpoint mappings."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


MappingStatus = Literal["active", "disabled"]


class SensorMappingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensor_id: UUID
    adapter_type: str = Field(min_length=1, max_length=64)
    endpoint_key: str = Field(min_length=1, max_length=255)
    mapping_status: MappingStatus = "active"

    @field_validator("adapter_type")
    @classmethod
    def normalize_adapter_type(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            raise ValueError("adapter_type must not be blank")
        return value

    @field_validator("endpoint_key")
    @classmethod
    def strip_endpoint_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("endpoint_key must not be blank")
        return value


class SensorMappingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensor_id: UUID | None = None
    adapter_type: str | None = Field(default=None, min_length=1, max_length=64)
    endpoint_key: str | None = Field(default=None, min_length=1, max_length=255)
    mapping_status: MappingStatus | None = None

    @field_validator("adapter_type")
    @classmethod
    def normalize_adapter_type(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip().lower()
        if not value:
            raise ValueError("adapter_type must not be blank")
        return value

    @field_validator("endpoint_key")
    @classmethod
    def strip_endpoint_key(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("endpoint_key must not be blank")
        return value


class SensorMappingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    device_id: UUID
    sensor_id: UUID
    adapter_type: str
    endpoint_key: str
    mapping_status: MappingStatus
    created_at: datetime
    updated_at: datetime
