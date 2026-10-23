"""Validated request and response models for device commands."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RelayParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relay: Annotated[int, Field(ge=1, le=4)]
    state: Literal["on", "off"]


class CommandCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command_type: Literal["relay.set"]
    parameters: RelayParameters
    idempotency_key: Annotated[str, Field(min_length=1, max_length=128)]
    expires_in_seconds: Annotated[int, Field(ge=5, le=300)] = 60
    correlation_id: UUID | None = None

    @field_validator("idempotency_key")
    @classmethod
    def key_must_not_be_whitespace(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("idempotency_key must not be blank")
        return value


class CommandResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    device_id: UUID
    command_type: str
    parameters: dict
    status: str
    created_at: datetime
    expires_at: datetime
    updated_at: datetime
    correlation_id: UUID | None = None
    result_summary: dict | None = None


class CommandEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: Annotated[str, Field(min_length=1, max_length=128)]
    event_type: Literal["acknowledged", "succeeded", "failed"]
    occurred_at: datetime | None = None
    details: dict = Field(default_factory=dict)

    @field_validator("event_id")
    @classmethod
    def event_id_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("event_id must not be blank")
        return value

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_must_have_timezone(cls, value):
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("occurred_at must include a timezone")
        return value
