"""Run the telemetry watchdog against smartfarm_test only."""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
WATCHDOG = ROOT / "scripts" / "check_telemetry_watchdog.py"


def main():
    values = dotenv_values(ENV_FILE)
    raw_url = values.get("SMARTFARM_DATABASE_URL")

    if not raw_url:
        print("ERROR: SMARTFARM_DATABASE_URL is missing from .env")
        return 2

    try:
        url = make_url(raw_url)
    except Exception:
        print("ERROR: Invalid database URL configuration")
        return 2

    # Refuse unexpected source configuration; never derive from another DB.
    if url.database != "smartfarm":
        print("ERROR: Expected the configured source database to be smartfarm")
        return 2

    test_url = url.set(database="smartfarm_test")

    env = os.environ.copy()
    env["SMARTFARM_DATABASE_URL"] = test_url.render_as_string(
        hide_password=False
    )

    try:
        result = subprocess.run(
            [sys.executable, str(WATCHDOG), *sys.argv[1:]],
            cwd=ROOT,
            env=env,
            check=False,
        )
        return result.returncode
    except OSError as exc:
        print(f"ERROR: Could not start watchdog ({type(exc).__name__})")
        return 2


if __name__ == "__main__":
    sys.exit(main())
