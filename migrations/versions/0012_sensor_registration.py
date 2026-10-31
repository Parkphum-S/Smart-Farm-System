"""Add sensor registration permissions and protocol endpoint mappings."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012_sensor_registration"
down_revision = "0011_device_platform_integration"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sensor_endpoint_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sensor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("adapter_type", sa.String(64), nullable=False),
        sa.Column("endpoint_key", sa.String(255), nullable=False),
        sa.Column(
            "mapping_status",
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
            ["tenant_id", "device_id", "sensor_id"],
            ["sensors.tenant_id", "sensors.device_id", "sensors.id"],
            name="fk_endpoint_mappings_tenant_device_sensor",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "device_id",
            "adapter_type",
            "endpoint_key",
            name="uq_endpoint_mappings_device_endpoint",
        ),
        sa.CheckConstraint(
            "mapping_status IN ('active', 'disabled')",
            name="ck_endpoint_mappings_status",
        ),
    )

    op.create_index(
        "ix_endpoint_mappings_tenant_device_sensor",
        "sensor_endpoint_mappings",
        ["tenant_id", "device_id", "sensor_id"],
    )

    op.execute(
        "GRANT INSERT "
        "(id, tenant_id, device_id, sensor_code, measurement_type, unit, status) "
        "ON TABLE sensors TO smartfarm_app"
    )
    op.execute("GRANT SELECT ON TABLE sensors TO smartfarm_app")
    op.execute(
        "GRANT UPDATE (measurement_type, unit, status) "
        "ON TABLE sensors TO smartfarm_app"
    )
    op.execute("REVOKE DELETE ON TABLE sensors FROM smartfarm_app")

    op.execute(
        "GRANT SELECT ON TABLE sensor_endpoint_mappings TO smartfarm_app"
    )
    op.execute(
        "GRANT INSERT "
        "(id, tenant_id, device_id, sensor_id, adapter_type, endpoint_key, mapping_status) "
        "ON TABLE sensor_endpoint_mappings TO smartfarm_app"
    )
    op.execute(
        "GRANT UPDATE "
        "(sensor_id, adapter_type, endpoint_key, mapping_status, updated_at) "
        "ON TABLE sensor_endpoint_mappings TO smartfarm_app"
    )
    op.execute(
        "REVOKE DELETE ON TABLE sensor_endpoint_mappings FROM smartfarm_app"
    )


def downgrade():
    op.execute(
        "REVOKE UPDATE "
        "(sensor_id, adapter_type, endpoint_key, mapping_status, updated_at) "
        "ON TABLE sensor_endpoint_mappings FROM smartfarm_app"
    )
    op.execute(
        "REVOKE INSERT "
        "(id, tenant_id, device_id, sensor_id, adapter_type, endpoint_key, mapping_status) "
        "ON TABLE sensor_endpoint_mappings FROM smartfarm_app"
    )
    op.execute(
        "REVOKE SELECT ON TABLE sensor_endpoint_mappings FROM smartfarm_app"
    )

    op.drop_index(
        "ix_endpoint_mappings_tenant_device_sensor",
        table_name="sensor_endpoint_mappings",
    )
    op.drop_table("sensor_endpoint_mappings")

    op.execute("REVOKE SELECT ON TABLE sensors FROM smartfarm_app")
    op.execute(
        "REVOKE UPDATE (measurement_type, unit, status) "
        "ON TABLE sensors FROM smartfarm_app"
    )
    op.execute(
        "REVOKE INSERT "
        "(id, tenant_id, device_id, sensor_code, measurement_type, unit, status) "
        "ON TABLE sensors FROM smartfarm_app"
    )
