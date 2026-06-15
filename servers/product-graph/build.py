#!/usr/bin/env python3
"""product-graph build + query CLI.

Build the graph:
    python build.py --repo omg

Query:
    python build.py --repo omg query feature <name>
    python build.py --repo omg query selectors <feature>
    python build.py --repo omg query route <path-substring>
    python build.py --repo omg query token <substring>

Resolution:
    AGENT_OS_HOME env (default ~/.agent-os) -> config.yml maps repo name to
    repo_root (source) and data (private data dir under AGENT_OS_HOME).
    Output DB: <AGENT_OS_HOME>/<data>/.product-graph/product.db

Pure stdlib + PyYAML (PyYAML only needed to read config.yml + registry).
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db as dbmod  # noqa: E402
from extract import routes as ex_routes  # noqa: E402
from extract import tt as ex_tt  # noqa: E402
from extract import scss as ex_scss  # noqa: E402
from extract import registry as ex_registry  # noqa: E402

try:
    import yaml
except ImportError:
    yaml = None


def agent_os_home():
    return os.path.abspath(
        os.path.expanduser(os.environ.get("AGENT_OS_HOME", "~/.agent-os"))
    )


def load_config(home):
    cfg_path = os.path.join(home, "config.yml")
    if yaml is None:
        sys.exit(
            "ERROR: PyYAML not installed. Install with: pip install pyyaml\n"
            "(config.yml and registry parsing require it)"
        )
    if not os.path.isfile(cfg_path):
        sys.exit("ERROR: config not found at %s" % cfg_path)
    with open(cfg_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def resolve_repo(home, repo_name):
    cfg = load_config(home)
    for entry in cfg.get("repos", []):
        if entry.get("name") == repo_name:
            repo_root = entry["repo_root"]
            data = entry.get("data", repo_name)
            data_dir = os.path.join(home, data)
            db_path = os.path.join(data_dir, ".product-graph", "product.db")
            return repo_root, data_dir, db_path
    sys.exit("ERROR: repo %r not found in config.yml" % repo_name)


def cmd_build(repo_root, data_dir, db_path):
    print("Building product-graph for repo source: %s" % repo_root)
    print("  data dir: %s" % data_dir)
    print("  output db: %s" % db_path)

    route_nodes = ex_routes.extract(repo_root)
    tt_nodes, tt_edges = ex_tt.extract(repo_root)
    scss_nodes = ex_scss.extract(repo_root)
    feat_nodes, feat_edges = ex_registry.extract(data_dir, route_nodes=route_nodes)

    all_nodes = route_nodes + tt_nodes + scss_nodes + feat_nodes
    all_edges = tt_edges + feat_edges

    conn = dbmod.connect(db_path)
    dbmod.rebuild_schema(conn)
    dbmod.insert_nodes(conn, all_nodes)
    dbmod.insert_edges(conn, all_edges)

    print("\nNode counts by type:")
    for ntype, count in sorted(dbmod.counts_by_type(conn).items()):
        print("  %-14s %d" % (ntype, count))
    print("  %-14s %d" % ("TOTAL", len(all_nodes)))

    print("\nEdge counts by type:")
    ec = dbmod.edge_counts_by_type(conn)
    if ec:
        for etype, count in sorted(ec.items()):
            print("  %-14s %d" % (etype, count))
    else:
        print("  (none)")
    print("  %-14s %d" % ("TOTAL", len(all_edges)))
    conn.close()


def _print_json(obj):
    print(json.dumps(obj, indent=2, sort_keys=True, default=str))


def cmd_query(db_path, qkind, qarg):
    if not os.path.isfile(db_path):
        sys.exit("ERROR: db not built yet at %s — run build first." % db_path)
    conn = dbmod.connect(db_path)

    if qkind == "feature":
        rows = dbmod.get_nodes(conn, node_type="feature", name=qarg)
        if not rows:
            print("No feature named %r" % qarg)
        else:
            _print_json(rows[0]["attrs"])

    elif qkind == "selectors":
        rows = dbmod.get_nodes(conn, node_type="feature", name=qarg)
        if not rows:
            print("No feature named %r" % qarg)
        else:
            _print_json(rows[0]["attrs"].get("selectors") or {})

    elif qkind == "route":
        rows = dbmod.get_nodes(conn, node_type="route", name_substring=qarg)
        if not rows:
            print("No routes matching %r" % qarg)
        else:
            _print_json([r["attrs"] for r in rows])

    elif qkind == "token":
        rows = dbmod.get_nodes(conn, node_type="design_token", name_substring=qarg)
        if not rows:
            print("No design tokens matching %r" % qarg)
        else:
            _print_json(
                [{"name": r["name"], **r["attrs"]} for r in rows]
            )
    else:
        sys.exit("ERROR: unknown query kind %r" % qkind)

    conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="product-graph build/query CLI")
    parser.add_argument("--repo", required=True, help="repo name from config.yml")
    parser.add_argument("rest", nargs=argparse.REMAINDER,
                        help="optional: query <kind> <arg>")
    args = parser.parse_args(argv)

    home = agent_os_home()
    repo_root, data_dir, db_path = resolve_repo(home, args.repo)

    rest = args.rest
    if not rest:
        cmd_build(repo_root, data_dir, db_path)
        return

    if rest[0] != "query":
        sys.exit("ERROR: unknown subcommand %r (expected 'query')" % rest[0])
    if len(rest) < 3:
        sys.exit("ERROR: usage: --repo R query <feature|selectors|route|token> <arg>")
    cmd_query(db_path, rest[1], " ".join(rest[2:]))


if __name__ == "__main__":
    main()
