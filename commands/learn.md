---
description: Extract reusable patterns from the current session and save as a skill file for future use.
argument-hint: "[optional pattern name or focus area]"
disable-model-invocation: true
---

# /learn - Extract Reusable Patterns

Analyze the current session and extract any patterns worth saving as skills.

## When to Use

After solving a non-trivial problem — especially:
- Error resolution patterns (root cause + fix)
- Non-obvious debugging techniques
- Workarounds for library quirks or API limitations
- OMG codebase-specific conventions discovered

## What NOT to Extract

- Trivial fixes (typos, simple syntax errors)
- One-time issues (specific API outages, etc.)
- Things already in CLAUDE.md or existing skills

## Process

1. Review the session for extractable patterns
2. Identify the most valuable/reusable insight
3. Draft the skill file
4. Ask user to confirm before saving
5. Save to `~/.claude/skills/learned/`

## Output Format

Create `~/.claude/skills/learned/<pattern-name>.md`:

```markdown
# [Descriptive Pattern Name]

**Extracted:** [Date]
**Context:** [Brief description of when this applies]

## Problem
[What problem this solves — be specific]

## Solution
[The pattern/technique/workaround]

## Example
[Code example if applicable]

## When to Use
[Trigger conditions]
```

Keep skills focused — one pattern per skill file.
