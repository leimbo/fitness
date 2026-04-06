#!/usr/bin/env python3
"""
Strava data importer.
Uses the official Strava REST API (v3) with OAuth2.
Handles automatic token refresh.

Usage:
  python strava_import.py \
    --credentials /path/to/strava.json \
    --output /path/to/output/dir \
    --start 2024-01-01 --end 2024-03-31
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from urllib.error import URLError, HTTPError

STRAVA_API_BASE = "https://www.strava.com/api/v3"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"


def load_credentials(creds_path: str) -> dict:
    with open(creds_path) as f:
        return json.load(f)


def save_credentials(creds: dict, creds_path: str):
    with open(creds_path, "w") as f:
        json.dump(creds, f, indent=2)


def save_json(data, output_dir: str, filename: str):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = os.path.join(output_dir, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def api_get(endpoint: str, access_token: str, params: dict = None) -> dict | list:
    """Make an authenticated GET request to the Strava API."""
    url = f"{STRAVA_API_BASE}{endpoint}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        raise RuntimeError(f"Strava API error {e.code} on {endpoint}: {e.read().decode()}")


def refresh_token_if_needed(creds: dict, creds_path: str) -> str:
    """Refresh the access token if it has expired or is close to expiry."""
    expires_at = creds.get("expires_at", 0)
    now = time.time()

    if now < expires_at - 300:  # still valid with 5-min buffer
        return creds["access_token"]

    print("  Access token expired — refreshing...")
    payload = urlencode({
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "grant_type": "refresh_token",
        "refresh_token": creds["refresh_token"],
    }).encode()

    req = Request(STRAVA_TOKEN_URL, data=payload, method="POST")
    try:
        with urlopen(req) as resp:
            token_data = json.loads(resp.read().decode())
    except (HTTPError, URLError) as e:
        raise RuntimeError(f"Token refresh failed: {e}")

    creds["access_token"] = token_data["access_token"]
    creds["refresh_token"] = token_data["refresh_token"]
    creds["expires_at"] = token_data["expires_at"]
    save_credentials(creds, creds_path)
    print("  ✓ Token refreshed")
    return creds["access_token"]


def fetch_activities(
    access_token: str,
    start: date,
    end: date,
    output_dir: str
) -> list:
    """Fetch activities list and detailed data for the date range."""
    print(f"  Fetching activities {start} → {end}...")

    start_epoch = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
    end_epoch = int(datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc).timestamp())

    all_activities = []
    page = 1
    per_page = 100

    while True:
        batch = api_get("/athlete/activities", access_token, {
            "after": start_epoch,
            "before": end_epoch,
            "page": page,
            "per_page": per_page,
        })
        if not batch:
            break
        all_activities.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
        time.sleep(0.5)  # be polite to the API

    save_json(all_activities, output_dir, "activities.json")

    # Fetch detailed data for each activity (includes segments, splits, etc.)
    detailed = []
    for act in all_activities:
        act_id = act["id"]
        try:
            detail = api_get(f"/activities/{act_id}", access_token, {"include_all_efforts": True})
            detailed.append(detail)
            time.sleep(0.3)  # rate limit caution
        except Exception as e:
            print(f"  WARNING: Could not fetch detail for activity {act_id}: {e}")
            detailed.append(act)

    save_json(detailed, output_dir, "activities_detailed.json")
    print(f"  ✓ {len(all_activities)} activities fetched")
    return all_activities


def fetch_athlete_stats(access_token: str, output_dir: str):
    """Fetch overall athlete stats (totals, PRs)."""
    print("  Fetching athlete profile and stats...")
    try:
        athlete = api_get("/athlete", access_token)
        athlete_id = athlete["id"]
        stats = api_get(f"/athletes/{athlete_id}/stats", access_token)
        save_json({"athlete": athlete, "stats": stats}, output_dir, "athlete_stats.json")
        print("  ✓ Athlete stats fetched")
    except Exception as e:
        print(f"  WARNING: Could not fetch athlete stats: {e}")


def fetch_zones(access_token: str, output_dir: str):
    """Fetch the athlete's HR and power zones."""
    print("  Fetching zones...")
    try:
        zones = api_get("/athlete/zones", access_token)
        save_json(zones, output_dir, "zones.json")
        print("  ✓ Zones fetched")
    except Exception as e:
        print(f"  WARNING: Could not fetch zones: {e}")


def main():
    parser = argparse.ArgumentParser(description="Import Strava data")
    parser.add_argument("--credentials", required=True, help="Path to strava.json credentials file")
    parser.add_argument("--output", required=True, help="Output directory for JSON files")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)

    print(f"\n{'='*50}")
    print(f"Strava Import: {start_date} → {end_date}")
    print(f"Output: {args.output}")
    print(f"{'='*50}\n")

    if not os.path.exists(args.credentials):
        print(f"ERROR: Credentials file not found at {args.credentials}")
        print("Run credential setup first — see references/credential_setup.md")
        sys.exit(1)

    creds = load_credentials(args.credentials)
    access_token = refresh_token_if_needed(creds, args.credentials)
    print("✓ Authenticated\n")

    fetch_activities(access_token, start_date, end_date, args.output)
    fetch_athlete_stats(access_token, args.output)
    fetch_zones(access_token, args.output)

    metadata = {
        "imported_at": datetime.now().isoformat(),
        "start": args.start,
        "end": args.end,
        "platform": "strava"
    }
    save_json(metadata, args.output, "_import_metadata.json")

    print(f"\n✓ Strava import complete → {args.output}")


if __name__ == "__main__":
    main()
