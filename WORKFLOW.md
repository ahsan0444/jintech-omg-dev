# OMG Pipeline — Workflow & Architecture

## 1. Pipeline Overview

```mermaid
flowchart LR
    GM["/grill-me\nSpec interview"]
    TK["/ticket\nInvestigation\n+ Plan"]
    IM["/implement\nCode changes"]
    PR_["/prepr\nPre-PR audit"]
    PR["/pr\nDraft PR"]

    GM -->|"optional handoff\n(fresh session)"| TK
    TK -->|"approved plan\nsaved to .planning/"| IM
    IM -->|"changes on branch"| PR_
    PR_ -->|"no blockers"| PR

    style GM fill:#e8f4fd,stroke:#4a9ede
    style TK fill:#e8f4fd,stroke:#4a9ede
    style IM fill:#e8f4fd,stroke:#4a9ede
    style PR_ fill:#e8f4fd,stroke:#4a9ede
    style PR fill:#e8f4fd,stroke:#4a9ede
```

**Session rule:** Each phase = its own fresh session. Exception: `/grill-me` may hand off to `/ticket` in the same session if the user confirms.

---

## 2. Session Boundaries & Artifacts

```mermaid
flowchart TD
    subgraph S1["Session 1 (optional)"]
        GM["/grill-me\nInterview + codebase exploration"]
        GF[".planning/grill-TICKET.md"]
        GM -->|saves| GF
    end

    subgraph S2["Session 2"]
        TK["/ticket\nOrchestrator"]
        GF -->|auto-loads if present| TK
        AP[".planning/approved-plan-TICKET.md"]
        TK -->|"user types 'approved'"| AP
    end

    subgraph S3["Session 3"]
        IM["/implement\nOrchestrator"]
        AP -->|auto-loads| IM
        CL["change log\n(in-session only)"]
        IM --> CL
    end

    subgraph S4["Session 4"]
        PP["/prepr\nAudit orchestrator"]
        AM["~/.claude/.../memory/antipatterns.md"]
        PP -->|"blockers → appends"| AM
    end

    subgraph S5["Session 5"]
        PR["/pr\nPR orchestrator"]
        PP -->|"clean branch"| PR
    end

    style S1 fill:#f0f8e8,stroke:#7cb87c
    style S2 fill:#e8f4fd,stroke:#4a9ede
    style S3 fill:#fff3e0,stroke:#e6a020
    style S4 fill:#fde8e8,stroke:#de4a4a
    style S5 fill:#f3e8fd,stroke:#9e4ade
```

---

## 3. /grill-me — Internal Architecture

```mermaid
flowchart TD
    Start["User: /grill-me [TICKET-ID]"]
    Setup["Step 0: Repo detection\nResolve TICKET_ID"]
    Orient["Architectural orientation (Haiku subagent)\nget_architecture_overview_tool\nget_community_tool · get_suggested_questions_tool"]
    Interview["Interview loop\nQ&A — one branch at a time\nSubagent: MCP codebase exploration (haiku)\nsemantic_search · query_graph · get_community"]
    Done{"User: done / enough\nor shared understanding reached"}
    Summary["Build alignment summary\nPROBLEM · DESIRED_STATE · KNOWN_COMPONENTS\nOUT_OF_SCOPE · CONSTRAINTS · KEY_DECISIONS"]
    Save["Save to .planning/grill-TICKET.md"]
    Prompt{"Proceed to /ticket?"}
    Fresh["Tell user: start fresh session\nrun /ticket TICKET-ID"]
    Stop["Notes saved. Run /ticket when ready."]

    Start --> Setup --> Orient --> Interview --> Done --> Summary --> Save --> Prompt
    Prompt -->|yes| Fresh
    Prompt -->|no| Stop
```

---

## 4. /ticket — Internal Architecture

