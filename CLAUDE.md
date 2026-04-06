# Health & Fitness Co-Work

Owen is a runner on a rolling plan co-built with Claude, using a Garmin Fenix 8.
Data syncs automatically at 6am daily via launchd. Credentials live in `.credentials/`.

## Opening move — Morning Briefing

When Owen starts a session (especially with a greeting or "morning"), read the data
and give a structured briefing without being asked. Cover:

1. **Yesterday** — planned workout (from Garmin calendar) vs actual (Garmin/Strava): distance,
   pace, avg HR. Was it completed? On target?
2. **Recovery** — last night's sleep score, HRV (lastNight), body battery peak.
   Flag anything notable (HRV drop >10%, sleep <6h, body battery peak <50).
3. **Today's plan** — what's scheduled on Garmin, key targets. Check calendar for
   conflicts or travel days that affect when/whether the session is realistic.
4. **Week ahead** — remaining scheduled sessions + any travel or schedule flags from
   the calendar (`data/calendar/training_impacts.json`). Surface conflicts early.

Keep the briefing tight — bullet points, no padding. Flag concerns, skip the obvious.

## Data locations

| What | Path |
|------|------|
| Garmin activities | `data/garmin/activities.json` |
| Garmin daily metrics (sleep, HRV, body battery, stress, steps, **readiness**) | `data/garmin/daily_metrics.json` |
| Body composition / smart scale (weight, body fat %, muscle mass) | `data/garmin/body_composition.json` |
| Training load + status (aerobic/anaerobic trend) | `data/garmin/training_status.json`, `training_load.json` |
| Race time predictions (5K / 10K / HM / marathon) | `data/garmin/race_predictions.json` |
| Jet lag flags (calendar-derived, 24h post-travel restriction) | `data/garmin/jet_lag_flags.json` |
| Strava activities | `data/strava/activities.json` |
| Google Calendar events (next 60 days) | `data/calendar/events_by_date.json` |
| Calendar training impact flags | `data/calendar/training_impacts.json` |
| Last sync timestamp | `data/last_import.json` |

### Reading daily_metrics.json

Keyed by date string (e.g. `"2026-04-04"`). Each day has:
- `resting_hr`, `avg_stress`, `vo2max`
- `hrv.hrvSummary.lastNight` — overnight HRV in ms
- `sleep.sleepTimeSeconds`, `sleep.sleepScores.overall.value`, `sleep.deepSleepSeconds`, `sleep.remSleepSeconds`
- `body_battery` — list of `{bodyBatteryLevel, ...}` readings; take `max()` for the day's peak
- `training_readiness` — Garmin's 0–100 readiness score. Green=70–100, Yellow=30–69, Red=<30
- `morning_readiness` — post-wake recalculation (most accurate for session planning)

### Reading race_predictions.json

Contains Garmin's predicted finish times. Key fields to check:
- Marathon predicted time → if >3:10:00, prioritize Critical Velocity intervals per the CEO-Athlete framework

### Reading jet_lag_flags.json

Keyed by date. Each entry: `{"jet_lag_risk": true, "reason": "travel_day"|"post_travel_24h", "no_intensity": bool}`
- `no_intensity: true` → do not prescribe high-intensity intervals (24h post-travel rule)
- Built from Google Calendar travel events — not a Garmin API field (not exposed by the API)

### Reading activities.json (Garmin)

Each activity has: `startTimeLocal`, `activityName`, `activityType.typeKey`, `distance` (meters),
`duration` (seconds), `averageSpeed` (m/s), `averageHR`, `maxHR`, `elevationGain`, `calories`,
`aerobicTrainingEffect`.

Pace from speed: `pace_min_per_km = 1000 / (speed_ms * 60)`.

## Owen's training context

- **Easy pace**: 5:45/km (~9:15/mi)
- **Interval pace**: ~4:05/km (~6:31/mi) for 800m reps
- **Tempo / marathon pace**: ~4:48/km (~7:45/mi)
- **HR zones**: easy = Z2, intervals = Z4–5
- Rolling plan is co-built with Claude and pushed directly to Garmin Connect
- Cadence baseline: high 160s (~166-169 spm), target: 175-178 spm

## Pushing workouts to Garmin

```bash
# List available built-in workouts
python3 import-scripts/garmin_push.py --workout-keys

# Push and schedule on a date
python3 import-scripts/garmin_push.py --workout rolling_800s --date 2026-04-07

# Push a full week plan from JSON
python3 import-scripts/garmin_push.py --plan week_plan.json

# See what's currently on Garmin Connect
python3 import-scripts/garmin_push.py --list
```

To add new workouts, edit `import-scripts/garmin_push.py` → `_builtin_workouts()`.
The `WorkoutBuilder` API is in `import-scripts/workout_builder.py`.

Week plan JSON format:
```json
[
  {"date": "2026-04-07", "workout": "rolling_800s"},
  {"date": "2026-04-09", "workout": "easy_run_10k"},
  {"date": "2026-04-12", "workout": "block_long_run_14mi"}
]
```

## Intervals.icu MCP (live training analysis)

When the Intervals.icu MCP is connected, use it for deeper analysis that the local files don't provide:

| Use MCP for | Don't need MCP for |
|-------------|-------------------|
| CTL / ATL / TSB (fitness/fatigue/form) | Daily readiness gate (use daily_metrics.json) |
| Power curves + peak effort analysis | Activities list (use activities.json) |
| Similar interval search across history | Sleep / HRV / body battery (use daily_metrics.json) |
| Real-time calendar event management | Workout push to Garmin (use garmin_push.py) |
| Activity time-series streams | Race predictions (use race_predictions.json) |

MCP setup files: `intervals-mcp/setup_intervals_mcp.command` (first-time) and `intervals-mcp/merge_mcp_config.py` (Claude Desktop config).

## Manual sync

```bash
./run_import.command          # pull Garmin + Strava + Calendar, update spreadsheet
./garmin_push.command         # interactive workout push (double-click friendly)
```

Auto-sync runs at 6am via launchd (`setup_launchagent.command` installs it).
Logs at `logs/daily_sync.log`.
