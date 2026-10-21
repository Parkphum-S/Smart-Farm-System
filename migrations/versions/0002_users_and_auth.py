"""Add users, credentials, memberships and sessions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_users_and_auth"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'disabled')",
                           name="ck_users_status"),
        sa.CheckConstraint("email = lower(btrim(email)) AND length(email) > 3",
                           name="ck_users_email_normalized"),
    )
    op.create_index("uq_users_email_lower", "users",
                    [sa.text("lower(email)")], unique=True)

    op.create_table(
        "user_credentials",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"],
                                name="fk_user_credentials_user",
                                ondelete="RESTRICT"),
        sa.CheckConstraint("failed_attempts >= 0",
                           name="ck_user_credentials_attempts"),
        sa.CheckConstraint("length(password_hash) > 0",
                           name="ck_user_credentials_hash"),
    )

    op.create_table(
        "tenant_memberships",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("tenant_id", "user_id",
                                name="pk_tenant_memberships"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name="fk_memberships_tenant",
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"],
                                name="fk_memberships_user",
                                ondelete="RESTRICT"),
        sa.CheckConstraint("role IN ('owner', 'operator', 'viewer')",
                           name="ck_memberships_role"),
        sa.CheckConstraint("status IN ('active', 'suspended')",
                           name="ck_memberships_status"),
    )
    op.create_index("ix_memberships_user", "tenant_memberships", ["user_id"])

    op.create_table(
        "user_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"],
                                name="fk_sessions_user",
                                ondelete="RESTRICT"),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'",
                           name="ck_sessions_token_hash"),
    )
    op.create_index("ix_sessions_user", "user_sessions", ["user_id"])

    op.execute("GRANT SELECT ON users, tenant_memberships TO smartfarm_app")
    op.execute("GRANT SELECT ON user_credentials TO smartfarm_app")
    op.execute(
        "GRANT UPDATE (failed_attempts, locked_until) "
        "ON user_credentials TO smartfarm_app"
    )
    op.execute("GRANT SELECT, INSERT ON user_sessions TO smartfarm_app")
    op.execute(
        "GRANT UPDATE (last_used_at, revoked_at) "
        "ON user_sessions TO smartfarm_app"
    )


def downgrade():
    op.drop_table("user_sessions")
    op.drop_table("tenant_memberships")
    op.drop_table("user_credentials")
    op.drop_table("users")
