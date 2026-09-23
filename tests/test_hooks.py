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
import sys
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

    def test_bash_grep_single_file_allowed(self):
        # Targeted single-file checks (e.g. layer-convention greps) are exempt.
        target = os.path.join(self.repo, "lib", "foo_db.pm")
        with open(target, "w") as f:
            f.write("package foo_db;\n1;\n")
        out, rc = run_hook("enforce-mcp-search", {
            "tool_name": "Bash",
            "tool_input": {"command": f"grep -n 'bless' {target}"},
            "cwd": self.repo,
        }, cwd=self.repo)
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_bash_grep_file_glob_allowed(self):
        # Explicit file globs with an extension (route files) are exempt.
        out, rc = run_hook("enforce-mcp-search", {
            "tool_name": "Bash",
            "tool_input": {"command": "grep -n 'route' lib/OMG*.pm"},
            "cwd": self.repo,
        }, cwd=self.repo)
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_grep_tool_single_file_allowed(self):
        target = os.path.join(self.repo, "lib", "foo_helper.pm")
        with open(target, "w") as f:
            f.write("package foo_helper;\n1;\n")
        out, rc = run_hook("enforce-mcp-search", {
            "tool_name": "Grep",
            "tool_input": {"path": target, "pattern": "_controller->"},
            "cwd": self.repo,
        }, cwd=self.repo)
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_bash_grep_mixed_file_and_dir_denied(self):
        # A directory anywhere in the targets keeps the block.
        out, rc = run_hook("enforce-mcp-search", {
            "tool_name": "Bash",
            "tool_input": {"command": f"grep -n foo {self.repo}/lib/foo.pm {self.repo}/lib/"},
            "cwd": self.repo,
        }, cwd=self.repo)
        self.assertEqual(rc, 0)
        self.assertEqual(parse_deny(out)["permissionDecision"], "deny")


class TestPostEditLint(unittest.TestCase):
    """post-edit-lint.py — pure-function coverage plus podman-free hook paths."""

    def setUp(self):
        import importlib.util
        path = os.path.join(PLUGIN_ROOT, "hook-scripts", "post-edit-lint.py")
        spec = importlib.util.spec_from_file_location("post_edit_lint", path)
        self.mod = importlib.util.module_from_spec(spec)
        sys.modules["post_edit_lint"] = self.mod
        spec.loader.exec_module(self.mod)

        self.repo = tempfile.mkdtemp(prefix="omg-lint-test-repo-")
        # Make the temp repo look like an "omg" repo without touching the real one.
        self.omg_repo = os.path.join(tempfile.mkdtemp(prefix="lint-parent-"), "omg")
        os.makedirs(os.path.join(self.omg_repo, "lib"), exist_ok=True)
        subprocess.run(["git", "init", "-q", self.omg_repo], check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(os.path.dirname(self.omg_repo), ignore_errors=True)

    def _run(self, file_path, session_id="test-session", extra_env=None):
        env = {**os.environ, "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT}
        if extra_env:
            env.update(extra_env)
        payload = json.dumps({
            "tool_input": {"file_path": file_path},
            "session_id": session_id,
        })
        result = subprocess.run(
            ["python3", DISPATCHER, "post-edit-lint"],
            input=payload, capture_output=True, text=True,
            cwd=PLUGIN_ROOT, env=env, timeout=15,
        )
        return result.stdout, result.returncode

    def test_non_omg_repo_no_output(self):
        # A repo whose basename isn't "omg" must never trigger the linter.
        f = os.path.join(self.repo, "lib", "foo.pm")
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f, "w") as fh:
            fh.write("package foo;\n1;\n")
        subprocess.run(["git", "init", "-q", self.repo], check=True, capture_output=True)
        out, rc = self._run(f)
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_unknown_extension_no_output(self):
        f = os.path.join(self.omg_repo, "lib", "notes.md")
        with open(f, "w") as fh:
            fh.write("# notes\n")
        out, rc = self._run(f)
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_container_not_running_no_output(self):
        f = os.path.join(self.omg_repo, "lib", "foo.pm")
        with open(f, "w") as fh:
            fh.write("package foo;\n1;\n")
        out, rc = self._run(
            f, session_id="down-session",
            extra_env={"OMG_LINT_FAKE_CONTAINER_DOWN": "1"},
        )
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_no_file_path_no_output(self):
        env = {**os.environ, "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT}
        result = subprocess.run(
            ["python3", DISPATCHER, "post-edit-lint"],
            input=json.dumps({"tool_input": {}}), capture_output=True, text=True,
            cwd=PLUGIN_ROOT, env=env, timeout=15,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_malformed_stdin_fails_open(self):
        out, rc = run_hook("post-edit-lint", "not json at all")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    # -- pure-function coverage (no podman needed) -----------------------
    def test_env_failure_ignored_but_syntax_error_reported(self):
        self.assertTrue(self.mod.is_env_failure(
            "List::Util version 1.56 required--this is only version 1.55 at x line 3."))
        self.assertFalse(self.mod.is_env_failure('syntax error at lib/a.pm line 4, near "}"'))

    def test_trim_errors_short_passthrough(self):
        self.assertEqual(self.mod.trim_errors("line1\nline2"), "line1\nline2")

    def test_trim_errors_truncates_long_output(self):
        text = "\n".join(f"line{i}" for i in range(40))
        out = self.mod.trim_errors(text, max_lines=30)
        lines = out.splitlines()
        self.assertEqual(len(lines), 31)  # 30 kept + truncation notice
        self.assertIn("10 more line(s) truncated", lines[-1])

    def test_block_json_from_perl_dash_c_error(self):
        perl_error = (
            "syntax error at /var/www/OMG/lib/foo.pm line 12, near \"}\"\n"
            "/var/www/OMG/lib/foo.pm had compilation errors.\n"
        )
        result = self.mod.block_json("lib/foo.pm", perl_error)
        self.assertEqual(result["decision"], "block")
        self.assertTrue(result["reason"].startswith("lib/foo.pm: "))
        self.assertIn("syntax error", result["reason"])

    def test_block_json_from_perlcritic_error(self):
        critic_error = (
            "Bareword file handle opened at line 5.  "
            "(Severity: 5)\n"
        )
        result = self.mod.block_json("lib/foo.pm", critic_error)
        self.assertEqual(result["decision"], "block")
        self.assertIn("Severity: 5", result["reason"])

    def test_to_container_path_maps_repo_root(self):
        path = self.mod.to_container_path("/Users/Shared/Code/omg", "/Users/Shared/Code/omg/lib/foo.pm")
        self.assertEqual(path, "/var/www/OMG/lib/foo.pm")

    def test_is_covered_repo_respects_env_override(self):
        with_env = os.environ.copy()
        os.environ["OMG_LINT_REPOS"] = "omg,otherapp"
        try:
            import importlib.util
            path = os.path.join(PLUGIN_ROOT, "hook-scripts", "post-edit-lint.py")
            spec = importlib.util.spec_from_file_location("post_edit_lint_reloaded", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self.assertTrue(mod.is_covered_repo("/x/y/otherapp"))
            self.assertFalse(mod.is_covered_repo("/x/y/unrelated"))
        finally:
            os.environ.clear()
            os.environ.update(with_env)


if __name__ == "__main__":
    unittest.main()
