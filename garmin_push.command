#!/bin/bash
# ============================================================
# Garmin Workout Push
# Double-click in Finder (or run in Terminal) to push a
# structured workout to Garmin Connect / Fenix 8.
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$SCRIPT_DIR/import-scripts"

echo ""
echo "=============================================="
echo "  Garmin Workout Push"
echo "=============================================="
echo ""

# ---- Dependencies -----------------------------------------
pip3 install garminconnect -q --break-system-packages 2>/dev/null || \
pip3 install garminconnect -q

# ---- Show available workouts ------------------------------
echo "Available workouts:"
python3 "$SCRIPTS/garmin_push.py" --workout-keys
echo ""

# ---- Prompt for action ------------------------------------
read -p "Enter workout key (or 'list' to see workouts on Garmin Connect): " WORKOUT_KEY

if [ -z "$WORKOUT_KEY" ]; then
    echo "No workout selected — exiting."
    read -p "Press Enter to close..."
    exit 0
fi

if [ "$WORKOUT_KEY" = "list" ]; then
    python3 "$SCRIPTS/garmin_push.py" --list
    echo ""
    read -p "Press Enter to close..."
    exit 0
fi

read -p "Schedule date YYYY-MM-DD (leave blank to upload without scheduling): " SCHEDULE_DATE

echo ""
if [ -n "$SCHEDULE_DATE" ]; then
    python3 "$SCRIPTS/garmin_push.py" --workout "$WORKOUT_KEY" --date "$SCHEDULE_DATE"
else
    python3 "$SCRIPTS/garmin_push.py" --workout "$WORKOUT_KEY"
fi

echo ""
read -p "Press Enter to close..."
