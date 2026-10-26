"""Read-only telemetry freshness check for the Smart Farm test database."""

import argparse
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


QUERY = text("""
    SELECT
        d.id AS device_id,
        d.device_code,
        d.name AS device_name,
        latest.received_at AS last_received_at,
        CURRENT_TIMESTAMP AS checked_at
    FROM devices AS d
    LEFT JOIN LATERAL (
        SELECT MAX(e.received_at) AS received_at
        FROM telemetry_events AS e
        WHERE e.device_id = d.id
          AND e.tenant_id = d.tenant_id
    ) AS latest ON TRUE
    WHERE d.status = 'active'
    ORDER BY d.device_code
""")


def classify(last_received_at, checked_at, threshold_seconds):
    if last_received_at is None:
        return "NO_DATA", None

    age_seconds = max(
        0.0,
        (checked_at - last_received_at).total_seconds(),
    )
    status = "STALE" if age_seconds > threshold_seconds else "OK"
    return status, age_seconds


def main():
    parser = argparse.ArgumentParser(
        description="Read-only telemetry freshness watchdog"
    )
    parser.add_argument(
        "--threshold-seconds",
        type=int,
        default=90,
        help="Maximum telemetry age in seconds (default: 90)",
    )
    args = parser.parse_args()

    if args.threshold_seconds < 1:
        parser.error("--threshold-seconds must be positive")

    load_dotenv(".env")
    database_url = os.environ.get("SMARTFARM_DATABASE_URL")
    if not database_url:
        print("ERROR: SMARTFARM_DATABASE_URL is not configured")
        return 2

    try:
        url = make_url(database_url)
    except Exception:
        print("ERROR: Invalid database URL configuration")
        return 2

    if url.database != "smartfarm_test":
        print("ERROR: Watchdog test mode only permits smartfarm_test")
        return 2

    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"options": "-c default_transaction_read_only=on"},
    )

    try:
        with engine.connect() as conn:
            db_name = conn.execute(
                text("SELECT current_database()")
            ).scalar_one()

            if db_name != "smartfarm_test":
                print("ERROR: Connected to an unexpected database")
                return 2

            rows = conn.execute(QUERY).mappings().all()

        checked_at = datetime.now(timezone.utc)
        stale_count = 0
        no_data_count = 0

        print(
            f"Telemetry watchdog | database={db_name} "
            f"| threshold={args.threshold_seconds}s"
        )

        if not rows:
            print("No active devices found.")

        for row in rows:
            last_received_at = row["last_received_at"]
            reference_time = row["checked_at"]

            status, age_seconds = classify(
                last_received_at,
                reference_time,
                args.threshold_seconds,
            )

            if status == "STALE":
                stale_count += 1
            elif status == "NO_DATA":
                no_data_count += 1

            age_display = (
                "never"
                if age_seconds is None
                else f"{age_seconds:.1f}s"
            )
            last_display = (
                "none"
                if last_received_at is None
                else last_received_at.isoformat()
            )

            print(
                f"{status} | device={row['device_code']} "
                f"| age={age_display} | last_received={last_display}"
            )

        print(
            f"Summary: devices={len(rows)}, stale={stale_count}, "
            f"no_data={no_data_count}"
        )

        return 1 if stale_count or no_data_count else 0

    except Exception as exc:
        print(f"ERROR: Watchdog check failed ({type(exc).__name__})")
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
