# /ticket — Plan Template

Loaded on demand by SKILL.md at the plan-writing step. Use the template below
verbatim — do not rename, reorder, or add sections. `## What I Understood` is
mandatory and must always be the first section after the title.

---

    # Plan: <TICKET_ID> — <title>

    ## What I Understood
    <1–2 sentences: the problem or need, and the proposed approach.
    User can redirect here before reading the full plan.>

    ## Problem
    <One sentence: what is broken or missing and why it matters.
    Derived from ticket SUMMARY + alignment notes if provided.>

    ## Out of Scope
    <Bullet list of what this ticket explicitly does NOT include.
    Source priority: grill-me OUT_OF_SCOPE field → USER_NOTES → ticket acceptance criteria → derived from ticket type.
    If nothing explicitly out of scope: "None stated — assume minimal footprint.">

    ## Approach
    <Only include if an approach choice was made during clarification.
    State which option was chosen and why in one sentence. Omit otherwise.>

    ## Affected Files
    - `path/to/file.ext:LINE` — reason

    ## Implementation Steps

    > **Line references come from subagent results — use them exactly as returned.** If a subagent returned a range (e.g. `450-480`), use that range. Do not approximate, guess, or invent line numbers. If a subagent did not return a line reference for a file, note it as `<line unknown — confirm in /implement>`.

    ### App Code — <REPO_NAME>
    1. **`file_path:line_range`** — what to change and why
       Dependencies: <none | requires step N>
       Grep for: `<unique string>`

       Change to:
           <replacement, indented 4 spaces>

    ### Database — omg_db
    *(omit this section if DB_COMPANION was not used)*
    N. **`dbscripts/sXX/NNN_<TICKET_ID>_description.sql`** — what the migration does
       Dependencies: <none | requires step N>
       Grep for: `(new file)`

       Content:
           <sql content, indented 4 spaces>

    ## Edge Cases
    - <anything needing special handling, or "None">

    ## Definition of Done
    - [ ] <one checkbox per acceptance criterion>
    - [ ] <include only if a step adds/changes user-facing strings in .tt or JS:
          "Locale key(s) added to all 7 locale/default/*.json files (en, es, fr,
          ja, pt, pt-br, zh-cn)">
    - [ ] No regressions in related areas
