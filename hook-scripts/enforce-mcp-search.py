#!/usr/bin/env python3
"""
PreToolUse hook: keep code-review-graph as the DEFAULT for codebase search, but
make the block STEERABLE and SELF-RELEASING so the graph's silence never reads as
established absence (the false-confidence trap).

Graph-first, then grep is the BLESSED path. grep is sanctioned (not merely
tolerated) when:
  1. Pattern is literal/multi-word (contains whitespace) — CRG indexes symbols and
     structure, not arbitrary substrings/comments, so grep is the right tool.
  2. The active graph is STALE: its build SHA != current HEAD (branch switch / pull),
     or, as a backstop, the graph.db is >3 days old. A fresh graph on a switched
     branch is the danger case, so SHA-mismatch is the primary trigger.
  3. A query-scoped breadcrumb exists: the graph was already queried for THIS target
     and returned empty (recorded by record-graph-empty.py). Consumed on use —
     one breadcrumb sanctions ONE grep for that target, then it's gone.

Covered dirs: lib/ (perl) and public/javascripts/ (js) — well-indexed structurally.
t/ is NOT blocked: CRG indexes it only thinly (a couple of nodes), so blocking grep
there would manufacture false absence.

Output contract (PreToolUse JSON): deny or allow with a visible reason; otherwise
silent exit 0. Fail-open on any error.
"""
import json
import os
import re
import subprocess
import sys
import time

