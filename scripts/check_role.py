from sqlalchemy import text

from app.db.session import engine

QUERIES = {
    "role attrs": "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls FROM pg_roles WHERE rolname = current_user",
    "schema public": "SELECT has_schema_privilege(current_user, 'public', 'USAGE'), has_schema_privilege(current_user, 'public', 'CREATE')",
    "database": "SELECT has_database_privilege(current_user, current_database(), 'CREATE'), has_database_privilege(current_user, current_database(), 'TEMP')",
    "memberships": "SELECT count(*) FROM pg_auth_members WHERE member = (SELECT oid FROM pg_roles WHERE rolname = current_user)",
}

with engine.connect() as conn:
    db, role = conn.execute(text("SELECT current_database(), current_user")).one()
    print("db:", db, "role:", role)
    for name, sql in QUERIES.items():
        print(name, tuple(conn.execute(text(sql)).one()))
