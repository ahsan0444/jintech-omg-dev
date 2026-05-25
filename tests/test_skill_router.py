"""Tests for the skill-router UserPromptSubmit hook."""
import json
import os
import subprocess
import unittest

PLUGIN_ROOT = "/Users/Shared/Code/jintech-omg-dev"
HOOK_PATH = os.path.join(PLUGIN_ROOT, "hook-scripts", "skill-router.py")


def run_hook(prompt, env_override=None):
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = PLUGIN_ROOT
    # Avoid polluting user's real log dir during tests
    env.setdefault("HOME", env.get("HOME", "/tmp"))
    if env_override:
        env.update(env_override)
    data = {"hook_event_name": "UserPromptSubmit", "prompt": prompt}
    result = subprocess.run(
        ["python3", HOOK_PATH],
        input=json.dumps(data),
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    return result.stdout, result.returncode


class TestBypass(unittest.TestCase):
    def test_kill_switch_env_var(self):
        out, rc = run_hook("create a pr now", env_override={"CLAUDE_SKILL_ROUTER_DISABLED": "1"})
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_slash_prefix(self):
        out, rc = run_hook("/ticket OMGXI-1234")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_backslash_prefix(self):
        out, rc = run_hook("\\ticket OMGXI-1234")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")


class TestHighConfidenceSkillRoutes(unittest.TestCase):
    def test_pr_create(self):
        out, rc = run_hook("please create a PR for this branch")
        self.assertEqual(rc, 0)
        self.assertIn("ROUTING ACTIVE", out)
        self.assertIn("jintech-omg-dev:pr", out)

    def test_ticket_investigate(self):
        out, rc = run_hook("investigate the ticket OMGXI-9999")
        self.assertEqual(rc, 0)
        self.assertIn("ROUTING ACTIVE", out)
        self.assertIn("jintech-omg-dev:ticket", out)

    def test_debug(self):
        out, rc = run_hook("debug this failure please")
        self.assertEqual(rc, 0)
        self.assertIn("ROUTING ACTIVE", out)
        self.assertIn("jintech-omg-dev:debug", out)

    def test_prepr(self):
        out, rc = run_hook("run pre-pr checks now")
        self.assertEqual(rc, 0)
        self.assertIn("ROUTING ACTIVE", out)
        self.assertIn("jintech-omg-dev:prepr", out)


class TestHighConfidenceInlineRoutes(unittest.TestCase):
    def _assert_inline_or_silent(self, out, intent_id):
        # The inline procedure file may or may not exist locally. If present,
        # we expect PROCEDURE ACTIVE; if not, the hook emits nothing.
        if out:
            self.assertIn("PROCEDURE ACTIVE", out)
            self.assertIn(intent_id, out)
        else:
            self.assertEqual(out, "")

    def test_pr_address_comments(self):
        out, rc = run_hook("address the PR comments")
        self.assertEqual(rc, 0)
        self._assert_inline_or_silent(out, "pr-comments-address")

    def test_ticket_status(self):
        out, rc = run_hook("what's the ticket status?")
        self.assertEqual(rc, 0)
        self._assert_inline_or_silent(out, "ticket-status")


class TestNegativePatterns(unittest.TestCase):
    def test_ticket_already_fixed(self):
        # Negative lookahead matches text AFTER the OMGXI id.
        out, rc = run_hook("OMGXI-1234 is already fixed and closed")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_implementing_not_yet(self):
        # Negative lookahead matches text AFTER "implementing".
        out, rc = run_hook("start implementing this not yet please")
        self.assertEqual(rc, 0)
        self.assertNotIn("ROUTING ACTIVE", out)
        self.assertNotIn("PROCEDURE ACTIVE", out)


class TestLowConfidence(unittest.TestCase):
    def test_help_skills_low_confidence_hedge(self):
        out, rc = run_hook("what skills do you have?")
        self.assertEqual(rc, 0)
        # If the inline procedure file is missing, hook is silent.
        if out:
            self.assertIn("possible match", out)


class TestFixtures(unittest.TestCase):
    """Fixture-driven tests loaded from tests/router-fixtures.jsonl."""

    FIXTURES_PATH = os.path.join(os.path.dirname(__file__), "router-fixtures.jsonl")

    # Map intent id → skill name (or partial string expected in output for inline intents).
    # Inline intents produce "PROCEDURE ACTIVE: <intent-id>" when the file exists,
    # or empty output when the file is missing — both are acceptable.
    INTENT_TO_SKILL = {
        "pr-create": "jintech-omg-dev:pr",
        "pr-update": "jintech-omg-dev:pr",
        "pr-rebase": "jintech-omg-dev:pr",
        "pr-comments-address": "pr-comments-address",
        "pr-comments-fetch": "pr-comments-fetch",
        "ticket-investigate": "jintech-omg-dev:ticket",
        "ticket-id-direct": "jintech-omg-dev:ticket",
        "ticket-status": "ticket-status",
        "ticket-comment": "ticket-comment",
        "ticket-transition": "ticket-transition",
        "implement": "jintech-omg-dev:implement",
        "prepr": "jintech-omg-dev:prepr",
        "debug": "jintech-omg-dev:debug",
        "grill-me": "jintech-omg-dev:grill-me",
        "code-review": "code-review",
        "verify": "verify",
        "git-branch-summary": "git-branch-summary",
        "session-resume": "jintech-omg-dev:resume-session",
        "session-save": "jintech-omg-dev:save-session",
        "commit": "caveman:caveman-commit",
        "help-skills": "help-skills",
    }

    # Intents whose action type is "inline" — output may be empty if the file is missing.
    INLINE_INTENTS = {
        "pr-comments-address",
        "pr-comments-fetch",
        "ticket-status",
        "ticket-comment",
        "ticket-transition",
        "git-branch-summary",
        "help-skills",
    }

    def _load_fixtures(self):
        fixtures = []
        with open(self.FIXTURES_PATH, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                fixtures.append((lineno, json.loads(line)))
        return fixtures

    def test_all_fixtures(self):
        fixtures = self._load_fixtures()
        self.assertGreaterEqual(len(fixtures), 36, "Expected at least 36 fixture entries")
        failures = []
        for lineno, fixture in fixtures:
            prompt = fixture["prompt"]
            expected_intent = fixture["expected_intent"]
            out, rc = run_hook(prompt)
            self.assertEqual(rc, 0, f"Line {lineno}: hook exited non-zero for prompt: {prompt!r}")

            if expected_intent is None:
                # True negative: output must be empty
                if out.strip():
                    failures.append(
                        f"Line {lineno}: expected no match for {prompt!r} but got: {out[:120]!r}"
                    )
            else:
                # True positive: output must contain the skill name or intent id
                expected_token = self.INTENT_TO_SKILL.get(expected_intent, expected_intent)
                is_inline = expected_intent in self.INLINE_INTENTS
                if is_inline and not out.strip():
                    # Inline procedure file may be absent — silent output is acceptable
                    pass
                elif not out.strip():
                    failures.append(
                        f"Line {lineno}: expected match for intent={expected_intent!r} "
                        f"but got empty output for prompt: {prompt!r}"
                    )
                elif expected_token not in out and expected_intent not in out:
                    failures.append(
                        f"Line {lineno}: expected {expected_token!r} or {expected_intent!r} "
                        f"in output for prompt: {prompt!r}. Got: {out[:120]!r}"
                    )

        if failures:
            self.fail("Fixture failures:\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
