import os

from dotenv import load_dotenv

from sqlalchemy import create_engine, text

load_dotenv(".env")

engine = create_engine(os.environ["SMARTFARM_MIGRATION_DATABASE_URL"])

SQL = """
SELECT pg_get_userbyid(defaclrole) AS grantor,
       defaclobjtype AS objtype,
       defaclacl::text AS acl
FROM pg_default_acl
ORDER BY 1, 2
"""

with engine.connect() as conn:
    print(conn.execute(text("SELECT current_database()")).scalar_one())
    rows = list(conn.execute(text(SQL)))
    print("default_acl rows:", len(rows))
    for row in rows:
        print(tuple(row))
