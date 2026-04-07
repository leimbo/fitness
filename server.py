#!/usr/bin/env python3
"""
Health & Fitness MCP Server
Exposes fitness data and Garmin workout push as MCP tools.
Deploy to Fly.io for access from any Claude instance.

Tools:
  get_daily_metrics   — sleep, HRV, body battery, readiness for a date
  get_activities      — recent Garmin activities
  get_calendar        — upcoming Google Calendar events
  get_training_impacts — travel/jet lag flags affecting training
  get_race_predictions — Garmin predicted 5K/10K/HM/marathon times
  list_workouts       — available workout templates
  push_workout        — push a workout to Garmin Connect
  trigger_sync        — pull fresh data from Garmin/Strava/Calendar
"""

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# ── Config ────────────────────────────────────────────────────────────────────
DATA_DIR    = Path(os.environ.get("DATA_DIR",    "./data"))
SCRIPTS_DIR = Path(os.environ.get("SCRIPTS_DIR", "./import-scripts"))
CREDS_DIR   = Path(os.environ.get("CREDS_DIR",   "./.credentials"))

mcp = FastMCP("health-fitness")
mcp.settings.host = "0.0.0.0"
mcp.settings.port = int(os.environ.get("PORT", "8080"))
os.environ["FASTMCP_ALLOWED_HOSTS"] = "*"

# ── Helpers ───────────────────────────────────────────────────────────────────
def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def fmt_pace(speed_ms: float) -> str:
    if not speed_ms:
        return "N/A"
    pace_sec = 1000 / speed_ms
    return f"{int(pace_sec // 60)}:{int(pace_sec % 60):02d}/km"


