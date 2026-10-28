"""Add tenant- and farm-safe device zone assignment."""

from alembic import op
import sqlalchemy as sa


revision = "0008_device_zone_assignment"
down_revision = "0007_zone_types_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Referenced columns must have a matching unique key for the composite FK.
    op.create_unique_constraint(
        "uq_zones_tenant_farm_id",
        "zones",
        ["tenant_id", "farm_id", "id"],
    )

    op.add_column(
        "devices",
        sa.Column("zone_id", sa.Uuid(), nullable=True),
    )

    op.create_check_constraint(
        "ck_devices_zone_requires_farm",
        "devices",
        "zone_id IS NULL OR farm_id IS NOT NULL",
    )

    op.create_foreign_key(
        "fk_devices_tenant_farm_zone",
        "devices",
        "zones",
        ["tenant_id", "farm_id", "zone_id"],
        ["tenant_id", "farm_id", "id"],
        ondelete="RESTRICT",
    )

    # Keep runtime permissions restricted to the fields needed by assignment.
    op.execute(
        "GRANT UPDATE (zone_id, updated_at) "
        "ON TABLE devices TO smartfarm_app"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE UPDATE (zone_id, updated_at) "
        "ON TABLE devices FROM smartfarm_app"
    )
    op.drop_constraint(
        "fk_devices_tenant_farm_zone", "devices", type_="foreignkey"
    )
    op.drop_constraint(
        "ck_devices_zone_requires_farm", "devices", type_="check"
    )
    op.drop_column("devices", "zone_id")
    op.drop_constraint(
        "uq_zones_tenant_farm_id", "zones", type_="unique"
    )
