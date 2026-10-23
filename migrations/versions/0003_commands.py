"""Add tenant-scoped device commands and append-only command events."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_commands"
down_revision = "0002_users_and_auth"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True),
                  nullable=False),
        sa.Column("command_type", sa.String(64), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False),
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result_summary", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "device_id"],
            ["devices.tenant_id", "devices.id"],
            name="fk_commands_tenant_device",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"],
            name="fk_commands_requested_by",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "requested_by_user_id", "idempotency_key",
            name="uq_commands_idempotency",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", "device_id",
            name="uq_commands_tenant_command_device",
        ),
        sa.CheckConstraint(
            "command_type = 'relay.set'",
            name="ck_commands_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'acknowledged', 'succeeded', "
            "'failed', 'expired', 'cancelled')",
            name="ck_commands_status",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_commands_expiry",
        ),
        sa.CheckConstraint(
            "idempotency_key <> '' AND length(idempotency_key) <= 128",
            name="ck_commands_idempotency_key",
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'",
            name="ck_commands_request_hash",
        ),
    )
    op.create_index(
        "ix_commands_device_status_expiry",
        "commands",
        ["tenant_id", "device_id", "status", "expires_at"],
    )
    op.create_index(
        "ix_commands_tenant_created",
        "commands",
        ["tenant_id", "created_at"],
    )

    op.create_table(
        "command_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "device_id"],
            ["devices.tenant_id", "devices.id"],
            name="fk_command_events_tenant_device",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "command_id", "device_id"],
            ["commands.tenant_id", "commands.id", "commands.device_id"],
            name="fk_command_events_command",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"],
            name="fk_command_events_actor_user",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "device_id", "event_id", name="uq_command_events_device_event",
        ),
        sa.CheckConstraint(
            "event_type IN ('created', 'delivered', 'acknowledged', "
            "'succeeded', 'failed', 'expired', 'cancelled')",
            name="ck_command_events_type",
        ),
        sa.CheckConstraint(
            "actor_type IN ('user', 'device', 'system')",
            name="ck_command_events_actor_type",
        ),
        sa.CheckConstraint(
            "event_id <> '' AND length(event_id) <= 128",
            name="ck_command_events_event_id",
        ),
    )
    op.create_index(
        "ix_command_events_command_received",
        "command_events",
        ["tenant_id", "command_id", "received_at"],
    )

    # The application may update command state but cannot modify/delete audit events.
    op.execute(
        "GRANT SELECT, INSERT ON commands TO smartfarm_app"
    )
    op.execute(
        "GRANT UPDATE (status, updated_at, result_summary) "
        "ON commands TO smartfarm_app"
    )
    op.execute(
        "GRANT SELECT, INSERT ON command_events TO smartfarm_app"
    )


def downgrade():
    op.drop_table("command_events")
    op.drop_index("ix_commands_tenant_created", table_name="commands")
    op.drop_index("ix_commands_device_status_expiry", table_name="commands")
    op.drop_table("commands")
