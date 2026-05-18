#!/usr/bin/env bash
# Bootstraps and starts the code-review-graph MCP server.
# On first run: creates a plugin-local venv and pip-installs code-review-graph from PyPI.
# On subsequent runs: starts the already-installed server directly.
#
# Required env (set in plugin.json mcpServers.env or project .mcp.json):
#   CRG_DB_PATH  — path to the project's graph.db (defaults to .code-review-graph/graph.db)

set -e

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
VENV_DIR="${PLUGIN_ROOT}/servers/venv"
CRG_BIN="${VENV_DIR}/bin/code-review-graph"
CRG_VERSION="2.3.2"

# Install if not present or version mismatch
if [ ! -x "$CRG_BIN" ]; then
  echo "[jintech-omg-dev] Installing code-review-graph==${CRG_VERSION}..." >&2
  python3 -m venv "$VENV_DIR" >&2
  "$VENV_DIR/bin/pip" install --quiet "code-review-graph==${CRG_VERSION}" >&2
  echo "[jintech-omg-dev] Installation complete." >&2
fi

# Determine DB path — fall back to project root detection if env var not set
if [ -z "$CRG_DB_PATH" ]; then
  PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
  DB_PATH="${PROJECT_ROOT}/.code-review-graph/graph.db"
else
  DB_PATH="$CRG_DB_PATH"
fi

# Start MCP server
exec "$CRG_BIN" serve --db "$DB_PATH"
