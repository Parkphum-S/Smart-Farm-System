"""Pydantic schemas for public device API responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DeviceResponse(BaseModel):
    """Public device fields; never expose device credentials."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    device_code: str
    device_type: str
    name: str
    status: str
    farm_id: UUID | None
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime
