# An AI-Powered Training System for Owen

*How this Cowork setup uses Claude, structured philosophy docs, and Garmin/Strava integrations to manage a rolling running plan — day to day, week to week.*

---

## What This Is

This is a self-coaching system where Claude acts as a training partner and execution layer — not replacing your judgment, but handling the repetitive, detail-heavy work of building workouts, reviewing data, managing calendar conflicts, and keeping the plan consistent. You make the decisions. Claude does the execution.

The whole thing runs on three pieces:

1. **Cowork (Claude)** — a persistent workspace with training context, philosophy docs, auto-memory, and conversation history
2. **Garmin + Strava + Google Calendar** — the data layer where activity, recovery, and schedule information lives
3. **garmin_push.py** — the bridge that lets Claude write structured workouts directly to Garmin Connect, which sync automatically to your Fenix 8

No external app subscriptions. No custom UI. Just Claude, well-written documents, and a clean data pipeline.

---

## The Architecture

```
┌─────────────────────────────────────────────────┐
│              Cowork Session                      │
│                                                  │
│  ┌──────────────────┐  ┌──────────────────────┐  │
│  │  CLAUDE.md       │  │  Auto-Memory         │  │
│  │  (project rules) │  │  - User profile      │  │
│  │  - Data paths    │  │  - Feedback history  │  │
│  │  - Pace targets  │  │  - Project context   │  │
│  │  - Push commands │  └──────────────────────┘  │
│  └──────────────────┘                            │
│                                                  │
│  ┌────────────────────────────────────────────┐  │
│  │  Data Layer (auto-synced at 6am daily)     │  │
│  │  - Garmin: activities, sleep, HRV, BB      │  │
│  │  - Strava: activity cross-reference        │  │
│  │  - Google Calendar: events + travel flags  │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  ┌────────────────────────────────────────────┐  │
│  │  garmin_push.py → Garmin Connect           │  │
│  │  - Write structured workouts               │  │
│  │  - Schedule on specific dates              │  │
│  │  - Push full week plans from JSON          │  │
│  └────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

### Why Persistent Context Matters

A regular Claude conversation starts from scratch every time. This setup maintains continuity through:

- **CLAUDE.md** — the project instruction file Claude reads on every session. Contains your pace targets, data paths, push commands, and the morning briefing protocol.
- **Auto-memory** — Claude's persistent memory system stores your profile, feedback, and project context across sessions. If you correct something ("don't stack hard days"), Claude remembers it next time.
- **Conversation history** — decisions made in previous sessions inform the current one. Claude knows what was built last week, what you've been flagging, and what's coming up.

---

## The Three Layers

### Layer 1: Training Philosophy (CLAUDE.md)

`CLAUDE.md` is the core instruction file for this project. It's what turns Claude from a generic AI into *your* training assistant. It currently encodes:

- **Data locations** — exactly where to find activities, daily metrics, calendar events, and body composition data
- **Owen's pace targets** — easy (5:45/km), interval (4:05/km for 800m reps), tempo/marathon (4:48/km)
- **HR zones** — easy = Z2, intervals = Z4–5
- **Cadence context** — baseline high 160s spm, target 175–178 spm
- **Morning briefing protocol** — the structure Claude follows when you open a session
- **Push commands** — how to get workouts onto your watch

**What's missing and worth adding over time:**

- Your periodization philosophy — how do you think about base vs. build vs. taper?
- Non-negotiables — what you always protect (e.g., never stack 2 hard days, long run is sacrosanct)
- A race / goal event calendar — so Claude can reason about training windows
- Recovery thresholds — what HRV/sleep numbers should trigger plan modifications?

The more specific CLAUDE.md gets, the better Claude performs. Vague guidance produces generic plans. Specific rules produce plans that actually match how you train.

### Layer 2: Workout Library (garmin_push.py)

The built-in workout library lives in `import-scripts/garmin_push.py → _builtin_workouts()`. Each workout is defined once, named, and can be scheduled to any date with a single command. Current library:

| Key | Workout | Description |
|-----|---------|-------------|
| `easy_run_cadence` | Easy Run — Cadence 172 | 10.5km @ 5:45/km with cadence target |
| `easy_run_6k` | Easy Run 6km | 6km @ 5:45/km |
| `easy_run_10k` | Easy Run 10km | 10km @ 5:45/km |
| `rolling_800s` | Rolling 800s — 5mi | 4 × 800m @ 4:05/km with float recovery |
| `block_long_run_14mi` | Block Long Run 14mi | 4mi easy + 6mi @ 7:45/mi tempo |
| `long_run_easy_hm` | Half Marathon Long Run | 21.1km at conversational pace |
| `test_short` | TEST — Short Easy Mile | For verifying end-to-end push |

**How to extend it:** Open `garmin_push.py` and add a new entry to `_builtin_workouts()`. The `WorkoutBuilder` API (in `workout_builder.py`) lets you chain warmup → intervals → recovery → cooldown steps with pace targets and cadence alerts. Once added, Claude can reference the key by name when building weekly plans.

Good candidates to add next:
- A 5km tempo run
- A progression long run (easy → marathon pace → easy)
- A strides/short acceleration session
- Race-week opener (20min easy + 4 × 30sec pickups)

### Layer 3: Data Integration (Auto-Sync Pipeline)

This is the equivalent of the MCP integration in Oz Racing's system. Instead of reading from Intervals.icu in real time, Owen's system pre-syncs data at 6am every day via a launchd job. Claude reads those local files at the start of every session.

**What syncs automatically:**

| Source | Data | File |
|--------|------|------|
| Garmin Connect | Activities, sleep, HRV, body battery, RHR, stress, steps, VO2max | `data/garmin/` |
| Garmin Connect | Body composition (weight, body fat %, muscle mass) | `data/garmin/body_composition.json` |
| Strava | Activity cross-reference | `data/strava/activities.json` |
| Google Calendar | Events next 60 days + travel flags | `data/calendar/` |

**Manual sync:**
```bash
./run_import.command    # re-pull everything and update the spreadsheet
```

**Pushing workouts to Garmin:**
```bash
# Single workout on a date
python3 import-scripts/garmin_push.py --workout rolling_800s --date 2026-04-07

