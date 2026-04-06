#!/bin/bash
# Starts a local server that receives Garmin data pulled from your browser.
# Run this first, then Claude will inject the data-pull script into Chrome.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$SCRIPT_DIR/data/garmin"
mkdir -p "$DATA_DIR"

python3 - "$DATA_DIR" <<'PYEOF'
import http.server, json, os, sys, threading
from pathlib import Path

DATA_DIR = sys.argv[1]
PORT = 8765
received = set()
expected = {"activities.json", "daily_metrics.json", "athlete_profile.json"}

class Handler(http.server.BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors(); self.end_headers()

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        filename = self.path.lstrip('/')
        filepath = os.path.join(DATA_DIR, filename)
        with open(filepath, 'wb') as f:
            f.write(body)
        received.add(filename)
        kb = len(body) / 1024
        print(f"  ✓ {filename}  ({kb:.1f} KB)")
        self.send_response(200); self._cors(); self.end_headers()
        self.wfile.write(b'{"ok":true}')
        if expected.issubset(received):
            print("\n✅  All Garmin data received — you can close this window.")
            threading.Timer(1.5, lambda: os.kill(os.getpid(), 9)).start()

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Type', 'application/json')

    def log_message(self, *a): pass

print(f"\n{'='*50}")
print(f"  Garmin Browser Pull — waiting on port {PORT}")
print(f"  Data will be saved to: {DATA_DIR}")
print(f"{'='*50}\n")
print("  Go back to Claude and tell it the server is running.")
print("  Don't close this window until you see ✅\n")

http.server.HTTPServer(('localhost', PORT), Handler).serve_forever()
PYEOF