def fmt_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_daily_metrics(date_str: str = None) -> str:
    """Get daily health metrics (sleep, HRV, body battery, readiness) for a date.

    Args:
        date_str: Date in YYYY-MM-DD format. Defaults to today.
    """
    target = date_str or date.today().isoformat()
    data = load_json(DATA_DIR / "garmin" / "daily_metrics.json")
    if not data:
        return "No daily metrics data available."

    entry = data.get(target)
    if not entry:
        available = sorted(data.keys())
        return f"No data for {target}. Most recent dates: {available[-5:]}"

    out = [f"## Daily Metrics — {target}"]

    # Readiness
    for key in ("training_readiness", "morning_readiness"):
        r = entry.get(key)
        if r is not None:
            score = r if isinstance(r, (int, float)) else r.get("score", "N/A")
            label = "Training readiness" if key == "training_readiness" else "Morning readiness"
            out.append(f"**{label}**: {score}/100")

    # HRV
    hrv_summary = entry.get("hrv", {}).get("hrvSummary", {})
    last_night = hrv_summary.get("lastNight")
    if last_night:
        out.append(f"**HRV (last night)**: {last_night} ms")

    # Sleep
    sleep = entry.get("sleep", {})
    sleep_secs = sleep.get("sleepTimeSeconds", 0)
    if sleep_secs:
        h, m = divmod(int(sleep_secs // 60), 60)
        score = sleep.get("sleepScores", {}).get("overall", {}).get("value", "N/A")
        out.append(f"**Sleep**: {h}h {m:02d}m (score: {score})")
        deep = sleep.get("deepSleepSeconds", 0)
        rem  = sleep.get("remSleepSeconds", 0)
        if deep:
            out.append(f"  Deep: {int(deep // 60)}m | REM: {int(rem // 60)}m")

    # Body battery
    bb_readings = entry.get("body_battery", [])
    if bb_readings:
        peak = max((r.get("bodyBatteryLevel", 0) for r in bb_readings), default=0)
        out.append(f"**Body battery peak**: {peak}")

    # Resting HR / stress
    if entry.get("resting_hr"):
        out.append(f"**Resting HR**: {entry['resting_hr']} bpm")
    if entry.get("avg_stress"):
        out.append(f"**Avg stress**: {entry['avg_stress']}")

    return "\n".join(out)


@mcp.tool()
def get_activities(limit: int = 10, activity_type: str = None) -> str:
    """Get recent Garmin activities.

    Args:
        limit: Number of activities to return (default 10).
        activity_type: Optional filter e.g. 'running', 'cycling'.
    """
    data = load_json(DATA_DIR / "garmin" / "activities.json")
    if not data:
        return "No activities data available."

    activities = data if isinstance(data, list) else data.get("activities", [])

    if activity_type:
        activities = [
            a for a in activities
            if activity_type.lower() in (a.get("activityType", {}).get("typeKey", "") or "").lower()
        ]

    activities = activities[:limit]
    if not activities:
        return f"No activities found{f' of type {activity_type}' if activity_type else ''}."

    lines = [f"## Recent Activities ({len(activities)})"]
    for a in activities:
        start    = a.get("startTimeLocal", "")[:16]
        name     = a.get("activityName", "Activity")
        dist_km  = (a.get("distance") or 0) / 1000
        speed    = a.get("averageSpeed") or 0
        avg_hr   = a.get("averageHR")
        duration = a.get("duration") or 0

        line = f"- **{start}** {name}"
        if dist_km:
            line += f" — {dist_km:.1f} km"
        if speed:
            line += f" @ {fmt_pace(speed)}"
        if duration:
            line += f" ({fmt_duration(duration)})"
        if avg_hr:
            line += f" HR:{int(avg_hr)}"
        lines.append(line)

    return "\n".join(lines)


@mcp.tool()
def get_calendar(days: int = 14) -> str:
    """Get upcoming Google Calendar events that may affect training.

    Args:
        days: Number of days ahead to look (default 14).
    """
    data = load_json(DATA_DIR / "calendar" / "events_by_date.json")
    if not data:
        return "No calendar data available."

    today = date.today()
    lines = [f"## Calendar — next {days} days"]
    found = False

    for offset in range(days):
        d = (today + timedelta(days=offset)).isoformat()
        events = data.get(d, [])
        if events:
            lines.append(f"\n**{d}**")
            for e in events:
                title    = e.get("summary", "Untitled")
                all_day  = e.get("all_day", False)
                start    = e.get("start", "")
                end      = e.get("end", "")
                time_str = "all day" if all_day else f"{start}–{end}"
                lines.append(f"  - {title} ({time_str})")
            found = True

    if not found:
        lines.append("No events in this period.")
    return "\n".join(lines)


@mcp.tool()
def get_training_impacts() -> str:
    """Get calendar-derived training impact flags (travel, jet lag, busy periods)."""
    impacts  = load_json(DATA_DIR / "calendar" / "training_impacts.json")
    jet_lag  = load_json(DATA_DIR / "garmin" / "jet_lag_flags.json")
    today    = date.today().isoformat()
    lines    = ["## Training Impacts"]

    if impacts:
        upcoming = {k: v for k, v in impacts.items() if k >= today}
        if upcoming:
            for d, impact in sorted(upcoming.items())[:14]:
                lines.append(f"- **{d}**: {impact}")
        else:
            lines.append("No upcoming training impacts.")
    else:
        lines.append("No training impacts data.")

    if jet_lag:
        upcoming_jl = {k: v for k, v in jet_lag.items() if k >= today}
        if upcoming_jl:
            lines.append("\n**Jet Lag Flags:**")
            for d, flag in sorted(upcoming_jl.items())[:7]:
                lines.append(f"- {d}: {flag.get('reason')} — no intensity: {flag.get('no_intensity')}")

    return "\n".join(lines)


@mcp.tool()
def get_race_predictions() -> str:
    """Get Garmin's predicted race finish times (5K, 10K, half marathon, marathon)."""
    data = load_json(DATA_DIR / "garmin" / "race_predictions.json")
    if not data:
        return "No race prediction data available."
    return f"## Race Predictions\n```json\n{json.dumps(data, indent=2)}\n```"


@mcp.tool()
def list_workouts() -> str:
    """List available built-in workout templates that can be pushed to Garmin."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "garmin_push.py"), "--workout-keys"],
        capture_output=True, text=True, cwd=str(SCRIPTS_DIR.parent)
    )
    if result.returncode == 0:
        return f"## Available Workouts\n{result.stdout}"
    return f"Error listing workouts:\n{result.stderr}"


@mcp.tool()
def push_workout(workout_key: str, date_str: str) -> str:
    """Push a structured workout to Garmin Connect and schedule it on the watch.

    Args:
        workout_key: Workout template key (use list_workouts to see options).
        date_str: Date to schedule in YYYY-MM-DD format.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "garmin_push.py"),
         "--workout", workout_key, "--date", date_str],
        capture_output=True, text=True, cwd=str(SCRIPTS_DIR.parent)
    )
    if result.returncode == 0:
        return f"Pushed '{workout_key}' to {date_str}\n{result.stdout}"
    return f"Error pushing workout:\n{result.stderr or result.stdout}"


@mcp.tool()
def trigger_sync() -> str:
    """Trigger a full data sync — pulls fresh data from Garmin, Strava, and Google Calendar."""
    results = []

    sync_tasks = [
        (
            "garmin_import.py",
            ["--credentials", str(CREDS_DIR / "garmin.json"),
             "--output", str(DATA_DIR / "garmin")]
        ),
        (
            "strava_import.py",
            ["--credentials", str(CREDS_DIR / "strava.json"),
             "--output", str(DATA_DIR / "strava")]
        ),
        (
            "calendar_import.py",
            ["--credentials", str(CREDS_DIR / "calendar.json"),
             "--output", str(DATA_DIR / "calendar")]
        ),
    ]

    for script_name, extra_args in sync_tasks:
        script = SCRIPTS_DIR / script_name
        if not script.exists():
            results.append(f"skip {script_name} (not found)")
            continue
        r = subprocess.run(
            [sys.executable, str(script)] + extra_args,
            capture_output=True, text=True, cwd=str(SCRIPTS_DIR.parent)
        )
        status = "ok" if r.returncode == 0 else "FAIL"
        results.append(f"{status}  {script_name}")
        if r.returncode != 0:
            results.append(f"     {r.stderr[:300]}")

    return "\n".join(results)


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
