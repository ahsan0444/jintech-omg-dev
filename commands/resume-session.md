---
description: Load the most recent session file from ~/.claude/session-data/ and resume work with full context from where the last session ended.
---

# Resume Session Command

Load the last saved session state and orient fully before doing any work.

## Usage

```
/resume-session                                              # loads most recent file
/resume-session 2024-01-15                                   # loads most recent for that date
/resume-session ~/.claude/session-data/2024-01-15-abc123de-session.tmp  # loads specific file
```

## Process

### Step 1: Find the session file

If no argument:
1. Check `~/.claude/session-data/`
2. Pick most recently modified `*-session.tmp` file
3. If none found: "No session files found. Run /save-session to create one." Then stop.

If argument is a date (`YYYY-MM-DD`): search `~/.claude/session-data/` for matching files, load most recent.
If argument is a file path: read that file directly.

### Step 2: Read the entire session file

Read complete file. Do not summarize yet.

### Step 3: Confirm understanding

Respond in this exact format:

```
SESSION LOADED: [resolved path]
════════════════════════════════════════════════

PROJECT: [project name / topic]

WHAT WE'RE BUILDING:
[2-3 sentence summary in your own words]

CURRENT STATE:
✓ Working: [count] items confirmed
→ In Progress: [files in progress]
○ Not Started: [planned but untouched]

WHAT NOT TO RETRY:
[every failed approach with its reason — critical]

OPEN QUESTIONS / BLOCKERS:
[blockers or unanswered questions]

NEXT STEP:
[exact next step if defined, otherwise "No next step defined — review 'What Has NOT Been Tried Yet'"]

════════════════════════════════════════════════
Ready to continue. What would you like to do?
```

### Step 4: Wait for the user

Do NOT start working automatically. Do NOT touch any files. Wait for user direction.

---

## Edge Cases

**Multiple sessions same date:** load most recently modified.

**File references files that no longer exist:** note "WARNING: `path` referenced but not found on disk."

**Session file older than 7 days:** note "WARNING: This session is N days old. Things may have changed."

**Empty or malformed file:** "Session file found but appears empty. You may need to create a new one with /save-session."
