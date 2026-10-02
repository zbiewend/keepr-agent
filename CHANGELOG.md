# Changelog

Each release lists the two versions it carries: the skill's (which is also the
plugin's) and the server's.

## 2.3.0 — 2026-10-02

Skill 2.3.0, keepr-mcp 0.5.0.

- **File and photo fields.** A card can hold a file field (any file, or photos only; one file or a list of up to 20; a size limit). `keepr_attach_file` takes an `element` and puts the upload into that field: a single field's file is replaced (the key needs `delete` scope, and the assistant says so first), a list gains it at the end. The field's limits are read from the schema first.
- **Re-runs are safe.** An attachment already on the item is reused only when it is a loose attachment with the same name and size, never a different file that merely shares the name.
- **Rows never carry files.** Imports and item updates leave file fields as they are; a row that tries to set or clear one is refused for that field (`file_not_settable`). The schema describes each file field so the assistant knows to attach rather than type.

## 2.2.0 — 2026-10-02

Skill 2.2.0, keepr-mcp 0.4.0.

- **Tags are back.** Rows and item updates carry the collection's tags by name (or by path for a nested tag), items are read with their tags, and the schema lists the tags there are. A name that is no tag of the collection is refused (`unknown_tag`), never created.
- **Restricted tags stay with people.** A tag that decides who can see what is applied or taken off only by a collection manager in keepr; your assistant leaves it alone and tells you.
- **A card proposal may bring new tags,** each optionally applied by a rule that arrives paused for you to turn on.
- The old tag words are retired: a row that still sends them is refused (`tags_retired`) until the assistant is updated.

## 2.1.5 — 2026-10-01

Skill 2.1.5, keepr-mcp 0.3.5.

- **Fields have rules now.** Text has length limits and can require a pattern or capitals; a field can hold unique values; links follow one rule (a bare address becomes https://). A row that breaks a rule comes back with the field and the reason (`too_long`, `pattern`, `invalid_url`, `duplicate_value`, `invalid_color`).
- **Defaults are filled in by keepr.** A field left out of a row starts at its default, as it does in the form.
- **Choices can allow multiple.** Send a list, or one value with entries split by `;`. Numbers may be sent as "1,234", and as "12.5%" on a field shown as a percent.
- **New field types and options:** color, and the angle, frequency and fuel-economy measures; a card lookup may offer only some items ("strict" refuses the rest — `lookup_filtered_out`).
- **Groups built from records** also protect the fields they read through another record: such a change is left to a signed-in person in keepr.

## 2.1.4 — 2026-09-30

Skill 2.1.4, keepr-mcp 0.3.4.

- **Groups built from records are protected.** In a collection where a group's
  members come from records (everyone linked to a Staff record, say), linking
  an account on such a record — or changing a field the group's rule reads,
  in a way that could put the linked person in the group — is now left to a
  signed-in person in keepr. Your assistant gets `session_required` for that
  row, leaves the value out, and tells you to set it in keepr. Re-sending a
  record exactly as it is stored still works.
- A row refused because the person behind the key lacks the access such a
  group gives is now named as `account_link_needs_access`: a manager makes
  that change.

## 2.1.3 — 2026-09-29

Skill 2.1.3, keepr-mcp 0.3.3.

- **A big dry run tells the truth.** An import of more than 200 rows goes in
  several batches, and a dry run writes nothing — so until now, a row that
  pointed at a record from an earlier batch (a task naming its epic) came
  back refused in the dry run, then imported fine. The dry run now tells each
  batch which records the earlier ones will create, so it checks out the way
  the import will.
- A dry-run update that names a different card for a record the import would
  create is now refused as the import would refuse it, instead of reading as
  fine.

## 2.1.2 — 2026-09-28

Skill 2.1.2, keepr-mcp 0.3.2.

- **Old records keep their own dates.** When the data you import says when
  a record was made — a spreadsheet's "Created" column, an export's
  timestamp — your assistant can send it with each row. keepr shows it on the
  record ("Created in *system* on *date* · added to keepr *date*"), as a
  **Created in source** column in the table, and in Excel and PDF exports,
  instead of every imported record looking as though it was made today.
  keepr's own created date is still the day of the import.
- The date is set once, when a record is first imported. Re-sending a row
  with a different date still updates the record, and says the date was not
  changed.

## 2.1.1 — 2026-09-28

Skill 2.1.1, keepr-mcp 0.3.1.

- **An import can be taken back.** Every batch of one import now carries the
  same import id, so keepr lists the batches as one import, and someone who
  manages the collection can undo it from the collection's **Settings →
  Imports** in the web app: the items it added are deleted and the ones it
  changed are put back — except anything someone has worked on since, which
  stays. Your assistant tells you the import's id when it writes, and where to
  undo it. It cannot undo an import itself; deleting stays yours.
- The skill keeps an import's id from its dry run to its commit, and through a
  re-send of the rows a commit refused; `--import-id` names it yourself.
- Against an older keepr, the rows are sent without the id.

## 2.1.0 — 2026-09-28

Skill 2.1.0, keepr-mcp 0.3.0.

- **Several cards at once, all or nothing.** Ask for "a Task that belongs to
  an Epic, depends on other tasks, and a count of tasks on each Epic" and your
  assistant proposes the whole set as one: cards that look each other up, a
  card that looks up its own kind, counts and totals rolled up from another
  card, how each card's items are titled, the filters the collection starts
  with and the columns a card's table shows. keepr checks all of it before
  anything is made, and says what it would refuse, line by line. When you say
  yes, it is made in one step; if any part is refused, nothing is kept, and
  your assistant says so.
- **The keys you see are the keys keepr stores.** A key like `Work_Item` is
  shown as `work-item` in the proposal, which is how keepr keeps it.
- **A lookup to one of keepr's global cards adds it to the collection.** A
  Task whose owner is a Person brings the Person card into the collection; the
  proposal says so before you agree, and the key needs **Read and write** as
  well as **Can change cards**, as it does for filters.
- With the skill, the same spec file goes to keepr as one set, and an older
  keepr is still served card by card.

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
