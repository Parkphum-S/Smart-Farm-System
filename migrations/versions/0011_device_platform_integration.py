"""Add extensible platform and capability metadata to devices."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011_device_platform_integration"
down_revision = "0010_device_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("platform", sa.String(64), nullable=True))
    op.add_column("devices", sa.Column("protocol", sa.String(64), nullable=True))
    op.add_column("devices", sa.Column("vendor", sa.String(100), nullable=True))
    op.add_column(
        "devices",
        sa.Column(
            "capabilities",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.execute(
        "GRANT INSERT (platform, protocol, vendor, capabilities) "
        "ON TABLE devices TO smartfarm_app"
    )
    op.execute(
        "GRANT UPDATE (platform, protocol, vendor, capabilities) "
        "ON TABLE devices TO smartfarm_app"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE UPDATE (platform, protocol, vendor, capabilities) "
        "ON TABLE devices FROM smartfarm_app"
    )
    op.execute(
        "REVOKE INSERT (platform, protocol, vendor, capabilities) "
        "ON TABLE devices FROM smartfarm_app"
    )
    op.drop_column("devices", "capabilities")
    op.drop_column("devices", "vendor")
    op.drop_column("devices", "protocol")
    op.drop_column("devices", "platform")
