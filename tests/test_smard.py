import time

import pandas as pd

from src.ingestion.smard import HOUR_MS, WEEK_MS, needs_refresh, parse_series, select_weeks

SAMPLE = {
    "meta_data": {"version": 1},
    "series": [
        [1785103200000, 86.04],
        [1785106800000, None],
        [1785110400000, 61.7],
    ],
}


def test_parse_series_shape():
    df = parse_series(SAMPLE, "price_day_ahead")
    assert list(df.columns) == ["timestamp", "series", "value"]
    assert len(df) == 3
    assert (df["series"] == "price_day_ahead").all()


def test_parse_series_keeps_nulls():
    df = parse_series(SAMPLE, "price_day_ahead")
    assert df["value"].iloc[0] == 86.04
    assert df["value"].isna().iloc[1]


def test_parse_series_timestamps_utc():
    df = parse_series(SAMPLE, "price_day_ahead")
    assert str(df["timestamp"].dt.tz) == "UTC"
    # 1785103200000 ms is 2026-07-26 22:00 UTC (= Monday 2026-07-27 00:00 Berlin)
    assert str(df["timestamp"].iloc[0]) == "2026-07-26 22:00:00+00:00"


def test_select_weeks_keeps_weeks_overlapping_window():
    week0 = 1_700_000_000_000
    timestamps = [week0, week0 + WEEK_MS, week0 + 2 * WEEK_MS]
    # window starts well inside the second week: first week is out, the rest stays
    start = week0 + WEEK_MS + 2 * HOUR_MS
    assert select_weeks(timestamps, start) == [week0 + WEEK_MS, week0 + 2 * WEEK_MS]


def test_select_weeks_keeps_dst_fallback_week():
    # the October fall-back week has 169 hours, a window starting in that extra
    # hour must not drop the week
    week0 = 1_700_000_000_000
    start = week0 + WEEK_MS + 30 * 60 * 1000
    assert select_weeks([week0], start) == [week0]


def test_select_weeks_keeps_future_weeks():
    # the price index already contains next week (day-ahead), it must not be dropped
    now_ms = int(time.time() * 1000)
    future_week = now_ms + 3 * 24 * HOUR_MS
    start = now_ms - 90 * 24 * HOUR_MS
    assert select_weeks([future_week], start) == [future_week]


def _write_parquet(path, values):
    ts = pd.date_range("2026-06-01", periods=len(values), freq="h", tz="UTC")
    pd.DataFrame({"timestamp": ts, "series": "x", "value": values}).to_parquet(path, index=False)


def test_needs_refresh(tmp_path):
    now = 1_800_000_000_000
    complete = tmp_path / "complete.parquet"
    _write_parquet(complete, [1.0, 2.0, 3.0])
    missing = tmp_path / "missing.parquet"
    assert needs_refresh(missing, now - 5 * WEEK_MS, now)  # missing is always fetched
    assert not needs_refresh(complete, now - 5 * WEEK_MS, now)  # old and complete: skip
    assert needs_refresh(complete, now - WEEK_MS, now)  # recent: refresh anyway


def test_needs_refresh_repairs_bad_files(tmp_path):
    now = 1_800_000_000_000
    old = now - 5 * WEEK_MS
    with_nulls = tmp_path / "nulls.parquet"
    _write_parquet(with_nulls, [1.0, None, 3.0])
    assert needs_refresh(with_nulls, old, now)  # null hours: fetched too early, repair
    broken = tmp_path / "broken.parquet"
    broken.write_bytes(b"not a parquet file")
    assert needs_refresh(broken, old, now)
