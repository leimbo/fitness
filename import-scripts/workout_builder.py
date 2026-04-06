#!/usr/bin/env python3
"""
workout_builder.py — Build structured Garmin Connect workouts from a clean spec.

Converts human-readable workout definitions (pace in min/km or min/mi, distance
in km or miles, HR targets, cadence targets) into the Garmin Connect workout JSON
format, ready for upload via garmin_push.py.

Usage:
    from workout_builder import WorkoutBuilder, Step, Repeat

    workout = (
        WorkoutBuilder("Rolling 800s", sport="running")
        .warmup(distance_km=0.8, pace_easy=True)
        .repeat(4,
            WorkoutBuilder.interval(distance_km=0.8, pace_min_per_km=4.05),
            WorkoutBuilder.recovery(distance_km=0.8, pace_easy=True),
        )
        .cooldown(distance_km=0.8, pace_easy=True)
        .build()
    )
"""

from __future__ import annotations
from typing import Any


# ── Pace / Speed helpers ──────────────────────────────────────────────────────

def pace_to_ms(pace_min_per_km: float) -> float:
    """Convert pace in min/km to m/s."""
    return 1000.0 / (pace_min_per_km * 60.0)

def pace_mi_to_ms(pace_min_per_mi: float) -> float:
    """Convert pace in min/mile to m/s."""
    return 1609.344 / (pace_min_per_mi * 60.0)

def ms_to_pace_km(speed_ms: float) -> float:
    """Convert m/s to min/km."""
    return 1000.0 / (speed_ms * 60.0)

def pace_window(pace_min_per_km: float, tolerance: float = 0.15) -> tuple[float, float]:
    """
    Return (low_speed_ms, high_speed_ms) for a pace target with ±tolerance min/km.
    low speed = faster end, high speed = slower end.
    """
    fast = pace_to_ms(pace_min_per_km - tolerance)
    slow = pace_to_ms(pace_min_per_km + tolerance)
    return slow, fast   # Garmin: low=min speed, high=max speed


# ── Target builders ──────────────────────────────────────────────────────────

class Target:
    """Factory for Garmin workout target dicts."""

    @staticmethod
    def no_target() -> dict:
        return {
            "workoutTargetTypeId": 1,
            "workoutTargetTypeKey": "no.target",
            "displayOrder": 1,
        }

    @staticmethod
    def pace(pace_min_per_km: float, tolerance: float = 0.15) -> dict:
        """Speed/pace target. Garmin uses m/s internally."""
        low, high = pace_window(pace_min_per_km, tolerance)
        return {
            "workoutTargetTypeId": 5,
            "workoutTargetTypeKey": "speed.zone",
            "displayOrder": 5,
            "targetValueOne": low,
            "targetValueTwo": high,
        }

    @staticmethod
    def hr_zone(zone: int) -> dict:
        """Heart rate zone target (zone 1–5)."""
        assert 1 <= zone <= 5, "HR zone must be 1–5"
        return {
            "workoutTargetTypeId": 4,
            "workoutTargetTypeKey": "heart.rate.zone",
            "displayOrder": 4,
            "targetValueOne": zone,
            "targetValueTwo": zone,
        }

    @staticmethod
    def hr_range(min_bpm: int, max_bpm: int) -> dict:
        """Heart rate range target."""
        return {
            "workoutTargetTypeId": 4,
            "workoutTargetTypeKey": "heart.rate.zone",
            "displayOrder": 4,
            "targetValueOne": min_bpm,
            "targetValueTwo": max_bpm,
        }

    @staticmethod
    def cadence(spm: int, tolerance: int = 3) -> dict:
        """Cadence target in steps per minute."""
        return {
            "workoutTargetTypeId": 3,
            "workoutTargetTypeKey": "cadence",
            "displayOrder": 3,
            "targetValueOne": spm - tolerance,
            "targetValueTwo": spm + tolerance,
        }


# ── End condition builders ────────────────────────────────────────────────────

def _end_distance(distance_m: float) -> tuple[dict, float]:
    return (
        {"conditionTypeId": 1, "conditionTypeKey": "distance", "displayOrder": 1, "displayable": True},
        distance_m,
    )

def _end_time(seconds: float) -> tuple[dict, float]:
    return (
        {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True},
        seconds,
    )

