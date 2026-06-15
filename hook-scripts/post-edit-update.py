#!/usr/bin/env python3
"""
PostToolUse hook: run an incremental code-review-graph update after Edit/Write.

Improvements over v1:
  - Reads the hook input and skips non-source files (.md, .json, .planning/ etc.)
    instead of running a graph update after every documentation edit.
  - Uses the edited file's location (not just cwd) to find the repo root, so
    edits made from a parent directory still trigger the right repo's update.

Exits 0 silently in every failure mode — safe for any project on any OS.
"""
import json
import os
import shutil
import subprocess
import sys

# Extensions code-review-graph actually parses — skip everything else.
SOURCE_EXTS = {'.pm', '.pl', '.t', '.js', '.mjs', '.ts', '.tsx', '.py', '.sql'}


def get_project_root(start_dir):
    try:
        r = subprocess.run(
            ['git', '-C', start_dir, 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return ''


def _agentos_repo(project_root):
    """Return (name, data_dir) for a repo from ~/.agent-os/config.yml, or ('','')."""
    home = os.path.abspath(os.path.expanduser(
        os.environ.get('AGENT_OS_HOME', '~/.agent-os')))
    cfg = os.path.join(home, 'config.yml')
    if not project_root or not os.path.exists(cfg):
        return '', ''
    pr = os.path.realpath(project_root)
    items, cur = [], {}
    try:
        with open(cfg, 'r') as f:
            for raw in f:
                line = raw.strip()
                if line.startswith('- '):
                    if cur:
                        items.append(cur)
                    cur = {}
                    line = line[2:].strip()
                if ':' in line and not line.startswith('#'):
                    k, _, v = line.partition(':')
                    v = v.strip()
                    if ' #' in v:            # strip inline YAML comment
                        v = v[:v.index(' #')].strip()
                    cur[k.strip()] = v
        if cur:
            items.append(cur)
    except Exception:
        return '', ''
    for it in items:
        rr = it.get('repo_root', '')
        if rr and os.path.realpath(os.path.expanduser(rr)) == pr:
            name = it.get('name', '')
            data = it.get('data') or name
            return name, (os.path.join(home, data) if data else '')
    return '', ''


def _affects_product_graph(file_path):
    """True if the edited file changes routes (lib/OMG*.pm), templates (.tt), or tokens (.scss)."""
    if not file_path:
        return False
    ext = os.path.splitext(file_path)[1].lower()
    if ext in ('.tt', '.scss'):
        return True
    if ext == '.pm' and os.path.basename(file_path).startswith('OMG'):
        return True
    return False


def refresh_product_graph(project_root, file_path):
    """Incrementally rebuild the product graph when a relevant file changed. Fail-open."""
    if not _affects_product_graph(file_path):
        return
    name, _ = _agentos_repo(project_root)
    if not name:
        return
    plugin_root = os.environ.get(
        'CLAUDE_PLUGIN_ROOT',
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    if sys.platform == 'win32':
        py = os.path.join(plugin_root, 'servers', 'venv', 'Scripts', 'python.exe')
    else:
        py = os.path.join(plugin_root, 'servers', 'venv', 'bin', 'python3')
    build = os.path.join(plugin_root, 'servers', 'product-graph', 'build.py')
    if not (os.path.exists(py) and os.path.exists(build)):
        return
    try:
        subprocess.run([py, build, '--repo', name], capture_output=True, timeout=50)
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    tool_input = data.get('tool_input', {}) or {}
    file_path = tool_input.get('file_path') or tool_input.get('notebook_path') or ''
    cwd = data.get('cwd') or os.getcwd()

    start_dir = (os.path.dirname(os.path.abspath(file_path)) or cwd) if file_path else cwd
    project_root = get_project_root(start_dir)

    # Product graph: refresh on .tt/.scss/route-file edits (independent of CRG's source exts).
    refresh_product_graph(project_root, file_path)

    # code-review-graph only parses its own source extensions.
    if file_path:
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in SOURCE_EXTS:
            sys.exit(0)
    if not project_root:
        sys.exit(0)

    graph_db = os.path.join(project_root, '.code-review-graph', 'graph.db')
    if not os.path.exists(graph_db):
        sys.exit(0)

    # Resolve CRG binary — plugin venv first, then PATH
    plugin_root = os.environ.get(
        'CLAUDE_PLUGIN_ROOT',
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    if sys.platform == 'win32':
        crg_in_plugin = os.path.join(plugin_root, 'servers', 'venv', 'Scripts', 'code-review-graph.exe')
    else:
        crg_in_plugin = os.path.join(plugin_root, 'servers', 'venv', 'bin', 'code-review-graph')

    crg = crg_in_plugin if os.path.exists(crg_in_plugin) else shutil.which('code-review-graph')
    if not crg:
        sys.exit(0)

    try:
        subprocess.run(
            [crg, 'update', '--skip-flows'],
            cwd=project_root, capture_output=True, timeout=50
        )
    except Exception:
        pass

    sys.exit(0)


if __name__ == '__main__':
    main()
