from datetime import datetime, timedelta, timezone

from scripts.check_telemetry_watchdog import classify


def test_recent_telemetry_is_ok():
    now = datetime.now(timezone.utc)
    status, age = classify(now - timedelta(seconds=30), now, 90)

    assert status == "OK"
    assert age == 30


def test_telemetry_over_threshold_is_stale():
    now = datetime.now(timezone.utc)
    status, age = classify(now - timedelta(seconds=120), now, 90)

    assert status == "STALE"
    assert age == 120


def test_missing_telemetry_is_no_data():
    now = datetime.now(timezone.utc)
    status, age = classify(None, now, 90)

    assert status == "NO_DATA"
    assert age is None


def test_exact_threshold_is_ok():
    now = datetime.now(timezone.utc)
    status, age = classify(now - timedelta(seconds=90), now, 90)

    assert status == "OK"
    assert age == 90


def test_future_timestamp_has_zero_age():
    now = datetime.now(timezone.utc)
    status, age = classify(now + timedelta(seconds=10), now, 90)

    assert status == "OK"
    assert age == 0