def _end_lap() -> tuple[dict, float]:
    return (
        {"conditionTypeId": 3, "conditionTypeKey": "lap.button", "displayOrder": 3, "displayable": True},
        None,
    )


# ── Step type dicts ───────────────────────────────────────────────────────────

_STEP_TYPES = {
    "warmup":   {"stepTypeId": 1, "stepTypeKey": "warmup",   "displayOrder": 1},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown", "displayOrder": 2},
    "interval": {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
    "recovery": {"stepTypeId": 4, "stepTypeKey": "recovery", "displayOrder": 4},
    "rest":     {"stepTypeId": 5, "stepTypeKey": "rest",     "displayOrder": 5},
    "repeat":   {"stepTypeId": 6, "stepTypeKey": "repeat",   "displayOrder": 6},
    "active":   {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},  # alias
}


# ── Step builders ─────────────────────────────────────────────────────────────

def _make_step(
    step_order: int,
    step_kind: str,
    end_condition: dict,
    end_value: float | None,
    target: dict | None = None,
) -> dict:
    step: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": step_order,
        "stepType": _STEP_TYPES[step_kind],
        "endCondition": end_condition,
    }
    if end_value is not None:
        step["endConditionValue"] = end_value
    step["targetType"] = target if target else Target.no_target()
    return step

def _make_repeat(step_order: int, iterations: int, child_steps: list[dict]) -> dict:
    return {
        "type": "RepeatGroupDTO",
        "stepOrder": step_order,
        "stepType": _STEP_TYPES["repeat"],
        "numberOfIterations": iterations,
        "workoutSteps": child_steps,
        "endCondition": {
            "conditionTypeId": 7,
            "conditionTypeKey": "iterations",
            "displayOrder": 7,
        },
        "endConditionValue": float(iterations),
        "smartRepeat": False,
    }


# ── Easy pace constant (Owen's easy = ~5:30–6:00/km, use 5:45 centre) ────────
EASY_PACE_MIN_PER_KM = 5.75   # ~9:15/mi — comfortable aerobic


# ── WorkoutBuilder ────────────────────────────────────────────────────────────

