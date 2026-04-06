#!/usr/bin/env python3
from __future__ import annotations
"""
Google Calendar importer.
Fetches Owen's private ICS feed and extracts upcoming events,
with a focus on travel, work blocks, and out-of-office days
that affect training planning.

Usage:
  python calendar_import.py \
    --credentials /path/to/calendar.json \
    --output /path/to/output/dir \
    --days 60
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

# CDT offset (UTC-5); handles Mar–Nov daylight saving for Bentonville, AR
CDT = timedelta(hours=-5)

# Keywords that suggest travel or schedule disruption
TRAVEL_KEYWORDS = [
    "flight", "fly", "travel", "hotel", "drive to", "trip", "offsite",
    "upfronts", "conference", "summit", "workshop", "miami", "dallas",
    "new york", "nyc", "chicago", "la ", "los angeles", "london",
    "bournemouth", "airport", "golf", "away", "move-in", "moving",
]

WORK_BLOCK_KEYWORDS = [
    "offsite", "strategy", "all hands", "all-hands", "board", "summit",
    "conference", "workshop", "retreat",
]


def load_credentials(creds_path: str) -> dict:
    with open(creds_path) as f:
        return json.load(f)


def save_json(data, output_dir: str, filename: str):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = os.path.join(output_dir, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def fetch_ics(url: str) -> str:
    try:
        with urlopen(url, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        raise RuntimeError(f"Could not fetch calendar: {e}")


def unfold(text: str) -> str:
    """Unfold RFC 5545 line continuations."""
    return re.sub(r"\r?\n[ \t]", "", text)


def parse_dt(value: str) -> tuple[datetime | None, bool]:
    """
    Parse a DTSTART/DTEND value. Returns (datetime, is_all_day).
    Naive datetimes are treated as UTC; 'Z' suffix confirmed UTC.
    All times converted to CDT (UTC-5).
    """
    value = value.strip()
    # Strip TZID= prefix if present (e.g. DTSTART;TZID=America/Chicago:...)
    if ":" in value:
        value = value.split(":")[-1]
    try:
        if "T" in value:
            ds = value[:15]
            dt = datetime.strptime(ds, "%Y%m%dT%H%M%S")
            # Treat as UTC → convert to CDT
            dt = dt + CDT
            return dt, False
        else:
            ds = value[:8]
            dt = datetime.strptime(ds, "%Y%m%d")
            return dt, True
    except ValueError:
        return None, False


def parse_events(ics_content: str, days_ahead: int = 60) -> list[dict]:
    content = unfold(ics_content)
    raw_events = re.split(r"BEGIN:VEVENT", content)[1:]

    now = datetime.utcnow() + CDT
    cutoff = now + timedelta(days=days_ahead)
    yesterday = now - timedelta(days=1)

    events = []
    for raw in raw_events:
        def field(name: str) -> str:
            m = re.search(rf"^{name}[^:]*:(.*)", raw, re.MULTILINE)
            return m.group(1).strip() if m else ""

        summary = field("SUMMARY")
        location = field("LOCATION")
        description = field("DESCRIPTION")
        uid = field("UID")
        status = field("STATUS")

        if status == "CANCELLED":
            continue

        dtstart_raw = field("DTSTART")
        dtend_raw = field("DTEND")

        dt_start, all_day = parse_dt(dtstart_raw)
        dt_end, _ = parse_dt(dtend_raw)

        if not dt_start:
            continue

        # Filter to window: yesterday → cutoff
        if dt_start < yesterday or dt_start > cutoff:
            continue

        # Classify
        text_lower = (summary + " " + location + " " + description).lower()
        is_travel = any(kw in text_lower for kw in TRAVEL_KEYWORDS)
        is_work_block = any(kw in text_lower for kw in WORK_BLOCK_KEYWORDS)
        is_multi_day = (
            all_day and dt_end and (dt_end - dt_start).days > 1
        ) if dt_end else False

        event = {
            "date": dt_start.strftime("%Y-%m-%d"),
            "time": None if all_day else dt_start.strftime("%H:%M"),
            "end_date": dt_end.strftime("%Y-%m-%d") if dt_end else None,
            "summary": summary,
            "location": location or None,
            "all_day": all_day,
            "multi_day": is_multi_day,
            "is_travel": is_travel,
            "is_work_block": is_work_block,
            "uid": uid,
        }
        events.append(event)

    # Deduplicate by uid (recurring events can repeat)
    seen = {}
    for e in sorted(events, key=lambda x: (x["date"], x["time"] or "")):
        key = e["uid"] or f"{e['date']}{e['summary']}"
        if key not in seen:
            seen[key] = e

    return list(seen.values())


def build_daily_index(events: list[dict]) -> dict:
    """Group events by date for easy lookup in morning briefing."""
    by_date = {}
    for e in events:
        d = e["date"]
        by_date.setdefault(d, []).append(e)
    return by_date


def flag_training_impacts(events: list[dict]) -> list[dict]:
    """
    Tag events that likely affect training.
    Returns a list of flagged dates with impact notes.
    """
    impacts = []
    for e in events:
        notes = []
        if e["is_travel"]:
            notes.append("travel day — check hotel/location for run route or gym")
        if e["multi_day"]:
            notes.append("multi-day block — plan training around availability")
        if e["all_day"] and not e["is_travel"] and not e["is_work_block"]:
            # Could be a personal commitment
            if any(kw in (e["summary"] or "").lower() for kw in ["move", "family", "wedding", "funeral", "vacation"]):
                notes.append("personal commitment — may affect training")
        if notes:
            impacts.append({
                "date": e["date"],
                "event": e["summary"],
                "notes": notes,
            })
    return impacts


def main():
    parser = argparse.ArgumentParser(description="Import Google Calendar events")
    parser.add_argument("--credentials", required=True, help="Path to calendar.json")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--days", type=int, default=60, help="Days ahead to import (default 60)")
    args = parser.parse_args()

    print(f"\n{'='*50}")
    print(f"Calendar Import: next {args.days} days")
    print(f"Output: {args.output}")
    print(f"{'='*50}\n")

    creds = load_credentials(args.credentials)
    ics_url = creds.get("google_calendar_ics")
    if not ics_url:
        print("ERROR: 'google_calendar_ics' key not found in credentials file")
        sys.exit(1)

    print("  Fetching Google Calendar...")
    ics_content = fetch_ics(ics_url)
    print(f"  ✓ Fetched ({len(ics_content):,} bytes)")

    # Save raw ICS
    Path(args.output).mkdir(parents=True, exist_ok=True)
    raw_path = os.path.join(args.output, "calendar.ics")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(ics_content)

    print("  Parsing events...")
    events = parse_events(ics_content, args.days)
    print(f"  ✓ {len(events)} upcoming events")

    save_json(events, args.output, "events.json")

    by_date = build_daily_index(events)
    save_json(by_date, args.output, "events_by_date.json")

    impacts = flag_training_impacts(events)
    save_json(impacts, args.output, "training_impacts.json")

    metadata = {
        "imported_at": datetime.now().isoformat(),
        "days_ahead": args.days,
        "event_count": len(events),
        "travel_days": [e["date"] for e in events if e["is_travel"]],
        "platform": "google_calendar",
    }
    save_json(metadata, args.output, "_import_metadata.json")

    print(f"\n  Travel / training-impact days flagged:")
    for imp in impacts:
        print(f"    {imp['date']}  {imp['event']}")
        for note in imp['notes']:
            print(f"             → {note}")

    print(f"\n✓ Calendar import complete → {args.output}")


if __name__ == "__main__":
    main()
