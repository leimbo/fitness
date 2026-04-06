#!/bin/bash
# Startup script for Fly.io deployment.
# Writes credentials from env vars to the persistent volume,
# seeds initial data if the volume is empty, then starts the MCP server.
set -e

echo "==> Setting up credentials..."
mkdir -p /data/.credentials

# Garmin (used by garmin_import.py and garmin_push.py)
if [ -n "$GARMIN_EMAIL" ] && [ -n "$GARMIN_PASSWORD" ]; then
  cat > /data/.credentials/garmin.json <<EOF
{"email": "$GARMIN_EMAIL", "password": "$GARMIN_PASSWORD"}
EOF
  echo "  garmin.json written"
fi

# Strava OAuth tokens
if [ -n "$STRAVA_CLIENT_ID" ]; then
  cat > /data/.credentials/strava.json <<EOF
{
  "client_id":     "$STRAVA_CLIENT_ID",
  "client_secret": "$STRAVA_CLIENT_SECRET",
  "access_token":  "$STRAVA_ACCESS_TOKEN",
  "refresh_token": "$STRAVA_REFRESH_TOKEN",
  "expires_at":    0
}
EOF
  echo "  strava.json written"
fi

# Google Calendar ICS URL
if [ -n "$CALENDAR_URL" ]; then
  cat > /data/.credentials/calendar.json <<EOF
{"ics_url": "$CALENDAR_URL"}
EOF
  echo "  calendar.json written"
fi

# Intervals.icu API key
if [ -n "$INTERVALS_API_KEY" ] && [ -n "$INTERVALS_ATHLETE_ID" ]; then
  cat > /data/.credentials/intervals_icu.json <<EOF
{"api_key": "$INTERVALS_API_KEY", "athlete_id": "$INTERVALS_ATHLETE_ID"}
EOF
  echo "  intervals_icu.json written"
fi

# Symlink so garmin_push.py finds credentials at its hardcoded path
ln -sfn /data/.credentials /app/.credentials

echo "==> Seeding initial data if volume is empty..."
if [ ! -f /data/garmin/daily_metrics.json ]; then
  echo "  Copying bundled data to /data..."
  cp -r /app/initial-data/. /data/
  echo "  Done."
else
  echo "  Volume already has data, skipping seed."
fi

echo "==> Starting MCP server..."
exec python /app/server.py
