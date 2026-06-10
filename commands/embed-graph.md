---
description: Generate vector embeddings for the code-review-graph to enable semantic search. Run once after `code-review-graph build`. Safe to re-run — only re-embeds changed nodes.
argument-hint: "[repo-path (optional — defaults to current repo)]"
allowed-tools: Bash(git *), Bash(ls *), Bash(echo *), mcp__code-review-graph__embed_graph_tool, mcp__plugin_jintech-omg-dev_code-review-graph__embed_graph_tool, ToolSearch
---

# /embed-graph

Use the MCP tool to compute vector embeddings for the code-review-graph.

Run directly in main context — no subagent needed.

## Step 1 — Detect repo

```bash
REPO_ROOT=$(git -C "$(pwd)" rev-parse --show-toplevel 2>/dev/null)
if [ -z "$REPO_ROOT" ]; then
  WS_ROOT="${OMG_WORKSPACE_ROOT:-/Users/Shared/Code}"
  for CANDIDATE in "$WS_ROOT/omg" "$WS_ROOT/omg_db" "$WS_ROOT/omg_ice"; do
    if git -C "$CANDIDATE" rev-parse --show-toplevel > /dev/null 2>&1; then
      REPO_ROOT=$(git -C "$CANDIDATE" rev-parse --show-toplevel); break
    fi
  done
fi
DB="$REPO_ROOT/.code-review-graph/graph.db"
[ -f "$DB" ] && echo "GRAPH_FOUND=yes ROOT=$REPO_ROOT" || echo "GRAPH_FOUND=no"
```

**If GRAPH_FOUND=no:** Stop. *"No graph.db found at $REPO_ROOT — run `code-review-graph build` first, then re-run /embed-graph."*

## Step 2 — Embed

Call the MCP tool:

```
mcp__code-review-graph__embed_graph_tool(repo_root="<REPO_ROOT>")
```

This uses the local `all-MiniLM-L6-v2` model (no API key required). Takes ~2-5 minutes for 8k nodes.

## Step 3 — Confirm

Output the result summary from the MCP tool response. Example:
```
Embedded 7605 nodes. Semantic search now active.
```

If the tool returns an error about `sentence-transformers` not installed:
```
Restart Claude Code so the MCP server reinstalls its venv (it self-installs sentence-transformers on first start)
Then re-run /embed-graph
```
