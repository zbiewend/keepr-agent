# Changelog

Each release lists the two versions it carries: the skill's (which is also the
plugin's) and the server's.

## 2.9.0 — 2026-10-06

Skill 2.9.0, keepr-mcp 0.11.0. Also the first release of 2.8.0 and 2.8.1, below.

- **Your assistant can read element ids.** keepr now names an element in a filter it stores by its permanent id, written `#k7f3q2xa`, so one card's element can't be confused with another card's element of the same name. `keepr_schema` shows each element's id beside its name. Every stored filter that `keepr_schema`, `keepr_chart`, `keepr_automations` and `keepr_propose_setup` print keeps keepr's own text, with a line beneath naming each id's element and card. The skill explains how to read them and when to write one.

## 2.8.1 — 2026-10-05

Skill 2.8.1, keepr-mcp 0.10.1.

- **A file too big to send inline is no longer a dead end.** `keepr_attach_file` names the way that works for your connector, ready to call: the file's path or `keepr_attach_folder` from the extension and the plugin, or `keepr_request_upload`'s link for you anywhere. It never suggests shrinking the file to fit.

## 2.8.0 — 2026-10-05

Skill 2.8.0, keepr-mcp 0.10.0.

- **Attach a whole folder from your computer in one step.** `keepr_attach_folder` matches each file to its record (from this session's import, a map, or a value the filenames carry, such as a receipt number), shows you the match first, then uploads the originals in the background, streamed from disk, up to 100 MB each. `keepr_attach_status` reports what arrived and what is still missing. Running the same folder again sends only what is new. These two tools are in the desktop extension and the Claude Code plugin, where the assistant can read your files.

## 2.7.2 — 2026-10-05

Skill 2.7.2, keepr-mcp 0.9.2.

- **A setup can change the charts and dashboards a collection already has.** A chart or dashboard in the setup that matches one shown to everyone (by its id, or by name) is shown as it is and as it becomes, and changed in place, so it stays pinned for everyone. A dashboard's tile can name a chart the collection already shows. If anything in the apply fails, each one is put back as it was.

## 2.7.1 — 2026-10-05

Skill 2.7.1, keepr-mcp 0.9.1.

- **New cards in a setup can be written the way the card chapter shows.** An element's options beside its name (`"isTitle": true`, `"choices": [...]`) and a lookup by card key (`"lookupCard": "release"`) are moved into keepr's shape before anything is sent. keepr refused them before.
- **A change says exactly what changes.** A changed rule or quick add lists each value that differs, as it was and as it becomes (`actions[0].title: Waiting on you → Work is waiting on you`), not only "actions". A changed tile, form or table is drawn as it is now and as it becomes.
- Plainer wording in keepr's previews: "reaches 1 person", and a reminder's window in days or hours with the condition it counts.

## 2.7.0 — 2026-10-05

Skill 2.7.0, keepr-mcp 0.9.0.

- **Your assistant can set up a collection.** Ask it to lay out how cards look in the list, which columns the table shows, how the item form is grouped, or a printable page, and to add saved filters, quick adds, tags, rules, notifications and charts, on new cards or ones you already have. `keepr_propose_setup` shows keepr's own preview: each part added, changed (with what it was and what it becomes) or already the same, a tile drawn as its rows, and each rule with what it does, how many records it would touch and who it would notify. `keepr_apply_setup` applies exactly what you saw, all at once or not at all, after you type the collection's name back.
- **Rules that act on their own wait for you.** A rule that only fills in values on the record that set it off runs at once. A rule that notifies people, changes other records, creates records or runs on a schedule arrives paused, and only you can turn it on, in keepr › Settings › Automations. Your assistant cannot, and it tells you so.
- **Read and pause rules, and see who changed what.** `keepr_automations` lists a collection's rules and notifications (on, paused or waiting for you, and who made each), reads a rule's recent runs, and pauses one. `keepr_history` reads an item's, a card's or a collection's changes. Neither deletes or undoes anything.
- **Change many items at once.** `keepr_update_item` takes up to 100 ids or a filter. It shows what would change first, with the count and a few titles, and makes the change only with the token that preview gave.
- **Ask for files your assistant cannot send.** `keepr_request_upload` lists the items waiting for files and gives you a link: open it, drop the files or pick photos, and keepr matches each to its item. `keepr_upload_status` says what has arrived and what is still missing.
- The script gains `setup`, `automations`, `history` and `request-upload`.

## 2.6.0 — 2026-10-04

Skill 2.6.0, keepr-mcp 0.8.0.

- **Short links to your records.** Every item now has a short address, such as `keepr.cloud/i/7k3qx9m`. `keepr_get_items` gives each item its `url`, and the assistant hands you that link instead of building a long one from ids. The links keep working when an item moves to another collection.
- **Filters in a card proposal are saved by id.** A filter that names a record by its title is refused, so a filter you approve keeps meaning the same thing after a rename.

## 2.5.0 — 2026-10-04

Skill 2.5.0, keepr-mcp 0.7.0.

- **Connect without a key.** In the Claude desktop extension (Cowork included) and the Claude Code plugin, you no longer need to create and paste an API key. The first time you ask for something in keepr, Claude opens keepr in your browser; sign in if you need to, choose what it may do, and click **Allow**. The connection is listed under **Connected assistants** on your keepr profile, where you can rename or disconnect it. Ask Claude to disconnect, or to connect again, at any time.
- **A key still works**, and wins when you set one. The extension's key field is now optional.

## 2.4.0 — 2026-10-04

Skill 2.4.0, keepr-mcp 0.6.0.

- **Ask for totals, not pages.** Questions like "how much did I spend on fuel by month?" or "how many orders by status this year?" are answered by keepr itself. The new `keepr_chart` tool runs a chart you saved, or a question built from your collection's fields, and answers a table: money in its currency, measurements in their unit, an Overall row, and what keepr left out. It counts only what you may export from keepr, and says how many items it left out for that reason. A read-only key is enough.
- **Filters can ask for part of a date and for who added an item.** `created.weekday in (sat, sun)`, `created.hour >= 9 and created.hour < 17`, `due.month = dec`, `created.by = me`. Days and hours are read in the collection's time zone; a plain date is its calendar day.

## 2.3.3 — 2026-10-03

Skill 2.3.3, keepr-mcp 0.5.1.

- **A new money field takes the right currency without being told.** When you ask for a card with a money field and don't name a currency, the assistant leaves it out, and keepr starts the field in the collection's currency, else your preferred currency (Preferences › Language & region), else US dollars. Name a currency and that one is used. A field that already exists keeps its currencies.

## 2.3.2 — 2026-10-03

Skill 2.3.2, keepr-mcp 0.5.1.

- **A tag name two tags share is refused in a search** (`ambiguous_tag`, listing each tag's path) instead of matching either: say which with the path or the id.
- **A choice's label works in a filter** and is read as its value; the value is still the one to write.

## 2.3.1 — 2026-10-03

Skill 2.3.1, keepr-mcp 0.5.1.

- **A refused upload says what keepr said.** When keepr refuses a file — for example on a record its card has locked, which now covers attachments too — `keepr_attach_file` reports keepr's own reason (`item_locked`: a manager can unlock it) instead of a bare error number.

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
