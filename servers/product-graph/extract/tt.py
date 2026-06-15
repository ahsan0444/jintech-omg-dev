"""Inventory Template Toolkit views (views/**/*.tt) and their include graph.

Pure stdlib.

Nodes:
    {type:"template", name:<path relative to repo>, attrs:{file}}

Edges (for INCLUDE / PROCESS / WRAPPER directives):
    {src:<this template rel path>, dst:<quoted target>, type:"includes"}

The dst is the raw target string as written in the directive (e.g. 'header.tt'),
since TT resolves it against INCLUDE_PATH at render time and we don't replicate
that resolution here.
"""

import glob
import os
import re

# INCLUDE / PROCESS / WRAPPER directives. Supports BOTH TT tag styles:
#   [% INCLUDE 'x' %]   (default TT2 tags)
#   <% INCLUDE "x" %>   (OMG's configured tag style)
# Tolerates optional whitespace and the `-` chomp markers ([%- / -%], <%- / -%>).
_RE_INCLUDE = re.compile(
    r"""(?:\[%|<%)-?\s*(?:INCLUDE|PROCESS|WRAPPER)\s+['"]([^'"]+)['"]""",
    re.IGNORECASE,
)


def extract(repo_root):
    """Return (nodes, edges) for all .tt templates under views/."""
    nodes = []
    edges = []
    pattern = os.path.join(repo_root, "views", "**", "*.tt")
    for path in sorted(glob.glob(pattern, recursive=True)):
        rel = os.path.relpath(path, repo_root)
        nodes.append(
            {
                "type": "template",
                "name": rel,
                "file": rel,
                "line": None,
                "attrs": {"file": rel},
            }
        )
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for target in _RE_INCLUDE.findall(text):
            edges.append({"src": rel, "dst": target, "type": "includes"})

    return nodes, edges
