"""Add explicit Zigbee IEEE address to Smart Farm device registrations."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0013_zigbee_device_registrations"
down_revision = "0012_sensor_registration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "zigbee_device_registrations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "ieee_address",
            sa.String(16),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(24),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "device_id"],
            ["devices.tenant_id", "devices.id"],
            name="fk_zigbee_registration_tenant_device",
        ),
        sa.UniqueConstraint(
            "ieee_address",
            name="uq_zigbee_registration_ieee",
        ),
        sa.CheckConstraint(
            "ieee_address ~ '^[0-9a-f]{16}$'",
            name="ck_zigbee_registration_ieee_format",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_zigbee_registration_status",
        ),
    )

    op.create_index(
        "ix_zigbee_registration_tenant_device",
        "zigbee_device_registrations",
        ["tenant_id", "device_id"],
    )

    op.execute(
        "GRANT SELECT ON TABLE "
        "zigbee_device_registrations TO smartfarm_app"
    )
    op.execute(
        "GRANT INSERT "
        "(id, tenant_id, device_id, ieee_address, status) "
        "ON TABLE zigbee_device_registrations TO smartfarm_app"
    )
    op.execute(
        "GRANT UPDATE (status, updated_at) "
        "ON TABLE zigbee_device_registrations TO smartfarm_app"
    )
    op.execute(
        "REVOKE DELETE ON TABLE "
        "zigbee_device_registrations FROM smartfarm_app"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE UPDATE (status, updated_at) "
        "ON TABLE zigbee_device_registrations FROM smartfarm_app"
    )
    op.execute(
        "REVOKE INSERT "
        "(id, tenant_id, device_id, ieee_address, status) "
        "ON TABLE zigbee_device_registrations FROM smartfarm_app"
    )
    op.execute(
        "REVOKE SELECT ON TABLE "
        "zigbee_device_registrations FROM smartfarm_app"
    )

    op.drop_index(
        "ix_zigbee_registration_tenant_device",
        table_name="zigbee_device_registrations",
    )
    op.drop_table("zigbee_device_registrations")
