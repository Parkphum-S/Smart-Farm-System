"""Grant runtime permission to update device last_seen_at.

Revision ID: 0014_device_last_seen_perm
Revises: 0012_sensor_registration
"""

from alembic import op


revision = "0014_device_last_seen_perm"
down_revision = "0012_sensor_registration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "GRANT UPDATE (last_seen_at) "
        "ON TABLE devices TO smartfarm_app"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE UPDATE (last_seen_at) "
        "ON TABLE devices FROM smartfarm_app"
    )
