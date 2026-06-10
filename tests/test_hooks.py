"""Tests for the PreToolUse enforcement hooks and the run-hook.py dispatcher.

Covers the official hook contracts:
  - allow  = exit 0, empty stdout
  - deny   = exit 0, stdout JSON {"hookSpecificOutput": {"permissionDecision": "deny", ...}}
  - fail-open: malformed stdin / missing script never exits non-zero
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

PLUGIN_ROOT = os.environ.get(
    "PLUGIN_ROOT_OVERRIDE",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
DISPATCHER = os.path.join(PLUGIN_ROOT, "hook-scripts", "run-hook.py")


def run_hook(script, payload, cwd=None):
    """Invoke a hook via the dispatcher exactly as hooks.json does."""
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    result = subprocess.run(
        ["python3", DISPATCHER, script],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd or PLUGIN_ROOT,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT},
        timeout=15,
    )
    return result.stdout, result.returncode


def parse_deny(stdout):
    data = json.loads(stdout)
    return data["hookSpecificOutput"]


class TestDispatcher(unittest.TestCase):
    def test_missing_script_fails_open(self):
        out, rc = run_hook("does-not-exist", {})
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_no_args_fails_open(self):
        result = subprocess.run(
            ["python3", DISPATCHER], input="{}", capture_output=True, text=True, timeout=15
        )
        self.assertEqual(result.returncode, 0)


class TestEnforceSkillUsage(unittest.TestCase):
    def test_gh_pr_create_denied(self):
        out, rc = run_hook("enforce-skill-usage", {
            "tool_name": "Bash", "tool_input": {"command": "gh pr create --title x"},
        })
        self.assertEqual(rc, 0)
        decision = parse_deny(out)
        self.assertEqual(decision["hookEventName"], "PreToolUse")
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("jintech-omg-dev:pr", decision["permissionDecisionReason"])

    def test_other_bash_allowed(self):
        out, rc = run_hook("enforce-skill-usage", {
            "tool_name": "Bash", "tool_input": {"command": "ls -la"},
        })
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_malformed_stdin_fails_open(self):
        out, rc = run_hook("enforce-skill-usage", "not json at all")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")


class TestEnforceMcpSearch(unittest.TestCase):
    """Build a throwaway git repo with a graph.db to exercise the deny path."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="crg-test-repo-")
        subprocess.run(["git", "init", "-q", self.repo], check=True, capture_output=True)
        os.makedirs(os.path.join(self.repo, ".code-review-graph"), exist_ok=True)
        with open(os.path.join(self.repo, ".code-review-graph", "graph.db"), "w") as f:
            f.write("")
        os.makedirs(os.path.join(self.repo, "lib"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_grep_tool_in_covered_dir_denied(self):
        out, rc = run_hook("enforce-mcp-search", {
            "tool_name": "Grep",
            "tool_input": {"path": os.path.join(self.repo, "lib")},
            "cwd": self.repo,
        }, cwd=self.repo)
        self.assertEqual(rc, 0)
        decision = parse_deny(out)
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("semantic_search_nodes_tool", decision["permissionDecisionReason"])

    def test_bash_grep_in_covered_dir_denied(self):
        out, rc = run_hook("enforce-mcp-search", {
            "tool_name": "Bash",
            "tool_input": {"command": f"grep -rn foo {self.repo}/lib/"},
            "cwd": self.repo,
        }, cwd=self.repo)
        self.assertEqual(rc, 0)
        self.assertEqual(parse_deny(out)["permissionDecision"], "deny")

    def test_grep_usr_lib_not_false_positive(self):
        # Regression: original hook blocked ANY path containing /lib/
        out, rc = run_hook("enforce-mcp-search", {
            "tool_name": "Bash",
            "tool_input": {"command": "grep foo /usr/lib/python3/dist-packages/x.py"},
            "cwd": self.repo,
        }, cwd=self.repo)
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_grep_in_views_allowed(self):
        out, rc = run_hook("enforce-mcp-search", {
            "tool_name": "Grep",
            "tool_input": {"path": os.path.join(self.repo, "views")},
            "cwd": self.repo,
        }, cwd=self.repo)
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_no_graph_repo_allowed(self):
        bare = tempfile.mkdtemp(prefix="no-graph-repo-")
        try:
            subprocess.run(["git", "init", "-q", bare], check=True, capture_output=True)
            out, rc = run_hook("enforce-mcp-search", {
                "tool_name": "Grep",
                "tool_input": {"path": os.path.join(bare, "lib")},
                "cwd": bare,
            }, cwd=bare)
            self.assertEqual(rc, 0)
            self.assertEqual(out, "")
        finally:
            shutil.rmtree(bare, ignore_errors=True)

    def test_non_grep_tool_allowed(self):
        out, rc = run_hook("enforce-mcp-search", {
            "tool_name": "Bash",
            "tool_input": {"command": f"ls {self.repo}/lib"},
            "cwd": self.repo,
        }, cwd=self.repo)
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
