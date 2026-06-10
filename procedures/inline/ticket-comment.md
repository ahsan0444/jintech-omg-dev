# Procedure: Add Comment to Ticket

## Step 1 — Get Ticket ID and Comment Text

```bash
TICKET_ID=$(git branch --show-current | grep -oiE 'OMGXI-[0-9]+' | head -1 | tr '[:lower:]' '[:upper:]')
echo "TICKET_ID=${TICKET_ID:-none}"
```

If TICKET_ID = none: ask user for ticket ID.
If comment text not provided in user message: ask for it.

## Step 2 — Post Comment

```
0. If tool unknown: ToolSearch(query="+jira <tool>") — Atlassian tool prefix varies by install; use the returned variant.
1. Call mcp__plugin_atlassian_atlassian__getAccessibleAtlassianResources → get cloudId
2. Call mcp__plugin_atlassian_atlassian__addCommentToJiraIssue with:
     cloudId = <cloudId>
     issueIdOrKey = <TICKET_ID>
     body = <comment text from user>
```

## Step 3 — Confirm

Report: "Comment added to <TICKET_ID>."
