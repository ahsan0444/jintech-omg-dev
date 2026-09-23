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


class TestGitGuardrails(unittest.TestCase):
    """git-guardrails.py — pure decision-function coverage, no real git push/reset."""

    def setUp(self):
        import importlib.util
        path = os.path.join(PLUGIN_ROOT, "hook-scripts", "git-guardrails.py")
        spec = importlib.util.spec_from_file_location("git_guardrails", path)
        self.mod = importlib.util.module_from_spec(spec)
        sys.modules["git_guardrails"] = self.mod
        spec.loader.exec_module(self.mod)

        self.repo = tempfile.mkdtemp(prefix="guardrail-test-repo-")
        subprocess.run(["git", "init", "-q", self.repo], check=True, capture_output=True)
        subprocess.run(["git", "-C", self.repo, "config", "user.email", "t@t.com"], check=True, capture_output=True)
        subprocess.run(["git", "-C", self.repo, "config", "user.name", "t"], check=True, capture_output=True)
        with open(os.path.join(self.repo, "a.txt"), "w") as f:
            f.write("x\n")
        subprocess.run(["git", "-C", self.repo, "add", "a.txt"], check=True, capture_output=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", self.repo, "checkout", "-q", "-b", "feature/x"], check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def _checkout(self, branch, create=False):
        args = ["git", "-C", self.repo, "checkout", "-q"]
        if create:
            args.append("-b")
        args.append(branch)
        subprocess.run(args, check=True, capture_output=True)

    def _opted_out_repo(self):
        parent = tempfile.mkdtemp(prefix="guardrail-parent-")
        self.addCleanup(shutil.rmtree, parent, True)
        repo = os.path.join(parent, "jintech-omg-dev")
        subprocess.run(["git", "init", "-q", repo], check=True, capture_output=True)
        return repo

    def test_cd_into_opted_out_repo_then_push_main_allowed(self):
        repo = self._opted_out_repo()
        cmd = f"cd {repo} && git commit -qam x\ngit push -q origin main"
        self.assertEqual(self.mod.evaluate_command(cmd, self.repo), "")

    def test_git_dash_c_opted_out_repo_push_main_allowed(self):
        repo = self._opted_out_repo()
        self.assertEqual(self.mod.evaluate_command(f"git -C {repo} push origin main", self.repo), "")

    def test_newline_chained_push_to_master_denied(self):
        reason = self.mod.evaluate_command("echo hi\ngit push origin master", self.repo)
        self.assertIn("protected branch", reason)

    def test_force_push_dash_f_denied(self):
        reason = self.mod.evaluate_command("git push -f origin feature/x", self.repo)
        self.assertIn("Force push", reason)

    def test_force_with_lease_denied(self):
        reason = self.mod.evaluate_command("git push --force-with-lease origin feature/x", self.repo)
        self.assertIn("Force push", reason)

    def test_push_explicit_master_denied(self):
        reason = self.mod.evaluate_command("git push origin feature/x:master", self.repo)
        self.assertIn("protected branch", reason)

    def test_push_release_branch_denied(self):
        reason = self.mod.evaluate_command("git push origin HEAD:omg-s202", self.repo)
        self.assertIn("protected branch", reason)

    def test_bare_push_on_protected_current_branch_denied(self):
        self._checkout("master")
        reason = self.mod.evaluate_command("git push", self.repo)
        self.assertIn("Bare git push", reason)

    def test_push_feature_branch_allowed(self):
        reason = self.mod.evaluate_command("git push origin feature/x", self.repo)
        self.assertEqual(reason, "")

    def test_commit_on_protected_branch_denied(self):
        self._checkout("omg-s202-p2", create=True)
        reason = self.mod.evaluate_command("git commit -m x", self.repo)
        self.assertIn("protected branch", reason)

    def test_commit_on_feature_branch_allowed(self):
        reason = self.mod.evaluate_command("git commit -m x", self.repo)
        self.assertEqual(reason, "")

    def test_chained_add_and_commit_on_protected_branch_denied(self):
        self._checkout("main", create=True)
        reason = self.mod.evaluate_command("git add . && git commit -m x", self.repo)
        self.assertIn("protected branch", reason)

    def test_allowed_repo_opt_out_skips_branch_check(self):
        opt_out_repo = os.path.join(tempfile.mkdtemp(prefix="opt-out-"), "jintech-omg-dev")
        os.makedirs(opt_out_repo)
        subprocess.run(["git", "init", "-q", opt_out_repo], check=True, capture_output=True)
        subprocess.run(["git", "-C", opt_out_repo, "config", "user.email", "t@t.com"], check=True, capture_output=True)
        subprocess.run(["git", "-C", opt_out_repo, "config", "user.name", "t"], check=True, capture_output=True)
        with open(os.path.join(opt_out_repo, "a.txt"), "w") as f:
            f.write("x\n")
        subprocess.run(["git", "-C", opt_out_repo, "add", "a.txt"], check=True, capture_output=True)
        try:
            reason = self.mod.evaluate_command("git commit -m x", opt_out_repo)
            self.assertEqual(reason, "")
            reason = self.mod.evaluate_command("git push origin main", opt_out_repo)
            self.assertEqual(reason, "")
        finally:
            shutil.rmtree(os.path.dirname(opt_out_repo), ignore_errors=True)

    def test_reset_hard_denied(self):
        reason = self.mod.evaluate_command("git reset --hard HEAD~1", self.repo)
        self.assertIn("reset --hard", reason)

    def test_clean_f_denied(self):
        reason = self.mod.evaluate_command("git clean -fd", self.repo)
        self.assertIn("clean -f", reason)

    def test_branch_delete_force_denied(self):
        reason = self.mod.evaluate_command("git branch -D feature/x", self.repo)
        self.assertIn("branch -D", reason)

    def test_non_git_command_allowed(self):
        reason = self.mod.evaluate_command("ls -la", self.repo)
        self.assertEqual(reason, "")

    def test_gitleaks_absent_allows_commit(self):
        # gitleaks is very unlikely to be on PATH in CI; either way this must
        # not raise, and must not deny unless it's genuinely installed and
        # genuinely finds something in this throwaway repo's tiny diff.
        reason = self.mod.evaluate_command("git commit -m x", self.repo)
        self.assertIsInstance(reason, str)

    def test_split_segments_handles_chain(self):
        segments = self.mod.split_segments("git add . && git commit -m x; git status")
        self.assertEqual(segments, ["git add .", "git commit -m x", "git status"])

    def test_hook_dispatcher_denies_force_push(self):
        out, rc = run_hook("git-guardrails", {
            "tool_name": "Bash",
            "tool_input": {"command": "git push -f origin feature/x"},
            "cwd": self.repo,
        }, cwd=self.repo)
        self.assertEqual(rc, 0)
        self.assertEqual(parse_deny(out)["permissionDecision"], "deny")

    def test_hook_dispatcher_allows_plain_command(self):
        out, rc = run_hook("git-guardrails", {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
            "cwd": self.repo,
        }, cwd=self.repo)
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_malformed_stdin_fails_open(self):
        out, rc = run_hook("git-guardrails", "not json at all")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")


class TestSessionEndCapture(unittest.TestCase):
    """session-end-capture.py — pure-function extraction/redaction/skip-rule
    coverage on a small synthetic transcript, plus the hook's file-writing
    behavior via CAPTURE_OUT (no real ~/.claude/projects writes)."""

    def setUp(self):
        import importlib.util
        path = os.path.join(PLUGIN_ROOT, "hook-scripts", "session-end-capture.py")
        spec = importlib.util.spec_from_file_location("session_end_capture", path)
        self.mod = importlib.util.module_from_spec(spec)
        sys.modules["session_end_capture"] = self.mod
        spec.loader.exec_module(self.mod)

        self.tmpdir = tempfile.mkdtemp(prefix="sec-test-")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_transcript(self, entries):
        path = os.path.join(self.tmpdir, "transcript.jsonl")
        with open(path, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        return path

    def test_extracts_correction_with_preceding_assistant_context(self):
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"role": "assistant",
             "content": [{"type": "text", "text": "I moved the file to lib/foo.pm as requested."}]}},
            {"type": "user", "message": {"role": "user",
             "content": "No, that's wrong — I said lib/bar.pm instead."}},
        ])
        results = self.mod.extract_corrections(transcript)
        self.assertEqual(len(results), 1)
        self.assertIn("wrong", results[0]["message"])
        self.assertIn("lib/foo.pm", results[0]["context"])

    def test_skips_tool_result_content_list(self):
        transcript = self._write_transcript([
            {"type": "user", "message": {"role": "user",
             "content": [{"tool_use_id": "x", "type": "tool_result", "content": "no wrong actually"}]}},
        ])
        self.assertEqual(self.mod.extract_corrections(transcript), [])

    def test_skips_task_notification_and_system_blocks(self):
        transcript = self._write_transcript([
            {"type": "user", "message": {"role": "user",
             "content": "<task-notification>no wrong actually stop</task-notification>"}},
            {"type": "user", "message": {"role": "user",
             "content": "[SYSTEM NOTIFICATION] no wrong actually stop this"}},
        ])
        self.assertEqual(self.mod.extract_corrections(transcript), [])

    def test_non_correction_message_skipped(self):
        transcript = self._write_transcript([
            {"type": "user", "message": {"role": "user",
             "content": "please add a new helper function for this"}},
        ])
        self.assertEqual(self.mod.extract_corrections(transcript), [])

    def test_too_short_message_skipped(self):
        transcript = self._write_transcript([
            {"type": "user", "message": {"role": "user", "content": "no"}},
        ])
        self.assertEqual(self.mod.extract_corrections(transcript), [])

    def test_max_items_cap(self):
        entries = []
        for i in range(20):
            entries.append({"type": "user", "message": {"role": "user",
                "content": f"no that's wrong, try again number {i}"}})
        transcript = self._write_transcript(entries)
        results = self.mod.extract_corrections(transcript, max_items=15)
        self.assertEqual(len(results), 15)

    def test_redact_github_pat_and_password(self):
        text = "here is github_pat_abc123XYZ and password=hunter2secretvalue"
        redacted = self.mod.redact(text)
        self.assertNotIn("abc123XYZ", redacted)
        self.assertNotIn("hunter2secretvalue", redacted)
        self.assertIn("<REDACTED>", redacted)

    def test_redact_bearer_token(self):
        redacted = self.mod.redact("Authorization: Bearer sk-abc123.def456")
        self.assertIn("<REDACTED>", redacted)
        self.assertNotIn("sk-abc123.def456", redacted)

    def test_is_correction_length_bounds(self):
        self.assertFalse(self.mod.is_correction("no"))  # too short
        self.assertTrue(self.mod.is_correction("no that isn't what I wanted at all"))
        too_long = "actually " + ("x" * 700)
        self.assertFalse(self.mod.is_correction(too_long))

    def test_append_corrections_writes_header_once(self):
        out_path = os.path.join(self.tmpdir, "memory", "_pending-corrections.md")
        self.mod.append_corrections(out_path, [{"message": "no wrong", "context": "did a thing"}])
        with open(out_path) as f:
            content = f.read()
        self.assertIn("Pending Corrections", content)
        self.assertIn("no wrong", content)

        self.mod.append_corrections(out_path, [{"message": "actually try again", "context": ""}])
        with open(out_path) as f:
            content2 = f.read()
        self.assertEqual(content2.count("Pending Corrections"), 1)
        self.assertIn("actually try again", content2)

    def test_append_corrections_noop_on_empty(self):
        out_path = os.path.join(self.tmpdir, "memory", "_pending-corrections.md")
        self.mod.append_corrections(out_path, [])
        self.assertFalse(os.path.exists(out_path))

    def test_append_corrections_over_cap_writes_consolidation_note(self):
        out_path = os.path.join(self.tmpdir, "memory", "_pending-corrections.md")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w") as f:
            for i in range(self.mod.MAX_FILE_LINES + 5):
                f.write(f"line {i}\n")
        self.mod.append_corrections(out_path, [{"message": "no wrong", "context": ""}])
        with open(out_path) as f:
            content = f.read()
        self.assertIn("consolidation needed", content)
        self.assertNotIn("no wrong", content)

    def test_slug_for_cwd(self):
        self.assertEqual(self.mod.slug_for_cwd("/Users/Shared/Code/omg"), "-Users-Shared-Code-omg")

    def test_hook_end_to_end_via_dispatcher(self):
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"role": "assistant",
             "content": [{"type": "text", "text": "Renamed the variable to foo."}]}},
            {"type": "user", "message": {"role": "user",
             "content": "no that's wrong, revert that rename please"}},
        ])
        out_path = os.path.join(self.tmpdir, "memory", "_pending-corrections.md")
        env = {**os.environ, "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT, "CAPTURE_OUT": out_path}
        result = subprocess.run(
            ["python3", DISPATCHER, "session-end-capture"],
            input=json.dumps({
                "session_id": "s1", "transcript_path": transcript,
                "cwd": "/Users/Shared/Code/omg", "reason": "other",
            }),
            capture_output=True, text=True, cwd=PLUGIN_ROOT, env=env, timeout=15,
        )
        self.assertEqual(result.returncode, 0)
        with open(out_path) as f:
            content = f.read()
        self.assertIn("revert", content)

    def test_missing_transcript_fails_open(self):
        env = {**os.environ, "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT}
        result = subprocess.run(
            ["python3", DISPATCHER, "session-end-capture"],
            input=json.dumps({"session_id": "s1", "transcript_path": "/no/such/file.jsonl",
                               "cwd": "/x", "reason": "other"}),
            capture_output=True, text=True, cwd=PLUGIN_ROOT, env=env, timeout=15,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_malformed_stdin_fails_open(self):
        out, rc = run_hook("session-end-capture", "not json at all")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
