"""Extract Dancer2 routes from Perl route files (lib/OMG*.pm).

Pure stdlib. Line-based regex matching of the Dancer2 DSL forms used in OMG:

    get  '/path'                       => \\&controller::sub;
    post '/path'                       => \\&controller::sub;
    del  '/path'                       => \\&controller::sub;
    put  '/path'                       => \\&controller::sub;
    patch '/path'                      => \\&controller::sub;
    any  ['get','post'] => '/path'     => \\&controller::sub;
    any  '/path'                       => \\&controller::sub;
    ajax ['post']       => '/path'     => \\&controller::sub;
    ajax '/path'                       => \\&controller::sub;

Only routes that resolve to a named handler (\\&controller::sub) are emitted.
Inline `sub { ... }` handlers and regex paths (qr{...}) are skipped because they
have no stable name/path to key on.

Each match -> one node:
    {type:"route", name:"<METHOD> <path>",
     attrs:{method, path, handler:"controller::sub", file, line}}
"""

import glob
import os
import re

# Verbs that introduce a route. `any`/`ajax` may carry a method-list prefix.
_VERBS = r"get|post|put|patch|del|delete|options|head"

# Quoted path, single or double quotes (named group). Captures inner path text.
_PATH = r"""['"](?P<path>[^'"]+)['"]"""

# A named handler reference: \&controller::sub  (controller may have ::)
_HANDLER = r"""\\&(?P<handler>[\w:]+)"""

# Simple verb form:   get '/path' => \&handler;
_RE_SIMPLE = re.compile(
    r"""^\s*(?P<method>%s)\s+%s\s*=>\s*%s""" % (_VERBS, _PATH, _HANDLER)
)

# any/ajax with optional ['get','post'] method list, then path, then handler.
#   any ['get','post'] => '/path' => \&handler;
#   any '/path' => \&handler;
#   ajax ['post'] => '/path' => \&handler;
#   ajax '/path' => \&handler;
_RE_ANYAJAX = re.compile(
    r"""^\s*(?P<kind>any|ajax)\s*"""
    r"""(?:\[(?P<methods>[^\]]*)\]\s*=>\s*)?"""
    r"""%s\s*=>\s*%s""" % (_PATH, _HANDLER)
)


def _parse_methods(raw):
    """'get','post' -> ['GET','POST']."""
    out = []
    for tok in re.findall(r"""['"]([^'"]+)['"]""", raw or ""):
        out.append(tok.strip().upper())
    return out


def extract(repo_root):
    """Return a list of route node dicts for every OMG*.pm route file."""
    nodes = []
    pattern = os.path.join(repo_root, "lib", "OMG*.pm")
    for path in sorted(glob.glob(pattern)):
        rel = os.path.relpath(path, repo_root)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue

        for lineno, line in enumerate(lines, start=1):
            # Try any/ajax first (it has a more specific prefix).
            m = _RE_ANYAJAX.match(line)
            if m:
                kind = m.group("kind")
                path_val = m.group("path")
                handler = m.group("handler")
                methods = _parse_methods(m.group("methods"))
                if not methods:
                    # any '/path' with no method list -> matches any verb.
                    # ajax with no method list -> POST by convention in Dancer2.
                    methods = ["ANY"] if kind == "any" else ["POST"]
                for method in methods:
                    label = "AJAX %s" % method if kind == "ajax" else method
                    nodes.append(_node(label, path_val, handler, rel, lineno))
                continue

            m = _RE_SIMPLE.match(line)
            if m:
                method = m.group("method").upper()
                if method == "DELETE":
                    method = "DEL"
                nodes.append(
                    _node(method, m.group("path"), m.group("handler"), rel, lineno)
                )
                continue

    return nodes


def _node(method, path_val, handler, rel, lineno):
    return {
        "type": "route",
        "name": "%s %s" % (method, path_val),
        "file": rel,
        "line": lineno,
        "attrs": {
            "method": method,
            "path": path_val,
            "handler": handler,
            "file": rel,
            "line": lineno,
        },
    }
