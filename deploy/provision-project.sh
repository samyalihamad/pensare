#!/usr/bin/env bash
#
# Provision ONE pensare project for S3 storage (and optionally the online board).
# Cheap and fast — just an S3 prefix + a secret + a stub sources.json. Run
# deploy/bootstrap.sh once first.
#
# Usage:
#   deploy/provision-project.sh <project> [--kanban]
#
#   <project>   kebab-case project name
#   --kanban    also register the online kanban board (prints the private URL)
#
# Effects:
#   - generates (or reuses) a 256-bit board secret, stored at
#       ~/.claude/contexts/<project>/.board-secret   (local sidecar, gitignored)
#     and uploaded to  s3://<bucket>/contexts/<project>/.board-secret
#   - writes the local STUB ~/.claude/contexts/<project>/sources.json
#     (storage:s3 + s3{} [+ kanban_hosting{}]) and uploads it to S3
#   - seeds journal/manifest.json in S3 if absent
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA="$HERE/.pensare-infra.json"

PROJECT="${1:-}"
KANBAN=false
for a in "$@"; do [ "$a" = "--kanban" ] && KANBAN=true; done

if [ -z "$PROJECT" ] || [ "${PROJECT#-}" != "$PROJECT" ]; then
  echo "Usage: provision-project.sh <project> [--kanban]" >&2
  exit 1
fi
if [ ! -f "$INFRA" ]; then
  echo "No shared infra found ($INFRA). Run deploy/bootstrap.sh first." >&2
  exit 1
fi

read_infra() { python3 -c "import json,sys;print(json.load(open('$INFRA'))['$1'])"; }
BUCKET="$(read_infra bucket)"
REGION="$(read_infra region)"
FUNCTION_URL="$(read_infra function_url)"   # ends with '/'

BASE="$HOME/.claude/contexts/$PROJECT"
PREFIX="contexts/$PROJECT/"
mkdir -p "$BASE"

# ── Secret ───────────────────────────────────────────────────────────────────
if [ ! -s "$BASE/.board-secret" ]; then
  openssl rand -hex 32 > "$BASE/.board-secret"
  chmod 600 "$BASE/.board-secret"
fi
SECRET="$(cat "$BASE/.board-secret")"
aws s3 cp "$BASE/.board-secret" "s3://$BUCKET/${PREFIX}.board-secret" \
  --region "$REGION" --content-type text/plain >/dev/null

# ── Stub sources.json (merge if present) ─────────────────────────────────────
BOARD_URL=""
if $KANBAN; then
  BOARD_URL="${FUNCTION_URL}?project=${PROJECT}&k=${SECRET}"
fi

PROJECT="$PROJECT" BUCKET="$BUCKET" PREFIX="$PREFIX" REGION="$REGION" \
FUNCTION_URL="$FUNCTION_URL" BOARD_URL="$BOARD_URL" KANBAN="$KANBAN" \
python3 - "$BASE/sources.json" <<'PY'
import json, os, sys
path = sys.argv[1]
try:
    cfg = json.load(open(path))
except Exception:
    cfg = {}
cfg["storage"] = "s3"
cfg["s3"] = {
    "bucket": os.environ["BUCKET"],
    "prefix": os.environ["PREFIX"],
    "region": os.environ["REGION"],
}
if os.environ["KANBAN"] == "true":
    cfg["kanban_hosting"] = {
        "enabled": True,
        "board_url": os.environ["BOARD_URL"],
        "api_base": os.environ["FUNCTION_URL"].rstrip("/"),
        "secret_ref": "file:.board-secret",
    }
json.dump(cfg, open(path, "w"), indent=2)
open(path, "a").write("\n")
PY

# Upload authoritative sources.json (without committing the secret — it isn't in it).
aws s3 cp "$BASE/sources.json" "s3://$BUCKET/${PREFIX}sources.json" \
  --region "$REGION" --content-type application/json >/dev/null

# ── Seed journal manifest if absent ──────────────────────────────────────────
if ! aws s3api head-object --bucket "$BUCKET" --key "${PREFIX}journal/manifest.json" \
     --region "$REGION" >/dev/null 2>&1; then
  printf '%s' '{"version": 1, "hot_retention_days": 30, "hot_files": [], "kb_files": [], "last_compaction": null, "compaction_in_progress": false, "legacy_journal_migrated": false}' \
    | aws s3 cp - "s3://$BUCKET/${PREFIX}journal/manifest.json" \
      --region "$REGION" --content-type application/json >/dev/null
fi

echo "Provisioned '$PROJECT' for S3 storage."
echo "  bucket/prefix: s3://$BUCKET/$PREFIX"
if $KANBAN; then
  echo ""
  echo "  Online board (private — keep this URL secret):"
  echo "    $BOARD_URL"
fi
