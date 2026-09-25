# Changelog

Each release lists the two versions it carries: the skill's (which is also the
plugin's) and the server's.

## 2.0.3 — 2026-09-25

Skill 2.0.3, keepr-mcp 0.2.3.

- **Sub-collections.** A keepr collection can now sit inside another one (a
  family's *Health* inside *Biewend*). `keepr_collections` says which
  collection a sub-collection belongs to, and a sub-collection's schema
  includes the cards it inherits from the collection above it. A parent's
  schema lists its sub-collections' cards under `familyCards`, each with the
  collection that holds it — a record of one of those is written **there**.
  A row sent to the parent instead fails with `card_not_allowed` and a hint
  (`card_in_sub_collection`) naming the right collection, and the skill knows
  to send it on.
- An API key limited to a collection also reaches its sub-collections.
- Nothing else changes: the same nine tools, the same key handling. A keepr
  deployment without sub-collections simply never sends a parent.

## 2.0.2 — 2026-09-25

Skill 2.0.2, keepr-mcp 0.2.2.

- **Money.** keepr has a currency element now. The skill reads and writes
  amounts like `12.50 USD` or `CA$12`, knows that an element may allow only
  some currencies, and explains the new `invalid_currency` refusal (an unknown
  code, a currency the element does not allow, or more decimals than the
  currency has) instead of guessing.
- **Deleting needs its own permission.** A keepr API key or connected
  assistant can no longer delete anything unless its key was created with
  **Can delete records** (off by default), and deletes through a key have a
  daily limit. Keys made before 24 September do not have it — re-create the key
  if you want your assistant to delete. The skill recognises the refusal
  (`insufficient_scope` with `requiredScope: "delete"`) and the daily limit
  (`delete_budget_exhausted`, never retried), and `keepr_collections` says
  whether the key in use can delete.
- The server reports its version on its health check, and carries the updated
  keepr contract.
- Nothing else changes: the same nine tools, the same key handling.

## 2.0.1 — 2026-09-23

Skill 2.0.1, keepr-mcp 0.2.1.

- Every keepr account now has a **personal collection** — the catch-all for a
  note or a to do you have not said where to put. `keepr_collections` (and the
  skill's reference) mark it with `kind: "personal"` and list it first, so an
  assistant asked to "jot this down" has an obvious home for it.
- Nothing else changes: the same nine tools, the same key handling. An older
  keepr deployment simply never sends `kind`.

## 2.0.0 — 2026-09-22

First public build. Skill 2.0.0, keepr-mcp 0.2.0.

- The `keepr` skill, renamed from `keepr-add`, now covers reading, adding and
  cards — `items`, `get`, `search`, `login`, `logout` and `change-card` join
  `keepr.py`.
- `keepr-mcp` bundled to a single file; nine tools; reads the key from
  `~/.config/keepr/credentials` when no environment variable is set, so the
  Claude Code plugin needs no configuration.
- The desktop extension (`.mcpb`), with the key kept by Claude desktop.
- This marketplace.
