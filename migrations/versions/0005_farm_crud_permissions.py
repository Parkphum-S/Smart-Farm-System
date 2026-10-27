"""Grant runtime CRUD permissions on farms."""

from alembic import op


revision = "0005_farm_crud_permissions"
down_revision = "0004_zones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SELECT is already available to the runtime role.
    # Keep writes limited to the fields used by the Farm CRUD API.
    op.execute(
        "GRANT INSERT, DELETE ON TABLE farms TO smartfarm_app"
    )
    op.execute(
        "GRANT UPDATE (name, timezone, updated_at) "
        "ON TABLE farms TO smartfarm_app"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE UPDATE (name, timezone, updated_at) "
        "ON TABLE farms FROM smartfarm_app"
    )
    op.execute(
        "REVOKE INSERT, DELETE ON TABLE farms FROM smartfarm_app"
    )
