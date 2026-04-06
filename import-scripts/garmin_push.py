#!/usr/bin/env python3
"""
garmin_push.py — Push structured workouts to Garmin Connect.

Authenticates using saved credentials (garmin.json) and session tokens,
then uploads one or more structured workouts and optionally schedules them
on specific dates. Uploaded workouts sync automatically to the Fenix 8.

Usage:
    # Push a single workout interactively (prompts for schedule date)
    python garmin_push.py --workout rolling_800s

    # Push and schedule on a specific date
    python garmin_push.py --workout easy_run_cadence --date 2026-04-09

    # Push a full week plan from a JSON file
    python garmin_push.py --plan week_plan.json

    # List workouts currently on Garmin Connect
    python garmin_push.py --list

    # Delete a workout by ID
    python garmin_push.py --delete 12345678

Credentials:
    Reads from import-scripts/garmin.json (same file as garmin_import.py).
    Session tokens saved to import-scripts/garmin_tokens/ — MFA only needed once.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

# ── Ensure import-scripts is on path for workout_builder ─────────────────────
sys.path.insert(0, str(Path(__file__).parent))

try:
    import garminconnect
except ImportError:
    print("ERROR: garminconnect not installed.")
    print("  Run: pip install garminconnect --break-system-packages")
    sys.exit(1)

from workout_builder import (
    WorkoutBuilder,
    easy_run,
    rolling_800s,
    block_long_run,
    EASY_PACE_MIN_PER_KM,
)


# ── Auth ──────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
CREDS_PATH = SCRIPT_DIR.parent / ".credentials" / "garmin.json"
TOKEN_DIR  = SCRIPT_DIR.parent / ".credentials" / "garmin_tokens"


def load_credentials() -> dict:
    if not CREDS_PATH.exists():
        print(f"ERROR: credentials not found at {CREDS_PATH}")
        sys.exit(1)
    with open(CREDS_PATH) as f:
        return json.load(f)


def get_client() -> garminconnect.Garmin:
    """Authenticate, reusing saved tokens if available (MFA only needed once)."""
    creds = load_credentials()

    if TOKEN_DIR.exists():
        print("  Found saved session — skipping MFA...")
        try:
            client = garminconnect.Garmin()
            client.login(tokenstore=str(TOKEN_DIR))
            print("  ✓ Authenticated via saved token")
            return client
        except Exception as e:
            print(f"  Token expired or invalid ({e}) — re-authenticating...")

    print("  Logging in with email/password...")
    print("  ⚠  Garmin will send a verification code to your email.")

    def prompt_mfa() -> str:
        print("\n" + "─" * 50)
        code = input("  Enter the Garmin MFA code from your email: ").strip()
        print("─" * 50)
        return code

    client = garminconnect.Garmin(
        creds["email"],
        creds["password"],
        is_cn=False,
        prompt_mfa=prompt_mfa,
    )
    client.login()

    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    client.client.dump(str(TOKEN_DIR))
    print(f"  ✓ Token saved → {TOKEN_DIR}")
    print("  Future runs will skip MFA automatically.")
    return client


# ── Strength workout helpers ──────────────────────────────────────────────────

def _strength_exercise(order: int, label: str) -> dict:
    """A strength exercise step — runs until the LAP button is pressed."""
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
        "endCondition": {
            "conditionTypeId": 3,
            "conditionTypeKey": "lap.button",
            "displayOrder": 3,
            "displayable": True,
        },
        "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1},
        "description": label,
    }


def _strength_rest(order: int, seconds: int = 90) -> dict:
    """A timed transition rest between strength exercises."""
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": {"stepTypeId": 5, "stepTypeKey": "rest", "displayOrder": 5},
        "endCondition": {
            "conditionTypeId": 2,
            "conditionTypeKey": "time",
            "displayOrder": 2,
            "displayable": True,
        },
        "endConditionValue": float(seconds),
        "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1},
    }


def _make_strength_workout(name: str, description: str, exercises: list) -> dict:
    """
    Build a strength workout dict. Each exercise step runs until LAP button press,
    followed by a 90s transition rest before the next exercise.
    Full sets/reps/weight details go in `description` (visible in Garmin Connect).
    """
    strength_sport = {"sportTypeId": 3, "sportTypeKey": "strength_training", "displayOrder": 3}
    steps = []
    order = 1
    for i, label in enumerate(exercises):
        steps.append(_strength_exercise(order, label))
        order += 1
        if i < len(exercises) - 1:
            steps.append(_strength_rest(order, 90))
            order += 1

    est_duration = len(exercises) * 300 + (len(exercises) - 1) * 90

    return {
        "workoutName": name,
        "description": description,
        "sportType": strength_sport,
        "estimatedDurationInSecs": est_duration,
        "workoutSegments": [{
            "segmentOrder": 1,
            "sportType": strength_sport,
            "workoutSteps": steps,
        }],
    }


# ── Built-in workout library ──────────────────────────────────────────────────
# Extend this as new sessions are built. Keyed by a short name for --workout flag.

def _builtin_workouts() -> dict[str, dict]:
    return {
        # Easy runs with cadence focus
        # Owen's baseline: high 160s (~166-169 spm), target: 175-178 spm
        "easy_run_cadence": easy_run(
            "Easy Run — Cadence 172",
            distance_km=10.5,
            pace_min_per_km=5.75,
            cadence_spm=172,
        ),
        "easy_run_6k": easy_run(
            "Easy Run 6km",
            distance_km=6.0,
            pace_min_per_km=5.75,
        ),
        "easy_run_10k": easy_run(
            "Easy Run 10km",
            distance_km=10.0,
            pace_min_per_km=5.75,
        ),

        # Intervals
        "rolling_800s": rolling_800s(
            name="Rolling 800s — 5mi",
            reps=4,
            interval_pace=4.05,   # ~6:31/mi
            float_pace=4.87,      # ~7:50/mi
        ),

        # Long runs
        "block_long_run_14mi": block_long_run(
            name="Block Long Run 14mi",
            easy_km=6.4,          # 4mi easy
            tempo_km=9.7,         # 6mi @ 7:45/mi
            pace_easy=5.75,
            pace_tempo=4.80,      # ~7:45/mi
        ),
        "long_run_easy_hm": (
            WorkoutBuilder("Half Marathon Long Run — Easy", description="13.1mi at conversational pace")
            .easy(distance_km=21.1, pace_min_per_km=5.75)
            .build()
        ),

        # Test workout — short, for verifying end-to-end
        "test_short": (
            WorkoutBuilder("TEST — Short Easy Mile", description="Test workout — safe to delete")
            .warmup(distance_km=0.4)
            .easy(distance_km=0.8)
            .cooldown(distance_km=0.4)
            .build()
        ),

        # ── Strength sessions ─────────────────────────────────────────────────
        # Mon: Upper body (swim speed) + core. Post-NWA Masters swim.
        # Each step runs until LAP button — do your 3 sets, then tap lap.
        "upper_body_lift": _make_strength_workout(
            name="Upper Body + Core — Mon",
            description=(
                "Post-swim. Tap LAP when done with each exercise (all 3 sets).\n"
                "1. Lat Pulldown wide grip — 3x12 @ 70 lbs\n"
                "2. Seated Cable Row — 3x12 @ 60 lbs\n"
                "3. Cable Face Pull — 3x15 @ 25 lbs\n"
                "4. Tricep Pushdown rope — 3x12 @ 35 lbs\n"
                "5. Cable Woodchop each side — 3x12 @ 20 lbs\n"
                "6. Plank — 3x40s (30s rest between sets)\n"
                "60s rest between sets on all other exercises.\n"
                "Report back which weights need adjusting."
            ),
            exercises=[
                "Lat Pulldown 3x12 @70lbs",
                "Seated Cable Row 3x12 @60lbs",
                "Cable Face Pull 3x15 @25lbs",
                "Tricep Pushdown 3x12 @35lbs",
                "Cable Woodchop 3x12 ea @20lbs",
                "Plank 3x40s",
            ],
        ),

        # Wed: Lower body (leg speed) + core. Post-NWA Masters swim.
        "lower_body_core_lift": _make_strength_workout(
            name="Lower Body + Core — Wed",
            description=(
                "Post-swim. Tap LAP when done with each exercise (all 3 sets).\n"
                "1. Leg Press — 3x12 @ 140 lbs\n"
                "2. Lying Hamstring Curl — 3x12 @ 50 lbs\n"
                "3. Leg Extension — 3x12 @ 50 lbs\n"
                "4. Standing Calf Raise — 3x15 @ 90 lbs\n"
                "5. Back Extension machine — 3x15 @ 40 lbs\n"
                "6. Ab Crunch machine — 3x15 @ 50 lbs\n"
                "60s rest between sets. Report weights back."
            ),
            exercises=[
                "Leg Press 3x12 @140lbs",
                "Hamstring Curl 3x12 @50lbs",
                "Leg Extension 3x12 @50lbs",
                "Calf Raise 3x15 @90lbs",
                "Back Extension 3x15 @40lbs",
                "Ab Crunch 3x15 @50lbs",
            ],
        ),

        # ── Z2 runs ───────────────────────────────────────────────────────────
        # Tue: 50 min easy. HR zone 2 target. Optional strides if HRV recovers.
        "easy_run_50min_z2": (
            WorkoutBuilder(
                "Easy Run 50min — Z2",
                description="50 min easy. HR zone 2 throughout — let pace come to you. Add 4x30s strides at end only if HRV >40."
            )
            .warmup(duration_secs=300)
            .easy(duration_secs=2400, hr_zone=2)
            .cooldown(duration_secs=300)
            .build()
        ),

        # Fri (travel): short easy run in LA
        "easy_run_35min_travel": (
            WorkoutBuilder(
                "Easy Run 35min — Travel",
                description="Travel run. Easy Z2. Explore LA. No pressure on pace or distance. Just move."
            )
            .warmup(duration_secs=300)
            .easy(duration_secs=1500, hr_zone=2)
            .cooldown(duration_secs=300)
            .build()
        ),

        # Sat (LA): moderate run — Z2 base with Z3 finish
        "moderate_run_55min": (
            WorkoutBuilder(
                "Moderate Run 55min — Z2/Z3 finish",
                description="55 min total. Warmup 5min, then 30min Z2, then 15min push into Z3 (elevated but not threshold), cooldown 5min."
            )
            .warmup(duration_secs=300)
            .easy(duration_secs=1800, hr_zone=2)
            .tempo(duration_secs=900)
            .cooldown(duration_secs=300)
            .build()
        ),
    }


# ── Core push functions ────────────────────────────────────────────────────────

def push_workout(client: garminconnect.Garmin, workout: dict, date_str: str | None = None) -> int:
    """Upload a workout and optionally schedule it. Returns workout ID."""
    name = workout.get("workoutName", "Unnamed")
    print(f"\n  Uploading: {name}")

    result = client.upload_workout(workout)

    # Extract workout ID from response
    workout_id = None
    if isinstance(result, dict):
        workout_id = result.get("workoutId") or result.get("workout", {}).get("workoutId")
    if workout_id is None:
        print(f"  ⚠  Could not determine workout ID from response: {result}")
        return -1

    print(f"  ✓ Uploaded — ID: {workout_id}")

    if date_str:
        client.schedule_workout(workout_id, date_str)
        print(f"  ✓ Scheduled for {date_str}")

    return workout_id


def push_week_plan(client: garminconnect.Garmin, plan_path: str):
    """
    Push a full week plan from a JSON file.

    Plan format:
    [
        {"date": "2026-04-07", "workout": "rolling_800s"},
        {"date": "2026-04-09", "workout": "easy_run_cadence"},
        {"date": "2026-04-11", "workout": "long_run_easy_hm"},
        {"date": "2026-04-07", "workout_json": { ...custom workout dict... }}
    ]
    """
    with open(plan_path) as f:
        plan = json.load(f)

    library = _builtin_workouts()
    results = []

    for entry in plan:
        date_str = entry.get("date")
        if "workout" in entry:
            key = entry["workout"]
            if key not in library:
                print(f"  ⚠  Unknown workout key '{key}' — skipping")
                continue
            workout = library[key]
        elif "workout_json" in entry:
            workout = entry["workout_json"]
        else:
            print(f"  ⚠  No workout defined for {date_str} — skipping")
            continue

        wid = push_workout(client, workout, date_str)
        results.append({"date": date_str, "workout_id": wid, "name": workout.get("workoutName")})

    print(f"\n  ✓ Plan complete — {len(results)} workouts pushed")
    for r in results:
        print(f"     {r['date']}  {r['name']}  (ID: {r['workout_id']})")


def list_workouts(client: garminconnect.Garmin, limit: int = 20):
    """Print workouts currently saved in Garmin Connect."""
    workouts = client.get_workouts(start=0, limit=limit)
    print(f"\n  {len(workouts)} workouts on Garmin Connect (most recent {limit}):\n")
    for w in workouts:
        wid   = w.get("workoutId", "?")
        name  = w.get("workoutName", "—")
        sport = w.get("sportType", {}).get("sportTypeKey", "?")
        print(f"  {wid:>12}  {sport:<12}  {name}")


def delete_workout(client: garminconnect.Garmin, workout_id: int):
    """Delete a workout from Garmin Connect by ID."""
    client.delete_workout(workout_id)
    print(f"  ✓ Deleted workout {workout_id}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Push structured workouts to Garmin Connect / Fenix 8",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python garmin_push.py --list
  python garmin_push.py --workout rolling_800s --date 2026-04-07
  python garmin_push.py --workout test_short
  python garmin_push.py --plan week_plan.json
  python garmin_push.py --delete 12345678
  python garmin_push.py --workout-keys
        """,
    )
    parser.add_argument("--workout",      help="Push a built-in workout by key name")
    parser.add_argument("--date",         help="Schedule date (YYYY-MM-DD) for --workout")
    parser.add_argument("--plan",         help="Push a full week plan from a JSON file")
    parser.add_argument("--list",         action="store_true", help="List workouts on Garmin Connect")
    parser.add_argument("--delete",       type=int, help="Delete workout by ID")
    parser.add_argument("--workout-keys", action="store_true", help="List available built-in workout keys")
    parser.add_argument("--print-json",   help="Print workout JSON without uploading (by key name)")

    args = parser.parse_args()

    # ── Print-only mode — no auth needed ─────────────────────────────────────
    if args.workout_keys:
        print("\nAvailable built-in workout keys:")
        for key in _builtin_workouts():
            print(f"  {key}")
        return

    if args.print_json:
        library = _builtin_workouts()
        if args.print_json not in library:
            print(f"Unknown key: {args.print_json}")
            sys.exit(1)
        print(json.dumps(library[args.print_json], indent=2))
        return

    if not any([args.workout, args.plan, args.list, args.delete]):
        parser.print_help()
        return

    # ── Auth ──────────────────────────────────────────────────────────────────
    print("\nConnecting to Garmin Connect...")
    client = get_client()

    # ── Dispatch ─────────────────────────────────────────────────────────────
    if args.list:
        list_workouts(client)

    elif args.delete:
        delete_workout(client, args.delete)

    elif args.plan:
        push_week_plan(client, args.plan)

    elif args.workout:
        library = _builtin_workouts()
        if args.workout not in library:
            print(f"\nERROR: Unknown workout key '{args.workout}'")
            print("Run --workout-keys to see available options.")
            sys.exit(1)
        push_workout(client, library[args.workout], args.date)

    print()


if __name__ == "__main__":
    main()
