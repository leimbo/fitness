#!/usr/bin/env python3
"""
Garmin Connect data importer.
Pulls activities, sleep, HRV, body battery, stress, steps, resting HR,
training readiness (0-100 score), morning readiness, race predictions,
and generates jet lag flags from calendar travel events.

Usage:
  python garmin_import.py \
    --credentials /path/to/garmin.json \
    --output /path/to/output/dir \
    --start 2024-01-01 --end 2024-03-31

Output files:
  activities.json          — activity list
  activities_detailed.json — per-activity detail
  daily_metrics.json       — per-day: sleep, HRV, body battery, stress, steps,
                             resting HR, training_readiness, morning_readiness
  body_composition.json    — Index S2 weigh-ins
  training_status.json     — aerobic/anaerobic load trend
  training_load.json       — training load data
  race_predictions.json    — Garmin predicted 5K/10K/HM/marathon times
  jet_lag_flags.json       — travel-derived high-intensity restriction flags
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta, datetime
from pathlib import Path

try:
    import garminconnect
except ImportError:
    print("ERROR: garminconnect not installed. Run: pip install garminconnect --break-system-packages")
    sys.exit(1)


def load_credentials(creds_path: str) -> dict:
    with open(creds_path) as f:
        return json.load(f)


def save_credentials(creds: dict, creds_path: str):
    Path(creds_path).parent.mkdir(parents=True, exist_ok=True)
    with open(creds_path, "w") as f:
        json.dump(creds, f, indent=2)


def get_client(creds: dict, tokenstore: str) -> garminconnect.Garmin:
    """
    Authenticate with Garmin Connect.

    On first run (no saved tokens): logs in with email/password, prompts
    for the MFA code interactively, then saves the session token to disk.

    On subsequent runs: loads the saved token — no MFA required.
    """
    tokenstore_path = Path(tokenstore)

    # ── Try loading saved tokens first ───────────────────────────────────────
    if tokenstore_path.exists():
        print("  Found saved session token — skipping MFA...")
        try:
            client = garminconnect.Garmin()
            client.login(tokenstore=str(tokenstore_path))
            print("  ✓ Authenticated via saved token")
            return client
        except Exception as e:
            print(f"  Saved token invalid or expired ({e}) — falling back to password login...")

    # ── Full login with MFA prompt ────────────────────────────────────────────
    print("  Logging in with email/password...")
    print("  ⚠️  Garmin will send a verification code to your email.")

    def prompt_mfa() -> str:
        print("\n" + "─" * 50)
        code = input("  Enter the Garmin verification code from your email: ").strip()
        print("─" * 50 + "\n")
        return code

    try:
        client = garminconnect.Garmin(
            creds["email"],
            creds["password"],
            is_cn=False,
            prompt_mfa=prompt_mfa,
        )
        client.login()
    except Exception as e:
        raise RuntimeError(f"Garmin login failed: {e}")

    # Save tokens so future runs skip MFA
    try:
        tokenstore_path.mkdir(parents=True, exist_ok=True)
        client.client.dump(str(tokenstore_path))
        print(f"  ✓ Session token saved → {tokenstore_path}")
        print("  Future runs will skip MFA automatically.")
    except Exception as e:
        print(f"  WARNING: Could not save session token: {e}")

    return client


def save_json(data: dict | list, output_dir: str, filename: str):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = os.path.join(output_dir, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def fetch_activities(client, start: date, end: date, output_dir: str) -> list:
    """Fetch all activities in date range."""
    print(f"  Fetching activities {start} → {end}...")
    try:
        activities = client.get_activities_by_date(
            start.isoformat(), end.isoformat()
        )
    except Exception as e:
        print(f"  WARNING: Could not fetch activities: {e}")
        return []

    # Save raw response
    save_json(activities, output_dir, "activities.json")

    # Also save individual activity details for richer data
    detailed = []
    for act in activities[:50]:  # cap at 50 to avoid rate limits
        act_id = act.get("activityId")
        if act_id:
            try:
                detail = client.get_activity_details(act_id)
                detail["_summary"] = act
                detailed.append(detail)
            except Exception:
                detailed.append({"_summary": act})

    save_json(detailed, output_dir, "activities_detailed.json")
    print(f"  ✓ {len(activities)} activities fetched")
    return activities


def fetch_daily_metrics(client, start: date, end: date, output_dir: str) -> dict:
    """Fetch day-by-day health metrics."""
    print(f"  Fetching daily metrics {start} → {end}...")
    metrics = {}

    current = start
    while current <= end:
        day_str = current.isoformat()
        day_data = {}

        # Sleep
        try:
            day_data["sleep"] = client.get_sleep_data(day_str)
        except Exception as e:
            day_data["sleep"] = {"error": str(e)}

        # Body battery
        try:
            raw_bb = client.get_body_battery(day_str)
            # Debug: log raw response on first non-empty result to diagnose format
            if raw_bb and raw_bb != {} and raw_bb != []:
                print(f"  DEBUG body_battery raw ({day_str}): {repr(raw_bb)[:300]}")
            day_data["body_battery"] = raw_bb
        except Exception as e:
            day_data["body_battery"] = {"error": str(e)}

        # Stress
        try:
            day_data["stress"] = client.get_stress_data(day_str)
        except Exception as e:
            day_data["stress"] = {"error": str(e)}

        # Steps
        try:
            day_data["steps"] = client.get_steps_data(day_str)
        except Exception as e:
            day_data["steps"] = {"error": str(e)}

        # HRV
        try:
            day_data["hrv"] = client.get_hrv_data(day_str)
        except Exception as e:
            day_data["hrv"] = {"error": str(e)}

        # Resting HR (from stats)
        try:
            stats = client.get_stats(day_str)
            day_data["resting_hr"] = stats.get("restingHeartRate")
            day_data["max_hr"] = stats.get("maxHeartRate")
            day_data["avg_stress"] = stats.get("averageStressLevel")
            day_data["vo2max"] = stats.get("vo2MaxValue")
        except Exception as e:
            day_data["stats_error"] = str(e)

        # Training Readiness (0–100 score: Green=70-100, Yellow=30-69, Red=<30)
        try:
            day_data["training_readiness"] = client.get_training_readiness(day_str)
        except Exception as e:
            day_data["training_readiness"] = {"error": str(e)}

        # Morning Readiness (post-wake recalculation — most accurate for session planning)
        try:
            day_data["morning_readiness"] = client.get_morning_training_readiness(day_str)
        except Exception as e:
            day_data["morning_readiness"] = {"error": str(e)}

        metrics[day_str] = day_data
        current += timedelta(days=1)

    save_json(metrics, output_dir, "daily_metrics.json")
    print(f"  ✓ Daily metrics fetched for {len(metrics)} days")
    return metrics


def fetch_body_composition(client, start: date, end: date, output_dir: str):
    """Fetch body composition / smart scale data (weight, body fat %, muscle mass, etc.)."""
    print(f"  Fetching body composition {start} → {end}...")
    try:
        data = client.get_body_composition(start.isoformat(), end.isoformat())
        save_json(data, output_dir, "body_composition.json")

        # Extract individual weigh-in entries for easier reading
        entries = []
        if isinstance(data, dict):
            for key in ("dateWeightList", "allWeightMetrics", "weightList"):
                if key in data and isinstance(data[key], list):
                    entries = data[key]
                    break

        if entries:
            print(f"  ✓ {len(entries)} body composition readings fetched")
        else:
            print("  ✓ Body composition data fetched (no scale readings yet in range)")
    except Exception as e:
        print(f"  WARNING: Body composition not available: {e}")


def fetch_training_status(client, start: date, end: date, output_dir: str):
    """Fetch training load and status (aerobic/anaerobic load trend)."""
    print("  Fetching training status...")
    try:
        training_status = client.get_training_status(start.isoformat(), end.isoformat())
        save_json(training_status, output_dir, "training_status.json")
        print(f"  ✓ Training status fetched")
    except Exception as e:
        print(f"  WARNING: Training status not available: {e}")

    try:
        training_load = client.get_training_load(start.isoformat(), end.isoformat())
        save_json(training_load, output_dir, "training_load.json")
        print(f"  ✓ Training load fetched")
    except Exception as e:
        print(f"  WARNING: Training load not available: {e}")


def fetch_race_predictions(client, output_dir: str):
    """
    Fetch Garmin race time predictions (5K, 10K, HM, marathon).
    Used to gate the CEO-Athlete framework: if predicted marathon > 3:10,
    prioritize Critical Velocity intervals.
    Saved to race_predictions.json — not date-ranged, reflects current fitness.
    """
    print("  Fetching race predictions...")
    try:
        predictions = client.get_race_predictions()
        save_json(predictions, output_dir, "race_predictions.json")
        print(f"  ✓ Race predictions fetched")
    except Exception as e:
        print(f"  WARNING: Race predictions not available: {e}")


def build_jet_lag_flags(calendar_path: str, output_dir: str):
    """
    Garmin's Jet Lag Adviser is not exposed via the API.
    As a proxy, we read the Google Calendar travel impact flags and
    generate a jet_lag_flags.json that marks dates where high-intensity
    training should be skipped (first 24h after cross-timezone travel).

    Logic:
    - Any event flagged is_travel=True in events_by_date.json marks
      that date and the following day as jet_lag_risk=True.
    - Claude uses this to apply the 'no intensity for 24h post-arrival'
      rule from the CEO-Athlete framework.
    """
    calendar_file = Path(calendar_path) / "events_by_date.json"
    if not calendar_file.exists():
        print("  INFO: No calendar data found — skipping jet lag flags")
        return

    try:
        with open(calendar_file) as f:
            events_by_date = json.load(f)

        jet_lag_flags = {}
        for event_date, events in events_by_date.items():
            has_travel = any(e.get("is_travel") for e in events)
            if has_travel:
                # Flag the travel date and the following day (24h recovery window)
                travel_dt = date.fromisoformat(event_date)
                next_dt = travel_dt + timedelta(days=1)
                jet_lag_flags[event_date] = {
                    "jet_lag_risk": True,
                    "reason": "travel_day",
                    "no_intensity": False,  # day of travel: adjust based on timing
                }
                jet_lag_flags[next_dt.isoformat()] = {
                    "jet_lag_risk": True,
                    "reason": "post_travel_24h",
                    "no_intensity": True,  # no high-intensity for 24h post-arrival
                }

        save_json(jet_lag_flags, output_dir, "jet_lag_flags.json")
        flagged = sum(1 for v in jet_lag_flags.values() if v["jet_lag_risk"])
        print(f"  ✓ Jet lag flags built ({flagged} dates flagged from calendar)")
    except Exception as e:
        print(f"  WARNING: Could not build jet lag flags: {e}")


def main():
    parser = argparse.ArgumentParser(description="Import Garmin Connect data")
    parser.add_argument("--credentials", required=True, help="Path to garmin.json credentials file")
    parser.add_argument("--output", required=True, help="Output directory for JSON files")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)

    print(f"\n{'='*50}")
    print(f"Garmin Import: {start_date} → {end_date}")
    print(f"Output: {args.output}")
    print(f"{'='*50}\n")

    # Load credentials
    if not os.path.exists(args.credentials):
        print(f"ERROR: Credentials file not found at {args.credentials}")
        print("Run credential setup first — see references/credential_setup.md")
        sys.exit(1)

    creds = load_credentials(args.credentials)

    # Authenticate — tokenstore lives next to the credentials file
    tokenstore = str(Path(args.credentials).parent / "garmin_tokens")
    print("Authenticating with Garmin Connect...")
    client = get_client(creds, tokenstore)
    print("✓ Authenticated\n")

    # Fetch everything
    fetch_activities(client, start_date, end_date, args.output)
    fetch_daily_metrics(client, start_date, end_date, args.output)
    fetch_body_composition(client, start_date, end_date, args.output)
    fetch_training_status(client, start_date, end_date, args.output)
    fetch_race_predictions(client, args.output)

    # Build jet lag flags from calendar data (no Garmin API equivalent exists)
    calendar_dir = str(Path(args.output).parent / "calendar")
    build_jet_lag_flags(calendar_dir, args.output)

    # Save import metadata
    metadata = {
        "imported_at": datetime.now().isoformat(),
        "start": args.start,
        "end": args.end,
        "platform": "garmin"
    }
    save_json(metadata, args.output, "_import_metadata.json")

    print(f"\n✓ Garmin import complete → {args.output}")


if __name__ == "__main__":
    main()
