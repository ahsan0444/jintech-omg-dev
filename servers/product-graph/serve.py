#!/usr/bin/env python3
"""product-graph MCP server (stdio).

Exposes the prebuilt product.db as MCP tools. The DB is built by build.py;
this server is read-only. Requires the `mcp` package (FastMCP).

Tools (each accepts repo:str="omg"):
    pg_feature(name, repo)              -> feature node attrs
    pg_selectors(feature, repo)         -> feature selectors dict
    pg_route(path, repo)                -> matching route nodes
    pg_design_tokens(query, repo)       -> matching design tokens
    pg_query(node_type, name_substring, repo) -> generic node lookup

Responses are compact JSON strings.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db as dbmod  # noqa: E402

try:
    import yaml
except ImportError:
    yaml = None

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("product-graph")


def _home():
    return os.path.abspath(
        os.path.expanduser(os.environ.get("AGENT_OS_HOME", "~/.agent-os"))
    )


def _db_path(repo):
    home = _home()
    cfg_path = os.path.join(home, "config.yml")
    if yaml is None:
        raise RuntimeError("PyYAML not installed")
    with open(cfg_path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    for entry in cfg.get("repos", []):
        if entry.get("name") == repo:
            data = entry.get("data", repo)
            return os.path.join(home, data, ".product-graph", "product.db")
    raise RuntimeError("repo %r not found in config.yml" % repo)


def _open(repo):
    path = _db_path(repo)
    if not os.path.isfile(path):
        raise RuntimeError("product.db not built for %r — run build.py first" % repo)
    return dbmod.connect(path)


def _compact(obj):
    return json.dumps(obj, separators=(",", ":"), default=str, sort_keys=True)


@mcp.tool()
def pg_feature(name: str, repo: str = "omg") -> str:
    """Return the attrs of a feature node by exact name."""
    conn = _open(repo)
    rows = dbmod.get_nodes(conn, node_type="feature", name=name)
    conn.close()
    return _compact(rows[0]["attrs"] if rows else {})


@mcp.tool()
def pg_selectors(feature: str, repo: str = "omg") -> str:
    """Return the selectors dict for a feature by exact name."""
    conn = _open(repo)
    rows = dbmod.get_nodes(conn, node_type="feature", name=feature)
    conn.close()
    sel = rows[0]["attrs"].get("selectors") if rows else None
    return _compact(sel or {})


@mcp.tool()
def pg_route(path: str, repo: str = "omg") -> str:
    """Return route nodes whose name (METHOD path) contains the given substring."""
    conn = _open(repo)
    rows = dbmod.get_nodes(conn, node_type="route", name_substring=path)
    conn.close()
    return _compact([r["attrs"] for r in rows])


@mcp.tool()
def pg_design_tokens(query: str, repo: str = "omg") -> str:
    """Return design tokens whose name contains the given substring."""
    conn = _open(repo)
    rows = dbmod.get_nodes(conn, node_type="design_token", name_substring=query)
    conn.close()
    return _compact([{"name": r["name"], **r["attrs"]} for r in rows])


@mcp.tool()
def pg_query(node_type: str, name_substring: str = "", repo: str = "omg") -> str:
    """Generic lookup: nodes of node_type whose name contains name_substring."""
    conn = _open(repo)
    rows = dbmod.get_nodes(
        conn,
        node_type=node_type,
        name_substring=name_substring or None,
    )
    conn.close()
    return _compact(
        [
            {"type": r["type"], "name": r["name"], "file": r["file"],
             "line": r["line"], "attrs": r["attrs"]}
            for r in rows
        ]
    )


if __name__ == "__main__":
    mcp.run()
