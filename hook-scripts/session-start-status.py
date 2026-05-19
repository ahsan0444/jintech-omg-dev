#!/usr/bin/env python3
"""
SessionStart hook: print code-review-graph status at session start.
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
    print('[jintech-omg-dev] code-review-graph not found — run: /plugin reinit jintech-omg-dev')
    sys.exit(0)

# Resolve active repo: git root with graph.db, or registered repo visible from cwd
def find_active_repo(crg_bin):
    project_root = get_project_root()
    if project_root:
        db = os.path.join(project_root, '.code-review-graph', 'graph.db')
        if os.path.exists(db):
            return project_root
    # Fallback: check registered repos
    try:
        r = subprocess.run([crg_bin, 'repos'], capture_output=True, text=True, timeout=5)
        cwd = os.path.realpath(os.getcwd())
        for line in r.stdout.splitlines():
            path = line.split('(')[0].strip()
            if not path or not os.path.exists(path):
                continue
            db = os.path.join(path, '.code-review-graph', 'graph.db')
            path_real = os.path.realpath(path)
            if os.path.exists(db) and (cwd.startswith(path_real) or path_real.startswith(cwd)):
                return path
    except Exception:
        pass
    return ''

project_root = find_active_repo(crg)
if not project_root:
    sys.exit(0)

try:
    subprocess.run([crg, 'status'], cwd=project_root, timeout=10)
except Exception:
    pass

sys.exit(0)
