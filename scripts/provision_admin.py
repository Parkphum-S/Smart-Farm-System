"""Provision the first admin account for the existing Smart Farm tenant."""

import sys
from getpass import getpass
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.security.user_auth import hash_password

EXPECTED_DATABASE = "smartfarm"
TENANT_ID = "00000000-0000-0000-0000-000000000001"


def main() -> int:
    raw_url = dotenv_values(".env").get("SMARTFARM_MIGRATION_DATABASE_URL")
    if not raw_url:
        print("ERROR: SMARTFARM_MIGRATION_DATABASE_URL is missing.", file=sys.stderr)
        return 1

    try:
        url = make_url(raw_url)
    except Exception:
        print("ERROR: Invalid database URL.", file=sys.stderr)
        return 1

    if (
        url.database != EXPECTED_DATABASE
        or url.username != "smartfarm_owner"
    ):
        print("ERROR: Refusing unexpected database or role.", file=sys.stderr)
        return 1

    email = input("Admin email: ").strip().lower()
    display_name = input("Display name: ").strip()
    password = getpass("Admin password (input hidden): ")
    password_confirm = getpass("Confirm password: ")

    if len(email) <= 3 or "@" not in email or not display_name:
        print("ERROR: Provide a valid email and non-empty display name.", file=sys.stderr)
        return 1

    if not password or password != password_confirm:
        print("ERROR: Password is empty or confirmation does not match.", file=sys.stderr)
        return 1

    if len(password) < 12:
        print("ERROR: Use a password of at least 12 characters.", file=sys.stderr)
        return 1

    # Hash before opening the transaction; never store plaintext passwords.
    password_hash = hash_password(password)
    del password, password_confirm

    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            db_name, db_role = conn.execute(
                text("SELECT current_database(), current_user")
            ).one()

            if db_name != EXPECTED_DATABASE:
                raise RuntimeError("Connected to an unexpected database")
            if db_role != "smartfarm_owner":
                raise RuntimeError("Connected with an unexpected database role")

            tenant = conn.execute(
                text("""
                    SELECT id, name, status
                    FROM public.tenants
                    WHERE id = :tenant_id
                    FOR SHARE
                """),
                {"tenant_id": TENANT_ID},
            ).mappings().first()

            if tenant is None or tenant["status"] != "active":
                raise RuntimeError("Expected active Default Tenant was not found")

            existing_user = conn.execute(
                text("""
                    SELECT id
                    FROM public.users
                    WHERE lower(email) = :email
                """),
                {"email": email},
            ).first()

            if existing_user:
                raise RuntimeError("Email already exists; no changes made")

            user_id = uuid4()

            conn.execute(
                text("""
                    INSERT INTO public.users
                        (id, email, display_name, status)
                    VALUES
                        (:id, :email, :display_name, 'active')
                """),
                {
                    "id": user_id,
                    "email": email,
                    "display_name": display_name,
                },
            )

            conn.execute(
                text("""
                    INSERT INTO public.user_credentials
                        (user_id, password_hash)
                    VALUES
                        (:user_id, :password_hash)
                """),
                {
                    "user_id": user_id,
                    "password_hash": password_hash,
                },
            )

            conn.execute(
                text("""
                    INSERT INTO public.tenant_memberships
                        (tenant_id, user_id, role, status)
                    VALUES
                        (:tenant_id, :user_id, 'owner', 'active')
                """),
                {
                    "tenant_id": TENANT_ID,
                    "user_id": user_id,
                },
            )

        print("Provisioning successful.")
        print(f"Database: {EXPECTED_DATABASE}")
        print(f"Tenant: {tenant['name']} ({TENANT_ID})")
        print(f"User ID: {user_id}")
        print(f"Email: {email}")
        print("Membership: owner (active)")
        return 0

    except Exception as exc:
        print(
            f"ERROR: Provisioning failed ({type(exc).__name__}); "
            "transaction rolled back.",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
