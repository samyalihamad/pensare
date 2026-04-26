#!/bin/bash
# inject-rules.sh — SessionStart hook
# Concatenates all *.md files from the plugin's rules/ directory and injects
# them as additionalContext. This is a workaround because Claude Code does not
# auto-discover rules/ from plugin directories.

RULES_DIR="${CLAUDE_PLUGIN_ROOT}/rules"
[ ! -d "$RULES_DIR" ] && exit 0

CONTENT=""
for f in "$RULES_DIR"/*.md; do
  [ -f "$f" ] && CONTENT="${CONTENT}$(cat "$f")\n\n"
done

[ -z "$CONTENT" ] && exit 0

ESCAPED=$(echo -e "$CONTENT" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')

cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": $ESCAPED
  }
}
EOF
