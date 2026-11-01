"""Pydantic schemas for farm API requests and responses."""
from datetime import datetime
from math import isfinite
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel, ConfigDict, Field, field_validator, model_validator
)


def _validate_coordinates(latitude, longitude):
    if (latitude is None) != (longitude is None):
        raise ValueError("Latitude and longitude must be provided together")
    if latitude is not None:
        if not isfinite(latitude) or not -90 <= latitude <= 90:
            raise ValueError("Latitude must be between -90 and 90")
        if not isfinite(longitude) or not -180 <= longitude <= 180:
            raise ValueError("Longitude must be between -180 and 180")


class FarmCreate(BaseModel):
    """Fields required to create a farm."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    latitude: float | None = Field(default=None, allow_inf_nan=False)
    longitude: float | None = Field(default=None, allow_inf_nan=False)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Farm name must not be blank")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Timezone must not be blank")
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Invalid timezone") from None
        return value

    @model_validator(mode="after")
    def validate_coordinate_pair(self):
        _validate_coordinates(self.latitude, self.longitude)
        return self


class FarmUpdate(BaseModel):
    """Fields that may be updated on a farm."""
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    latitude: float | None = Field(default=None, allow_inf_nan=False)
    longitude: float | None = Field(default=None, allow_inf_nan=False)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Farm name must not be blank")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Timezone must not be blank")
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Invalid timezone") from None
        return value

    @model_validator(mode="after")
    def validate_coordinate_pair(self):
        fields = self.model_fields_set
        if ("latitude" in fields) != ("longitude" in fields):
            raise ValueError("Latitude and longitude must be updated together")
        if "latitude" in fields:
            _validate_coordinates(self.latitude, self.longitude)
        return self


class FarmResponse(BaseModel):
    """Public fields returned for a farm."""
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    timezone: str
    latitude: float | None
    longitude: float | None
    created_at: datetime
    updated_at: datetime
