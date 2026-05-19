#!/usr/bin/env python3
"""
PreToolUse hook: block Grep/Bash-grep in MCP-covered dirs when code-review-graph is available.
Exits 0 (silent pass) if no graph DB exists — safe for any project on any OS.
Exit 2 = Claude Code hard block; stdout is shown as the reason.
"""
import sys
import json
import subprocess
import os
import re

def get_project_root():
    try:
        r = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return ''

project_root = get_project_root()
if not project_root:
    sys.exit(0)

graph_db = os.path.join(project_root, '.code-review-graph', 'graph.db')
if not os.path.exists(graph_db):
    sys.exit(0)

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

tool = data.get('tool_name', '')
tool_input = data.get('tool_input', {})

BLOCK_MSG = """BLOCKED — code-review-graph MCP is available. Use these tools instead of grep:
  mcp__code-review-graph__semantic_search_nodes_tool(query="<term>", repo_root="<REPO_ROOT>")
    → find functions/classes/files by name or keyword

  mcp__code-review-graph__query_graph_tool(pattern="callers_of", target="<name>", repo_root="<REPO_ROOT>")
    → patterns: callers_of | callees_of | imports_of | importers_of | tests_for | file_summary

  mcp__code-review-graph__traverse_graph_tool(query="<term>", mode="bfs", depth=3, repo_root="<REPO_ROOT>")
    → BFS/DFS exploration when semantic search returns 0 results

Do NOT fall back to grep. If all MCP searches return 0 results, set CONFIDENCE: low."""

# views/ excluded: MCP has no Template Toolkit coverage
MCP_COVERED = re.compile(r'[/\\](lib|public[/\\]javascripts|t)([/\\]|$)')

if tool == 'Grep':
    path = tool_input.get('path', '')
    if MCP_COVERED.search(path):
        print(BLOCK_MSG)
        sys.exit(2)

if tool == 'Bash':
    cmd = tool_input.get('command', '')
    if re.search(r'grep.+[/\\](lib|public[/\\]javascripts|t)([/\\]|$)', cmd):
        print(BLOCK_MSG)
        sys.exit(2)

sys.exit(0)
