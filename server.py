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
  create_events       — create/update Intervals.icu calendar events (workouts, notes, races)
  delete_events       — delete Intervals.icu calendar events by id or external_id
  update_event        — update a single Intervals.icu event
  update_wellness     — push wellness data (weight, HRV, steps, etc.) to Intervals.icu
  get_wellness        — read wellness data for a date range from Intervals.icu
"""

import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# ── Config ────────────────────────────────────────────────────────────────────
DATA_DIR    = Path(os.environ.get("DATA_DIR",    "./data"))
SCRIPTS_DIR = Path(os.environ.get("SCRIPTS_DIR", "./import-scripts"))
CREDS_DIR   = Path(os.environ.get("CREDS_DIR",   "./.credentials"))

ICU_ATHLETE_ID = os.environ.get("ICU_ATHLETE_ID", "i547993")
ICU_API_KEY    = os.environ.get("ICU_API_KEY", "")
ICU_BASE       = "https://intervals.icu/api/v1"

mcp = FastMCP("health-fitness")
mcp.settings.host = "0.0.0.0"
mcp.settings.port = int(os.environ.get("PORT", "8080"))


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


def _icu_auth_header() -> str:
    token = base64.b64encode(f"API_KEY:{ICU_API_KEY}".encode()).decode()
    return f"Basic {token}"


def _icu_request(method: str, path: str, body: Any = None) -> Any:
    """Make an authenticated request to the Intervals.icu API."""
    url = f"{ICU_BASE}/athlete/{ICU_ATHLETE_ID}/{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": _icu_auth_header(),
            "Content-Type": "application/json",
        }
    )
    try:
        with urllib.request.urlopen(req) as resp:
            resp_body = resp.read().decode()
            return json.loads(resp_body) if resp_body.strip() else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        raise RuntimeError(f"HTTP {e.code}: {err_body}") from e


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


# ── Intervals.icu write/read tools ────────────────────────────────────────────

@mcp.tool()
def create_events(events: list) -> str:
    """Create or update calendar events on Intervals.icu (workouts, notes, races).

    Uses upsert — if an event with the same external_id already exists it is updated,
    otherwise a new event is created. Workouts auto-sync to Garmin Connect if
    icu_garmin_upload_workouts is enabled on the account.

    Args:
        events: List of event objects. Each object must have:
            - category (str): WORKOUT, NOTE, RACE, or TARGET
            - start_date_local (str): ISO datetime e.g. "2026-04-08T00:00:00"
            - name (str): Display name on calendar
            - type (str): Activity type for WORKUTs — Run, Ride, WeightTraining,
              Swim, TrailRun, VirtualRide, etc.
            - description (str, optional): Workout text syntax for structured
              workouts e.g. "- 10m Z2\\n- 5x 3m Z4 1m Z1\\n- 5m Z1"
            - moving_time (int, optional): Duration in seconds
            - external_id (str, optional): Unique key for upsert; use "claude-"
              prefix to identify Claude-created events
            - color (str, optional): For notes — red, orange, yellow, green,
              blue, purple, gray
    """
    if not ICU_API_KEY:
        return "Error: ICU_API_KEY environment variable not set."
    if not events:
        return "Error: events list is empty."

    try:
        result = _icu_request("POST", "events/bulk?upsert=true", events)
    except RuntimeError as e:
        return f"Error creating events: {e}"

    if not isinstance(result, list):
        return f"Unexpected response: {result}"

    lines = [f"## Created/Updated {len(result)} event(s)"]
    for ev in result:
        ev_id    = ev.get("id", "?")
        name     = ev.get("name", "Untitled")
        date_str = (ev.get("start_date_local") or "")[:10]
        category = ev.get("category", "")
        ext_id   = ev.get("external_id", "")
        line = f"- **{date_str}** [{ev_id}] {name} ({category})"
        if ext_id:
            line += f" — `{ext_id}`"
        lines.append(line)

    return "\n".join(lines)


@mcp.tool()
def delete_events(events: list) -> str:
    """Delete Intervals.icu calendar events by id or external_id.

    Args:
        events: List of objects, each with either:
            - external_id (str): The external_id used when creating the event
            - id (int): The Intervals.icu numeric event id
    """
    if not ICU_API_KEY:
        return "Error: ICU_API_KEY environment variable not set."
    if not events:
        return "Error: events list is empty."

    try:
        result = _icu_request("PUT", "events/bulk-delete", events)
    except RuntimeError as e:
        return f"Error deleting events: {e}"

    count = result.get("count", result) if isinstance(result, dict) else result
    return f"Deleted {count} event(s)."


@mcp.tool()
def update_event(
    event_id: int,
    name: str = None,
    description: str = None,
    start_date_local: str = None,
    type: str = None,
    category: str = None,
    moving_time: int = None,
    color: str = None,
) -> str:
    """Update a single existing Intervals.icu calendar event (partial update).

    Only the fields you provide will be changed. Useful for rescheduling,
    renaming, or changing workout details without recreating the event.

    Args:
        event_id: Numeric Intervals.icu event id (required).
        name: New display name.
        description: New workout description (Intervals.icu text syntax).
        start_date_local: New date/time e.g. "2026-04-09T00:00:00".
        type: Activity type e.g. Run, Ride, WeightTraining.
        category: WORKOUT, NOTE, RACE, or TARGET.
        moving_time: Duration in seconds.
        color: For notes — red, orange, yellow, green, blue, purple, gray.
    """
    if not ICU_API_KEY:
        return "Error: ICU_API_KEY environment variable not set."

    payload: dict[str, Any] = {}
    if name             is not None: payload["name"]             = name
    if description      is not None: payload["description"]      = description
    if start_date_local is not None: payload["start_date_local"] = start_date_local
    if type             is not None: payload["type"]             = type
    if category         is not None: payload["category"]         = category
    if moving_time      is not None: payload["moving_time"]      = moving_time
    if color            is not None: payload["color"]            = color

    if not payload:
        return "Error: no fields provided to update."

    try:
        result = _icu_request("PUT", f"events/{event_id}", payload)
    except RuntimeError as e:
        return f"Error updating event {event_id}: {e}"

    updated_name = result.get("name", "?")
    updated_date = (result.get("start_date_local") or "")[:10]
    return f"Updated event {event_id}: **{updated_name}** on {updated_date}."


@mcp.tool()
def update_wellness(data: list) -> str:
    """Push wellness data (weight, HRV, sleep, steps, etc.) to Intervals.icu.

    Args:
        data: List of daily wellness objects. Each must have:
            - id (str): ISO date e.g. "2026-04-06" (required)
            - weight (float, optional): Body weight in kg
            - restingHR (int, optional): Resting heart rate in bpm
            - hrv (float, optional): HRV in ms
            - hrvSDNN (float, optional): HRV SDNN
            - sleepSecs (int, optional): Total sleep in seconds
            - sleepScore (int, optional): Sleep quality score 0–100
            - steps (int, optional): Step count
            - calories (int, optional): Total calories
            - spO2 (float, optional): Blood oxygen %
            - respiration (float, optional): Breaths per minute
    """
    if not ICU_API_KEY:
        return "Error: ICU_API_KEY environment variable not set."
    if not data:
        return "Error: data list is empty."

    try:
        result = _icu_request("PUT", "wellness-bulk", data)
    except RuntimeError as e:
        return f"Error updating wellness: {e}"

    if isinstance(result, list):
        dates = [r.get("id", "?") for r in result]
        return f"Updated wellness for {len(result)} day(s): {', '.join(dates)}."
    return f"Wellness updated: {result}"


@mcp.tool()
def get_wellness(oldest: str, newest: str) -> str:
    """Get wellness data from Intervals.icu for a date range.

    Args:
        oldest: Start date in YYYY-MM-DD format (inclusive).
        newest: End date in YYYY-MM-DD format (inclusive).
    """
    if not ICU_API_KEY:
        return "Error: ICU_API_KEY environment variable not set."

    try:
        result = _icu_request("GET", f"wellness?oldest={oldest}&newest={newest}")
    except RuntimeError as e:
        return f"Error fetching wellness: {e}"

    if not result:
        return f"No wellness data found between {oldest} and {newest}."

    entries = result if isinstance(result, list) else [result]
    lines = [f"## Wellness — {oldest} to {newest}"]
    for entry in entries:
        d      = entry.get("id", "?")
        weight = entry.get("weight")
        hrv    = entry.get("hrv")
        rhr    = entry.get("restingHR")
        sleep  = entry.get("sleepSecs")
        score  = entry.get("sleepScore")
        steps  = entry.get("steps")

        parts = []
        if weight  is not None: parts.append(f"weight={weight}kg")
        if rhr     is not None: parts.append(f"rHR={rhr}bpm")
        if hrv     is not None: parts.append(f"HRV={hrv}ms")
        if sleep   is not None: parts.append(f"sleep={int(sleep)//3600}h{(int(sleep)%3600)//60}m")
        if score   is not None: parts.append(f"sleepScore={score}")
        if steps   is not None: parts.append(f"steps={steps}")

        lines.append(f"- **{d}**: {', '.join(parts) if parts else '(no data)'}")

    return "\n".join(lines)


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run(transport="sse")
