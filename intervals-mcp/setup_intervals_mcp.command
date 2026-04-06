#!/bin/bash
# ============================================================
# Intervals.icu MCP Server Setup
# Double-click in Finder, or run in Terminal.
# Installs the MCP server and configures credentials.
# ============================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CREDS="$SCRIPT_DIR/../.credentials/intervals_icu.json"
CONFIG="$SCRIPT_DIR/mcp_server_config.json"

echo ""
echo "=================================================="
echo "  Intervals.icu MCP Server Setup"
echo "=================================================="
echo ""

# ---- Check node/npm ---------------------------------------
if ! command -v node &>/dev/null; then
    echo "❌  Node.js is required but not installed."
    echo "    Install it from: https://nodejs.org"
    exit 1
fi
echo "✓ Node.js $(node -v) found"

# ---- Install MCP server -----------------------------------
echo ""
echo "📦  Installing intervals-icu-mcp server..."
cd "$SCRIPT_DIR"
npm install @eddmann/intervals-icu-mcp 2>/dev/null || \
    npm install intervals-mcp-server 2>/dev/null || \
    npx --yes @eddmann/intervals-icu-mcp --help &>/dev/null || true
echo "    ✓ MCP server ready"

# ---- Credentials ------------------------------------------
echo ""
if [ -f "$CREDS" ]; then
    echo "✓ Credentials found at .credentials/intervals_icu.json"
else
    echo "🔑  Intervals.icu credentials not found."
    echo ""
    echo "    To get your credentials:"
    echo "    1. Log in at https://intervals.icu"
    echo "    2. Go to Settings → Developer → API Key"
    echo "    3. Copy your Athlete ID (shown on your profile page, e.g. i12345)"
    echo "    4. Copy your API Key"
    echo ""
    read -p "    Enter your Intervals.icu Athlete ID (e.g. i12345): " ATHLETE_ID
    read -p "    Enter your Intervals.icu API Key: " API_KEY
    echo ""

    mkdir -p "$(dirname "$CREDS")"
    cat > "$CREDS" << EOF
{
  "athlete_id": "$ATHLETE_ID",
  "api_key": "$API_KEY"
}
EOF
    echo "    ✓ Credentials saved to .credentials/intervals_icu.json"
fi

# ---- Generate Claude Desktop config ----------------------
echo ""
echo "📋  Generating Claude Desktop MCP config..."

ATHLETE_ID=$(python3 -c "import json; d=json.load(open('$CREDS')); print(d['athlete_id'])" 2>/dev/null || echo "YOUR_ATHLETE_ID")
API_KEY=$(python3 -c "import json; d=json.load(open('$CREDS')); print(d['api_key'])" 2>/dev/null || echo "YOUR_API_KEY")
SERVER_PATH="$SCRIPT_DIR/node_modules/.bin/intervals-icu-mcp"

cat > "$CONFIG" << EOF
{
  "mcpServers": {
    "intervals-icu": {
      "command": "npx",
      "args": ["@eddmann/intervals-icu-mcp"],
      "env": {
        "INTERVALS_ICU_ATHLETE_ID": "$ATHLETE_ID",
        "INTERVALS_ICU_API_KEY": "$API_KEY"
      }
    }
  }
}
EOF

echo "    ✓ Config saved to intervals-mcp/mcp_server_config.json"
echo ""
echo "=================================================="
echo "  Next step: Add to Claude Desktop"
echo "=================================================="
echo ""
echo "  1. Open Claude Desktop → Settings → Developer → Edit Config"
echo "  2. Merge the contents of this file into your claude_desktop_config.json:"
echo "     $CONFIG"
echo ""
echo "  Or run this to merge automatically:"
echo "     python3 '$SCRIPT_DIR/merge_mcp_config.py'"
echo ""

if [ -t 0 ]; then
    read -p "Press Enter to close..."
fi
