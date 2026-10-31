"""Grant narrowly scoped runtime permissions for device management."""

from alembic import op


revision = "0010_device_management"
down_revision = "0009_farm_images"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "GRANT INSERT "
        "(id, tenant_id, farm_id, device_code, device_type, name, status) "
        "ON TABLE devices TO smartfarm_app"
    )
    op.execute(
        "GRANT UPDATE (farm_id, device_type, name, status, updated_at) "
        "ON TABLE devices TO smartfarm_app"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE UPDATE (farm_id, device_type, name, status, updated_at) "
        "ON TABLE devices FROM smartfarm_app"
    )
    op.execute(
        "REVOKE INSERT "
        "(id, tenant_id, farm_id, device_code, device_type, name, status) "
        "ON TABLE devices FROM smartfarm_app"
    )
