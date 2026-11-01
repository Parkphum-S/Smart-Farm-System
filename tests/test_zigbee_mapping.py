from uuid import UUID
from unittest.mock import Mock

import pytest

from app.integrations.zigbee.mapping import (
    ZigbeeMappingError,
    ZigbeeSensorBinding,
    resolve_sensor_bindings,
)


TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
DEVICE_ID = UUID("22222222-2222-4222-8222-222222222222")
SENSOR_ID = UUID("33333333-3333-4333-8333-333333333333")


class FakeResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return self.row


class FakeDB:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def execute(self, statement, params):
        self.calls.append((statement, params))
        row = self.rows.pop(0) if self.rows else None
        return FakeResult(row)


def binding():
    return ZigbeeSensorBinding(
        metric="air_temperature",
        unit="Cel",
        endpoint_key="ieee:00124b0024c12345/endpoint:1/cluster:0402/attribute:0000",
    )


def test_resolves_active_sensor_mapping():
    db = FakeDB([{
        "sensor_id": SENSOR_ID,
        "measurement_type": "air_temperature",
        "unit": "Cel",
    }])

    result = resolve_sensor_bindings(
        db,
        tenant_id=TENANT_ID,
        device_id=DEVICE_ID,
        bindings=[binding()],
    )

    assert result == {"air_temperature": SENSOR_ID}
    assert len(db.calls) == 1
    assert db.calls[0][1] == {
        "tenant_id": TENANT_ID,
        "device_id": DEVICE_ID,
        "endpoint_key": binding().endpoint_key,
    }

    sql = str(db.calls[0][0])
    assert "m.adapter_type = 'zigbee'" in sql
    assert "m.mapping_status = 'active'" in sql
    assert "s.status = 'active'" in sql
    assert "m.tenant_id = :tenant_id" in sql
    assert "m.device_id = :device_id" in sql


def test_accepts_sensor_id_returned_as_string():
    db = FakeDB([{
        "sensor_id": str(SENSOR_ID),
        "measurement_type": "air_temperature",
        "unit": "Cel",
    }])

    result = resolve_sensor_bindings(
        db,
        tenant_id=TENANT_ID,
        device_id=DEVICE_ID,
        bindings=[binding()],
    )

    assert result["air_temperature"] == SENSOR_ID


def test_missing_mapping_is_rejected():
    db = FakeDB([None])

    with pytest.raises(ZigbeeMappingError, match="No active"):
        resolve_sensor_bindings(
            db,
            tenant_id=TENANT_ID,
            device_id=DEVICE_ID,
            bindings=[binding()],
        )


@pytest.mark.parametrize(
    "row",
    [
        {
            "sensor_id": SENSOR_ID,
            "measurement_type": "humidity",
            "unit": "Cel",
        },
        {
            "sensor_id": SENSOR_ID,
            "measurement_type": "air_temperature",
            "unit": "%",
        },
    ],
)
def test_metric_or_unit_mismatch_is_rejected(row):
    db = FakeDB([row])

    with pytest.raises(ZigbeeMappingError, match="mismatch"):
        resolve_sensor_bindings(
            db,
            tenant_id=TENANT_ID,
            device_id=DEVICE_ID,
            bindings=[binding()],
        )


def test_empty_bindings_are_rejected():
    with pytest.raises(ZigbeeMappingError, match="at least one"):
        resolve_sensor_bindings(
            Mock(),
            tenant_id=TENANT_ID,
            device_id=DEVICE_ID,
            bindings=[],
        )


def test_duplicate_metric_is_rejected_before_database_access():
    db = FakeDB([])

    with pytest.raises(ZigbeeMappingError, match="duplicate metric"):
        resolve_sensor_bindings(
            db,
            tenant_id=TENANT_ID,
            device_id=DEVICE_ID,
            bindings=[binding(), binding()],
        )

    assert db.calls == []


def test_duplicate_endpoint_key_is_rejected():
    db = FakeDB([])
    first = binding()
    second = ZigbeeSensorBinding(
        metric="air_humidity",
        unit="%",
        endpoint_key=first.endpoint_key,
    )

    with pytest.raises(ZigbeeMappingError, match="duplicate endpoint_key"):
        resolve_sensor_bindings(
            db,
            tenant_id=TENANT_ID,
            device_id=DEVICE_ID,
            bindings=[first, second],
        )

    assert db.calls == []


def test_invalid_endpoint_key_is_rejected():
    db = FakeDB([])
    invalid = ZigbeeSensorBinding(
        metric="air_temperature",
        unit="Cel",
        endpoint_key="x" * 256,
    )

    with pytest.raises(ZigbeeMappingError, match="invalid endpoint_key"):
        resolve_sensor_bindings(
            db,
            tenant_id=TENANT_ID,
            device_id=DEVICE_ID,
            bindings=[invalid],
        )

    assert db.calls == []



def test_loads_active_sensor_bindings_from_database():
    rows = [
        {
            "endpoint_key": "endpoint-temperature",
            "measurement_type": "air_temperature",
            "unit": "Cel",
        },
        {
            "endpoint_key": "endpoint-humidity",
            "measurement_type": "air_humidity",
            "unit": "%",
        },
    ]
    db = FakeDB([rows])

    from app.integrations.zigbee.mapping import load_sensor_bindings

    result = load_sensor_bindings(
        db,
        tenant_id=TENANT_ID,
        device_id=DEVICE_ID,
    )

    assert result == [
        ZigbeeSensorBinding("air_temperature", "Cel", "endpoint-temperature"),
        ZigbeeSensorBinding("air_humidity", "%", "endpoint-humidity"),
    ]
    assert len(db.calls) == 1
    sql = str(db.calls[0][0])
    assert "m.adapter_type = 'zigbee'" in sql
    assert "m.mapping_status = 'active'" in sql
    assert "s.status = 'active'" in sql
    assert "FOR SHARE OF m, s" in sql


def test_load_sensor_bindings_rejects_duplicate_metric():
    db = FakeDB([[
        {
            "endpoint_key": "endpoint-1",
            "measurement_type": "air_temperature",
            "unit": "Cel",
        },
        {
            "endpoint_key": "endpoint-2",
            "measurement_type": "air_temperature",
            "unit": "Cel",
        },
    ]])

    from app.integrations.zigbee.mapping import load_sensor_bindings

    with pytest.raises(ZigbeeMappingError, match="ambiguous"):
        load_sensor_bindings(
            db,
            tenant_id=TENANT_ID,
            device_id=DEVICE_ID,
        )


def test_load_sensor_bindings_rejects_empty_result():
    db = FakeDB([[]])

    from app.integrations.zigbee.mapping import load_sensor_bindings

    with pytest.raises(ZigbeeMappingError, match="no active"):
        load_sensor_bindings(
            db,
            tenant_id=TENANT_ID,
            device_id=DEVICE_ID,
        )
