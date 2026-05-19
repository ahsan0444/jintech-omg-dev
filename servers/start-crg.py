#!/usr/bin/env python3
"""
Cross-platform bootstrap for the code-review-graph MCP server.
On first run: creates a plugin-local venv and pip-installs code-review-graph.
On subsequent runs: starts the already-installed server directly.

The server is multi-repo — no fixed DB path needed at startup.
Each MCP tool call passes repo_root to select the correct graph.

Auto-embed: if a registered repo has a graph.db but no embeddings table
(or 0 embeddings), triggers embed in a background subprocess before serving.
This ensures semantic search works on first boot after `code-review-graph build`.
"""
import sys
import os
import sqlite3
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
    PYTHON_BIN = os.path.join(VENV_DIR, 'Scripts', 'python.exe')
else:
    CRG_BIN = os.path.join(VENV_DIR, 'bin', 'code-review-graph')
    PIP_BIN = os.path.join(VENV_DIR, 'bin', 'pip')
    PYTHON_BIN = os.path.join(VENV_DIR, 'bin', 'python3')

def install():
    print('[jintech-omg-dev] Installing code-review-graph...', file=sys.stderr)
    subprocess.run([sys.executable, '-m', 'venv', VENV_DIR], check=True)
    subprocess.run([PIP_BIN, 'install', '--quiet', '-r', REQUIREMENTS], check=True)
    print('[jintech-omg-dev] Installation complete.', file=sys.stderr)

def _needs_embed(graph_db: str) -> bool:
    """Return True if graph.db has nodes but no embeddings (or empty embeddings table)."""
    try:
        conn = sqlite3.connect(graph_db)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM nodes WHERE kind != 'File'")
        node_count = c.fetchone()[0]
        if node_count == 0:
            conn.close()
            return False
        try:
            c.execute("SELECT COUNT(*) FROM embeddings")
            embedded = c.fetchone()[0]
            conn.close()
            return embedded == 0
        except sqlite3.OperationalError:
            # embeddings table doesn't exist yet
            conn.close()
            return True
    except Exception:
        return False

def _find_repos_needing_embed() -> list:
    """Find all registered repos with graph.db but no embeddings."""
    crg = CRG_BIN if os.path.exists(CRG_BIN) else shutil.which('code-review-graph')
    if not crg:
        return []
    try:
        result = subprocess.run([crg, 'repos'], capture_output=True, text=True, timeout=5)
        repos = []
        for line in result.stdout.splitlines():
            path = line.split('(')[0].strip()
            if not path or not os.path.isdir(path):
                continue
            db = os.path.join(path, '.code-review-graph', 'graph.db')
            if os.path.exists(db) and _needs_embed(db):
                repos.append(path)
        return repos
    except Exception:
        return []

def _trigger_embed(repo_root: str) -> None:
    """Spawn embed as a detached background process — does not block server startup.

    Uses _run_embed.py (shipped alongside this file) with the venv Python so
    imports resolve correctly. stderr goes to a log file for debugging.
    """
    embed_script = os.path.join(PLUGIN_ROOT, 'servers', '_run_embed.py')
    if not os.path.exists(embed_script):
        print(f'[jintech-omg-dev] Auto-embed skipped — _run_embed.py not found at {embed_script}', file=sys.stderr)
        return

    log_path = os.path.join(PLUGIN_ROOT, 'servers', 'embed.log')
    try:
        with open(log_path, 'a') as log:
            subprocess.Popen(
                [PYTHON_BIN, embed_script, repo_root],
                stdout=subprocess.DEVNULL,
                stderr=log,
                start_new_session=True,
            )
        print(f'[jintech-omg-dev] Embedding {repo_root} in background — see servers/embed.log for progress', file=sys.stderr)
    except Exception as e:
        print(f'[jintech-omg-dev] Auto-embed spawn failed: {e}', file=sys.stderr)

if not os.path.exists(CRG_BIN):
    install()

# Auto-embed any registered repos that have a graph but no embeddings
for repo in _find_repos_needing_embed():
    _trigger_embed(repo)

os.execv(CRG_BIN, [CRG_BIN, 'serve'])
