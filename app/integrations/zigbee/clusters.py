"""Zigbee cluster value conversion and Zigbee2MQTT state normalization."""

from dataclasses import dataclass
from math import isfinite
from typing import Any


@dataclass(frozen=True)
class NormalizedMeasurement:
    metric: str
    value: float
    unit: str


# Zigbee2MQTT state values are already expressed in display units.
# Do not apply ZCL scaling to these values again.
_STATE_FIELDS = {
    "temperature": ("air_temperature", "Cel"),
    "humidity": ("air_humidity", "%"),
    "soil_moisture": ("soil_moisture", "%"),
}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if not isfinite(result):
        return None
    return result


def normalize_z2m_state(state: dict[str, Any]) -> list[NormalizedMeasurement]:
    """Extract supported measurements from a Zigbee2MQTT state object.

    Diagnostic/control fields such as battery, linkquality, occupancy,
    action and switch state are deliberately not telemetry readings.
    """
    if not isinstance(state, dict):
        raise ValueError("state must be an object")

    readings: list[NormalizedMeasurement] = []

    for field, (metric, unit) in _STATE_FIELDS.items():
        if field not in state:
            continue

        value = _finite_number(state[field])
        if value is None:
            continue

        readings.append(
            NormalizedMeasurement(metric=metric, value=value, unit=unit)
        )

    return readings


def zcl_temperature(raw_value: Any) -> float:
    """Convert raw ZCL Temperature Measurement MeasuredValue to °C."""
    value = _finite_number(raw_value)
    if value is None:
        raise ValueError("invalid ZCL temperature value")
    if value == 0x8000 or value < -27315:
        raise ValueError("invalid ZCL temperature sentinel or range")
    return value / 100.0


def zcl_relative_humidity(raw_value: Any) -> float:
    """Convert raw ZCL Relative Humidity MeasuredValue to percent."""
    value = _finite_number(raw_value)
    if value is None:
        raise ValueError("invalid ZCL humidity value")
    if value == 0xFFFF or not 0 <= value <= 10000:
        raise ValueError("invalid ZCL humidity sentinel or range")
    return value / 100.0


def zcl_occupancy(raw_value: Any) -> bool:
    """Decode bit 0 of the ZCL Occupancy bitmap."""
    value = _finite_number(raw_value)
    if value is None or not value.is_integer() or value < 0:
        raise ValueError("invalid ZCL occupancy bitmap")
    return bool(int(value) & 0x01)
