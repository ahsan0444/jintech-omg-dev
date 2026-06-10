#!/usr/bin/env python3
"""
PreToolUse hook: block Grep/Bash-grep in MCP-covered dirs when code-review-graph is available.

Output contract (official PreToolUse JSON decision):
  - Allow:  exit 0, no output.
  - Block:  exit 0, stdout = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
            "permissionDecision": "deny", "permissionDecisionReason": "<shown to Claude>"}}
  This replaces the legacy stdout+exit-2 pattern (whose message must go to stderr,
  not stdout, to reach Claude — an easy contract to violate).

Fail-open: any error, missing graph, or non-matching tool → silent exit 0.

Resolution order:
  1. cwd from hook input (fall back to os.getcwd) → git root → .code-review-graph/graph.db
  2. If not in a git repo, check CRG registered repos and treat as covered if cwd
     is a parent or child of a registered repo that has a graph.
"""
import json
import os
import re
import subprocess
import sys

PLUGIN_ROOT = os.environ.get(
    'CLAUDE_PLUGIN_ROOT',
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

if sys.platform == 'win32':
    CRG_BIN = os.path.join(PLUGIN_ROOT, 'servers', 'venv', 'Scripts', 'code-review-graph.exe')
else:
    CRG_BIN = os.path.join(PLUGIN_ROOT, 'servers', 'venv', 'bin', 'code-review-graph')

# views/ excluded: MCP has no Template Toolkit coverage
MCP_COVERED = re.compile(r'[/\\](lib|public[/\\]javascripts|t)([/\\]|$)')


def get_git_root(cwd):
    try:
        r = subprocess.run(
            ['git', '-C', cwd, 'rev-parse', '--show-toplevel'],
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


def find_active_repo(cwd):
    """Return repo_root for the current context, or None."""
    git_root = get_git_root(cwd)
    if git_root:
        db = os.path.join(git_root, '.code-review-graph', 'graph.db')
        if os.path.exists(db):
            return git_root

    cwd_real = os.path.realpath(cwd)
    for repo in get_registered_repos_with_graph():
        repo_real = os.path.realpath(repo)
        # cwd is inside registered repo, OR registered repo is inside cwd (parent dir case)
        if cwd_real.startswith(repo_real) or repo_real.startswith(cwd_real):
            return repo
    return None


def block_message(project_root):
    return f"""BLOCKED — code-review-graph MCP is available for {project_root}. Use these tools instead of grep:

STEP 1 — Load schemas (MCP tools are deferred; calling without this causes InputValidationError):
  ToolSearch(query="select:mcp__code-review-graph__semantic_search_nodes_tool,mcp__code-review-graph__query_graph_tool,mcp__code-review-graph__traverse_graph_tool")

STEP 2 — Then call one of:
  mcp__code-review-graph__semantic_search_nodes_tool(query="<term>", repo_root="{project_root}")
    → find functions/classes/files by name or keyword

  mcp__code-review-graph__query_graph_tool(pattern="callers_of", target="<name>", repo_root="{project_root}")
    → patterns: callers_of | callees_of | imports_of | importers_of | tests_for | file_summary

  mcp__code-review-graph__traverse_graph_tool(query="<term>", mode="bfs", depth=3, repo_root="{project_root}")
    → BFS/DFS exploration when semantic search returns 0 results

Do NOT fall back to directory-wide grep. If all MCP searches return 0 results, set CONFIDENCE: low.
Exception: grep scoped to ONE explicit file (path ending in a filename with extension) is permitted.

LIMITED SUBAGENT (no ToolSearch/MCP tools available, e.g. cavecrew-investigator): return an empty result with CONFIDENCE: low — do NOT retry with Grep. Ask the parent context to perform MCP search instead."""


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main():
    # Parse input FIRST — skip all subprocess work for non-matching calls.
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool = data.get('tool_name', '')
    tool_input = data.get('tool_input', {})
    cwd = data.get('cwd') or os.getcwd()

    if tool == 'Grep':
        candidate = tool_input.get('path', '')
        if not MCP_COVERED.search(candidate):
            sys.exit(0)
        # Exemption: Grep scoped to a single existing file is a targeted
        # inspection (e.g. layer-convention checks), not a codebase search.
        if candidate and os.path.isfile(os.path.realpath(os.path.expanduser(candidate))):
            sys.exit(0)
    elif tool == 'Bash':
        candidate = tool_input.get('command', '')
        if not re.search(r'\bgrep\b.+[/\\]?(lib|public[/\\]javascripts|t)([/\\]|\s|$)', candidate):
            sys.exit(0)
    else:
        sys.exit(0)

    # Only now do the (subprocess-heavy) repo detection.
    project_root = find_active_repo(cwd)
    if not project_root:
        sys.exit(0)

    # Anchor to the active repo via canonical paths: realpath resolves macOS
    # /var → /private/var aliases and Windows 8.3 short names (RUNNER~1);
    # normcase folds Windows case and slash direction. Comparing canonical
    # forms beats enumerating root spellings in a regex — git emits
    # forward-slash paths on Windows while tempfile/tools emit backslashes,
    # and the two never regex-match each other.
    def _canon(p):
        try:
            return os.path.normcase(os.path.realpath(p))
        except Exception:
            return os.path.normcase(p)

    root_canon = _canon(project_root).rstrip('/\\')
    cwd_in_repo = _canon(cwd).startswith(root_canon)
    rel_covered = re.compile(r'^(lib|public[/\\]javascripts|t)([/\\]|$)')

    def covered_rel(rel):
        return bool(rel_covered.match(rel.lstrip('/\\').replace('\\', '/')))

    def covered_abs(p):
        c = _canon(os.path.expanduser(p))
        return c.startswith(root_canon + os.sep) and covered_rel(c[len(root_canon):])

    if tool == 'Grep':
        path = tool_input.get('path', '')
        if path and (
            covered_abs(path)
            or (cwd_in_repo and not os.path.isabs(path) and covered_rel(path))
        ):
            deny(block_message(project_root))
    elif tool == 'Bash':
        cmd = tool_input.get('command', '')
        # Collect command tokens that target covered dirs of THIS repo —
        # absolute tokens via canonical comparison, relative tokens only when
        # cwd is inside the repo. Avoids false blocks on /usr/lib etc.
        hits = []
        for tok in cmd.split():
            t = tok.strip('\'";,')
            if not t:
                continue
            if re.match(r'^([A-Za-z]:[/\\]|[/\\]|~)', t):
                if covered_abs(t):
                    hits.append(t)
            elif cwd_in_repo and rel_covered.match(t):
                hits.append(t)
        if hits:
            # Exemption: every covered-path token names an explicit file (or
            # file glob) with an extension — targeted single-file checks like
            # `grep -n 'bless' lib/foo/dao/foo_db.pm` or `grep -n 'route'
            # lib/OMG*.pm` are allowed; directory sweeps stay blocked.
            if all(re.search(r'\.\w{1,4}$', t) for t in hits):
                sys.exit(0)
            deny(block_message(project_root))

    sys.exit(0)


if __name__ == '__main__':
    main()
