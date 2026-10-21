import os

from sqlalchemy import create_engine, text

engine = create_engine(os.environ["SMARTFARM_MIGRATION_DATABASE_URL"])

COLS = """
SELECT column_name, data_type, numeric_precision, numeric_scale, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'sensor_readings'
ORDER BY ordinal_position
"""
IDX = """
SELECT indexname, indexdef FROM pg_indexes
WHERE schemaname = 'public' AND tablename IN ('sensor_readings', 'telemetry_events')
ORDER BY indexname
"""

with engine.connect() as conn:
    print(conn.execute(text("SELECT current_database()")).scalar_one())
    for row in conn.execute(text(COLS)):
        print(row)
    for row in conn.execute(text(IDX)):
        print(row)
