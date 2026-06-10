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


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    tool_input = data.get('tool_input', {}) or {}
    file_path = tool_input.get('file_path') or tool_input.get('notebook_path') or ''
    cwd = data.get('cwd') or os.getcwd()

    if file_path:
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in SOURCE_EXTS:
            sys.exit(0)
        start_dir = os.path.dirname(os.path.abspath(file_path)) or cwd
    else:
        start_dir = cwd

    project_root = get_project_root(start_dir)
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