class WorkoutBuilder:
    """
    Fluent builder for Garmin Connect structured workouts.

    All paces are in min/km unless noted. Distances in km.

    Example — Rolling 800s:
        w = (WorkoutBuilder("Rolling 800s — 5mi")
            .warmup(distance_km=1.2)
            .repeat(4,
                [WorkoutBuilder.interval(distance_km=0.8, pace_min_per_km=4.05),
                 WorkoutBuilder.recovery(distance_km=0.8)])
            .cooldown(distance_km=0.8)
            .build())
    """

    def __init__(self, name: str, sport: str = "running", description: str = ""):
        self.name = name
        self.sport = sport
        self.description = description
        self._steps: list[dict] = []
        self._order = 1

    # ── Static step factories (for use inside repeat()) ──

    @staticmethod
    def interval(
        distance_km: float | None = None,
        duration_secs: float | None = None,
        pace_min_per_km: float | None = None,
        hr_zone: int | None = None,
        cadence_spm: int | None = None,
    ) -> dict:
        return WorkoutBuilder._step_spec("interval", distance_km, duration_secs, pace_min_per_km, hr_zone, cadence_spm)

    @staticmethod
    def recovery(
        distance_km: float | None = None,
        duration_secs: float | None = None,
        pace_min_per_km: float | None = None,
        pace_easy: bool = True,
    ) -> dict:
        pace = pace_min_per_km if pace_min_per_km else (EASY_PACE_MIN_PER_KM if pace_easy else None)
        return WorkoutBuilder._step_spec("recovery", distance_km, duration_secs, pace)

    @staticmethod
    def _step_spec(
        kind: str,
        distance_km: float | None,
        duration_secs: float | None,
        pace_min_per_km: float | None,
        hr_zone: int | None = None,
        cadence_spm: int | None = None,
    ) -> dict:
        """Return a step spec dict (resolved to final step dict later with order assigned)."""
        return {
            "_spec": True,
            "kind": kind,
            "distance_km": distance_km,
            "duration_secs": duration_secs,
            "pace_min_per_km": pace_min_per_km,
            "hr_zone": hr_zone,
            "cadence_spm": cadence_spm,
        }

    def _resolve_spec(self, spec: dict, order: int) -> dict:
        """Convert a _step_spec dict to a final Garmin step dict."""
        if spec.get("distance_km"):
            end_cond, end_val = _end_distance(spec["distance_km"] * 1000)
        elif spec.get("duration_secs"):
            end_cond, end_val = _end_time(spec["duration_secs"])
        else:
            end_cond, end_val = _end_lap()

        if spec.get("hr_zone"):
            target = Target.hr_zone(spec["hr_zone"])
        elif spec.get("cadence_spm"):
            target = Target.cadence(spec["cadence_spm"])
        elif spec.get("pace_min_per_km"):
            target = Target.pace(spec["pace_min_per_km"])
        else:
            target = Target.no_target()

        return _make_step(order, spec["kind"], end_cond, end_val, target)

    def _add(self, step: dict):
        self._steps.append(step)
        self._order += 1

    # ── Fluent methods ────────────────────────────────────────────────────────

    def warmup(
        self,
        distance_km: float | None = None,
        duration_secs: float | None = None,
        pace_min_per_km: float | None = None,
        cadence_spm: int | None = None,
    ) -> "WorkoutBuilder":
        pace = pace_min_per_km or EASY_PACE_MIN_PER_KM
        if cadence_spm:
            target = Target.cadence(cadence_spm)
        elif pace:
            target = Target.pace(pace)
        else:
            target = Target.no_target()

        if distance_km:
            ec, ev = _end_distance(distance_km * 1000)
        elif duration_secs:
            ec, ev = _end_time(duration_secs)
        else:
            ec, ev = _end_lap()

        self._add(_make_step(self._order, "warmup", ec, ev, target))
        return self

    def cooldown(
        self,
        distance_km: float | None = None,
        duration_secs: float | None = None,
        pace_min_per_km: float | None = None,
    ) -> "WorkoutBuilder":
        pace = pace_min_per_km or EASY_PACE_MIN_PER_KM
        if distance_km:
            ec, ev = _end_distance(distance_km * 1000)
        elif duration_secs:
            ec, ev = _end_time(duration_secs)
        else:
            ec, ev = _end_lap()
        self._add(_make_step(self._order, "cooldown", ec, ev, Target.pace(pace)))
        return self

    def easy(
        self,
        distance_km: float | None = None,
        duration_secs: float | None = None,
        pace_min_per_km: float | None = None,
        cadence_spm: int | None = None,
        hr_zone: int | None = None,
    ) -> "WorkoutBuilder":
        """Add a steady easy/active step (not warmup/cooldown framing)."""
        pace = pace_min_per_km or EASY_PACE_MIN_PER_KM
        if cadence_spm:
            target = Target.cadence(cadence_spm)
        elif hr_zone:
            target = Target.hr_zone(hr_zone)
        else:
            target = Target.pace(pace)

        if distance_km:
            ec, ev = _end_distance(distance_km * 1000)
        elif duration_secs:
            ec, ev = _end_time(duration_secs)
        else:
            ec, ev = _end_lap()
        self._add(_make_step(self._order, "active", ec, ev, target))
        return self

    def tempo(
        self,
        distance_km: float | None = None,
        duration_secs: float | None = None,
        pace_min_per_km: float | None = None,
    ) -> "WorkoutBuilder":
        if distance_km:
            ec, ev = _end_distance(distance_km * 1000)
        elif duration_secs:
            ec, ev = _end_time(duration_secs)
        else:
            ec, ev = _end_lap()
        target = Target.pace(pace_min_per_km) if pace_min_per_km else Target.no_target()
        self._add(_make_step(self._order, "interval", ec, ev, target))
        return self

    def repeat(self, iterations: int, steps: list[dict]) -> "WorkoutBuilder":
        """Add a repeat group. Steps are spec dicts from WorkoutBuilder.interval() etc."""
        child_steps = []
        child_order = 1
        for spec in steps:
            if spec.get("_spec"):
                child_steps.append(self._resolve_spec(spec, child_order))
            else:
                child_steps.append(spec)
            child_order += 1
        self._add(_make_repeat(self._order, iterations, child_steps))
        return self

    def rest(self, duration_secs: float) -> "WorkoutBuilder":
        ec, ev = _end_time(duration_secs)
        self._add(_make_step(self._order, "rest", ec, ev, Target.no_target()))
        return self

    # ── Build ─────────────────────────────────────────────────────────────────

    def build(self) -> dict:
        """Return the workout JSON dict ready for upload_workout()."""
        sport_map = {
            "running": {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1},
            "cycling": {"sportTypeId": 2, "sportTypeKey": "cycling", "displayOrder": 2},
            "swimming": {"sportTypeId": 5, "sportTypeKey": "swimming", "displayOrder": 5},
            "strength": {"sportTypeId": 3, "sportTypeKey": "strength_training", "displayOrder": 3},
        }
        sport_type = sport_map.get(self.sport, sport_map["running"])

        return {
            "workoutName": self.name,
            "description": self.description,
            "sportType": sport_type,
            "estimatedDurationInSecs": self._estimate_duration(),
            "workoutSegments": [
                {
                    "segmentOrder": 1,
                    "sportType": sport_type,
                    "workoutSteps": self._steps,
                }
            ],
        }

    def _estimate_duration(self) -> int:
        """Rough duration estimate in seconds for Garmin's metadata."""
        total = 0
        for step in self._steps:
            if step.get("type") == "ExecutableStepDTO":
                cond = step.get("endCondition", {}).get("conditionTypeKey")
                val = step.get("endConditionValue", 0) or 0
                if cond == "time":
                    total += val
                elif cond == "distance":
                    # assume ~5:30/km = 330s/km
                    total += (val / 1000) * 330
            elif step.get("type") == "RepeatGroupDTO":
                iters = step.get("numberOfIterations", 1)
                for sub in step.get("workoutSteps", []):
                    cond = sub.get("endCondition", {}).get("conditionTypeKey")
                    val = sub.get("endConditionValue", 0) or 0
                    if cond == "time":
                        total += val * iters
                    elif cond == "distance":
                        total += (val / 1000) * 330 * iters
        return int(total)