```mermaid
flowchart TD
    Start["User: /ticket [TICKET-ID]"]
    S0["Step 0 (main ctx)\nRepo detection · branch\nGrill-file auto-load · merge target confirm"]
    S1["Step 1 — Ticket Fetch\nHaiku subagent: Jira MCP\nReturns: TYPE · SUMMARY · AC · URLs"]
    Signals["Resolve signals (main ctx)\nDB_SIGNAL · LIB_SIGNAL"]

    subgraph Parallel["Step 2 — Parallel gathering (one message)"]
        S2a["2a: Confluence specs\n(if CONFLUENCE URL found)\nHaiku · Explore"]
        S2b["2b: JAM bug context\n(if JAM URL found)\nHaiku · Explore"]
        S2c["2c: Codebase query\n(always)\nHaiku · Explore\nMCP semantic + graph search\n(grep only for .tt fallback)"]
        S2cdb["2c-db: DB companion\n(if DB_SIGNAL=yes)\nHaiku · Explore"]
        S2d["2d: Test coverage\n(always)\nHaiku · Explore"]
    end

    Gate["INVESTIGATION GATE\nNo more subagents after this point"]
    S3["Step 3 — Confidence Evaluation (main ctx)\nPROBLEM_CLARITY · FILE_CONFIDENCE\nAPPROACH_CLARITY · MISSING_CONTEXT"]
    Clarify{"All 4 pass?"}
    ClarRound["Clarification Round\nMax 2 rounds · ask user\nNo subagents"]
    S4["Step 4 — Plan Mode\nEnterPlanMode · synthesise plan\nUser reviews + amends"]
    Approve{"User: 'approved'"}
    Save["Save to .planning/approved-plan-TICKET.md"]
    NextUp["Tell user: start fresh session\nrun /implement"]

    Retry["2c retry (if CONFIDENCE=low)\nHaiku · Explore"]

    Start --> S0 --> S1 --> Signals --> Parallel
    S2c --> Retry
    Parallel --> Gate --> S3 --> Clarify
    Clarify -->|no| ClarRound --> S3
    Clarify -->|yes| S4 --> Approve -->|yes| Save --> NextUp
```

---

## 5. /implement — Internal Architecture

```mermaid
flowchart TD
    Start["User: /implement"]
    S0["Step 0 (main ctx)\nLoad approved plan · detect repo\nFreshness check · plan conflict check"]
    S1["Step 1 — Pre-read (Haiku, Explore)\nVerify grep strings still match\nFlag stale line refs"]
    S2["Step 2 — Execute Steps\nPer plan implementation order"]

    subgraph ExecLoop["Execution loop (per step)"]
        Dep{"Dependencies\nsatisfied?"}
        Par["Parallel: spawn all\nindependent steps\n(Sonnet or Opus, general-purpose)"]
        Seq["Sequential: wait for\ndependencies"]
        Log["Update change log\nafter each subagent returns"]
        Retry{"Step failed?"}
        Attempt2["Retry (attempt 2)"]
        Escalate["Escalate to user\n(2 failures = stop)"]
    end

    S3["Step 3 — Cleanup\nrm .planning/approved-plan-*.md"]
    S4["Step 4 — Post-check (Haiku, Explore)\nVerify each edited file exists\nGrep for intended changes"]
    Done["Tell user: Done — start fresh session\nrun /prepr"]

    Start --> S0 --> S1 --> S2 --> ExecLoop
    Dep -->|no| Seq --> Log
    Dep -->|yes| Par --> Log
    Log --> Retry
    Retry -->|yes, attempt 1| Attempt2 --> Retry
    Retry -->|yes, attempt 2| Escalate
    Retry -->|no| S3 --> S4 --> Done
```

---

## 6. /prepr — Internal Architecture

