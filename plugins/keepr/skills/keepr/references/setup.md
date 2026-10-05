# Setup — arranging a collection and the rules it runs on

A **setup** is everything about a collection that is not its records: how its
cards look in a list (tile layouts), which columns its tables show, how its
item form is grouped, its printable pages, its saved filters and quick adds,
its tags, the **rules** that run on its records (automations), its
notifications, and its charts and dashboards. One setup can make new cards
too, and arrange the ones the collection already has.

keepr previews the whole setup before anything changes, and applies it **all
or nothing**. The preview is what the person agrees to — so read it to them.

## When to use it

| the person wants… | use |
| --- | --- |
| a new card, or a field added to one card | `keepr_propose_card` / `keepr.py create-card`, `change-card` (`references/cards.md`) |
| a list, table, form or page laid out differently | a setup |
| filters or quick adds for everyone | a setup |
| "when X happens, do Y" — stamp a date, notify me, update linked records, make a task every week | a setup (automations) |
| a notification for the collection | a setup (notifications) |
| new cards **and** their layouts, filters and rules together | a setup — one preview, one apply |
| to see what rules run, pause one, or see who changed something | `keepr_automations`, `keepr_history` (below) |

## Commands and tools

| | CLI | MCP tool |
| --- | --- | --- |
| read the collection's cards and its rules | `keepr.py schema --collection X`, `keepr.py automations --collection X` | `keepr_schema` |
| read each card's layouts (what a layout entry would replace) | — (the MCP tool only) | `keepr_schema` with `include_layouts: true` |
| propose a setup | `keepr.py setup --collection X --spec setup.json` (prints keepr's preview and a fingerprint; writes nothing) | `keepr_propose_setup` |
| apply it | `keepr.py setup --collection X --spec setup.json --apply --expect FINGERPRINT` | `keepr_apply_setup` with the token and the collection name typed back |
| list rules, a rule's runs, pause one | `keepr.py automations --collection X [--runs RULE] [--pause RULE]` | `keepr_automations` (`list`, `runs`, `pause`, `turn_on`) |
| who changed what | `keepr.py history --item ID` · `--card KEY --collection X` · `--collection X` | `keepr_history` |

The apply sends exactly the setup that was previewed, and **checks the plan has
not moved**: if something was added or renamed in the collection since the
preview (so an "adds" would now be a "changes"), nothing is applied and you
propose again. A tool token lasts 30 minutes and is used once; the CLI's
`--expect` is the fingerprint the preview printed.

## The setup document

It is keepr's own format — the same one `references/cards.md` calls a card
blueprint — so there is nothing to translate. Every section is optional:

```jsonc
{
  "cards": [ { "localId": "bug", "name": "Bug", "elements": [ … ] } ],   // new cards (references/cards.md)
  "collection": {
    "cardLayouts":       [ … ],   // tile, table, page, form
    "savedFilters":      [ { "name": "Open bugs", "query": "card = bug and status != done" } ],
    "quickAddTemplates": [ { "name": "New bug", "cardRef": { "ref": "bug" },
                             "defaults": { "status": { "kind": "static", "value": "open" } } } ],
    "tags":              [ … ],   // new tags, each optionally applied by a rule — which always arrives paused,
                                  // and the person turns it on in keepr › Settings › Tags
    "automations":       [ … ],   // rules — below
    "notifications":     [ … ],   // the collection's notifications — below
    "charts": [ … ], "dashboards": [ … ], "overview": { "dashboardRef": "…" }
  }
}
```

**Naming a card.** `{ "ref": "bug" }` is a card this setup makes (its
`localId`); `{ "key": "task" }` is one the collection has (from `schema`);
`{ "globalKey": "person" }` a global card. A rule's `card_id` takes the same.

**Changing what is there.** An entry that matches something the collection
has — a tile or table or form at its tier, or a page layout, filter, quick add
or rule by `id` or exact name (a notification by `key`) — **changes** it rather
than adding a second. The preview marks every entry `adds`, `CHANGES` (with
what changes, before and after) or `unchanged`; an unchanged one is not
written. An entry says the whole of what it sets: give every key you mean to
keep.

## Layouts

Each entry: `{ "kind": "tile" | "table" | "form" | "page", "cardRef": …,
"scope": "collection" | "card", "body": … }`. On a card the collection owns,
`scope: "card"` sets it wherever the card is used; by default the layout
belongs to this collection, and `scope: "card"` on a card the collection does
not own is refused (`layout_tier`), not moved. A form layout is card-tier
only, on a card the collection owns. A page layout also has a `name`.

**Tile** — the card as it appears in the item list. A grid of **3 columns and at
most 3 rows**; each row's spans add up to 3 at most, and each element appears
once:

```json
{ "kind": "tile", "cardRef": { "key": "task" },
  "body": { "rows": [ [ { "element": "title", "span": 2 }, { "element": "status", "span": 1 } ],
                      [ { "element": "due", "span": 1 }, { "element": "owner", "span": 2 } ] ] } }
```

Every type needs room to be read, and a span narrower than that is refused
(`span_too_narrow`), never quietly widened:

| element type | span at least |
| --- | --- |
| short text, email, url, location, a looked-up record | 2 |
| long text, rich text | 2 — alone in the body at 3, it is the tile's paragraph |
| everything else (numbers, dates, choices, a person, a phone, a file's photo…) | 1 |

The tile's header — its badge, date, Open and ⋯ — is keepr's; the body is
what you arrange. Zero rows is a tile of identity and date alone.

**Table** — the item table's columns, in order: `{ "columns": [ { "element":
"title" }, { "system": "updatedAt" }, … ] }`. System columns: `title`,
`primaryDate`, `updatedAt`, `createdAt`, `sourceCreatedAt`, `tags`, `owner`.

**Form** — the item form's order and groups: `{ "groups": [ { "id": "g1",
"title": "Basics", "elements": ["title", "status"] }, { "id": "g2", "title":
"Dates", "elements": ["due"], "collapsed": true } ] }`. Order and grouping only:
a form never hides an element (a required one hidden is a record nobody can
save).

**Page** — paper: a record per sheet (a face sheet, a label) or the records a
query selects, with blocks placed in the sheet's units. Pages are designed
best in keepr's page editor; propose one only from an existing page's body the
person shows you, or for a change the person names precisely (a new name, a
size). The preview shows a page by its subject, size and number of blocks.

## Rules (automations)

A rule says **when** (its trigger) and **what** (its actions):

```jsonc
// Done stamps the date — runs at once
{ "name": "Done stamps the date",
  "trigger": { "type": "item-event", "card_id": { "key": "work-item" }, "events": ["updated"],
               "condition": { "kql": "status = done" } },
  "actions": [ { "type": "set-elements", "elements": { "done-on": "{{today}}" } } ] }

