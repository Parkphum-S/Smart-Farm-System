import os

from sqlalchemy import create_engine, text

engine = create_engine(os.environ["SMARTFARM_MIGRATION_DATABASE_URL"])

SQL = """
SELECT conrelid::regclass AS tbl, conname, pg_get_constraintdef(oid) AS def
FROM pg_constraint
WHERE conrelid IN ('telemetry_events'::regclass, 'sensor_readings'::regclass)
ORDER BY 1, 2
"""

with engine.connect() as conn:
    print(conn.execute(text("SELECT current_database()")).scalar_one())
    for row in conn.execute(text(SQL)):
        print(row)
