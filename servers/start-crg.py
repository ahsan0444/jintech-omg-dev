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

Failure behaviour: install errors print an actionable message to stderr and
exit 1 (MCP client reports "server failed to start" instead of a raw
traceback). Serving uses exec on POSIX and a blocking subprocess on Windows
(os.exec* does not reliably replace console processes on Windows, which
breaks stdio MCP transport).
"""
import os
import sqlite3
import subprocess
import shutil
import sys

PLUGIN_ROOT = os.environ.get(
    'CLAUDE_PLUGIN_ROOT',
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
VENV_DIR = os.path.join(PLUGIN_ROOT, 'servers', 'venv')
REQUIREMENTS = os.path.join(PLUGIN_ROOT, 'servers', 'requirements.txt')
EMBED_LOG = os.path.join(PLUGIN_ROOT, 'servers', 'embed.log')
EMBED_LOG_MAX_BYTES = 5 * 1024 * 1024

# Venv bin/Scripts varies by OS
if sys.platform == 'win32':
    CRG_BIN = os.path.join(VENV_DIR, 'Scripts', 'code-review-graph.exe')
    PYTHON_BIN = os.path.join(VENV_DIR, 'Scripts', 'python.exe')
else:
    CRG_BIN = os.path.join(VENV_DIR, 'bin', 'code-review-graph')
    PYTHON_BIN = os.path.join(VENV_DIR, 'bin', 'python3')


def install():
    print('[jintech-omg-dev] Installing code-review-graph...', file=sys.stderr)
    if sys.version_info < (3, 12):
        print(f'[jintech-omg-dev] ERROR: Python 3.12+ required, found '
              f'{sys.version_info.major}.{sys.version_info.minor}. '
              f'Install a newer Python and ensure python3 on PATH points to it.',
              file=sys.stderr)
        sys.exit(1)
    try:
        subprocess.run([sys.executable, '-m', 'venv', VENV_DIR], check=True)
        # `python -m pip` instead of a pip binary path — the pip shim is not
        # guaranteed to exist on all platforms/venv configurations.
        subprocess.run(
            [PYTHON_BIN, '-m', 'pip', 'install', '--quiet', '-r', REQUIREMENTS],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f'[jintech-omg-dev] ERROR: install failed ({e}). '
              f'Fix the issue (network? Python version?) then reinstall the plugin, '
              f'or run manually:\n'
              f'  {sys.executable} -m venv "{VENV_DIR}"\n'
              f'  "{PYTHON_BIN}" -m pip install -r "{REQUIREMENTS}"',
              file=sys.stderr)
        # Remove a half-built venv so the next start retries cleanly
        shutil.rmtree(VENV_DIR, ignore_errors=True)
        sys.exit(1)
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


def _rotate_embed_log():
    """Cap embed.log growth — keep one previous generation."""
    try:
        if os.path.exists(EMBED_LOG) and os.path.getsize(EMBED_LOG) > EMBED_LOG_MAX_BYTES:
            os.replace(EMBED_LOG, EMBED_LOG + '.1')
    except OSError:
        pass


def _trigger_embed(repo_root: str) -> None:
    """Spawn embed as a detached background process — does not block server startup.

    Uses _run_embed.py (shipped alongside this file) with the venv Python so
    imports resolve correctly. stderr goes to a log file for debugging.
    """
    embed_script = os.path.join(PLUGIN_ROOT, 'servers', '_run_embed.py')
    if not os.path.exists(embed_script):
        print(f'[jintech-omg-dev] Auto-embed skipped — _run_embed.py not found at {embed_script}', file=sys.stderr)
        return

    _rotate_embed_log()
    try:
        with open(EMBED_LOG, 'a') as log:
            kwargs = {'stdout': subprocess.DEVNULL, 'stderr': log}
            if sys.platform == 'win32':
                kwargs['creationflags'] = 0x00000208  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            else:
                kwargs['start_new_session'] = True
            subprocess.Popen([PYTHON_BIN, embed_script, repo_root], **kwargs)
        print(f'[jintech-omg-dev] Embedding {repo_root} in background — see servers/embed.log for progress', file=sys.stderr)
    except Exception as e:
        print(f'[jintech-omg-dev] Auto-embed spawn failed: {e}', file=sys.stderr)


def main():
    if not os.path.exists(CRG_BIN):
        install()

    # Auto-embed any registered repos that have a graph but no embeddings
    for repo in _find_repos_needing_embed():
        _trigger_embed(repo)

    if sys.platform == 'win32':
        # os.exec* on Windows spawns a new console process and returns in the
        # parent, severing the MCP stdio pipes. Block on a child instead.
        sys.exit(subprocess.run([CRG_BIN, 'serve']).returncode)
    else:
        os.execv(CRG_BIN, [CRG_BIN, 'serve'])


if __name__ == '__main__':
    main()
