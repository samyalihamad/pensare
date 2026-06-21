#!/bin/bash
# inject-rules.sh — SessionStart hook
# Injects the plugin's rules/*.md as additionalContext, because Claude Code does
# not auto-discover rules/ from plugin directories.
#
# Gated so the plugin doesn't spend tokens where pensare isn't actually in use:
#   - If no pensare project exists (~/.claude/contexts empty/absent), inject
#     nothing — saves the full rule payload on unrelated work.
#   - The S3 storage-backend rule is the largest and only matters when an
#     S3-backed project exists, so it's appended only in that case.

RULES_DIR="${CLAUDE_PLUGIN_ROOT}/rules"
[ ! -d "$RULES_DIR" ] && exit 0

CONTEXTS_DIR="${HOME}/.claude/contexts"
[ ! -d "$CONTEXTS_DIR" ] && exit 0

shopt -s nullglob
PROJECTS=("$CONTEXTS_DIR"/*/)
[ ${#PROJECTS[@]} -eq 0 ] && exit 0

# Only inject the S3 storage rule when at least one project is S3-backed.
HAS_S3=0
for proj in "${PROJECTS[@]}"; do
  src="${proj}sources.json"
  if [ -f "$src" ] && grep -q '"storage"[[:space:]]*:[[:space:]]*"s3"' "$src"; then
    HAS_S3=1
    break
  fi
done

CONTENT=""
for f in "$RULES_DIR"/*.md; do
  [ -f "$f" ] || continue
  if [ "$(basename "$f")" = "storage-backend.md" ] && [ "$HAS_S3" -eq 0 ]; then
    continue
  fi
  CONTENT="${CONTENT}$(cat "$f")\n\n"
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
