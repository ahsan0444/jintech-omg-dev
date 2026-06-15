"""SQLite schema + helpers for the product-knowledge graph.

Schema:
    nodes(id INTEGER PK, type TEXT, name TEXT, file TEXT, line INT, attrs TEXT json)
    edges(id INTEGER PK, src TEXT, dst TEXT, type TEXT)
Indexes on nodes(type) and nodes(name).

Rebuild is deterministic: drop + recreate.
Pure stdlib (sqlite3, json).
"""

import json
import os
import sqlite3


def connect(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def rebuild_schema(conn):
    """Drop and recreate all tables + indexes (idempotent rebuild)."""
    cur = conn.cursor()
    cur.executescript(
        """
        DROP TABLE IF EXISTS nodes;
        DROP TABLE IF EXISTS edges;

        CREATE TABLE nodes (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            type  TEXT,
            name  TEXT,
            file  TEXT,
            line  INTEGER,
            attrs TEXT
        );
        CREATE TABLE edges (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            src  TEXT,
            dst  TEXT,
            type TEXT
        );

        CREATE INDEX idx_nodes_type ON nodes(type);
        CREATE INDEX idx_nodes_name ON nodes(name);
        """
    )
    conn.commit()


def insert_nodes(conn, nodes):
    cur = conn.cursor()
    cur.executemany(
        "INSERT INTO nodes (type, name, file, line, attrs) VALUES (?, ?, ?, ?, ?)",
        [
            (
                n.get("type"),
                n.get("name"),
                n.get("file"),
                n.get("line"),
                json.dumps(n.get("attrs", {}), sort_keys=True, default=str),
            )
            for n in nodes
        ],
    )
    conn.commit()


def insert_edges(conn, edges):
    cur = conn.cursor()
    cur.executemany(
        "INSERT INTO edges (src, dst, type) VALUES (?, ?, ?)",
        [(e.get("src"), e.get("dst"), e.get("type")) for e in edges],
    )
    conn.commit()


def counts_by_type(conn):
    cur = conn.cursor()
    cur.execute("SELECT type, COUNT(*) AS c FROM nodes GROUP BY type ORDER BY type")
    return {row["type"]: row["c"] for row in cur.fetchall()}


def edge_counts_by_type(conn):
    cur = conn.cursor()
    cur.execute("SELECT type, COUNT(*) AS c FROM edges GROUP BY type ORDER BY type")
    return {row["type"]: row["c"] for row in cur.fetchall()}


def get_nodes(conn, node_type=None, name=None, name_substring=None):
    """Fetch nodes with optional filters. Returns list of dicts (attrs parsed)."""
    sql = "SELECT id, type, name, file, line, attrs FROM nodes WHERE 1=1"
    params = []
    if node_type is not None:
        sql += " AND type = ?"
        params.append(node_type)
    if name is not None:
        sql += " AND name = ?"
        params.append(name)
    if name_substring is not None:
        sql += " AND name LIKE ?"
        params.append("%" + name_substring + "%")
    sql += " ORDER BY name"
    cur = conn.cursor()
    cur.execute(sql, params)
    return [_row_to_dict(r) for r in cur.fetchall()]


def _row_to_dict(row):
    try:
        attrs = json.loads(row["attrs"]) if row["attrs"] else {}
    except (ValueError, TypeError):
        attrs = {}
    return {
        "id": row["id"],
        "type": row["type"],
        "name": row["name"],
        "file": row["file"],
        "line": row["line"],
        "attrs": attrs,
    }
