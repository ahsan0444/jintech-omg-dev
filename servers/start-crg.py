#!/usr/bin/env python3
"""
Cross-platform bootstrap for the code-review-graph MCP server.
On first run: creates a plugin-local venv and pip-installs code-review-graph.
On subsequent runs: starts the already-installed server directly.

The server is multi-repo — no fixed DB path needed at startup.
Each MCP tool call passes repo_root to select the correct graph.
"""
import sys
import os
import subprocess

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

os.execv(CRG_BIN, [CRG_BIN, 'serve'])
