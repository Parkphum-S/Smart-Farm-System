"""Pydantic schemas for public device API responses."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue


DeviceStatus = Literal["pending", "active", "disabled", "revoked"]


class DeviceZoneAssignment(BaseModel):
    """Explicit zone assignment; null unassigns the device from its zone."""

    model_config = ConfigDict(extra="forbid")

    zone_id: UUID | None


class DeviceResponse(BaseModel):
    """Public device fields; never expose device credentials."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    device_code: str
    device_type: str
    name: str
    status: str
    farm_id: UUID | None
    zone_id: UUID | None
    platform: str | None = None
    protocol: str | None = None
    vendor: str | None = None
    capabilities: dict[str, JsonValue] = Field(default_factory=dict)
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DeviceCreate(BaseModel):
    """Fields accepted when registering a device in a tenant."""

    model_config = ConfigDict(extra="forbid")

    device_code: str | None = Field(default=None, min_length=1, max_length=100)
    device_type: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    farm_id: UUID | None = None
    status: DeviceStatus = "pending"
    platform: str | None = Field(default=None, max_length=64)
    protocol: str | None = Field(default=None, max_length=64)
    vendor: str | None = Field(default=None, max_length=100)
    capabilities: dict[str, JsonValue] = Field(default_factory=dict)


class DeviceUpdate(BaseModel):
    """Editable device metadata; identity and credentials remain immutable."""

    model_config = ConfigDict(extra="forbid")

    device_type: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    farm_id: UUID | None = None
    status: DeviceStatus | None = None
    platform: str | None = Field(default=None, max_length=64)
    protocol: str | None = Field(default=None, max_length=64)
    vendor: str | None = Field(default=None, max_length=100)
    capabilities: dict[str, JsonValue] | None = None
