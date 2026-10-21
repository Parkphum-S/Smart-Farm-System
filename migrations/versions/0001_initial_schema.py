"""Initial Smart Farm core schema.

Revision ID: 0001_initial_schema
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'suspended', 'closed')",
                           name="ck_tenants_status"),
    )

    op.create_table(
        "farms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "id", name="uq_farms_tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name="fk_farms_tenant"),
    )

    op.create_table(
        "devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("device_code", sa.String(100), nullable=False),
        sa.Column("device_type", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "id", name="uq_devices_tenant_id"),
        sa.UniqueConstraint("tenant_id", "device_code",
                            name="uq_devices_tenant_code"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name="fk_devices_tenant"),
        sa.ForeignKeyConstraint(["tenant_id", "farm_id"],
                                ["farms.tenant_id", "farms.id"],
                                name="fk_devices_tenant_farm"),
        sa.CheckConstraint("status IN ('pending', 'active', 'disabled', 'revoked')",
                           name="ck_devices_status"),
    )

    op.create_table(
        "device_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id", "device_id"],
                                ["devices.tenant_id", "devices.id"],
                                name="fk_credentials_tenant_device"),
        sa.UniqueConstraint("secret_hash", name="uq_device_credentials_hash"),
        sa.CheckConstraint("secret_hash ~ '^[0-9a-f]{64}$'",
                           name="ck_device_credentials_hash_format"),
    )

    op.create_table(
        "sensors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sensor_code", sa.String(100), nullable=False),
        sa.Column("measurement_type", sa.String(64), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "device_id", "sensor_code",
                            name="uq_sensors_device_code"),
        sa.UniqueConstraint("tenant_id", "device_id", "id",
                            name="uq_sensors_tenant_device_id"),
        sa.ForeignKeyConstraint(["tenant_id", "device_id"],
                                ["devices.tenant_id", "devices.id"],
                                name="fk_sensors_tenant_device"),
        sa.CheckConstraint("status IN ('active', 'disabled', 'retired')",
                           name="ck_sensors_status"),
    )

    op.create_table(
        "telemetry_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("device_id", "event_id",
                            name="uq_telemetry_device_event"),
        sa.UniqueConstraint("tenant_id", "id", "device_id",
                            name="uq_telemetry_tenant_event_device"),
        sa.ForeignKeyConstraint(["tenant_id", "device_id"],
                                ["devices.tenant_id", "devices.id"],
                                name="fk_telemetry_tenant_device"),
        sa.CheckConstraint("schema_version > 0",
                           name="ck_telemetry_schema_version"),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'",
                           name="ck_telemetry_payload_hash"),
    )
    op.create_index("ix_telemetry_received_at", "telemetry_events", ["received_at"])
    op.create_index("ix_telemetry_device_observed",
                    "telemetry_events", ["device_id", "observed_at"])

    op.create_table(
        "sensor_readings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telemetry_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sensor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("measurement_type", sa.String(64), nullable=False),
        sa.Column("value", sa.Numeric(20, 8), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("quality_status", sa.String(24), nullable=False,
                  server_default="valid"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "telemetry_event_id", "device_id"],
            ["telemetry_events.tenant_id", "telemetry_events.id",
             "telemetry_events.device_id"],
            name="fk_readings_tenant_event_device",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "device_id", "sensor_id"],
            ["sensors.tenant_id", "sensors.device_id", "sensors.id"],
            name="fk_readings_tenant_device_sensor",
        ),
        sa.CheckConstraint(
            "quality_status IN ('valid', 'suspect', 'invalid')",
            name="ck_readings_quality_status",
        ),
    )
    op.create_index("ix_readings_sensor_measured",
                    "sensor_readings", ["sensor_id", "measured_at"])
    op.create_index("ix_readings_tenant_received",
                    "sensor_readings", ["tenant_id", "received_at"])


def downgrade():
    op.drop_table("sensor_readings")
    op.drop_index("ix_telemetry_device_observed", table_name="telemetry_events")
    op.drop_index("ix_telemetry_received_at", table_name="telemetry_events")
    op.drop_table("telemetry_events")
    op.drop_table("sensors")
    op.drop_table("device_credentials")
    op.drop_table("devices")
    op.drop_table("farms")
    op.drop_table("tenants")
