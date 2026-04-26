#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PLUGIN_NAME="pensare"
INSTALL_DIR="$HOME/.claude/plugins/$PLUGIN_NAME"
COMMANDS_DIR="$HOME/.claude/commands/$PLUGIN_NAME"
SETTINGS_FILE="$HOME/.claude/settings.json"

DEV_MODE=false
UNINSTALL=false

for arg in "$@"; do
  case "$arg" in
    --dev)       DEV_MODE=true ;;
    --uninstall) UNINSTALL=true ;;
  esac
done

# ── Uninstall ──────────────────────────────────────────────────────────────────

if [ "$UNINSTALL" = true ]; then
  rm -rf "$INSTALL_DIR" "$COMMANDS_DIR"
  echo "Pensare uninstalled."
  echo "Note: hooks remain in $SETTINGS_FILE — remove manually if desired."
  exit 0
fi

# ── Step 1: Install plugin files ───────────────────────────────────────────────

echo "Installing $PLUGIN_NAME..."

mkdir -p "$(dirname "$INSTALL_DIR")"

if [ "$DEV_MODE" = true ]; then
  ln -sfn "$SCRIPT_DIR" "$INSTALL_DIR"
  echo "  Dev mode: $INSTALL_DIR -> $SCRIPT_DIR"
else
  rm -rf "$INSTALL_DIR"
  mkdir -p "$INSTALL_DIR"
  cp -r "$SCRIPT_DIR/commands" "$SCRIPT_DIR/hooks" "$SCRIPT_DIR/rules" "$SCRIPT_DIR/templates" "$INSTALL_DIR/"
  [ -f "$SCRIPT_DIR/README.md" ] && cp "$SCRIPT_DIR/README.md" "$INSTALL_DIR/"
  [ -f "$SCRIPT_DIR/LICENSE"   ] && cp "$SCRIPT_DIR/LICENSE"   "$INSTALL_DIR/"
  echo "  Installed to $INSTALL_DIR"
fi

chmod +x "$INSTALL_DIR/hooks/inject-rules.sh"
chmod +x "$INSTALL_DIR/hooks/update-memory.py"

# ── Step 2: Register slash commands ────────────────────────────────────────────

mkdir -p "$COMMANDS_DIR"
find "$COMMANDS_DIR" -maxdepth 1 -name "*.md" -type l -delete 2>/dev/null || true
for f in "$INSTALL_DIR/commands/"*.md; do
  [ -f "$f" ] && ln -sf "$f" "$COMMANDS_DIR/$(basename "$f")"
done
echo "  Commands registered in $COMMANDS_DIR"

# ── Step 3: Merge hooks into settings.json ─────────────────────────────────────

python3 - "$SETTINGS_FILE" "$INSTALL_DIR" <<'PYEOF'
import sys, json, os
from pathlib import Path

settings_file = sys.argv[1]
install_dir   = sys.argv[2]

if os.path.exists(settings_file):
    with open(settings_file) as f:
        settings = json.load(f)
else:
    settings = {}

settings.setdefault("hooks", {})

inject_cmd = f"CLAUDE_PLUGIN_ROOT={install_dir} {install_dir}/hooks/inject-rules.sh"
memory_cmd = f"CLAUDE_PLUGIN_ROOT={install_dir} python3 {install_dir}/hooks/update-memory.py"

def has_command(hooks_list, cmd):
    return any(
        h.get("command") == cmd
        for group in hooks_list
        for h in group.get("hooks", [])
    )

settings["hooks"].setdefault("SessionStart", [])
if not has_command(settings["hooks"]["SessionStart"], inject_cmd):
    settings["hooks"]["SessionStart"].append({
        "hooks": [{"type": "command", "command": inject_cmd}]
    })

settings["hooks"].setdefault("PostToolUse", [])
if not has_command(settings["hooks"]["PostToolUse"], memory_cmd):
    settings["hooks"]["PostToolUse"].append({
        "matcher": "Write|Edit",
        "hooks": [{"type": "command", "command": memory_cmd}]
    })

Path(settings_file).parent.mkdir(parents=True, exist_ok=True)
with open(settings_file, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")

print(f"  Hooks configured in {settings_file}")
PYEOF

# ── Done ───────────────────────────────────────────────────────────────────────

echo ""
echo "Pensare installed. Start a new Claude Code session to activate."
echo ""
echo "Quick start:"
echo "  /pensare setup   — Create a new project"
echo "  /pensare load    — Load project context"
echo "  /pensare help    — Show all commands"
