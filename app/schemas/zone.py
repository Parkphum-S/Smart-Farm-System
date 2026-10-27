from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    BaseModel, ConfigDict, Field, ValidationInfo,
    field_validator, model_validator,
)


ZoneType = Literal[
    "plant", "livestock", "fish_pond", "mushroom", "cctv", "lighting"
]

_ZONE_DETAIL_FIELDS: dict[str, set[str]] = {
    "plant": {"crop_name", "crop_type"},
    "livestock": {"species"},
    "fish_pond": {"fish_species"},
    "mushroom": {"mushroom_type", "variety"},
    "cctv": {"camera_name", "camera_id", "stream_url"},
    "lighting": {"switch_count", "relay_mapping"},
}


def validate_zone_category_details(
    zone_type: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    """Validate category-specific zone details without accepting unknown fields."""
    if zone_type not in _ZONE_DETAIL_FIELDS:
        raise ValueError("Unsupported zone type")
    if not isinstance(details, dict):
        raise ValueError("Category details must be an object")

    unknown = set(details) - _ZONE_DETAIL_FIELDS[zone_type]
    if unknown:
        raise ValueError(
            "Unsupported category detail fields: " + ", ".join(sorted(unknown))
        )

    string_fields = _ZONE_DETAIL_FIELDS[zone_type] - {
        "switch_count", "relay_mapping"
    }
    for key in string_fields:
        if key not in details:
            continue
        value = details[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string")
        details[key] = value.strip()

    if "stream_url" in details:
        parsed = urlsplit(details["stream_url"])
        if parsed.scheme not in {"http", "https", "rtsp", "rtsps"} or not parsed.netloc:
            raise ValueError("stream_url must be an absolute HTTP(S) or RTSP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "stream_url must not contain credentials, query parameters, or fragments"
            )

    if "switch_count" in details:
        count = details["switch_count"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError("switch_count must be a positive integer")

    if "relay_mapping" in details:
        mapping = details["relay_mapping"]
        if not isinstance(mapping, dict):
            raise ValueError("relay_mapping must be an object")
        for switch, relay in mapping.items():
            if not isinstance(switch, str) or not switch.strip():
                raise ValueError("relay_mapping keys must be non-empty strings")
            if isinstance(relay, bool) or not isinstance(relay, int) or relay < 1:
                raise ValueError("relay_mapping values must be positive integers")
        count = details.get("switch_count")
        if count is not None and len(mapping) > count:
            raise ValueError("relay_mapping cannot contain more entries than switch_count")

    return details


class ZoneCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    status: Literal["active", "disabled"] = "active"
    zone_type: ZoneType = "plant"
    category_details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Zone name must not be blank")
        return value

    @field_validator("category_details")
    @classmethod
    def validate_category_details(
        cls,
        value: dict[str, Any],
        info: ValidationInfo,
    ) -> dict[str, Any]:
        zone_type = info.data.get("zone_type", "plant")
        return validate_zone_category_details(zone_type, value)


class ZoneUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    status: Literal["active", "disabled"] | None = None
    zone_type: ZoneType | None = None
    category_details: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Zone name must not be blank")
        return value

    @model_validator(mode="after")
    def validate_type_and_details_together(self):
        if "zone_type" in self.model_fields_set or "category_details" in self.model_fields_set:
            if "zone_type" not in self.model_fields_set:
                raise ValueError(
                    "zone_type is required when category_details is updated"
                )
            if "category_details" not in self.model_fields_set:
                raise ValueError(
                    "category_details is required when zone_type is updated"
                )
            if self.category_details is None:
                raise ValueError(
                    "category_details must not be null when updating zone type/details"
                )
            validate_zone_category_details(
                self.zone_type,
                self.category_details,
            )
        return self


class ZoneResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    farm_id: UUID
    name: str
    description: str | None
    status: str
    zone_type: ZoneType
    category_details: dict[str, Any]
    created_at: datetime
    updated_at: datetime
