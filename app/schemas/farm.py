"""Pydantic schemas for farm API responses."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FarmResponse(BaseModel):
    """Public fields returned for a farm."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    timezone: str
    created_at: datetime
    updated_at: datetime
