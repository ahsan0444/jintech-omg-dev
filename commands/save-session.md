---
description: Save current session state to a dated file in ~/.claude/session-data/ so work can be resumed in a future session with full context.
argument-hint: "[optional one-line topic override]"
---

**Today's date (use this — do not guess):** !`date +%Y-%m-%d`

# Save Session Command

Capture everything that happened in this session — what was built, what worked, what failed, what's left — and write it to a dated file so the next session can pick up exactly where this one left off.

## When to Use

- End of a work session before closing Claude Code
- Before hitting context limits (run this first, then start a fresh session)
- After solving a complex problem you want to remember
- Any time you need to hand off context to a future session

## Process

### Step 1: Gather context

Before writing the file, collect:

- Read all files modified during this session (use git diff or recall from conversation)
- Review what was discussed, attempted, and decided
- Note any errors encountered and how they were resolved (or not)
- Check current test/build status if relevant

### Step 2: Create the sessions folder if it doesn't exist

```bash
mkdir -p ~/.claude/session-data
```

### Step 3: Write the session file

Create `~/.claude/session-data/YYYY-MM-DD-<short-id>-session.tmp` using today's actual date and a short-id (lowercase letters, digits, hyphens, 8+ chars to avoid collisions). Example: `2024-01-15-abc123de-session.tmp`

### Step 4: Populate the file

Write every section honestly. Write "Nothing yet" or "N/A" if a section has no content — do not skip sections.

### Step 5: Show the file to the user

After writing, display the full contents and ask:

```
Session saved to [path]

Does this look accurate? Anything to correct or add before we close?
```

Wait for confirmation. Make edits if requested.

---

## Session File Format

```markdown
# Session: YYYY-MM-DD

**Started:** [approximate time if known]
**Last Updated:** [current time]
**Project:** [project name or path]
**Topic:** [one-line summary of what this session was about]

---

## What We Are Building

[1-3 paragraphs describing the feature, bug fix, or task with enough context that someone
with zero memory of this session can understand the goal, why it's needed, and how it fits
into the larger system.]

---

## What WORKED (with evidence)

[List only confirmed working items. For each include WHY you know it works — test passed,
ran in browser, returned 200, etc. Without evidence, move to "Not Tried Yet".]

- **[thing that works]** — confirmed by: [specific evidence]

If nothing confirmed: "Nothing confirmed working yet."

---

## What Did NOT Work (and why)

[Most important section. Every failed approach with EXACT reason — "threw X error because Y"
not "didn't work".]

- **[approach tried]** — failed because: [exact reason / error message]

If nothing failed: "No failed approaches yet."

---

## What Has NOT Been Tried Yet

[Approaches that seem promising but haven't been attempted.]

- [approach / idea]

---

## Current State of Files

| File | Status | Notes |
|------|--------|-------|
| `path/to/file` | Complete / In Progress / Broken / Not Started | [notes] |

---

## Decisions Made

- **[decision]** — reason: [why this was chosen over alternatives]

---

## Blockers & Open Questions

- [blocker / open question]

---

## Exact Next Step

[Single most important thing to do when resuming. Precise enough that resuming requires
zero thinking about where to start. If unknown: "Review 'What Has NOT Been Tried Yet'
and 'Blockers' to decide direction."]
```
