# Available Skills & Natural Language Triggers

## SDLC Skills (jintech-omg-dev)
- `/ticket` — Investigate Jira ticket, produce plan → "investigate OMGXI-1234" / "look into ticket X" / mention ticket ID
- `/implement` — Execute approved plan → "start implementing" / "implement this"
- `/pr` — Create/update/rebase Bitbucket PR → "create a PR" / "rebase this branch" / "update the PR"
- `/prepr` — Pre-PR audit → "run prepr" / "check before PR" / "pre-PR checks"
- `/debug` — Root cause analysis → "debug this" / "something's broken" / "diagnose the issue"
- `/grill-me` — Spec-polishing interview → "grill me on this" / "stress test the plan"

## Review & Quality
- `/code-review` — Review diff → "review the diff" / "review the code" / "review branch changes"
- `/verify` — Verify change works → "verify this works" / "confirm the fix works"

## Session
- `/save-session` → "save the session" / "save where we are"
- `/resume-session` → "resume where we left off" / "continue the session"

## Inline Procedures (auto-triggered, no slash command)
- "address the PR comments" → address unresolved review comments
- "fetch the review comments" → show open PR comments
- "what's the ticket status" → fetch Jira status
- "add a comment to the ticket" → post Jira comment
- "move ticket to in progress" → transition ticket
- "what's in this branch" → git log + diff stat summary
