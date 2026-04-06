#!/bin/bash
# ============================================================
# Health & Fitness Data Import
# Double-click this file in Finder, or run it in Terminal.
# It will pull data from Garmin, Strava, and Runna, then
# update your health dashboard spreadsheet.
# ============================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$SCRIPT_DIR/import-scripts"
CREDS="$SCRIPT_DIR/.credentials"
DATA="$SCRIPT_DIR/data"
# Use the Python that has garminconnect installed
PYTHON=$(command -v /usr/local/bin/python3 || command -v python3)

# ---- Dates ------------------------------------------------
# Default: last 90 days. Change START_DATE / END_DATE to override.
END_DATE=$(date +%Y-%m-%d)
START_DATE=$(date -v-90d +%Y-%m-%d 2>/dev/null || date -d "90 days ago" +%Y-%m-%d)

# If last_import.json exists, sync only since last run
LAST_IMPORT="$DATA/last_import.json"
if [ -f "$LAST_IMPORT" ]; then
    LAST=$(python3 -c "import json; d=json.load(open('$LAST_IMPORT')); print(d.get('last_import',''))" 2>/dev/null)
    if [ -n "$LAST" ]; then
        # Step back 1 day to catch late-syncing activities
        START_DATE=$(python3 -c "from datetime import date, timedelta; print((date.fromisoformat('$LAST') - timedelta(days=1)).isoformat())" 2>/dev/null || echo "$LAST")
        echo "🔄  Incremental sync: $START_DATE → $END_DATE (1-day overlap)"
    fi
else
    echo "🔄  First run — importing last 90 days: $START_DATE → $END_DATE"
fi

echo ""

# ---- Python deps ------------------------------------------
echo "📦  Installing Python dependencies..."
pip3 install garminconnect openpyxl requests -q --break-system-packages 2>/dev/null || \
pip3 install garminconnect openpyxl requests -q
echo "    ✓ Dependencies ready"
echo ""

# ---- Garmin -----------------------------------------------
echo "🏃  Garmin Connect..."
if [ -f "$CREDS/garmin.json" ]; then
    mkdir -p "$DATA/garmin"
    $PYTHON "$SCRIPTS/garmin_import.py" \
        --credentials "$CREDS/garmin.json" \
        --output "$DATA/garmin" \
        --start "$START_DATE" --end "$END_DATE" || echo "  ⚠️  Garmin import failed — check credentials"
else
    echo "  ⚠️  No Garmin credentials found at $CREDS/garmin.json — skipping"
fi
echo ""

# ---- Strava -----------------------------------------------
echo "🚴  Strava..."
if [ -f "$CREDS/strava.json" ]; then
    mkdir -p "$DATA/strava"
    $PYTHON "$SCRIPTS/strava_import.py" \
        --credentials "$CREDS/strava.json" \
        --output "$DATA/strava" \
        --start "$START_DATE" --end "$END_DATE" || echo "  ⚠️  Strava import failed — check credentials"
else
    echo "  ⚠️  No Strava credentials found at $CREDS/strava.json — skipping"
fi
echo ""

# ---- Google Calendar --------------------------------------
echo "📆  Google Calendar..."
if [ -f "$CREDS/calendar.json" ]; then
    mkdir -p "$DATA/calendar"
    $PYTHON "$SCRIPTS/calendar_import.py" \
        --credentials "$CREDS/calendar.json" \
        --output "$DATA/calendar" \
        --days 60 || echo "  ⚠️  Calendar import failed"
else
    echo "  ⚠️  No calendar credentials found at $CREDS/calendar.json — skipping"
fi
echo ""

# ---- Save last import date --------------------------------
python3 -c "
import json, os
path = '$LAST_IMPORT'
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, 'w') as f:
    json.dump({'last_import': '$END_DATE', 'platforms': ['garmin', 'strava', 'calendar']}, f, indent=2)
"

echo "✅  Import complete! Data saved to: $DATA"
echo ""

# ---- Update spreadsheet -----------------------------------
echo "📊  Updating health dashboard spreadsheet..."
$PYTHON "$SCRIPTS/update_spreadsheet.py" \
    --data-dir "$DATA" \
    --output "$SCRIPT_DIR/health_dashboard.xlsx" \
    && echo "    ✓ health_dashboard.xlsx updated" \
    || echo "    ⚠️  Spreadsheet update failed — run manually if needed"
echo ""

# Only pause when run interactively (not via launchd/cron)
if [ -t 0 ]; then
    read -p "Press Enter to close..."
fi
