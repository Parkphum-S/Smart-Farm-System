from datetime import datetime, timedelta, timezone

import pytest

from app.services.archive_reader import (
    _validate_range,
    iter_events,
    iter_readings,
)


def test_validate_range_normalizes_to_utc():
    start = datetime(2026, 1, 1, 7, 0, tzinfo=timezone(timedelta(hours=7)))
    end = datetime(2026, 1, 2, 7, 0, tzinfo=timezone(timedelta(hours=7)))

    start_utc, end_utc = _validate_range(start, end)

    assert start_utc == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert end_utc == datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("function", [iter_events, iter_readings])
def test_reader_rejects_naive_datetimes(function):
    start = datetime(2026, 1, 1)
    end = datetime(2026, 1, 2)

    with pytest.raises(ValueError, match="timezone-aware"):
        function(None, start, end)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (
            datetime(2026, 1, 2, tzinfo=timezone.utc),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        (
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    ],
)
def test_validate_range_rejects_empty_or_reversed_range(start, end):
    with pytest.raises(ValueError, match="start_at must be earlier"):
        _validate_range(start, end)


@pytest.mark.parametrize("function", [iter_events, iter_readings])
def test_reader_rejects_non_positive_batch_size(function):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="batch_size must be positive"):
        list(function(None, start, end, batch_size=0))

def test_stream_query_closes_result_after_exhaustion():
    from unittest.mock import MagicMock, call

    from app.services.archive_reader import EVENTS_SQL, _stream_query

    connection = MagicMock()
    result = connection.execution_options.return_value.execute.return_value
    row = MagicMock()
    row._mapping = {"id": "event-1"}
    result.partitions.return_value = [[row], []]

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)

    rows = list(_stream_query(connection, EVENTS_SQL, start, end, 1))

    assert rows == [{"id": "event-1"}]
    connection.execution_options.assert_called_once_with(
        stream_results=True, yield_per=1
    )
    result.partitions.assert_called_once_with(1)
    result.close.assert_called_once_with()


def test_stream_query_closes_result_when_iteration_fails():
    from unittest.mock import MagicMock

    from app.services.archive_reader import EVENTS_SQL, _stream_query

    connection = MagicMock()
    result = connection.execution_options.return_value.execute.return_value

    def broken_partitions(_batch_size):
        yield []
        raise RuntimeError("simulated fetch failure")

    result.partitions.side_effect = broken_partitions

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)

    with pytest.raises(RuntimeError, match="simulated fetch failure"):
        list(_stream_query(connection, EVENTS_SQL, start, end, 10))

    result.close.assert_called_once_with()
