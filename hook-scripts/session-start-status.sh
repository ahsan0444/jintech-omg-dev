#!/usr/bin/env bash
# SessionStart hook: print code-review-graph status at the start of each session.
# Exits silently (0) if no graph DB found — safe for any project.

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
GRAPH_DB="${PROJECT_ROOT}/.code-review-graph/graph.db"

if [ ! -f "$GRAPH_DB" ]; then
  exit 0
fi

# Resolve CRG binary
CRG="${CLAUDE_PLUGIN_ROOT}/servers/venv/bin/code-review-graph"
if [ ! -x "$CRG" ]; then
  CRG=$(command -v code-review-graph 2>/dev/null)
fi

if [ -z "$CRG" ]; then
  echo "[jintech-omg-dev] code-review-graph binary not found — run: /plugin reinit jintech-omg-dev"
  exit 0
fi

cd "$PROJECT_ROOT" && "$CRG" status 2>/dev/null
exit 0
