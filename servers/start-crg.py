#!/usr/bin/env python3
"""
Cross-platform bootstrap for the code-review-graph MCP server.
On first run: creates a plugin-local venv and pip-installs code-review-graph.
On subsequent runs: starts the already-installed server directly.

Environment:
  CRG_DB_PATH  — path to graph.db (falls back to .code-review-graph/graph.db in git root)
"""
import sys
import os
import subprocess
import shutil

PLUGIN_ROOT = os.environ.get(
    'CLAUDE_PLUGIN_ROOT',
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
VENV_DIR = os.path.join(PLUGIN_ROOT, 'servers', 'venv')
REQUIREMENTS = os.path.join(PLUGIN_ROOT, 'servers', 'requirements.txt')

# Venv bin/Scripts varies by OS
if sys.platform == 'win32':
    CRG_BIN = os.path.join(VENV_DIR, 'Scripts', 'code-review-graph.exe')
    PIP_BIN = os.path.join(VENV_DIR, 'Scripts', 'pip.exe')
else:
    CRG_BIN = os.path.join(VENV_DIR, 'bin', 'code-review-graph')
    PIP_BIN = os.path.join(VENV_DIR, 'bin', 'pip')

def install():
    print('[jintech-omg-dev] Installing code-review-graph...', file=sys.stderr)
    subprocess.run([sys.executable, '-m', 'venv', VENV_DIR], check=True)
    subprocess.run([PIP_BIN, 'install', '--quiet', '-r', REQUIREMENTS], check=True)
    print('[jintech-omg-dev] Installation complete.', file=sys.stderr)

if not os.path.exists(CRG_BIN):
    install()

# Resolve DB path
db_path = os.environ.get('CRG_DB_PATH', '')
if not db_path:
    try:
        r = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, timeout=5
        )
        project_root = r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        project_root = ''
    db_path = os.path.join(project_root, '.code-review-graph', 'graph.db') if project_root else ''

args = [CRG_BIN, 'serve']
if db_path:
    args += ['--db', db_path]

os.execv(CRG_BIN, args)
