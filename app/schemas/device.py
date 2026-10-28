"""Pydantic schemas for public device API responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime
