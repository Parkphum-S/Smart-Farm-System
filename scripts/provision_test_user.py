"""Provision a user in smartfarm_test only."""

import getpass
import os
import re
import sys
from pathlib import Path
from uuid import uuid4

# Make the repository root importable when invoked as a script.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app.security.user_auth import hash_password


def main() -> int:
    load_dotenv(".env")

    raw_url = os.environ.get("SMARTFARM_MIGRATION_DATABASE_URL")
    if not raw_url:
        print("ERROR: Migration database URL is not configured.", file=sys.stderr)
        return 1

    try:
        url = make_url(raw_url).set(database="smartfarm_test")
    except Exception:
        print("ERROR: Invalid database URL configuration.", file=sys.stderr)
        return 1

    if url.database != "smartfarm_test":
        print("ERROR: Refusing unexpected database.", file=sys.stderr)
        return 1

    email = input("Email: ").strip().lower()
    display_name = input("Display name: ").strip()
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")

    if (
        len(email) <= 3
        or len(email) > 320
        or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)
    ):
        print("ERROR: Enter a valid email address.", file=sys.stderr)
        return 1

    if not display_name or len(display_name) > 160:
        print("ERROR: Display name is required (max 160 characters).", file=sys.stderr)
        return 1

    if not password or password != confirm:
        print("ERROR: Password is empty or confirmation does not match.", file=sys.stderr)
        return 1

    try:
        password_hash = hash_password(password)
    except Exception:
        print("ERROR: Password could not be hashed.", file=sys.stderr)
        return 1

    user_id = uuid4()
    engine = create_engine(url, pool_pre_ping=True)

    try:
        with engine.begin() as conn:
            db_name = conn.execute(
                text("SELECT current_database()")
            ).scalar_one()

            if db_name != "smartfarm_test":
                raise RuntimeError("Unexpected database")

            exists = conn.execute(
                text("""
                    SELECT 1
                    FROM public.users
                    WHERE lower(email) = :email
                """),
                {"email": email},
            ).first()

            if exists:
                print(
                    "ERROR: A user with that email already exists.",
                    file=sys.stderr,
                )
                return 1

            conn.execute(
                text("""
                    INSERT INTO public.users (id, email, display_name, status)
                    VALUES (:id, :email, :display_name, 'active')
                """),
                {
                    "id": user_id,
                    "email": email,
                    "display_name": display_name,
                },
            )

            conn.execute(
                text("""
                    INSERT INTO public.user_credentials (user_id, password_hash)
                    VALUES (:user_id, :password_hash)
                """),
                {
                    "user_id": user_id,
                    "password_hash": password_hash,
                },
            )

        print(f"Created test user: {email}")
        print(f"User ID: {user_id}")
        print("No tenant membership was created.")
        return 0

    except IntegrityError:
        print(
            "ERROR: Database constraint failed; transaction rolled back.",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        message = (
            "Unexpected database error."
            if isinstance(exc, RuntimeError)
            else f"Provisioning failed ({type(exc).__name__})."
        )
        print(f"ERROR: {message}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
