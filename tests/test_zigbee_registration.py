from uuid import UUID, uuid4
from unittest.mock import Mock

import pytest

from app.integrations.zigbee import registration
from app.integrations.zigbee.registration import (
    ZigbeeRegistrationError,
    register_device,
    resolve_device_identity,
    set_registration_status,
)
from app.security.device_auth import DeviceIdentity


TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
DEVICE_ID = UUID("22222222-2222-4222-8222-222222222222")
REGISTRATION_ID = UUID("33333333-3333-4333-8333-333333333333")
IEEE = "00124b0000000001"


class FakeResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class FakeDB:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def execute(self, statement, params):
        self.calls.append((str(statement), params))
        row = self.rows.pop(0) if self.rows else None
        return FakeResult(row)


def test_registers_ieee_to_active_device():
    db = FakeDB([
        {"id": DEVICE_ID},
        {"id": REGISTRATION_ID},
    ])

    result = register_device(
        db,
        tenant_id=TENANT_ID,
        device_id=DEVICE_ID,
        ieee_address="0x00124B0000000001",
        registration_id=REGISTRATION_ID,
    )

    assert result == REGISTRATION_ID
    assert len(db.calls) == 2

    eligibility_sql, eligibility_params = db.calls[0]
    assert "d.status = 'active'" in eligibility_sql
    assert "t.status = 'active'" in eligibility_sql
    assert "FOR SHARE OF d" in eligibility_sql
    assert eligibility_params == {
        "tenant_id": TENANT_ID,
        "device_id": DEVICE_ID,
    }

    insert_sql, insert_params = db.calls[1]
    assert "INSERT INTO zigbee_device_registrations" in insert_sql
    assert insert_params["ieee_address"] == IEEE
    assert insert_params["tenant_id"] == TENANT_ID
    assert insert_params["device_id"] == DEVICE_ID


def test_registration_rejects_inactive_or_missing_device():
    db = FakeDB([None])

    with pytest.raises(
        ZigbeeRegistrationError,
        match="active tenant device not found",
    ):
        register_device(
            db,
            tenant_id=TENANT_ID,
            device_id=DEVICE_ID,
            ieee_address=IEEE,
            registration_id=REGISTRATION_ID,
        )

    assert len(db.calls) == 1


def test_registration_rejects_invalid_ieee_before_database_access():
    db = FakeDB([])

    with pytest.raises(ZigbeeRegistrationError, match="invalid"):
        register_device(
            db,
            tenant_id=TENANT_ID,
            device_id=DEVICE_ID,
            ieee_address="not-an-ieee",
            registration_id=REGISTRATION_ID,
        )

    assert db.calls == []


@pytest.mark.parametrize("status", ["active", "disabled"])
def test_updates_registration_status(status):
    db = FakeDB([{"id": REGISTRATION_ID}])

    result = set_registration_status(
        db,
        tenant_id=TENANT_ID,
        registration_id=REGISTRATION_ID,
        status=status,
    )

    assert result == REGISTRATION_ID
    sql, params = db.calls[0]
    assert "UPDATE zigbee_device_registrations" in sql
    assert "updated_at = now()" in sql
    assert params == {
        "tenant_id": TENANT_ID,
        "registration_id": REGISTRATION_ID,
        "status": status,
    }


def test_rejects_invalid_registration_status_before_database_access():
    db = FakeDB([])

    with pytest.raises(ZigbeeRegistrationError, match="status must be"):
        set_registration_status(
            db,
            tenant_id=TENANT_ID,
            registration_id=REGISTRATION_ID,
            status="revoked",
        )

    assert db.calls == []


def test_status_update_is_tenant_scoped():
    db = FakeDB([None])

    with pytest.raises(ZigbeeRegistrationError, match="not found"):
        set_registration_status(
            db,
            tenant_id=TENANT_ID,
            registration_id=REGISTRATION_ID,
            status="disabled",
        )

    assert "WHERE tenant_id = :tenant_id" in db.calls[0][0]


def test_resolves_active_registration_to_device_identity():
    db = FakeDB([{
        "tenant_id": TENANT_ID,
        "device_id": DEVICE_ID,
    }])

    identity = resolve_device_identity(
        db,
        ieee_address="0x00124B0000000001",
    )

    assert identity == DeviceIdentity(
        tenant_id=TENANT_ID,
        device_id=DEVICE_ID,
    )

    sql, params = db.calls[0]
    assert "r.status = 'active'" in sql
    assert "d.status = 'active'" in sql
    assert "t.status = 'active'" in sql
    assert "FOR SHARE OF r, d" in sql
    assert params == {"ieee_address": IEEE}


def test_unregistered_or_inactive_ieee_is_rejected():
    db = FakeDB([None])

    with pytest.raises(
        ZigbeeRegistrationError,
        match="no active Smart Farm registration",
    ):
        resolve_device_identity(db, ieee_address=IEEE)


def test_resolve_rejects_invalid_ieee_before_database_access():
    db = FakeDB([])

    with pytest.raises(ZigbeeRegistrationError, match="invalid"):
        resolve_device_identity(db, ieee_address="bad")

    assert db.calls == []


def test_resolve_accepts_database_uuid_strings():
    db = FakeDB([{
        "tenant_id": str(TENANT_ID),
        "device_id": str(DEVICE_ID),
    }])

    identity = resolve_device_identity(db, ieee_address=IEEE)

    assert identity.tenant_id == TENANT_ID
    assert identity.device_id == DEVICE_ID
