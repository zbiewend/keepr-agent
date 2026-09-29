# Changelog

Each release lists the two versions it carries: the skill's (which is also the
plugin's) and the server's.

## 2.0.5 — 2026-09-28

Skill 2.0.5, keepr-mcp 0.2.5.

- **A card that inherits from another is created with its parent, or not at
  all.** Ask for "a Bug card that is a Work item plus a severity" and your
  assistant now finds the parent — in the same request, in the collection, or
  among keepr's global cards — creates it first, and links the child to it. A
  parent that names nothing is refused before anything is created. Before
  this, the connector could say "inheriting from Work item" and create the
  card without it.
- **Created cards report their real keys and ids.** keepr sometimes adjusts a
  key you ask for (`book` becomes `book-2` when `book` is taken); the result now
  says so, instead of showing no key at all.
- **Your assistant sees when an element becomes required.** "Acceptance
  criteria is required when status is ready" now reads as exactly that, rather
  than as optional. Numbered elements say how they are shown (`KPR-0042`) and
  that they are matched by the number.
- **Asking for items of a card by its key works.** A card key or name is
  looked up first; one that does not exist is named as such, instead of an
  answer of 0 items.
- With the skill, a spec whose parent or lookup names nothing now stops before
  its first card is created, not halfway through.

## 2.0.4 — 2026-09-26

Skill 2.0.4, keepr-mcp 0.2.4.

- **It tells you when it is out of date.** Your assistant now hears from keepr
  when a newer version is out, and tells you once, in a sentence — with the
  steps for the way you connected. A skill installed from the skill link
  updates itself (`keepr.py update`); for the plugin, Claude Code can run the
  update for you, or you can turn on auto-update once (`/plugin` →
  Marketplaces → keepr-agent → Enable auto-update). The extension and a skill
  uploaded to Claude get short steps. Every way:
  https://keepr.cloud/docs/guides/assistants/update-your-assistant
- Your keepr **API keys** list now says which assistant last used each key,
  and marks it **Out of date** when it is.
- Every release now also carries `keepr.zip` and `keepr.mcpb`, so the
  `releases/latest/download/…` links always get the newest.
- If you use Claude or ChatGPT, the **keepr connector** is the simplest way in:
  nothing to install, no key, and always current. See the README.

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
