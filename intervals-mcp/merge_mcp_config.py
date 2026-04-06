#!/usr/bin/env python3
"""
Merges the Intervals.icu MCP server config into Claude Desktop's
claude_desktop_config.json automatically.

Usage:
    python3 merge_mcp_config.py
"""

import json
import os
import shutil
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
SERVER_CONFIG = SCRIPT_DIR / "mcp_server_config.json"

# Claude Desktop config location (macOS)
CLAUDE_CONFIG = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"


def main():
    print("\nMerging Intervals.icu MCP config into Claude Desktop...\n")

    # ── Validate server config exists ────────────────────────────────────────
    if not SERVER_CONFIG.exists():
        print("ERROR: mcp_server_config.json not found.")
        print("       Run setup_intervals_mcp.command first.")
        sys.exit(1)

    with open(SERVER_CONFIG) as f:
        new_config = json.load(f)

    new_servers = new_config.get("mcpServers", {})
    if not new_servers:
        print("ERROR: No mcpServers found in mcp_server_config.json")
        sys.exit(1)

    # ── Load or create Claude Desktop config ─────────────────────────────────
    CLAUDE_CONFIG.parent.mkdir(parents=True, exist_ok=True)

    if CLAUDE_CONFIG.exists():
        # Backup before modifying
        backup = CLAUDE_CONFIG.with_suffix(f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        shutil.copy(CLAUDE_CONFIG, backup)
        print(f"  ✓ Backup saved → {backup.name}")

        with open(CLAUDE_CONFIG) as f:
            claude_config = json.load(f)
    else:
        claude_config = {}
        print("  INFO: No existing Claude Desktop config found — creating new one")

    # ── Merge ─────────────────────────────────────────────────────────────────
    if "mcpServers" not in claude_config:
        claude_config["mcpServers"] = {}

    for server_name, server_def in new_servers.items():
        if server_name in claude_config["mcpServers"]:
            print(f"  ↻  Updating existing server: {server_name}")
        else:
            print(f"  +  Adding new server: {server_name}")
        claude_config["mcpServers"][server_name] = server_def

    # ── Save ──────────────────────────────────────────────────────────────────
    with open(CLAUDE_CONFIG, "w") as f:
        json.dump(claude_config, f, indent=2)

    print(f"\n  ✓ Config updated → {CLAUDE_CONFIG}")
    print("\n  ⚠️  Restart Claude Desktop to activate the new MCP server.")
    print("      File → Quit Claude, then reopen it.\n")


if __name__ == "__main__":
    main()
