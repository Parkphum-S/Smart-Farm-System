from sqlalchemy import text

from app.db.session import engine

SQL = """
SELECT c.relname,
       has_table_privilege(current_user, c.oid, 'SELECT') AS sel,
       has_table_privilege(current_user, c.oid, 'INSERT') AS ins,
       has_table_privilege(current_user, c.oid, 'UPDATE') AS upd,
       has_table_privilege(current_user, c.oid, 'DELETE') AS del,
       has_table_privilege(current_user, c.oid, 'TRUNCATE') AS trunc
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY c.relname
"""

with engine.connect() as conn:
    db, role = conn.execute(text("SELECT current_database(), current_user")).one()
    print("db:", db, "role:", role)
    for row in conn.execute(text(SQL)):
        print(row)
