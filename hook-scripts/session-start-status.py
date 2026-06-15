#!/usr/bin/env python3
"""
SessionStart hook: print code-review-graph status at session start.
stdout on exit 0 is added to Claude's context — keep it short.
Exits 0 silently if no graph DB exists — safe for any project on any OS.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time


def get_project_root(start_dir):
    try:
        r = subprocess.run(
            ['git', '-C', start_dir, 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return ''


def _agentos_data_dir(project_root):
    """Resolve the Agent OS data dir for a repo from ~/.agent-os/config.yml.

    Stdlib-only line parse (hooks run on system python without pyyaml). The
    config is a simple list of {name, repo_root, data} items.
    """
    home = os.path.abspath(os.path.expanduser(
        os.environ.get('AGENT_OS_HOME', '~/.agent-os')))
    cfg = os.path.join(home, 'config.yml')
    if not project_root or not os.path.exists(cfg):
        return ''
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
        return ''
    for it in items:
        rr = it.get('repo_root', '')
        if rr and os.path.realpath(os.path.expanduser(rr)) == pr:
            data = it.get('data') or it.get('name') or ''
            return os.path.join(home, data) if data else ''
    return ''


def print_product_graph_status(project_root):
    """Print product-graph freshness for the active repo, if a product.db exists."""
    data_dir = _agentos_data_dir(project_root)
    if not data_dir:
        return
    db = os.path.join(data_dir, '.product-graph', 'product.db')
    if not os.path.exists(db):
        return
    try:
        conn = sqlite3.connect(db)
        rows = conn.execute(
            "SELECT type, COUNT(*) FROM nodes GROUP BY type").fetchall()
        conn.close()
        counts = {t: n for t, n in rows}
        age_days = (time.time() - os.path.getmtime(db)) / 86400.0
        built = 'today' if age_days < 1 else f'{int(age_days)}d ago'
        summary = ', '.join(
            f"{counts.get(k, 0)} {k}s" for k in ('route', 'template', 'design_token', 'feature'))
        print(f'[agent-os] product-graph: {summary} (built {built}). '
              f'Query via mcp__plugin_jintech-omg-dev_product-graph__pg_* tools.')
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    cwd = data.get('cwd') or os.getcwd()

    # Product-graph freshness — independent of CRG; prints only if a product.db exists.
    print_product_graph_status(get_project_root(cwd))

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
        print('[jintech-omg-dev] code-review-graph not installed yet — it installs '
              'automatically when the MCP server first starts. If this persists, '
              'reinstall the plugin: /plugin → jintech-omg-dev → reinstall.')
        sys.exit(0)

    # Resolve active repo: git root with graph.db, or registered repo visible from cwd
    def find_active_repo(crg_bin):
        project_root = get_project_root(cwd)
        if project_root:
            db = os.path.join(project_root, '.code-review-graph', 'graph.db')
            if os.path.exists(db):
                return project_root
        # Fallback: check registered repos
        try:
            r = subprocess.run([crg_bin, 'repos'], capture_output=True, text=True, timeout=5)
            cwd_real = os.path.realpath(cwd)
            for line in r.stdout.splitlines():
                path = line.split('(')[0].strip()
                if not path or not os.path.exists(path):
                    continue
                db = os.path.join(path, '.code-review-graph', 'graph.db')
                path_real = os.path.realpath(path)
                if os.path.exists(db) and (cwd_real.startswith(path_real) or path_real.startswith(cwd_real)):
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


if __name__ == '__main__':
    main()
