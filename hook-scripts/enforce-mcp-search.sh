#!/usr/bin/env bash
# Policy hook: block Grep/Bash-grep codebase searches when code-review-graph is available.
# Exits silently (0) if the graph DB is not present — safe for any project.
# Exit 2 = Claude Code hard block; Claude sees stdout as the reason.

# Guard: only enforce if a code-review-graph DB exists for this project
PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
GRAPH_DB="${PROJECT_ROOT}/.code-review-graph/graph.db"

if [ ! -f "$GRAPH_DB" ]; then
  exit 0
fi

INPUT=$(cat)
TOOL=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null)

BLOCK_MSG="BLOCKED — code-review-graph MCP is available. Use these tools instead of grep:
  mcp__code-review-graph__semantic_search_nodes_tool(query=\"<term>\", repo_root=\"<REPO_ROOT>\")
    → find functions/classes/files by name or keyword

  mcp__code-review-graph__query_graph_tool(pattern=\"callers_of\", target=\"<name>\", repo_root=\"<REPO_ROOT>\")
    → patterns: callers_of | callees_of | imports_of | importers_of | tests_for | file_summary

  mcp__code-review-graph__traverse_graph_tool(query=\"<term>\", mode=\"bfs\", depth=3, repo_root=\"<REPO_ROOT>\")
    → BFS/DFS exploration when semantic search returns 0 results

Do NOT fall back to grep. If all MCP searches return 0 results, set CONFIDENCE: low."

# views/ excluded: MCP has no Template Toolkit coverage — grep is the only way to find templates
MCP_COVERED_DIRS="/(lib|public/javascripts|t)(/|$)"

if [ "$TOOL" = "Grep" ]; then
  SEARCH_PATH=$(echo "$INPUT" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('path',''))" 2>/dev/null)
  if echo "$SEARCH_PATH" | grep -qE "$MCP_COVERED_DIRS"; then
    echo "$BLOCK_MSG"
    exit 2
  fi
fi

if [ "$TOOL" = "Bash" ]; then
  CMD=$(echo "$INPUT" | python3 -c \
    "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)
  if echo "$CMD" | grep -qE "grep.+/(lib|public/javascripts|t)(/|$)"; then
    echo "$BLOCK_MSG"
    exit 2
  fi
fi

exit 0
