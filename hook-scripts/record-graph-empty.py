#!/usr/bin/env python3
"""
PostToolUse hook: record a QUERY-SCOPED breadcrumb when a graph query (CRG or
product-graph) returns empty. enforce-mcp-search consumes it to sanction ONE
grep for the SAME target — "graph first; if silent, grep to confirm absence".

Design (per review):
  - Breadcrumb is query-scoped: records WHAT was queried. Release is tied to the
    target, not a blanket time window.
  - One breadcrumb = one grep: enforce-mcp-search consumes (removes) it on use.
  - TTL is only a safety cap against orphaned entries, not the release mechanism.
  - Session-scoped via session_id so concurrent sessions don't cross-release.

Cache: ~/.agent-os/.cache/graph-empty-<session_id>.json  (gitignored).
Fail-open: any error → silent exit 0.
"""
import json
import os
import sys
import time

TTL_SECONDS = 15 * 60          # orphaned-entry safety cap
GRAPH_TOOL_MARK = ('code-review-graph', 'product-graph')
# tool_input keys that carry the search subject, in priority order
TARGET_KEYS = ('query', 'target', 'name_substring', 'name', 'path', 'feature', 'term')


def cache_dir():
    home = os.path.abspath(os.path.expanduser(
        os.environ.get('AGENT_OS_HOME', '~/.agent-os')))
    d = os.path.join(home, '.cache')
    os.makedirs(d, exist_ok=True)
    return d


def response_is_empty(resp):
    """True only on a CLEAR empty result — conservative."""
    text = ''
    if isinstance(resp, str):
        text = resp
    elif isinstance(resp, dict):
        # MCP responses often wrap content in a list of {type,text}
        content = resp.get('content')
        if isinstance(content, list):
            text = ' '.join(
                (c.get('text', '') if isinstance(c, dict) else str(c)) for c in content)
        else:
            text = json.dumps(resp)
    elif isinstance(resp, list):
        if len(resp) == 0:
            return True
        text = json.dumps(resp)
    else:
        return False
    t = text.strip().lower()
    if t in ('', '[]', '{}', 'null', 'none'):
        return True
    markers = ('no nodes', 'no results', '0 results', 'no matches found',
               'not found', 'no matching', 'returned 0', 'empty result')
    return any(m in t for m in markers)


def extract_target(tool_input):
    if not isinstance(tool_input, dict):
        return ''
    for k in TARGET_KEYS:
        v = tool_input.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ''


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool = data.get('tool_name', '') or ''
    if not any(m in tool for m in GRAPH_TOOL_MARK):
        sys.exit(0)

    target = extract_target(data.get('tool_input', {}))
    if not target:
        sys.exit(0)
    if not response_is_empty(data.get('tool_response')):
        sys.exit(0)

    session_id = data.get('session_id') or 'default'
    repo = data.get('cwd') or os.getcwd()
    path = os.path.join(cache_dir(), f'graph-empty-{session_id}.json')

    now = time.time()
    try:
        entries = []
        if os.path.exists(path):
            with open(path) as f:
                entries = json.load(f)
            if not isinstance(entries, list):
                entries = []
        # drop orphaned/stale entries, then append this one
        entries = [e for e in entries
                   if isinstance(e, dict) and (now - e.get('ts', 0)) < TTL_SECONDS]
        entries.append({'target': target, 'ts': now, 'repo': repo, 'tool': tool})
        with open(path, 'w') as f:
            json.dump(entries, f)
    except Exception:
        pass
    sys.exit(0)


if __name__ == '__main__':
    main()
