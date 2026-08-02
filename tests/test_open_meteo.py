from datetime import date

import pandas as pd

from src.ingestion.open_meteo import (
    drop_unfinished_hours,
    needs_refresh,
    parse_hourly,
    week_end,
    week_starts,
)

SAMPLE = {
    "hourly": {
        "time": ["2026-07-27T00:00", "2026-07-27T01:00", "2026-07-27T02:00"],
        "temperature_2m": [18.2, None, 17.5],
        "wind_speed_100m": [7.1, 6.8, None],
        "shortwave_radiation": [0.0, 0.0, 12.5],
    }
}


def test_parse_hourly_shape():
    df = parse_hourly(SAMPLE, "hamburg")
    assert list(df.columns) == [
        "timestamp",
        "location",
        "temperature_2m",
        "wind_speed_100m",
        "shortwave_radiation",
    ]
    assert len(df) == 3
    assert (df["location"] == "hamburg").all()


def test_parse_hourly_utc_and_nulls():
    df = parse_hourly(SAMPLE, "hamburg")
    assert str(df["timestamp"].dt.tz) == "UTC"
    assert str(df["timestamp"].iloc[0]) == "2026-07-27 00:00:00+00:00"
    assert df["temperature_2m"].isna().iloc[1]
    assert df["wind_speed_100m"].dtype == "float64"


def test_parse_hourly_all_null_column_stays_float():
    raw = {
        "hourly": {
            "time": ["2026-07-27T00:00", "2026-07-27T01:00"],
            "temperature_2m": [None, None],
            "wind_speed_100m": [None, None],
            "shortwave_radiation": [None, None],
        }
    }
    df = parse_hourly(raw, "berlin")
    value_cols = ["temperature_2m", "wind_speed_100m", "shortwave_radiation"]
    assert (df.dtypes[value_cols] == "float64").all()


def test_week_starts_aligns_to_monday():
    # 2026-07-08 is a Wednesday, its week starts Monday 2026-07-06
    weeks = week_starts(date(2026, 7, 8), date(2026, 8, 2))
    assert weeks[0] == date(2026, 7, 6)
    assert weeks[-1] == date(2026, 7, 27)
    assert all(d.weekday() == 0 for d in weeks)


def _write_parquet(path, rows):
    ts = pd.date_range("2026-06-01", periods=rows, freq="h", tz="UTC")
    pd.DataFrame({"timestamp": ts}).to_parquet(path, index=False)


def test_needs_refresh(tmp_path):
    today = date(2026, 8, 3)  # a Monday
    full = tmp_path / "full.parquet"
    _write_parquet(full, 168)
    missing = tmp_path / "missing.parquet"
    assert needs_refresh(missing, date(2026, 6, 1), today)  # missing is always fetched
    assert not needs_refresh(full, date(2026, 6, 1), today)  # old and complete: skip
    # boundary of the refresh window: exactly 14 days refreshes, 21 days skips
    assert needs_refresh(full, date(2026, 7, 20), today)
    assert not needs_refresh(full, date(2026, 7, 13), today)


def test_needs_refresh_repairs_bad_files(tmp_path):
    today = date(2026, 8, 3)
    old = date(2026, 6, 1)
    partial = tmp_path / "partial.parquet"
    _write_parquet(partial, 72)  # a current week frozen by a cron outage
    assert needs_refresh(partial, old, today)
    broken = tmp_path / "broken.parquet"
    broken.write_bytes(b"not a parquet file")
    assert needs_refresh(broken, old, today)


def test_week_end_capped_at_today():
    monday = date(2026, 7, 27)
    assert week_end(monday, date(2026, 8, 10)) == date(2026, 8, 2)  # past week: full
    assert week_end(monday, date(2026, 7, 29)) == date(2026, 7, 29)  # running week: capped


def test_drop_unfinished_hours():
    df = parse_hourly(SAMPLE, "hamburg")  # hours 00, 01, 02 on 2026-07-27
    now = pd.Timestamp("2026-07-27 02:30", tz="UTC")
    out = drop_unfinished_hours(df, now)
    # hour 02 is still running at 02:30 and must not be kept
    assert list(out["timestamp"].dt.hour) == [0, 1]