PLUGIN_ROOT = os.environ.get(
    'CLAUDE_PLUGIN_ROOT',
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

if sys.platform == 'win32':
    CRG_BIN = os.path.join(PLUGIN_ROOT, 'servers', 'venv', 'Scripts', 'code-review-graph.exe')
else:
    CRG_BIN = os.path.join(PLUGIN_ROOT, 'servers', 'venv', 'bin', 'code-review-graph')

# t/ removed — CRG indexes it too thinly to justify blocking grep there.
# (^|sep) so relative paths like "lib/foo" are pre-filtered too, not just absolute.
MCP_COVERED = re.compile(r'(^|[/\\])(lib|public[/\\]javascripts)([/\\]|$)')
STALE_AGE_DAYS = 3
BREADCRUMB_TTL = 15 * 60


# ---------------------------------------------------------------- repo detection
def get_git_root(cwd):
    try:
        r = subprocess.run(['git', '-C', cwd, 'rev-parse', '--show-toplevel'],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return ''


def get_registered_repos_with_graph():
    if not os.path.exists(CRG_BIN):
        return []
    try:
        r = subprocess.run([CRG_BIN, 'repos'], capture_output=True, text=True, timeout=5)
        repos = []
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith('No repositories'):
                continue
            path = line.split('(')[0].strip()
            if path and os.path.exists(path):
                db = os.path.join(path, '.code-review-graph', 'graph.db')
                if os.path.exists(db):
                    repos.append(path)
        return repos
    except Exception:
        return []


def find_active_repo(cwd):
    git_root = get_git_root(cwd)
    if git_root:
        db = os.path.join(git_root, '.code-review-graph', 'graph.db')
        if os.path.exists(db):
            return git_root
    cwd_real = os.path.realpath(cwd)
    for repo in get_registered_repos_with_graph():
        repo_real = os.path.realpath(repo)
        if cwd_real.startswith(repo_real) or repo_real.startswith(cwd_real):
            return repo
    return None


# ---------------------------------------------------------------- staleness (SHA-first)
def graph_staleness(project_root):
    """Return a sanctioning reason string if the graph is stale, else ''.

    Primary signal: graph build SHA != current HEAD (branch switch / pull since
    build). Backstop: graph.db older than STALE_AGE_DAYS.
    """
    db = os.path.join(project_root, '.code-review-graph', 'graph.db')
    if not os.path.exists(db):
        return ''
    # SHA mismatch
    try:
        import sqlite3
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT value FROM metadata WHERE key='git_head_sha'").fetchone()
        conn.close()
        build_sha = (row[0] if row else '') or ''
        head = subprocess.run(['git', '-C', project_root, 'rev-parse', 'HEAD'],
                              capture_output=True, text=True, timeout=5)
        head_sha = head.stdout.strip() if head.returncode == 0 else ''
        if build_sha and head_sha and build_sha != head_sha:
            return (f"graph was built at {build_sha[:10]} but HEAD is now "
                    f"{head_sha[:10]} (branch switch / pull) — it may not index "
                    f"current code")
    except Exception:
        pass
    # age backstop
    try:
        age_days = (time.time() - os.path.getmtime(db)) / 86400.0
        if age_days > STALE_AGE_DAYS:
            return f"graph.db is {int(age_days)} days old"
    except Exception:
        pass
    return ''


# ---------------------------------------------------------------- breadcrumbs
def _cache_dir():
    home = os.path.abspath(os.path.expanduser(
        os.environ.get('AGENT_OS_HOME', '~/.agent-os')))
    return os.path.join(home, '.cache')


def _tokens(s):
    return {t for t in re.split(r'[^A-Za-z0-9]+', (s or '').lower()) if len(t) >= 3}


def consume_breadcrumb(session_id, pattern):
    """If a fresh breadcrumb's target shares a token with the grep pattern, release
    ONE logical grep for that target and return the target.

    One breadcrumb -> one LOGICAL grep, query-scoped. A single grep call may fire
    this hook more than once (e.g. duplicate wirings, or PreToolUse retries), so
    release is marked with a timestamp and honoured again only within RELEASE_GRACE
    seconds — long enough to cover the same call's sibling fires, short enough that a
    later, separate grep sees the breadcrumb as spent (deny). Not a hard delete-on-
    first-touch (which would deny the same call's second fire)."""
    path = os.path.join(_cache_dir(), f'graph-empty-{session_id or "default"}.json')
    if not os.path.exists(path):
        return ''
    ptoks = _tokens(pattern)
    if not ptoks:
        return ''
    now = time.time()
    RELEASE_GRACE = 5
    try:
        with open(path) as f:
            entries = json.load(f)
        if not isinstance(entries, list):
            return ''
        out, hit, changed = [], '', False
        for e in entries:
            if not isinstance(e, dict) or (now - e.get('ts', 0)) >= BREADCRUMB_TTL:
                changed = True
                continue  # drop stale/orphaned
            matches = bool(_tokens(e.get('target', '')) & ptoks)
            rel = e.get('released')
            if matches and not hit:
                if rel is None:
                    e['released'] = now            # first fire of this logical grep
                    hit = e.get('target', '')
                    changed = True
                    out.append(e)
                elif (now - rel) <= RELEASE_GRACE:
                    hit = e.get('target', '')       # sibling fire of the same grep
                    out.append(e)
                else:
                    changed = True                  # spent -> drop, deny
                    continue
            else:
                out.append(e)
        if changed:
            with open(path, 'w') as f:
                json.dump(out, f)
        return hit
    except Exception:
        return ''


# ---------------------------------------------------------------- messages
def block_message(project_root):
    return f"""code-review-graph is the default for codebase search in {project_root}. Query it FIRST.

WHAT THE GRAPH COVERS (and does NOT):
  • Indexes STRUCTURE of perl/js/python/php/java/bash — functions, classes, files, call edges.
  • Does NOT index: string literals, comments, Template Toolkit (.tt), SQL, YAML/config, JSON, markdown.
  • product-graph covers routes / .tt includes / SCSS tokens — but only partially. Its silence is a PROPOSAL to confirm, not proof of absence.

STEP 1 — load schemas (deferred MCP tools):
  ToolSearch(query="select:mcp__code-review-graph__semantic_search_nodes_tool,mcp__code-review-graph__query_graph_tool,mcp__code-review-graph__traverse_graph_tool")
STEP 2 — query:
  mcp__code-review-graph__semantic_search_nodes_tool(query="<term>", repo_root="{project_root}")
  mcp__code-review-graph__query_graph_tool(pattern="callers_of|callees_of|imports_of|tests_for|file_summary", target="<name>", repo_root="{project_root}")
  mcp__code-review-graph__traverse_graph_tool(query="<term>", mode="bfs", depth=3, repo_root="{project_root}")

SANCTIONED grep (the blessed graph-then-grep path — not a workaround):
  • If you ALREADY queried the graph for this target and it returned EMPTY, grep is now permitted to CONFIRM ABSENCE — re-issue the grep, it will pass (one-shot, scoped to that target).
  • Literal / multi-word patterns (with spaces) are permitted directly — the graph can't do substring/comment matching.
  • Single-file greps (path ending in a filename) are permitted.
A single source's silence is a proposal, not established fact — verify before concluding something does not exist."""


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason}}))
    sys.exit(0)


