"""Load the private registry for a repo's data home.

Reads from:  $AGENT_OS_HOME/<data>/registry/
    env            (ini-ish KEY=VAL; .env / .env.local* — optional)
    auth.yml       (auth config — optional)
    features/*.yml (one feature per file — PyYAML)

Per feature file emits:
    {type:"feature", name:<file stem>,
     attrs:{ticket, description, routes, selectors, acceptance,
            test_path_template, _env, _auth}}

For each feature route path, emits a best-effort edge to a matching GET route
node (matched by path string):
    {src:<feature name>, dst:"GET <path>", type:"tests_route"}

PyYAML is the only non-stdlib dependency here.
"""

import glob
import os

try:
    import yaml
except ImportError:  # pragma: no cover - surfaced clearly at call site
    yaml = None


def _parse_env(path):
    """Parse an ini-ish KEY=VAL env file. Ignores blanks and # comments."""
    out = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):]
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                out[key.strip()] = val.strip().strip("'\"")
    except OSError:
        pass
    return out


def _load_yaml(path):
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required to load the registry. Install with: pip install pyyaml"
        )
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return yaml.safe_load(fh) or {}
    except OSError:
        return {}


def _feature_route_paths(feat):
    """Yield every 'path' string found under the feature's routes mapping."""
    routes = feat.get("routes") if isinstance(feat, dict) else None
    if not isinstance(routes, dict):
        return
    for _key, spec in routes.items():
        if isinstance(spec, dict) and isinstance(spec.get("path"), str):
            yield spec["path"]
        elif isinstance(spec, str):
            yield spec


def extract(data_dir, route_nodes=None):
    """Return (nodes, edges).

    data_dir   : absolute path to $AGENT_OS_HOME/<data>
    route_nodes: optional list of already-extracted route nodes, used to build
                 tests_route edges (best-effort path match).
    """
    nodes = []
    edges = []
    registry_dir = os.path.join(data_dir, "registry")

    # Shared env + auth context (attached to every feature for convenience).
    env_ctx = {}
    for env_name in (".env.local", ".env", "env"):
        env_path = os.path.join(registry_dir, env_name)
        if os.path.isfile(env_path):
            env_ctx.update(_parse_env(env_path))

    auth_ctx = {}
    auth_path = os.path.join(registry_dir, "auth.yml")
    if os.path.isfile(auth_path):
        auth_ctx = _load_yaml(auth_path)

    # Index GET routes by path for edge matching.
    path_to_route = {}
    for rn in route_nodes or []:
        attrs = rn.get("attrs", {})
        if attrs.get("method") == "GET":
            path_to_route.setdefault(attrs.get("path"), rn["name"])
    # Fallback: also index any method if no GET exists for the path.
    any_path_to_route = {}
    for rn in route_nodes or []:
        any_path_to_route.setdefault(rn.get("attrs", {}).get("path"), rn["name"])

    feat_glob = os.path.join(registry_dir, "features", "*.yml")
    for path in sorted(glob.glob(feat_glob)):
        stem = os.path.splitext(os.path.basename(path))[0]
        feat = _load_yaml(path)
        if not isinstance(feat, dict):
            feat = {}
        nodes.append(
            {
                "type": "feature",
                "name": stem,
                "file": os.path.relpath(path, data_dir),
                "line": None,
                "attrs": {
                    "ticket": feat.get("ticket"),
                    "description": feat.get("description"),
                    "routes": feat.get("routes"),
                    "selectors": feat.get("selectors"),
                    "acceptance": feat.get("acceptance"),
                    "test_path_template": feat.get("test_path_template"),
                    "_env": env_ctx,
                    "_auth": auth_ctx,
                },
            }
        )

        for rpath in _feature_route_paths(feat):
            target = path_to_route.get(rpath) or any_path_to_route.get(rpath)
            if target:
                edges.append(
                    {"src": stem, "dst": target, "type": "tests_route"}
                )

    return nodes, edges
