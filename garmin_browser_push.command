#!/bin/bash
# ============================================================
# Garmin Browser Push
# Serves a workout JSON on localhost so Claude in Chrome can
# inject it into Garmin Connect using your logged-in session.
#
# Usage:
#   1. Double-click this file (or run in Terminal)
#   2. Tell Claude which workout to push (and optional date)
#   3. Claude will handle the rest via Chrome
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$SCRIPT_DIR/import-scripts"
PORT=8766

# ── Dependency check ─────────────────────────────────────────
echo ""
echo "=============================================="
echo "  Garmin Browser Push"
echo "=============================================="
echo ""

pip3 install garminconnect openpyxl -q --break-system-packages 2>/dev/null || \
pip3 install garminconnect openpyxl -q

# ── Start server ─────────────────────────────────────────────
python3 - "$SCRIPTS" "$PORT" <<'PYEOF'
import http.server, json, os, sys, subprocess
from pathlib import Path

SCRIPTS_DIR = sys.argv[1]
PORT = int(sys.argv[2])

# Import workout library from garmin_push — single source of truth
sys.path.insert(0, SCRIPTS_DIR)
from garmin_push import _builtin_workouts
WORKOUTS = _builtin_workouts()

class Handler(http.server.BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        # /workout/<key>  — serve workout JSON
        # /workouts       — list available keys
        path = self.path.lstrip('/')

        if path == 'workouts':
            payload = json.dumps(list(WORKOUTS.keys())).encode()
            self.send_response(200)
            self._cors()
            self.end_headers()
            self.wfile.write(payload)
            return

        if path.startswith('workout/'):
            key = path[len('workout/'):]
            if key in WORKOUTS:
                payload = json.dumps(WORKOUTS[key]).encode()
                self.send_response(200)
                self._cors()
                self.end_headers()
                self.wfile.write(payload)
                print(f"  → Served: {key}  ({len(payload)} bytes)")
                return
            else:
                self.send_response(404)
                self._cors()
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Unknown workout key: {key}"}).encode())
                return

        self.send_response(404)
        self._cors()
        self.end_headers()

    def do_POST(self):
        # /result  — Chrome sends back the Garmin API response
        if self.path.lstrip('/') == 'result':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            self.send_response(200)
            self._cors()
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            try:
                result = json.loads(body)
                workout_id = result.get('workoutId') or result.get('workout', {}).get('workoutId')
                name = result.get('workoutName', '')
                if workout_id:
                    print(f"\n  ✅  Workout uploaded!")
                    print(f"      Name: {name}")
                    print(f"      ID:   {workout_id}")
                    print(f"\n  It will sync to your Fenix 8 shortly.")
                    print(f"  Check Garmin Connect → Workouts to confirm.\n")
                else:
                    print(f"\n  ⚠  Got response but no workout ID: {body.decode()[:200]}")
            except Exception as e:
                print(f"\n  Response: {body.decode()[:200]}")

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Type', 'application/json')

    def log_message(self, *a):
        pass  # suppress default request logging

print(f"  Available workouts:")
for k in WORKOUTS:
    print(f"    • {k}")
print(f"\n  Server ready on port {PORT}")
print(f"  Go back to Claude and tell it which workout to push.\n")
print(f"  Don't close this window until you see ✅\n")

http.server.HTTPServer(('localhost', PORT), Handler).serve_forever()
PYEOF