# Full week from JSON
python3 import-scripts/garmin_push.py --plan week_plan.json

# See what's currently scheduled
python3 import-scripts/garmin_push.py --list
```

Week plan JSON format:
```json
[
  {"date": "2026-04-07", "workout": "rolling_800s"},
  {"date": "2026-04-09", "workout": "easy_run_10k"},
  {"date": "2026-04-12", "workout": "block_long_run_14mi"}
]
```

---

## What a Typical Session Looks Like

### Morning Briefing (Default Open)

**You say:** "Morning" or just open the session.

**Claude does automatically:**
1. Reads `data/garmin/daily_metrics.json` for last night's sleep score, HRV, and body battery peak
2. Reads `data/garmin/activities.json` for yesterday's completed activity
3. Compares actual vs. planned (distance, pace, avg HR)
4. Checks today's Garmin calendar for what's scheduled
5. Checks Google Calendar for any conflicts, travel days, or schedule flags affecting timing
6. Scans the week ahead for training impacts
7. Delivers a tight briefing — flags concerns, skips the obvious

### Building or Reviewing a Training Week

**You say:** "Let's review next week's plan" or "Build me a week."

**Claude does:**
1. Reads recent activities (last 7–14 days) to understand training load and any missed sessions
2. Checks recovery metrics (HRV trend, sleep scores, body battery)
3. Reads Google Calendar for the target week — flags travel days, early mornings, or back-to-back demanding days
4. References your pace targets and workout library
5. Proposes a week with specific sessions and dates, calling out any conflicts
6. Waits for your approval before pushing anything to Garmin

### Reviewing Completed Training

**You say:** "How did last week go?" or "Review my training."

**Claude does:**
1. Pulls all activities from the past 7 days
2. Compares actual vs. prescribed (distance, pace, HR)
3. Checks cadence data — flags sessions below 170 spm given the target of 175–178
4. Looks at compliance and effort quality
5. Reviews recovery trend over the week
6. Summarizes honestly: what's working, what needs attention, any patterns to address

### Pre-Travel / Race Planning

**You say:** "I'm in LA next weekend — map out training around it."

**Claude does:**
1. Reads the calendar block to understand timing constraints
2. Identifies the best windows for quality sessions before/after travel
3. Suggests route-friendly formats (easy runs work anywhere, long runs need planning)
4. Adjusts the week structure to protect the key sessions while being realistic about logistics
5. Gets your sign-off, then pushes to Garmin

---

## How to Evolve the System

### When to Update CLAUDE.md

Update the project instructions when:
- Your pace targets change (fitness improvements, race goal shifts)
- You want Claude to apply a new rule consistently (e.g., "always protect the long run", "HRV below 30 = mandatory easy day")
- You've added new workouts to the library and want Claude to know when to prescribe them
- You're entering a new training phase with different priorities

### When to Add Workouts to garmin_push.py

Add a new built-in workout when:
- You've run a session type manually and want it repeatable
- You're approaching a new training phase that needs sessions you haven't built yet
- Claude has been writing ad-hoc custom workout JSON — that's a signal it should be a named template

### Adding a Race / Goal Event

There's no formal race calendar in the system yet. When you have a goal event, tell Claude and it will factor it into weekly planning. For a more durable version, add a `data/calendar/goal_events.json` file with dates, priorities (A/B/C), and distance — then reference it in CLAUDE.md. Claude will use it to reason about training windows automatically.

---

## What Works Well, What Still Needs You

### What works well:
- **Morning briefings** — Claude reads the data and flags what matters without being asked
- **Calendar conflict detection** — travel days and schedule pressure surface automatically
- **Workout execution** — structured workouts land on your watch in the right format
- **Recovery awareness** — HRV drops and bad sleep get flagged before the plan goes sideways
- **Consistency** — Claude applies the same logic every session; nothing slips through because it was a casual conversation

### What still needs you:
- **Big calls** — phase transitions, dialing back volume during a stressful stretch, deciding whether to race or treat an event as a training day
- **Feel data** — how your legs actually felt, motivation, life stress. Claude can see the metrics, not the qualitative picture. Give it that context and it makes much better calls.
- **Philosophy evolution** — what you know about how your body responds changes over time. Keep CLAUDE.md updated to reflect current thinking, not just what was true six months ago.
- **Override judgment** — sometimes the data says go, your body says no. You're the authority.

### Practical notes:
- **garminconnect must be installed** to push workouts: `pip install garminconnect --break-system-packages`. If the push fails with an import error, that's why.
- **Session tokens save MFA** — after the first authenticated push, tokens are stored in `.credentials/garmin_tokens/` and MFA is skipped automatically.
- **CLAUDE.md is literal** — if a rule is in there, Claude follows it. Write rules with that in mind. "Flag HRV drops over 10%" means Claude will flag them every time, even when it's probably noise. Calibrate the thresholds to what actually matters to you.
- **Auto-memory accumulates** — Claude saves feedback, preferences, and context across sessions. If you've corrected something ("stop suggesting tempo runs mid-week"), it remembers. If something's stale or wrong, ask Claude to update or delete the memory.

---

## Quick Reference

### Push a single workout
```bash
python3 import-scripts/garmin_push.py --workout <key> --date YYYY-MM-DD
```

### Push a full week
```bash
python3 import-scripts/garmin_push.py --plan week_plan.json
```

### See what's on Garmin
```bash
python3 import-scripts/garmin_push.py --list
```

### Re-sync all data
```bash
./run_import.command
```

### Available workout keys
```bash
python3 import-scripts/garmin_push.py --workout-keys
```

---

*This system was built for Owen specifically — a runner on a rolling plan who travels frequently, trains in the mornings, and uses a Garmin Fenix 8. The key insight from Oz Racing's approach applies here too: Claude is only as good as the documents you give it. Keep CLAUDE.md sharp, keep the workout library growing, and the system gets better with every week of use.*
