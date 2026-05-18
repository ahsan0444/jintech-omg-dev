#!/usr/bin/env bash
# PostToolUse hook: update the code-review-graph after every Edit or Write.
# Exits silently (0) if no graph DB found — safe for any project.

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
GRAPH_DB="${PROJECT_ROOT}/.code-review-graph/graph.db"

if [ ! -f "$GRAPH_DB" ]; then
  exit 0
fi

# Resolve CRG binary: prefer plugin venv, fall back to PATH
CRG="${CLAUDE_PLUGIN_ROOT}/servers/venv/bin/code-review-graph"
if [ ! -x "$CRG" ]; then
  CRG=$(command -v code-review-graph 2>/dev/null)
fi

if [ -z "$CRG" ]; then
  exit 0
fi

cd "$PROJECT_ROOT" && "$CRG" update --skip-flows 2>/dev/null
exit 0
