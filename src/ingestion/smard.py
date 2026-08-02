import argparse
import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from src.utils.logging_config import setup_logging
from src.utils.storage import load_settings, raw_dir

logger = logging.getLogger(__name__)

BASE_URL = "https://www.smard.de/app/chart_data"
REGION = "DE"
HOUR_MS = 3600 * 1000
WEEK_MS = 7 * 24 * HOUR_MS

# SMARD filter ids (https://smard.api.bund.dev). Prices in EUR/MWh, everything else in MWh.
FILTERS = {
    "price_day_ahead": 4169,
    "load": 410,
    "wind_onshore": 4067,
    "wind_offshore": 1225,
    "solar": 4068,
    "biomass": 4066,
    "hydro": 1226,
    "lignite": 1223,
    "hard_coal": 4069,
    "natural_gas": 4071,
    "pumped_storage": 4070,
    "other_conventional": 1227,
    "other_renewables": 1228,
}


def fetch_index(client: httpx.Client, filter_id: int) -> list[int]:
    resp = client.get(f"{BASE_URL}/{filter_id}/{REGION}/index_hour.json")
    resp.raise_for_status()
    return resp.json()["timestamps"]


def fetch_week(client: httpx.Client, filter_id: int, week_ts: int) -> dict:
    url = f"{BASE_URL}/{filter_id}/{REGION}/{filter_id}_{REGION}_hour_{week_ts}.json"
    resp = client.get(url)
    resp.raise_for_status()
    return resp.json()


def select_weeks(timestamps: list[int], start_ms: int) -> list[int]:
    # a week file covers [ts, ts + 7 days), keep every week that ends after start_ms;
    # one hour of slack because the DST fall-back week in October has 169 hours
    return [ts for ts in timestamps if ts + WEEK_MS + HOUR_MS > start_ms]


def needs_refresh(path, week_ts: int, now_ms: int) -> bool:
    # old weeks are final, recent ones still get late data and corrections
    return not path.exists() or now_ms - week_ts <= 2 * WEEK_MS


def parse_series(raw: dict, name: str) -> pd.DataFrame:
    df = pd.DataFrame(raw["series"], columns=["timestamp_ms", "value"])
    df["timestamp"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
    df["series"] = name
    return df[["timestamp", "series", "value"]]


def week_label(week_ts: int) -> str:
    """Week start as local date, used in file names (weeks start Monday 00:00 Berlin time)."""
    return datetime.fromtimestamp(week_ts / 1000, tz=ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d")


def ingest(backfill_days: int) -> None:
    out_dir = raw_dir("smard")
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - backfill_days * 24 * 3600 * 1000

    with httpx.Client(timeout=30, transport=httpx.HTTPTransport(retries=3)) as client:
        for name, filter_id in FILTERS.items():
            weeks = select_weeks(fetch_index(client, filter_id), start_ms)
            fetched = skipped = 0
            for week_ts in weeks:
                path = out_dir / f"{name}_{week_label(week_ts)}.parquet"
                if not needs_refresh(path, week_ts, now_ms):
                    skipped += 1
                    continue
                df = parse_series(fetch_week(client, filter_id, week_ts), name)
                # write to a temp file first so a killed run never leaves a half file behind
                tmp = path.with_name(path.name + ".tmp")
                df.to_parquet(tmp, index=False)
                os.replace(tmp, path)
                fetched += 1
            logger.info("%s: fetched %d weeks, skipped %d already present", name, fetched, skipped)


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Download SMARD electricity data as parquet")
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=load_settings()["ingestion"]["backfill_days"],
    )
    args = parser.parse_args()
    ingest(args.backfill_days)


if __name__ == "__main__":
    main()
