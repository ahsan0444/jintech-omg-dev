"""Extract design tokens from SCSS source.

Pure stdlib. Scans:
    public/css/**/*.scss
    public/custom/**/*.scss

SOURCE ONLY. Compiled/minified/bundled files are NEVER read:
    *.min.*  and any compiled .css are skipped.

Tokens:
    SCSS vars:        ^\\s*$name: value;
    CSS custom props:  --name: value;

Nodes:
    {type:"design_token", name:"$<var>" or "--<var>",
     attrs:{value, file, line}}
"""

import glob
import os
import re

# SCSS variable:  $primary-color: #fff;
_RE_SCSS_VAR = re.compile(r"^\s*\$([\w-]+)\s*:\s*(.+?);")
# CSS custom property:  --primary-color: #fff;
_RE_CSS_VAR = re.compile(r"--([\w-]+)\s*:\s*(.+?);")


def _is_skippable(path):
    base = os.path.basename(path).lower()
    if ".min." in base:
        return True
    # Defensive: never touch bundled/vendor trees even if globbed.
    lower = path.replace(os.sep, "/").lower()
    return any(seg in lower for seg in ("/node_modules/", "/dist/", "/vendor/"))


def extract(repo_root):
    """Return a list of design_token node dicts."""
    nodes = []
    roots = [
        os.path.join(repo_root, "public", "css", "**", "*.scss"),
        os.path.join(repo_root, "public", "custom", "**", "*.scss"),
    ]
    seen_files = set()
    for pattern in roots:
        for path in sorted(glob.glob(pattern, recursive=True)):
            if path in seen_files or _is_skippable(path):
                continue
            seen_files.add(path)
            rel = os.path.relpath(path, repo_root)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()
            except OSError:
                continue
            for lineno, line in enumerate(lines, start=1):
                m = _RE_SCSS_VAR.match(line)
                if m:
                    nodes.append(
                        _token("$" + m.group(1), m.group(2).strip(), rel, lineno)
                    )
                    continue
                m = _RE_CSS_VAR.search(line)
                if m:
                    nodes.append(
                        _token("--" + m.group(1), m.group(2).strip(), rel, lineno)
                    )
    return nodes


def _token(name, value, rel, lineno):
    return {
        "type": "design_token",
        "name": name,
        "file": rel,
        "line": lineno,
        "attrs": {"value": value, "file": rel, "line": lineno},
    }
