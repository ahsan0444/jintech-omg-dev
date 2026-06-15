---
name: verify
description: Autonomous tiered verification of a code change against the OMG testing runbook — restart, readiness, auth, render/behaviour — judged by assertions, never impression. Reports done ONLY on passing evidence (Definition of Done). Slots between /implement and /prepr; also standalone. Use after implementing a change, when asked to verify a fix works, or to confirm UI behaviour before a PR.
---

# /verify [feature]

Proves a change actually does what it should — or reports NOT done with evidence. Assertions
are the source of truth. Never a green status on unverified work.

This is the AUTONOMOUS verifier (scripted, headless, assertion-based). For interactive FE
exploration / visual debugging use the Claude Code Chrome extension in a SEPARATE session —
it is NOT a substitute for this skill (it declares success by glancing; that is the exact
false-completion failure this skill exists to prevent).

## 0. Resolve context (no re-pasting — pull from the graph + registry)
- repo = active repo (git root mapped in `~/.agent-os/config.yml`). data_dir = `~/.agent-os/<repo>`.
- feature = arg, or infer from the diff via product-graph (`pg_route` on changed routes → `tests_route` → feature).
- Load: `pg_feature(feature)`, `pg_selectors(feature)`, registry `env`/`auth.yml`/`features/<feature>.yml`, RUNBOOK (`servers/verify/RUNBOOK.md`). These give test URL, selectors, acceptance, restart cmd, readiness contract.

## 1. Classify the change (decides tier — never browse when curl suffices)
`git diff --name-only <base>...HEAD` (base = merge-base with the destination branch).
- **Backend-only** (.pm/.pl/.sql, and NO `.tt`/`.scss`/`.js` and not a UI-facing route via `pg_route`) → **Tier 1 only**.
- **Touches `.tt`/`.scss`/`.js`, OR a route file (`OMG*.pm`) feeding a UI route** (graph maps changed file → affected routes) → **Tier 1 then Tier 2**.
- Unsure → Tier 1+2 (bias to proof).

## 2. Run via the omg-verifier agent (isolated — diagnosis/self-fix churn stays out of main context)
Before dispatch, if Tier 2: record sha256 of the feature's spec file → **SPEC-TAMPER GUARD**.
Spawn `Agent(subagent_type="jintech-omg-dev:omg-verifier", model="sonnet", ...)` with repo/feature/tier/base/data_dir + resolved context. It runs the harness (restart → tier1 → auth → run-spec), judges by the result file, and on behavioral failure self-fixes (impl only, max 2). It returns the STATUS schema.

After the agent returns, if Tier 2: re-hash the spec file. **If it changed → REJECT the run** ("spec modified during self-fix"), treat as FAIL, alert. This makes "self-fix never edits the test" mechanical, not prompt-trust.

## 3. Definition of Done — decision tree (the trust core)
```
STATUS == PASS and the assertion exercises THE CHANGE?
 └─ yes → DONE. Report PASS + result.json + screenshot path.
NOT_PROVEN (app up, no assertion covers the change)
 └─ NOT DONE. State the missing assertion. Do not report success.
FAIL_INFRA (no compile / container not Up / port dead)
 └─ revert verify-session edits to last-known-good (git stash the working changes) so the
    env is never left broken → ALERT (assertion + what + that it was reverted).
FAIL_BEHAVIORAL (app up, assertion failed after 2 self-fix attempts)
 └─ leave server up + edits INTACT for inspection → ALERT (failing assertion + screenshot
    + observed vs expected). Never silent. Never done.
AUTH (storageState expired/missing)
 └─ STOP → ALERT "re-capture auth: node servers/verify/capture-auth.mjs --repo <repo>".
```
Rules: alert BEFORE any revert; behavioral→leave intact, infra→revert; a self-fix edits
implementation only; "app loaded" is never "done".

## 4. Alert
Terminal summary + `PushNotification` (load via ToolSearch): `VERIFY <STATUS> <feature> — <assertion> — <screenshot>`. Compact; the full page never enters context.

## 5. Write-back (discovery → proposal, never auto-trust)
Facts confirmed live during the run (a real selector, the working test URL/campaign id, a flow
step) → write to `<data_dir>/registry/.pending/<feature>.yml` and tell the user to review/merge.
Never edit the committed (trusted) registry directly.

## 6. End
Report STATUS + evidence paths. On DONE you may hand to /prepr. Say: "Done — start a fresh session for the next phase."
