from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TelemetryReadingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    sensor_id: UUID
    sensor_code: str
    device_id: UUID
    device_name: str
    metric: str
    value: float
    unit: str
    quality_status: str
    measured_at: datetime
    received_at: datetime
