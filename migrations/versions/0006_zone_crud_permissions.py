"""Grant runtime UPDATE permissions on supported zone fields."""

from alembic import op


revision = "0006_zone_crud_permissions"
down_revision = "0005_farm_crud_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "GRANT UPDATE (name, description, status, updated_at) "
        "ON TABLE zones TO smartfarm_app"
    )


def downgrade() -> None:
    # Migration 0004_zones already grants these column-level UPDATE
    # privileges. PostgreSQL cannot distinguish duplicate grants by
    # migration, so revoking here would remove privileges owned by 0004.
    pass