# ── Preset workout factory functions ─────────────────────────────────────────

def easy_run(name: str, distance_km: float, pace_min_per_km: float = EASY_PACE_MIN_PER_KM, cadence_spm: int | None = None) -> dict:
    """A simple easy run with optional cadence target."""
    b = WorkoutBuilder(name)
    b.warmup(distance_km=min(1.6, distance_km * 0.1))
    remainder = distance_km - min(1.6, distance_km * 0.1) - min(1.6, distance_km * 0.1)
    b.easy(distance_km=max(0.5, remainder), pace_min_per_km=pace_min_per_km, cadence_spm=cadence_spm)
    b.cooldown(distance_km=min(1.6, distance_km * 0.1))
    return b.build()


def rolling_800s(name: str = "Rolling 800s", reps: int = 4, interval_pace: float = 4.05, float_pace: float = 4.75) -> dict:
    """
    Rolling 800s: alternating 800m @ interval_pace / 800m @ float_pace.
    Default paces ~6:30/mi interval, ~7:40/mi float.
    """
    return (
        WorkoutBuilder(name, description=f"{reps}x 800m @ {interval_pace:.2f}/km / 800m float @ {float_pace:.2f}/km")
        .warmup(distance_km=0.8)
        .repeat(reps, [
            WorkoutBuilder.interval(distance_km=0.8, pace_min_per_km=interval_pace),
            WorkoutBuilder.recovery(distance_km=0.8, pace_min_per_km=float_pace),
        ])
        .cooldown(distance_km=0.8)
        .build()
    )


def block_long_run(name: str, easy_km: float, tempo_km: float, pace_easy: float = EASY_PACE_MIN_PER_KM, pace_tempo: float = 4.80) -> dict:
    """
    Block long run: easy / tempo block / easy.
    E.g. 6.4km easy → 9.7km @ marathon pace → 6.4km easy.
    """
    return (
        WorkoutBuilder(name, description=f"{easy_km:.1f}km easy / {tempo_km:.1f}km @ {pace_tempo:.2f}/km / {easy_km:.1f}km easy")
        .easy(distance_km=easy_km, pace_min_per_km=pace_easy)
        .tempo(distance_km=tempo_km, pace_min_per_km=pace_tempo)
        .easy(distance_km=easy_km, pace_min_per_km=pace_easy)
        .build()
    )


if __name__ == "__main__":
    import json

    # Demo: print a Rolling 800s workout JSON
    w = rolling_800s()
    print(json.dumps(w, indent=2))
