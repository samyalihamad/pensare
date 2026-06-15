#!/usr/bin/env bash
# Bundle the pensare kanban Lambda into a flat zip.
#
# The handler imports `kanban_core` and `storage` as top-level modules, so they
# must sit at the zip root (flat). boto3 is already in the Lambda runtime.
# algo_viz.{js,css} are bundled flat too — the handler reads them next to itself
# to render ```algo-viz blocks in /doc pages. Lambda entrypoint: lambda_handler.handler
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
OUT="$HERE/kanban-lambda.zip"

rm -f "$OUT"
( cd "$ROOT/lib" && zip -j -q "$OUT" storage.py kanban_core.py lambda_handler.py algo_viz.js algo_viz.css )
echo "Built $OUT ($(du -h "$OUT" | cut -f1))"
