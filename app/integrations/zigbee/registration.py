"""Explicit, tenant-safe Zigbee IEEE address registration."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.integrations.zigbee.discovery import (
    ZigbeePayloadError,
    normalize_ieee_address,
)
from app.security.device_auth import DeviceIdentity


class ZigbeeRegistrationError(ValueError):
    """A Zigbee IEEE address registration is invalid or unavailable."""


def _normalize_address(value: str) -> str:
    try:
        return normalize_ieee_address(value)
    except (ZigbeePayloadError, TypeError, ValueError) as exc:
        raise ZigbeeRegistrationError("invalid Zigbee IEEE address") from exc


def register_device(
    db: Session,
    *,
    tenant_id: UUID,
    device_id: UUID,
    ieee_address: str,
    registration_id: UUID,
) -> UUID:
    """Register an IEEE address to an existing active tenant device.

    The caller owns the transaction. The device and tenant are locked while
    validating eligibility. Database uniqueness prevents duplicate IEEE
    registrations, including registrations across different tenants.
    """
    address = _normalize_address(ieee_address)

    device = (
        db.execute(
            text("""
                SELECT d.id
                FROM devices AS d
                JOIN tenants AS t ON t.id = d.tenant_id
                WHERE d.tenant_id = :tenant_id
                  AND d.id = :device_id
                  AND d.status = 'active'
                  AND t.status = 'active'
                FOR SHARE OF d
            """),
            {
                "tenant_id": tenant_id,
                "device_id": device_id,
            },
        )
        .mappings()
        .first()
    )

    if device is None:
        raise ZigbeeRegistrationError(
            "active tenant device not found"
        )

    row = (
        db.execute(
            text("""
                INSERT INTO zigbee_device_registrations (
                    id,
                    tenant_id,
                    device_id,
                    ieee_address,
                    status
                )
                VALUES (
                    :id,
                    :tenant_id,
                    :device_id,
                    :ieee_address,
                    'active'
                )
                RETURNING id
            """),
            {
                "id": registration_id,
                "tenant_id": tenant_id,
                "device_id": device_id,
                "ieee_address": address,
            },
        )
        .mappings()
        .first()
    )

    if row is None:
        raise ZigbeeRegistrationError(
            "registration could not be created"
        )

    result_id = row["id"]
    return result_id if isinstance(result_id, UUID) else UUID(str(result_id))


def set_registration_status(
    db: Session,
    *,
    tenant_id: UUID,
    registration_id: UUID,
    status: str,
) -> UUID:
    """Enable or disable a registration without deleting its history."""
    if status not in {"active", "disabled"}:
        raise ZigbeeRegistrationError(
            "registration status must be active or disabled"
        )

    row = (
        db.execute(
            text("""
                UPDATE zigbee_device_registrations
                SET status = :status,
                    updated_at = now()
                WHERE tenant_id = :tenant_id
                  AND id = :registration_id
                RETURNING id
            """),
            {
                "tenant_id": tenant_id,
                "registration_id": registration_id,
                "status": status,
            },
        )
        .mappings()
        .first()
    )

    if row is None:
        raise ZigbeeRegistrationError(
            "registration not found for tenant"
        )

    result_id = row["id"]
    return result_id if isinstance(result_id, UUID) else UUID(str(result_id))


def resolve_device_identity(
    db: Session,
    *,
    ieee_address: str,
) -> DeviceIdentity:
    """Resolve an active IEEE registration to its Smart Farm identity."""
    address = _normalize_address(ieee_address)

    row = (
        db.execute(
            text("""
                SELECT
                    r.tenant_id,
                    r.device_id
                FROM zigbee_device_registrations AS r
                JOIN devices AS d
                  ON d.tenant_id = r.tenant_id
                 AND d.id = r.device_id
                JOIN tenants AS t
                  ON t.id = r.tenant_id
                WHERE r.ieee_address = :ieee_address
                  AND r.status = 'active'
                  AND d.status = 'active'
                  AND t.status = 'active'
                FOR SHARE OF r, d
            """),
            {"ieee_address": address},
        )
        .mappings()
        .first()
    )

    if row is None:
        raise ZigbeeRegistrationError(
            "no active Smart Farm registration for Zigbee device"
        )

    tenant_id = row["tenant_id"]
    device_id = row["device_id"]

    if not isinstance(tenant_id, UUID):
        tenant_id = UUID(str(tenant_id))
    if not isinstance(device_id, UUID):
        device_id = UUID(str(device_id))

    return DeviceIdentity(
        tenant_id=tenant_id,
        device_id=device_id,
    )
