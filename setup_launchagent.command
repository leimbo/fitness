#!/bin/bash
# ============================================================
# Health & Fitness — Daily Sync LaunchAgent Installer
# Double-click this file to install. Run it again to uninstall.
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IMPORT_SCRIPT="$SCRIPT_DIR/run_import.command"
PLIST_LABEL="com.health-fitness.daily-sync"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"

echo ""
echo "========================================"
echo "  Health & Fitness Daily Sync — Setup"
echo "========================================"
echo ""

# ---- Check if already installed ----
if [ -f "$PLIST_PATH" ]; then
    echo "✅  LaunchAgent is already installed."
    echo ""
    echo "Options:"
    echo "  1) Uninstall it"
    echo "  2) Reinstall / update"
    echo "  3) Cancel"
    echo ""
    read -p "Enter 1, 2, or 3: " choice
    case "$choice" in
        1)
            launchctl unload "$PLIST_PATH" 2>/dev/null
            rm "$PLIST_PATH"
            echo ""
            echo "🗑️   LaunchAgent uninstalled. Daily sync is now off."
            echo ""
            read -p "Press Enter to close..."
            exit 0
            ;;
        3)
            echo "Cancelled."
            exit 0
            ;;
        *)
            # Fall through to reinstall
            launchctl unload "$PLIST_PATH" 2>/dev/null
            ;;
    esac
fi

# ---- Verify run_import.command exists ----
if [ ! -f "$IMPORT_SCRIPT" ]; then
    echo "❌  Error: Could not find run_import.command at:"
    echo "    $IMPORT_SCRIPT"
    echo ""
    echo "Make sure this script is in the same folder as run_import.command."
    read -p "Press Enter to close..."
    exit 1
fi

chmod +x "$IMPORT_SCRIPT"

# ---- Write the plist ----
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$IMPORT_SCRIPT</string>
    </array>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>6</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>$SCRIPT_DIR/logs/daily_sync.log</string>

    <key>StandardErrorPath</key>
    <string>$SCRIPT_DIR/logs/daily_sync_error.log</string>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST

# ---- Create logs directory ----
mkdir -p "$SCRIPT_DIR/logs"

# ---- Load it ----
launchctl load "$PLIST_PATH"

if [ $? -eq 0 ]; then
    echo "✅  LaunchAgent installed and active!"
    echo ""
    echo "  Schedule: every day at 6:00 AM"
    echo "  Script:   $IMPORT_SCRIPT"
    echo "  Logs:     $SCRIPT_DIR/logs/daily_sync.log"
    echo ""
    echo "Your Garmin, Strava, and Runna data will sync automatically."
    echo "Run this script again if you ever want to uninstall it."
else
    echo "⚠️  LaunchAgent loaded with warnings — check Console.app if sync doesn't run."
fi

echo ""
read -p "Press Enter to close..."
