import argparse
import logging
import os
from datetime import date, datetime, timedelta, timezone

import httpx
import pandas as pd

from src.utils.logging_config import setup_logging
from src.utils.storage import load_settings, raw_dir

logger = logging.getLogger(__name__)

# ERA5 reanalysis; recent days are preliminary and get refreshed on later runs
BASE_URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY_VARS = ["temperature_2m", "wind_speed_100m", "shortwave_radiation"]
HOURS_PER_WEEK = 168


def utc_today() -> date:
    # week buckets are UTC and the API rejects dates beyond the current UTC day;
    # the local Berlin date would already be tomorrow between 00:00 and 02:00
    return datetime.now(timezone.utc).date()


def week_starts(start: date, end: date) -> list[date]:
    """All Mondays of the weeks covering [start, end]."""
    monday = start - timedelta(days=start.weekday())
    weeks = []
    while monday <= end:
        weeks.append(monday)
        monday += timedelta(days=7)
    return weeks


def week_end(monday: date, today: date) -> date:
    # the API rejects an end_date beyond the current UTC day
    return min(monday + timedelta(days=6), today)


def needs_refresh(path, week_start: date, today: date) -> bool:
    if not path.exists():
        return True
    if (today - week_start).days <= 14:
        # same rule as smard: recent ERA5 data is preliminary and changes retroactively
        return True
    try:
        rows = len(pd.read_parquet(path, columns=["timestamp"]))
    except Exception:
        return True  # unreadable file: re-fetch and overwrite it
    # a week that never got all its hours (e.g. the cron was down for a while,
    # so the partial file aged out of the refresh window) must be repaired
    return rows < HOURS_PER_WEEK


def drop_unfinished_hours(df: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    # the archive API fills not-yet-elapsed hours of today with preliminary values;
    # only keep hours that have fully passed
    return df[df["timestamp"] < now.floor("h")]


def fetch_week(client: httpx.Client, lat: float, lon: float, start: date, end: date) -> dict:
    resp = client.get(
        BASE_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": ",".join(HOURLY_VARS),
            "wind_speed_unit": "ms",
            "timezone": "UTC",
            "start_date": str(start),
            "end_date": str(end),
        },
    )
    resp.raise_for_status()
    return resp.json()


def parse_hourly(raw: dict, location: str) -> pd.DataFrame:
    df = pd.DataFrame(raw["hourly"])
    df["timestamp"] = pd.to_datetime(df.pop("time"), utc=True)
    df["location"] = location
    # keep the value columns float even if a week comes back all-null
    df[HOURLY_VARS] = df[HOURLY_VARS].astype("float64")
    return df[["timestamp", "location", *HOURLY_VARS]]


def ingest(backfill_days: int) -> None:
    settings = load_settings()
    out_dir = raw_dir("open_meteo")
    today = utc_today()
    start = today - timedelta(days=backfill_days)
    # one cutoff for the whole run so all locations end at the same hour
    now = pd.Timestamp.now(tz="UTC")

    with httpx.Client(timeout=30, transport=httpx.HTTPTransport(retries=3)) as client:
        for loc in settings["weather"]["locations"]:
            fetched = skipped = 0
            for monday in week_starts(start, today):
                path = out_dir / f"{loc['name']}_{monday}.parquet"
                if not needs_refresh(path, monday, today):
                    skipped += 1
                    continue
                raw = fetch_week(client, loc["lat"], loc["lon"], monday, week_end(monday, today))
                df = parse_hourly(raw, loc["name"])
                df = drop_unfinished_hours(df, now)
                # write to a temp file first so a killed run never leaves a half file behind
                tmp = path.with_name(path.name + ".tmp")
                df.to_parquet(tmp, index=False)
                os.replace(tmp, path)
                fetched += 1
            logger.info(
                "%s: fetched %d weeks, skipped %d already present", loc["name"], fetched, skipped
            )


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Download Open-Meteo weather data as parquet")
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=load_settings()["ingestion"]["backfill_days"],
    )
    args = parser.parse_args()
    ingest(args.backfill_days)


if __name__ == "__main__":
    main()
