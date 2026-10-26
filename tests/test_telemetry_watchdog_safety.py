import sys
from unittest.mock import MagicMock, patch

from sqlalchemy.engine import URL

from scripts import check_telemetry_watchdog as watchdog


def test_production_database_is_rejected_before_engine_creation(monkeypatch):
    monkeypatch.setattr(watchdog, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(
        watchdog.os,
        "environ",
        {"SMARTFARM_DATABASE_URL": "postgresql://user:pass@localhost/smartfarm"},
    )

    with patch.object(watchdog, "create_engine") as create_engine:
        with patch.object(sys, "argv", ["check_telemetry_watchdog.py"]):
            result = watchdog.main()

    assert result == 2
    create_engine.assert_not_called()


def test_missing_database_url_returns_error(monkeypatch):
    monkeypatch.setattr(watchdog, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(watchdog.os, "environ", {})

    with patch.object(watchdog, "create_engine") as create_engine:
        with patch.object(sys, "argv", ["check_telemetry_watchdog.py"]):
            result = watchdog.main()

    assert result == 2
    create_engine.assert_not_called()


def test_database_connection_failure_returns_error(monkeypatch, capsys):
    monkeypatch.setattr(watchdog, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(
        watchdog.os,
        "environ",
        {
            "SMARTFARM_DATABASE_URL":
                "postgresql://user:pass@localhost/smartfarm_test"
        },
    )

    engine = MagicMock()
    engine.connect.side_effect = RuntimeError("simulated connection failure")

    with patch.object(watchdog, "create_engine", return_value=engine):
        with patch.object(sys, "argv", ["check_telemetry_watchdog.py"]):
            result = watchdog.main()

    output = capsys.readouterr().out
    assert result == 2
    assert "Watchdog check failed (RuntimeError)" in output
    assert "simulated connection failure" not in output
    engine.dispose.assert_called_once()


def test_stale_and_no_data_rows_return_alert_exit_code(monkeypatch, capsys):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    rows = [
        {
            "device_id": "device-1",
            "device_code": "TEST-STALE",
            "device_name": "Stale test device",
            "last_received_at": now - timedelta(seconds=120),
            "checked_at": now,
        },
        {
            "device_id": "device-2",
            "device_code": "TEST-NO-DATA",
            "device_name": "No data test device",
            "last_received_at": None,
            "checked_at": now,
        },
    ]

    monkeypatch.setattr(watchdog, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(
        watchdog.os,
        "environ",
        {
            "SMARTFARM_DATABASE_URL":
                "postgresql://user:pass@localhost/smartfarm_test"
        },
    )

    connection = MagicMock()
    connection.execute.return_value.scalar_one.return_value = "smartfarm_test"
    connection.execute.return_value.mappings.return_value.all.return_value = rows

    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection

    with patch.object(watchdog, "create_engine", return_value=engine):
        with patch.object(sys, "argv", ["check_telemetry_watchdog.py"]):
            result = watchdog.main()

    output = capsys.readouterr().out
    assert result == 1
    assert "STALE | device=TEST-STALE" in output
    assert "NO_DATA | device=TEST-NO-DATA" in output
    assert "stale=1, no_data=1" in output
    engine.dispose.assert_called_once()