def allow(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "permissionDecisionReason": reason}}))
    sys.exit(0)


def gated_deny(project_root, session_id, pattern_text):
    """Apply the self-release gates in order; deny only if none sanction the grep."""
    # 1. literal / multi-word pattern
    if pattern_text and re.search(r'\s', pattern_text.strip()):
        allow("graph-then-grep: literal/multi-word pattern — code-review-graph indexes "
              "symbols/structure, not substrings or comments. grep is the sanctioned tool here.")
    # 2. staleness (SHA-first)
    st = graph_staleness(project_root)
    if st:
        allow(f"graph-then-grep: {st}. grep sanctioned to verify against current code; "
              f"rebuild with `code-review-graph update` to restore graph-first.")
    # 3. query-scoped breadcrumb (consume on use)
    tgt = consume_breadcrumb(session_id, pattern_text)
    if tgt:
        allow(f"graph-then-grep: the graph was already queried for '{tgt}' and returned "
              f"empty — grep sanctioned to confirm absence (one-shot, scoped to this target).")
    deny(block_message(project_root))


# ---------------------------------------------------------------- bash pattern extract
def bash_grep_pattern(cmd):
    """Best-effort extract the search pattern from a grep command (for literal/
    breadcrumb matching). Returns '' if not confidently found."""
    m = re.search(r'\bgrep\b([^|;]*)', cmd)
    seg = m.group(1) if m else cmd
    q = re.search(r"""(['"])(.+?)\1""", seg)
    if q:
        return q.group(2)
    for tok in seg.split():
        if tok.startswith('-'):
            continue
        if re.search(r'[/\\]', tok) or re.search(r'\.\w{1,4}$', tok):
            continue  # looks like a path, not the pattern
        return tok
    return ''


# ---------------------------------------------------------------- main
def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool = data.get('tool_name', '')
    tool_input = data.get('tool_input', {})
    cwd = data.get('cwd') or os.getcwd()
    session_id = data.get('session_id') or ''

    if tool == 'Grep':
        candidate = tool_input.get('path', '')
        if not MCP_COVERED.search(candidate):
            sys.exit(0)
        if candidate and os.path.isfile(os.path.realpath(os.path.expanduser(candidate))):
            sys.exit(0)
    elif tool == 'Bash':
        candidate = tool_input.get('command', '')
        if not re.search(r'\bgrep\b.+[/\\]?(lib|public[/\\]javascripts)([/\\]|\s|$)', candidate):
            sys.exit(0)
    else:
        sys.exit(0)

    project_root = find_active_repo(cwd)
    if not project_root:
        sys.exit(0)

    def _canon(p):
        try:
            return os.path.normcase(os.path.realpath(p))
        except Exception:
            return os.path.normcase(p)

    root_canon = _canon(project_root).rstrip('/\\')
    cwd_in_repo = _canon(cwd).startswith(root_canon)
    rel_covered = re.compile(r'^(lib|public[/\\]javascripts)([/\\]|$)')

    def covered_rel(rel):
        return bool(rel_covered.match(rel.lstrip('/\\').replace('\\', '/')))

    def covered_abs(p):
        c = _canon(os.path.expanduser(p))
        return c.startswith(root_canon + os.sep) and covered_rel(c[len(root_canon):])

    if tool == 'Grep':
        path = tool_input.get('path', '')
        if path and (covered_abs(path)
                     or (cwd_in_repo and not os.path.isabs(path) and covered_rel(path))):
            gated_deny(project_root, session_id, tool_input.get('pattern', ''))
    elif tool == 'Bash':
        cmd = tool_input.get('command', '')
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
            if all(re.search(r'\.\w{1,4}$', t) for t in hits):
                sys.exit(0)  # single-file / file-glob greps allowed
            gated_deny(project_root, session_id, bash_grep_pattern(cmd))

    sys.exit(0)


if __name__ == '__main__':
    main()
