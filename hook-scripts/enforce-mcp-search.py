#!/usr/bin/env python3
"""
PreToolUse hook: block Grep/Bash-grep in MCP-covered dirs when code-review-graph is available.
Exits 0 (silent pass) if no graph is reachable — safe for any project on any OS.
Exit 2 = Claude Code hard block; stdout is shown as the reason.

Resolution order:
  1. git rev-parse -> project_root -> check for .code-review-graph/graph.db
  2. If not in a git repo (e.g. /Users/Shared/Code), check CRG registered repos
     and treat as covered if cwd is a parent or child of a registered repo that has a graph.
"""
import sys
import json
import subprocess
import os
import re

PLUGIN_ROOT = os.environ.get(
    'CLAUDE_PLUGIN_ROOT',
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# Resolve CRG binary
if sys.platform == 'win32':
    CRG_BIN = os.path.join(PLUGIN_ROOT, 'servers', 'venv', 'Scripts', 'code-review-graph.exe')
else:
    CRG_BIN = os.path.join(PLUGIN_ROOT, 'servers', 'venv', 'bin', 'code-review-graph')

def get_git_root():
    try:
        r = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return ''

def get_registered_repos_with_graph():
    """Return list of registered repo paths that have a built graph.db."""
    if not os.path.exists(CRG_BIN):
        return []
    try:
        r = subprocess.run([CRG_BIN, 'repos'], capture_output=True, text=True, timeout=5)
        repos = []
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith('No repositories'):
                continue
            # Format: "  /path/to/repo  (alias)" or just "  /path/to/repo"
            path = line.split('(')[0].strip()
            if path and os.path.exists(path):
                db = os.path.join(path, '.code-review-graph', 'graph.db')
                if os.path.exists(db):
                    repos.append(path)
        return repos
    except Exception:
        return []

def find_active_repo():
    """Return (repo_root, graph_db) for the current context, or (None, None)."""
    cwd = os.getcwd()

    # Primary: git root with graph.db
    git_root = get_git_root()
    if git_root:
        db = os.path.join(git_root, '.code-review-graph', 'graph.db')
        if os.path.exists(db):
            return git_root, db

    # Fallback: cwd is parent of (or equal to) a registered repo, OR cwd is inside one
    for repo in get_registered_repos_with_graph():
        repo_real = os.path.realpath(repo)
        cwd_real = os.path.realpath(cwd)
        # cwd is inside registered repo, OR registered repo is inside cwd (parent dir case)
        if cwd_real.startswith(repo_real) or repo_real.startswith(cwd_real):
            return repo, os.path.join(repo, '.code-review-graph', 'graph.db')

    return None, None

project_root, graph_db = find_active_repo()
if not project_root:
    sys.exit(0)

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

tool = data.get('tool_name', '')
tool_input = data.get('tool_input', {})

BLOCK_MSG = f"""BLOCKED — code-review-graph MCP is available for {project_root}. Use these tools instead of grep:

STEP 1 — Load schemas (MCP tools are deferred; calling without this causes InputValidationError):
  ToolSearch(query="select:mcp__code-review-graph__semantic_search_nodes_tool,mcp__code-review-graph__query_graph_tool,mcp__code-review-graph__traverse_graph_tool")

STEP 2 — Then call one of:
  mcp__code-review-graph__semantic_search_nodes_tool(query="<term>", repo_root="{project_root}")
    → find functions/classes/files by name or keyword

  mcp__code-review-graph__query_graph_tool(pattern="callers_of", target="<name>", repo_root="{project_root}")
    → patterns: callers_of | callees_of | imports_of | importers_of | tests_for | file_summary

  mcp__code-review-graph__traverse_graph_tool(query="<term>", mode="bfs", depth=3, repo_root="{project_root}")
    → BFS/DFS exploration when semantic search returns 0 results

Do NOT fall back to grep. If all MCP searches return 0 results, set CONFIDENCE: low.

LIMITED SUBAGENT (no ToolSearch/MCP tools available, e.g. cavecrew-investigator): return an empty result with CONFIDENCE: low — do NOT retry with Grep. Ask the parent context to perform MCP search instead."""

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
