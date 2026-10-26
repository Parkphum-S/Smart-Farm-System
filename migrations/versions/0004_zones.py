"""Add tenant-scoped farm zones."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_zones"
down_revision = "0003_commands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "zones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "id", name="uq_zones_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "farm_id", "name",
            name="uq_zones_tenant_farm_name",
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0", name="ck_zones_name_not_blank"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')", name="ck_zones_status"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"],
            ["farms.tenant_id", "farms.id"],
            name="fk_zones_tenant_farm",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_zones_tenant_farm_name", "zones",
        ["tenant_id", "farm_id", "name"],
    )
    op.execute(
        "GRANT SELECT, INSERT, DELETE ON TABLE zones TO smartfarm_app"
    )
    op.execute(
        "GRANT UPDATE (name, description, status, updated_at) "
        "ON TABLE zones TO smartfarm_app"
    )


def downgrade() -> None:
    op.execute("REVOKE ALL PRIVILEGES ON TABLE zones FROM smartfarm_app")
    op.drop_index("ix_zones_tenant_farm_name", table_name="zones")
    op.drop_table("zones")
