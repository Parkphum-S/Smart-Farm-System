"""Add zone type and category-specific details."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_zone_types_details"
down_revision = "0006_zone_crud_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "zones",
        sa.Column(
            "zone_type",
            sa.String(24),
            nullable=False,
            server_default=sa.text("'plant'"),
        ),
    )
    op.add_column(
        "zones",
        sa.Column(
            "category_details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_zones_zone_type",
        "zones",
        "zone_type IN ('plant', 'livestock', 'fish_pond', "
        "'mushroom', 'cctv', 'lighting')",
    )
    op.create_check_constraint(
        "ck_zones_category_details_object",
        "zones",
        "jsonb_typeof(category_details) = 'object'",
    )
    op.execute(
        "GRANT UPDATE (zone_type, category_details) "
        "ON TABLE zones TO smartfarm_app"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE UPDATE (zone_type, category_details) "
        "ON TABLE zones FROM smartfarm_app"
    )
    op.drop_constraint(
        "ck_zones_category_details_object", "zones", type_="check"
    )
    op.drop_constraint("ck_zones_zone_type", "zones", type_="check")
    op.drop_column("zones", "category_details")
    op.drop_column("zones", "zone_type")
