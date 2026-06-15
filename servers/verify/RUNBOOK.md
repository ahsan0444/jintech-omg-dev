# Verify Runbook (editable)

The Python `/verify` skill reads this file and shells into the Node harness in this directory.
**This runbook is the editable contract** — steps and URLs below are meant to be tweaked by
developers as the app evolves. The harness reports back ONLY via exit code + a tiny result
file (`<DATA>/.verify/out/<feature>.result.json`); it never dumps page DOM or stdout payloads.

`<DATA>` = `$AGENT_OS_HOME/<repo data>` — for `omg` that is `~/.agent-os/omg`.

---

## 1. Restart after a backend change

The omg source is live-mounted; restarting the container re-runs the web server so Perl
changes are picked up.

```
node restart.mjs --repo omg
```

To validate against an already-running app WITHOUT disrupting it (probe only, no restart):

```
node restart.mjs --repo omg --check-only
```

## 2. Confirm Up AND the host actually serves

READY requires **both**:

- container is `Up` (`podman ps --filter name=^omg$` status contains `Up`), and
- `HEALTH_URL` returns `HEALTH_EXPECT`.

> **SSO redirect = UP.** This host 302-redirects every unauthenticated request to the IdP.
> `HEALTH_EXPECT=redirect:/loginsso` means a `3xx` whose `Location` contains `/loginsso` is
> HEALTHY. A *started* container is NOT the same as *ready* — only the health match confirms
> the host is serving. Connection-refused / 502 / 504 / timeout = NOT ready.

## 3. Auth replay (storageState)

The harness replays a captured Playwright `storageState`; it never drives the IdP.

```
node auth.mjs validate --repo omg
```

- exit 0 `AUTH_OK` — session live, proceed.
- exit 3 `AUTH_MISSING` — no state file; run the one-time manual capture:
  `node capture-auth.mjs --repo omg` (opens a headed browser; complete SSO).
- exit 2 `AUTH_EXPIRED` — probe redirected to `/loginsso`. **STOP and re-capture.**

The session token / cookies are PRIVATE: never logged, never screenshotted, never committed.

## 4. Navigate to the feature test URL

Test URLs come from the feature registry (`<DATA>/registry/features/<feature>.yml`).
For `jobs-deliverable-chooser` the planning-jobs URL is built from
`test_path_template: /campaigns/${TEST_CAMPAIGN_ID}/jobs` — set `TEST_CAMPAIGN_ID` in
`<DATA>/registry/.env.local`, or let verify discover and propose one.

- Tier 1 (no browser): `node tier1.mjs --repo omg --feature <feature> [--endpoint /path --expect status:200|redirect:/x]`
- Tier 2 (browser): `node run-spec.mjs --repo omg --feature <feature> --spec <path-to-spec>`

## 5. Verify acceptance assertions

Acceptance assertions live in the feature YAML under `acceptance:`. Tier-2 specs encode them
as Playwright assertions. The harness reduces the run to the FIRST failing assertion only.

## 6. Capture evidence

Evidence lands in `<DATA>/.verify/out/`:

- `<feature>.result.json` — the PASS/FAIL contract file.
- `<feature>.pw-report.json` — raw Playwright JSON report (Tier 2).
- screenshots (only-on-failure, Tier 2).

---

## Result file schema

```json
{
  "status": "PASS",
  "tier": 1,
  "feature": "jobs-deliverable-chooser",
  "failing_assertion": null,
  "screenshot": null,
  "observed": "302 -> http://.../loginsso?...",
  "expected": "redirect:/loginsso"
}
```

Exit code: `0` = PASS, non-zero = FAIL.