// A release ships its items — changes OTHER records, so it arrives paused
{ "name": "A release ships its items",
  "trigger": { "type": "item-event", "card_id": { "key": "release" }, "events": ["updated"],
               "condition": { "kql": "status = released" } },
  "actions": [ { "type": "update-items",
                 "scope": { "via": "lookup", "card_id": { "key": "work-item" }, "linkElementName": "release" },
                 "set": { "status": "deployed" } } ] }

// Tell me when work waits on me — notifies, so it arrives paused
{ "name": "Tell me when work waits on me",
  "trigger": { "type": "item-event", "card_id": { "key": "work-item" }, "events": ["updated"],
               "condition": { "kql": "status = needs-input or status = in-review" } },
  "actions": [ { "type": "notify", "channels": ["inApp"], "audience": { "type": "role", "minRole": "manage" },
                 "title": "Waiting on you" } ] }

// The stale-work nudge — runs on a schedule, so it arrives paused
{ "name": "Stale work nudge", "kind": "expected-item",
  "trigger": { "type": "schedule", "schedule": { "every": 1, "unit": "day", "time": "09:00", "timezone": "America/Los_Angeles" } },
  "check": { "card_id": { "key": "work-item" }, "window": { "type": "rolling", "minutes": 10080 },
             "condition": { "kql": "status = in-progress" } },
  "actions": [ { "type": "notify", "channels": ["inApp"], "audience": { "type": "role", "minRole": "manage" },
                 "title": "Nothing moved this week" } ] }
```

Kinds: `rule` (the default), `threshold` (a value crossing a bound),
`expected-item` (something that should have happened by a time) and
`generate-items` (make a record per source record, on a schedule). Never send
`enabled` — keepr decides it.

**How a rule arrives.** A rule that only sets values on the record that set it
off **runs as soon as it is applied**. A rule that **notifies anyone, changes
other records, creates records, or runs on a schedule arrives PAUSED**, and so
does every notification — whoever applies the setup. It stays paused, marked
as waiting for the person, until **they** turn it on in keepr. keepr refuses an
assistant or an API key that tries (`person_must_enable`), and that is the
design. Changing what a running rule of that kind does — who it tells, what it
says, which records it changes — pauses it again; a rename does not.

**Reading the preview aloud.** For each rule the preview gives keepr's own
sentence for what it does, how many records it would touch today, who a
notification would reach and what it would say, its next runs, and whether it
runs at once or arrives paused, with why. Tell the person all of it, in those
words. Then, for every rule that arrives paused, say exactly:

> Only you can turn this on, in keepr › Settings › Automations.

(For a notification: **in keepr › Settings › Notifications.** For an automatic
tag's rule: **in keepr › Settings › Tags.**)

**Never promise that a paused rule will run**, or that it is "set up and
working". It is set up; it is not on. If the person says "turn it on", call
`keepr_automations` with `turn_on` once — keepr answers that it is theirs to do,
and you say the sentence above. Do not retry, and do not look for another way.

A rule naming a card the setup makes cannot be previewed until the card
exists: its step says so, and it is judged when the setup is applied (a refusal
then leaves nothing behind).

## Notifications

A collection notification is a definition everyone in the collection may
receive: `{ "key": "work-waiting", "name": "Work is waiting", "severity":
"info", "category": "items", "trigger": { … }, "audience": { … }, "channels":
[], "template": { "title": "…" } }`. **Always send `channels`**: `[]` is the
inbox only, and leaving it out means email — it leaves keepr. A key keepr's own notifications use is refused
(`notification_key_taken`) — pick another. Every notification arrives paused.

## Reading and switching rules

`keepr_automations` (`keepr.py automations`) lists a collection's rules and
notifications: what each does, whether it is **ON**, **PAUSED**, or **WAITING**
for the person, and who made it — a person, an API key, an assistant. It reads
a rule's recent runs, and it **pauses** one by id or exact name. Pausing is
always open; turning on is the person's when keepr says so.

`keepr_history` (`keepr.py history`) reads who changed what and when — an
item's, a card's, or the collection's. It reads only.

## What is not here

**Deleting, sharing, undoing and keys are the person's, in keepr — never from
here.** No tool deletes a card, a rule, a filter, a layout or a record; none
shares a collection or sends an invitation or share link; none reverts a
change or undoes an import; none makes or changes API keys. A rule that is no
longer wanted is **paused** here, and deleted by the person in keepr. Say so
plainly when asked, and point them to the place.