```mermaid
flowchart TD
    Start["User: /prepr  OR  /prepr fix"]
    S0["Step 0 (main ctx)\nRepo detect · base branch · changed files\nBucket into: perl · sql · tt · js · scss · css"]
    S05["Step 0.5 — Semantic Risk Assessment (Haiku)\ndetect_changes_tool → risk-score every file\nget_impact_radius_tool → blast radius for high-risk nodes\nOutputs: RISK_TIER · HIGH_RISK_FILES · IMPACT_RADIUS"]

    subgraph Checks["Step 1 — Parallel checks (one message)"]
        C1a["1a: Perl review\nperlcritic + OMG layer conventions\nHaiku · Explore"]
        C1b["1b: TT template review\nHTML encoding · i18n · inline JS\nHaiku · Explore"]
        C1c["1c: JS review\nomg namespace · $.ajax · globals\nHaiku · Explore"]
        C1d["1d: CSS/SCSS review\ndirect CSS edits · import order\nHaiku · Explore"]
        C1e["1e: SQL review\nnaming · rollback pair · live DB check\nHaiku · Explore"]
    end

    S2["Step 2 — Perl test suite\n(only if Perl files changed)\nHaiku · prove -l t/"]
    S3["Step 3 — Synthesise report\nBLOCKERS · WARNINGS · CLEAN"]
    S3b["Step 3b — Antipattern memory\nAppend each BLOCKER to\nantipatterns.md"]

    Fix{"/prepr fix\ninvoked?"}
    S3c["Step 3c — Self-heal\nSonnet fix agent per WARNING\nRe-check · mark (auto-fixed)"]
    Out{"Blockers?"}
    Clear["No blockers — run /pr"]
    Blocked["Fix blockers · re-run /prepr"]

    Start --> S0 --> S05 --> Checks --> S2 --> S3 --> S3b --> Fix
    Fix -->|yes| S3c --> Out
    Fix -->|no| Out
    Out -->|no| Clear
    Out -->|yes| Blocked
```

---

## 7. /pr — Internal Architecture

```mermaid
flowchart TD
    Start["User: /pr"]
    S0["Step 0 (main ctx)\nRepo detect · Bitbucket slug mapping\nomg-docker guard (GitLab → stop)"]
    S1["Step 1 — Ticket fetch\nHaiku · Jira MCP\nReturns: TITLE · SUMMARY · AC"]
    S2["Step 2 — Confirm destination branch"]
    S3["Step 3 — Check existing PR\ncurl Bitbucket API"]
    ExistPR{"PR exists?"}
    Rebase["Rebase + push\nUpdate existing PR"]
    S4["Step 4 — Merge conflict check\ngit merge-tree"]
    S5["Step 5 — Generate change summary\ngit diff + approved-plan if present"]

    subgraph SubAgents["Step 5b — Parallel subagents"]
        S5risk["Risk assessment (Haiku)\ndetect_changes_tool → RISK_TIER\nget_affected_flows_tool → affected flows"]
        S6["Perlcritic report\n(only if Perl files changed)\nHaiku subagent"]
        S5ticket["Ticket fetch (Haiku · Jira MCP)\n(only if TICKET_ID known)"]
    end

    S7["Step 7 — Synthesise PR body\nTitle · Summary · AC · Changes\n+ Risk Assessment section (if high/medium)"]
    S8["Step 8 — Write payload + Create draft PR\nWrite tool → /tmp/pr_payload.json\ncurl Bitbucket REST v2"]
    Done["Return PR URL to user"]

    Start --> S0 --> S1 --> S2 --> S3 --> ExistPR
    ExistPR -->|yes| Rebase --> Done
    ExistPR -->|no| S4 --> S5 --> SubAgents --> S7 --> S8 --> Done
```

---

## 8. Subagent Model Ladder

```mermaid
flowchart LR
    subgraph Models
        H["Haiku\n(cheapest)"]
        S["Sonnet\n(default)"]
        O["Opus\n(heaviest)"]
    end

    H --> |"reads · greps\nticket fetch · JAM\nprepr checks\npost-impl verify"| Use1["Explore subagents\n(context discarded after)"]
    S --> |"plan synthesis\norchestration decisions\nprepr fix agents\nsimple/medium edits"| Use2["Main context\nor general-purpose subagent"]
    O --> |"complex/architectural edits\nhard debugging"| Use3["general-purpose subagent\n(isolated context)"]
```

---

## 9. Persistence Map

```mermaid
flowchart LR
    subgraph Files[".planning/ (per repo)"]
        GF["grill-TICKET.md\nwritten by /grill-me\nread by /ticket"]
        AP["approved-plan-TICKET.md\nwritten by /ticket\nread by /implement\ndeleted after /implement"]
    end

    subgraph Memory["~/.claude/projects/.../memory/"]
        SL["session-log.md\nauto-written by Stop hook\nbranch · tickets · plan-saves"]
        AM["antipatterns.md\nauto-appended by /prepr\nBLOCKER patterns"]
        RM["MEMORY.md\nindex of all memory files"]
    end

    subgraph Context["CLAUDE.md (project root)"]
        CD["Compact instructions\nalways in context\nmodel ladder · session rules\nsubagent discipline"]
    end
```
