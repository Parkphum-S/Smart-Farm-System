"""Add farm coordinates for weather lookup.

Revision ID: 0015_farm_weather_coordinates
Revises: 0014_device_last_seen_perm
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_farm_weather_coordinates"
down_revision = "0014_device_last_seen_perm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("farms", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("farms", sa.Column("longitude", sa.Float(), nullable=True))
    op.create_check_constraint(
        "ck_farms_latitude_range",
        "farms",
        "latitude IS NULL OR latitude BETWEEN -90 AND 90",
    )
    op.create_check_constraint(
        "ck_farms_longitude_range",
        "farms",
        "longitude IS NULL OR longitude BETWEEN -180 AND 180",
    )
    op.create_check_constraint(
        "ck_farms_coordinates_pair",
        "farms",
        "(latitude IS NULL) = (longitude IS NULL)",
    )
    op.execute(
        "GRANT UPDATE (latitude, longitude) "
        "ON TABLE farms TO smartfarm_app"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE UPDATE (latitude, longitude) "
        "ON TABLE farms FROM smartfarm_app"
    )
    op.drop_constraint("ck_farms_coordinates_pair", "farms", type_="check")
    op.drop_constraint("ck_farms_longitude_range", "farms", type_="check")
    op.drop_constraint("ck_farms_latitude_range", "farms", type_="check")
    op.drop_column("farms", "longitude")
    op.drop_column("farms", "latitude")
