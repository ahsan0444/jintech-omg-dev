---
name: figma-omg
description: Implement a Figma design/frame/node as OMG code — Perl Dancer2 + Template Toolkit .tt + jQuery + Bootstrap 3.3.5 + per-client SCSS + Bryntum widgets. Trigger when the user wants to implement, build, or match a Figma design/frame/node inside the OMG repo, or pastes a figma.com URL in the context of OMG work.
argument-hint: [figma URL or TICKET-ID]
disable-model-invocation: false
---

# /figma-omg [figma URL or TICKET-ID]

Turns a Figma frame into OMG code without shipping raw Figma tokens, without fighting
per-client `!important`, and without claiming "done" on CSS reasoning alone. OMG stack:
Dancer2, Template Toolkit (`.tt`), jQuery, Bootstrap 3.3.5, per-client SCSS under
`public/custom/<client>/` (compiled by `build_sass.sh`), Bryntum Scheduler/Grid widgets.
Fonts are **Helvetica Neue / SourceSansPro** — never Inter.

## 0. Account gate — before any other Figma call

Call the Figma MCP `whoami`. It must show the **company devops account** with a **Dev or
Full seat** on the client plan (client org **"Inside Ideas Group"**).

- View/Collab seat, or a personal account → **STOP**. Tell the user: View seats get
  **6 calls/month**, Dev/Full get **600/day**. Do not burn calls on the wrong account —
  ask them to switch accounts before continuing.
- Only proceed past this step once Dev/Full on the right org is confirmed.

## 1. Parse the node and scope the read

Parse the `node-id` from the URL (or ask for one if only a TICKET-ID was given and no
Figma link exists on the ticket). `get_metadata` on the frame to get the node tree, then
pick out the actual **component nodes** you need. Never pull a whole page's metadata —
scope to the target frame and its children.

## 2. Screenshot once, reuse always

`get_screenshot` per target node. Keep this screenshot and reuse it for the rest of the
task — never call `get_screenshot` again with `excludeScreenshot` after the first call
for the same node; re-fetching burns quota for no new information.

## 3. Design context — ask for plain output, not framework output

`get_design_context` per component node. Explicitly request **plain HTML + SCSS** (not
React/Tailwind) and note in the same call that you'll adapt it to `.tt` + Bootstrap 3.
Treat the returned markup/CSS as a reference shape, not literal output — it still needs
step 5 (token mapping) and step 6 (conflict scan) before it's shippable.

## 4. Variable defs — query variants directly

`get_variable_defs` per component node, **including nested variants**. A variant node's
values are often hidden from the parent frame's query — if the frame has variants
(hover/active/disabled states as separate nodes), query each variant node directly, not
just the top-level frame.

## 5. Token mapping — never ship a Figma variable name

For every Figma value/variable returned in steps 3-4, resolve it to an **existing** SCSS
variable or CSS custom property before it goes anywhere near code:

1. Query `mcp__plugin_jintech-omg-dev_product-graph__pg_design_tokens` first.
2. Grep `public/custom/_global.scss`, `public/custom/<client>/_style.scss`, and
   `public/css` for a matching existing name.
3. Check `~/.claude/docs/agents/figma-token-map.md` if it exists — a prior mapping may
   already be recorded there.
4. Use whatever existing name you find. **Never** paste a raw Figma variable name (e.g.
   `--Radius-radius-8`, `--Background-Panels`) into shipped CSS — these are Figma's
   internal token names, not OMG's, and they will not resolve to anything in the
   compiled SCSS.
5. No match found → use the raw value (px/rgb) and flag it explicitly in the plan file
   (step 8) as "no existing token — new raw value introduced."

## 6. Conflict scan — before writing a line of CSS

- Grep all `public/custom/*/_style.scss` and `public/css` for **bare-element selectors**
  (`label`, `input`, etc.) and **`!important`** on the target selectors/elements (`.btn`,
  `.btn-default`, etc.) — these are the two ways an existing theme rule silently beats a
  new one.
- Check Bryntum class specificity via **context7 docs** (Bryntum Scheduler topic) — never
  read `*.module.js` to figure this out.
- Assume Bryntum **re-injects its own classes at render** (`b-icon-align-start`,
  `b-text`, `b-box-item`, etc.) — an override written against a snapshot of the DOM will
  be gone on next render unless it targets a class Bryntum itself re-applies.
- Scope every override under a wrapper class. Do not write bare-element or global
  selectors to satisfy a Figma spec.

## 7. Assets

`download_assets` into `public/images/...`. Never link a Figma CDN URL directly in code —
those URLs **expire in 7 days** and will silently break the page later.

## 8. Write the plan file and get sign-off

Write `.planning/figma-<TICKET>.md` containing:
- Nodes used (id, name)
- Token map table: Figma value/variable → SCSS var/custom property (or "raw value, no
  match" per step 5.5)
- States present in the Figma file vs missing (hover/active/focus/disabled/empty/loading)
- Responsive behaviour called out in the design
- Per-client impact list (which `public/custom/<client>/` themes this touches)

Restate this plan to the user and ask **one round** of questions (frontier format: `❓ Q`
/ `➡️ recommended answer`) for missing states or ambiguities. Wait for confirmation
before writing implementation code.

## 9. Write the /verify design spec

Write `~/.agent-os/omg/.verify/design/<TICKET>.design.json`:

```json
{
  "url": "...",
  "viewport": {"width": 0, "height": 0},
  "elements": [
    {
      "selector": "...",
      "expect": { "css-prop": "value" },
      "states": { "hover": { "css-prop": "value" } }
    }
  ],
  "figma_screenshot": "..."
}
```

Expected values come from Figma, in **px** and **`rgb()`** — not Figma's variable names,
not `%`/`em` guesses.

## 10. Implement, then build only the affected clients

Write `.tt` / `.scss` / `.js`. Run `build_sass.sh` **only for the affected clients** — the
script compiles per-client lines; run the matching lines, not all 100+.

## 11. Hand off to /verify — never self-certify from CSS reasoning

Tell the user to run `/verify` (it reads the design.json from step 9 and checks computed
styles). Never report "done" from reading the CSS/diff alone — computed-style evidence
from `/verify` is the only acceptable proof.

---

## Common failure causes

1. **Theme `!important` beats the new rule** — an existing per-client `!important` on a
   bare-element or `.btn`-style selector silently wins; caught in step 6, not after.
2. **Spacing drift** — px values transcribed by eye instead of read from `get_design_context`/
   `get_variable_defs`, or rounded to the nearest existing utility class.
3. **Unverified "done"** — claiming completion from reading SCSS/diff instead of running
   `/verify` against computed styles.
4. **Figma variable names pasted into shipped CSS** — e.g. `--Background-Panels` ends up
   in a `.scss` file instead of being mapped to the existing OMG token in step 5.
5. **Bryntum class re-injection** — an override written against a one-time DOM snapshot
   disappears because Bryntum re-applies its own classes (`b-icon-align-start`, `b-text`,
   `b-box-item`) on every render; scope to a stable wrapper class instead.

## Browser JS note

When using the Browser JS tool to inspect computed styles or DOM state, wrap every
snippet in an IIFE: `(function () { ... })();` — this avoids leaking `const`/`let`
redeclarations across repeated calls in the same page context.
