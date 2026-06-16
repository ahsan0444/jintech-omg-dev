# OMG Layer Rules

Loaded by `implement/SKILL.md` Step 2 when falling back to `general-purpose` subagent type.
Normal usage: `omg-implementer` agent type has these rules baked in — no manual inclusion needed.

---

## Layers

**dao** (`lib/<area>/dao/*_db.pm`) — the ONLY layer that touches the database.
- Returns unblessed hashes/arrays only — no `bless()`, no `->new()` in returns.
- All DB access goes through PostgreSQL stored functions with bound params:
  `database->prepare('SELECT * FROM <function_name>(?, ?)')` + `execute(@binds)`.
- Never build SQL by string interpolation.
- There is no ORM — no DBIC, no Rose::DB; never write `->create/->find/->update` style calls.

**dom** (`lib/<area>/dom/*_dom.pm`) — Moo-based domain object.
- Use `Moo` — not Moose, not hand-rolled bless.
- Must have `sub TO_JSON { return { %{ shift() } }; }`.
- No DB access in this layer.

**helper** (`*_helper.pm`) — business logic; orchestrates dao + dom.
- Sole public API for this module.
- No foreign `_controller->` calls, no foreign `_db->` calls, no direct `database->` calls.

**controller** (`*_controller.pm`) — Dancer2 route handlers only.
- Calls helpers and renders/returns.
- No business logic, no `database->` calls, no foreign `_controller->` calls, no direct `_db` imports.

**i18n** — when edit adds or changes a user-facing string in `.tt` or JS:
- Use Locale::Wolowitz: `<% l('key_name') %>` in TT, `OMG.l('key_name')` / `localText.<key>` in JS (match surrounding form).
- Add key to ALL locale files: `locale/default/en.json`, `es.json`, `fr.json`, `ja.json`, `pt.json`, `pt-br.json`, `zh-cn.json`.
- Never hardcode display text.
