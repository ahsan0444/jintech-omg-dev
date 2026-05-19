#!/usr/bin/env python3
"""
PostToolUse hook: run code-review-graph update after every Edit or Write.
Exits 0 silently if no graph DB exists — safe for any project on any OS.
"""
import sys
import subprocess
import os
import shutil

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
        cwd=project_root, capture_output=True, timeout=30
    )
except Exception:
    pass

sys.exit(0)
