#!/usr/bin/env python3
"""
Cross-platform bootstrap for the product-graph MCP server.

Reuses the same plugin-local venv as code-review-graph (servers/venv). On first
run it ensures the venv exists and that product-graph deps (pyyaml, mcp) are
installed, then execs the local serve.py.

serve.py is read-only over a prebuilt product.db (built by product-graph/build.py).
The server is multi-repo — each MCP tool call passes repo to select the graph.

Failure behaviour: dep install errors print an actionable message to stderr and
exit 1. Serving uses exec on POSIX and a blocking subprocess on Windows (os.exec*
does not reliably replace console processes on Windows, breaking stdio MCP).
"""
import os
import subprocess
import sys

PLUGIN_ROOT = os.environ.get(
    'CLAUDE_PLUGIN_ROOT',
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
VENV_DIR = os.path.join(PLUGIN_ROOT, 'servers', 'venv')
PG_DIR = os.path.join(PLUGIN_ROOT, 'servers', 'product-graph')
REQUIREMENTS = os.path.join(PG_DIR, 'requirements.txt')
SERVE = os.path.join(PG_DIR, 'serve.py')

if sys.platform == 'win32':
    PYTHON_BIN = os.path.join(VENV_DIR, 'Scripts', 'python.exe')
else:
    PYTHON_BIN = os.path.join(VENV_DIR, 'bin', 'python3')


def _venv_python():
    """Return a usable venv python, creating the venv if missing."""
    if os.path.exists(PYTHON_BIN):
        return PYTHON_BIN
    if sys.version_info < (3, 12):
        print(f'[jintech-omg-dev] ERROR: Python 3.12+ required, found '
              f'{sys.version_info.major}.{sys.version_info.minor}.', file=sys.stderr)
        sys.exit(1)
    try:
        subprocess.run([sys.executable, '-m', 'venv', VENV_DIR], check=True)
    except subprocess.CalledProcessError as e:
        print(f'[jintech-omg-dev] ERROR: venv create failed ({e}).', file=sys.stderr)
        sys.exit(1)
    return PYTHON_BIN


def _ensure_deps(py):
    """Install product-graph deps into the venv if mcp/yaml are missing."""
    check = subprocess.run(
        [py, '-c', 'import mcp, yaml'],
        capture_output=True
    )
    if check.returncode == 0:
        return
    print('[jintech-omg-dev] Installing product-graph deps (mcp, pyyaml)...', file=sys.stderr)
    try:
        subprocess.run([py, '-m', 'pip', 'install', '--quiet', '-r', REQUIREMENTS], check=True)
    except subprocess.CalledProcessError as e:
        print(f'[jintech-omg-dev] ERROR: product-graph dep install failed ({e}). '
              f'Run manually: "{py}" -m pip install -r "{REQUIREMENTS}"', file=sys.stderr)
        sys.exit(1)


def main():
    py = _venv_python()
    _ensure_deps(py)
    if not os.path.exists(SERVE):
        print(f'[jintech-omg-dev] ERROR: product-graph serve.py not found at {SERVE}', file=sys.stderr)
        sys.exit(1)
    if sys.platform == 'win32':
        sys.exit(subprocess.run([py, SERVE]).returncode)
    else:
        os.execv(py, [py, SERVE])


if __name__ == '__main__':
    main()
