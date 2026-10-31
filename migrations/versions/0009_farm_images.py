"""Add private image storage to farms."""

from alembic import op
import sqlalchemy as sa

revision = "0009_farm_images"
down_revision = "0008_device_zone_assignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "farms",
        sa.Column("image_content", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "farms",
        sa.Column("image_content_type", sa.String(32), nullable=True),
    )
    op.create_check_constraint(
        "ck_farms_image_content_type",
        "farms",
        "image_content_type IS NULL OR "
        "image_content_type IN ('image/jpeg', 'image/png', 'image/webp')",
    )
    op.execute(
        "GRANT UPDATE (image_content, image_content_type) "
        "ON TABLE farms TO smartfarm_app"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE UPDATE (image_content, image_content_type) "
        "ON TABLE farms FROM smartfarm_app"
    )
    op.drop_constraint(
        "ck_farms_image_content_type", "farms", type_="check"
    )
    op.drop_column("farms", "image_content_type")
    op.drop_column("farms", "image_content")
