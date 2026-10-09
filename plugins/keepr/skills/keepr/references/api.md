# The keepr API, as the skill uses it

Base URL `https://api.keepr.cloud` unless the user
self-hosts. Every call carries the key:

```
Authorization: Bearer kpr_...
```

## What a key can and cannot do

A key is a credential **for a user**, carrying a subset of that user's
authority — never a new account, never admin.

| | |
| --- | --- |
| scopes | each scope a key can carry, and what it allows, is in the contract's `auth.scopes` (§ 7). A call the key's scopes do not cover is refused with **403**, and `requiredScope` names the one it lacks. This skill never deletes |
| collection allowlist | the key sees only the collections it was created for; everything else answers **404**, exactly as an unshared collection would |
| closed to keys entirely | the surfaces only a person signed in to keepr may use (sharing, keys, deleting a collection and others — the contract's `auth.notes` lists them) refuse a key whatever it holds; no scope fixes it. Send the person to keepr |
| archived collection | readable, but every write answers **403** |

Revoking a key takes effect on the next request.

## 1. Who am I / what can I reach

```bash
curl -s -H "Authorization: Bearer $KEEPR_API_KEY" \
  https://api.keepr.cloud/api/user-info

curl -s -H "Authorization: Bearer $KEEPR_API_KEY" \
  https://api.keepr.cloud/api/collections
```

`user-info` is the profile plus, for a key, an `auth` block — the only way a
key can learn its own authority, because the key-management routes are
session-only:

```jsonc example
{ "email": "ada@example.com", "fullName": "Ada Lovelace",
  "auth": { "kind": "api-key", "scopes": ["read", "write"], "collectionIds": ["65a1…"] } }
```

`collectionIds: null` means every collection the owner can reach. An older
deployment returns no `auth` block at all.

Collections come back with `_id`, `name`, `status`, `myAccess` (the
caller's role in that collection) and, on the account's own **personal
collection**, `kind: "personal"` — the catch-all every account has, and the
right home for a note or a to do the user has not said where to put. The
personal collection is listed first. (`kind` is absent on an ordinary
collection; an older deployment never sends it.)

## 2. What does this collection accept

```bash
curl -s -H "Authorization: Bearer $KEEPR_API_KEY" \
  https://api.keepr.cloud/api/collections/<collectionId>/schema
```

Per card writable here, the **ancestor-flattened** element list — so you never
reconstruct card inheritance yourself — rendered twice from one source:
`elements[]` for reading, and `jsonSchema` (draft-07) per card, which is the
better thing to hand a model composing rows.

```jsonc example
{
  "collection": { "id": "…", "name": "My Books", "allowAttachments": true, "status": "active" },
  "cards": [
    { "id": "…", "key": "book", "name": "Book", "parentCardId": null,
      "elements": [
        { "name": "title", "label": "Title", "dataType": "text-small", "required": true, "isTitle": true },
        { "name": "status", "dataType": "choice", "choices": [ { "value": "reading", "label": "Reading" } ] },
        { "name": "shelf", "dataType": "card-lookup", "lookupCardKey": "shelf", "allowMultiple": false },
        { "name": "added", "dataType": "date", "driven": true }
      ],
      "itemTags": "off",               // "chosen" | "every": this card's items are used as tags here
      "jsonSchema": { "type": "object", "properties": { … }, "additionalProperties": false } }
  ],
  "tags": [                            // the collection's tags — the only ones a row may name
    { "id": "…", "name": "Sci-fi", "path": "Genre/Sci-fi", "parentId": "…",
      "restricted": false, "rule": null, "aliases": ["SF"] }
  ],
  "writeContract": { "maxBatch": 200, "idempotency": "source.externalId", "strictDefault": true,
                     "ingestPath": "/api/collections/<id>/ingest" }
}
```

Nothing is cached server-side — ask right before you write. An element marked
`driven` or `sequence` is written by keepr; never send one. What each element
takes is its type plus its options; the contract's `elementTypes` (§ 7) says,
for every type, what to send.

**`tags`** is the collection's tag vocabulary: its own tags, then the ones of
the collection above it (marked `inheritedFrom`), as far as this key may see
them. `path` is how to name a tag that shares its name with another
(`Genre/Sci-fi`). `restricted: true` — it decides who can see what: only a
manager, signed in to keepr, puts it on or takes it off (a key never can),
and a collection may put it on new items of chosen cards
by itself. `rule: { "strict": true }` — a rule applies it and nothing else may; never
send it. **Items used as tags are never listed** (their names are their items'
titles): a card with `itemTags` other than `off` has them, and
`GET /api/tags/search?q=` (below) finds one by title, to send by id. Private
tags are never listed either — no item carries one.

The schema lists the collection's member cards whatever the key's scope, so a
read-only key uses it too: for element names to query on, the title element,
and each card's resolved `primaryDate`.

## 2a. List items

```bash
curl -s -H "Authorization: Bearer $KEEPR_API_KEY" \
  "https://api.keepr.cloud/api/items?collection_id=<collectionId>&q=status%20%3D%20open&limit=25&skip=0"
```

| param | meaning |
| --- | --- |
| `collection_id` | required with `q`; the collection to list |
| `q` | a KQL filter (`references/kql.md`). Malformed → **400** naming the character position; an unknown element name matches nothing, silently |
| `card_id` | one card by id, exact match (`include_descendants=true` to include its children). `card = <key>` inside `q` does the same by key, descendants included |
| `sort_field` | `primaryDate` (the default — each item's card's primary date), `createdAt`, `updatedAt`, or an element name. An unknown value falls back to the default rather than erroring |
| `sort_direction` | `asc` or `desc` (default `desc`) |
| `limit` | page size, default 50, **max 200** |
| `skip` | offset, default 0 |

Sorting happens before paging, and empty values sort last whichever the
direction. The response is a **bare array** of items; the total for the whole
filter — not the page — is the **`X-Total-Count`** header.

```jsonc example
[
  { "_id": "66b2…", "collection_id": "65a1…", "card_id": "75a1…",
    "elements": { "title": "Dune", "author": "Frank Herbert", "rating": 5, "read-on": "2026-01-10" },
    "displayValue": "Dune",              // the item's title, server-computed
    "notes": "…",                        // only when the card's Notes field is on
    "tagIds": ["…"],                     // tags applied by hand (absent when none)
    "tagAutoIds": ["…"],                 // tags a rule applied (absent when none)
    "tagTitles": { "<tagId>": { "kind": "tag", "name": "Sci-fi", "restricted": false },
                   "<itemTagId>": { "title": "Mom", "item_id": "…" } },   // what each is called, as far as this key may see
    "myTags": [ { "tagId": "…", "kind": "tag", "name": "To reread" } ],   // the key owner's own private tags
    "owner": "…", "createdAt": "2026-01-11T00:00:00.000Z", "updatedAt": "2026-01-12T00:00:00.000Z" }
]
```

Tags are ids on the item; `tagTitles` names them. A collection tag's entry is
`{ kind: "tag", name }`; an item used as a tag is `{ title }` — or
`{ unavailable: true }` when this key can no longer read that item. An id with
no entry is a tag this key cannot see the name of. `myTags` are the key
owner's own private tags (only they see them; `fromCollection: true` when the
tag is on the collection rather than the item).

Values come back as keepr stores them: a measurement as `{ value, unit, base }`,
money as `{ amount, currency }` with the amount in **minor units** (divide by
10 to the currency's exponent, `currencies.exponents` in the contract), a
place as an address or `{ address, lat, lng }`. The web
address of an item is `https://keepr.cloud/i/<code>` — its short address, from the
item's `code` (`/c/`, `/d/`, `/t/`, `/e/` and `/f/` do the same for a collection, card,
tag, element set and multi add). An item without a `code` yet keeps its long address,
`https://keepr.cloud/collections/<collection_id>/items/<_id>`, which always works.
`GET /api/codes/{kind}/{code}` turns a code back into an id.

`GET /api/items/count` takes the same filter params and returns `{ "count": n }`.

## 2b. One item, or a batch by id

```bash
curl -s -H "Authorization: Bearer $KEEPR_API_KEY" \
  https://api.keepr.cloud/api/items/<itemId>

curl -s -H "Authorization: Bearer $KEEPR_API_KEY" \
  "https://api.keepr.cloud/api/items?ids=<id1>,<id2>,<id3>"
```

A single fetch returns the item above, or **404** when it is missing or not
readable by this key — the two are indistinguishable on purpose.

The batch form returns the **readable subset**, projected to `_id`,
`collection_id`, `card_id` and `elements` (no `displayValue`, no timestamps, no tags),
in no promised order. Missing, invalid and unreadable ids are **silently
omitted**; the cap is **100 ids** and extras are ignored. A short answer is
therefore "not readable by this key", never "deleted", and never a reason to
retry.

## 2c. Free-text search

```bash
curl -s -H "Authorization: Bearer $KEEPR_API_KEY" \
  "https://api.keepr.cloud/api/search?q=blue%20bottle&types=items&limit=20"
```

| param | meaning |
| --- | --- |
| `q` | required, at least 2 characters after trimming. A case-insensitive **substring**, not a query |
| `types` | comma-separated subset of `collections,cards,items`; default all three |
| `limit` | per bucket, default 20, max 50. No pagination — search is a jump-off, not a listing |

Each bucket uses exactly the read scope of its own list endpoint. Items are
matched on `notes` and text-bearing element values; the response has
every bucket, empty when not searched:

```jsonc
{ "query": "blue bottle",
  "collections": [ { "_id", "name", "status", "myAccess" } ],
  "cards":       [ { "_id", "name", "key", "description", "scope", "collection_id" } ],
  "items":       [ { "_id", "collection_id", "card_id", "elements", "notes" } ] }
```

Tags have their own search:

```bash
curl -s -H "Authorization: Bearer $KEEPR_API_KEY" \
  "https://api.keepr.cloud/api/tags/search?q=mom&collection_id=<collectionId>"
```

`{ "results": [ { "kind": "private" | "collection" | "item", "tag": { "_id", "name"?, "path"?, "title"? }, "collection"? } ], "more": false }`
— your private tags, collection tags by name or alias, and **items used as
tags by their item's title** (`kind: "item"`, `tag.title`): that `tag._id` is
what a row's `tags` sends to apply one. `collection_id` narrows it to that
collection (its tags and the ones above it; its items and its sub-collections'); `limit` (max 50) and `skip` page it.

## 2d. Totals, counts and averages — charts

keepr works a total, a count, an average or a breakdown out over every item
(docs/SCHEMA.md "Charts"); `charts.md` says when, and how to build the spec.
A read key may ask (they are POSTs that only read). **Always send
`"grade": "export"`**: an assistant's answer leaves keepr, so it counts only
what the person may export, as an item export would.

```bash
# a question that is not saved
curl -s -X POST -H "Authorization: Bearer $KEEPR_API_KEY" -H "Content-Type: application/json" \
  https://api.keepr.cloud/api/collections/<collectionId>/charts/preview \
  -d '{ "grade": "export", "spec": { "card_id": "<card id>",
        "time": { "on": "filled-on", "range": { "preset": "thisYear" } },
        "measures": [ { "key": "spent", "op": "sum", "element": "cost" } ],
        "groupBy": { "on": "filled-on", "bucket": "month" },
        "show": { "type": "table" } } }'

# the saved charts, then one of them (range is optional: it replaces the chart's own)
curl -s -H "Authorization: Bearer $KEEPR_API_KEY" \
  https://api.keepr.cloud/api/collections/<collectionId>/charts
curl -s -X POST -H "Authorization: Bearer $KEEPR_API_KEY" -H "Content-Type: application/json" \
  https://api.keepr.cloud/api/charts/run \
  -d '{ "runs": [ { "chart_id": "<chart id>", "collection_id": "<collectionId>", "grade": "export",
                    "range": { "preset": "last90d" } } ] }'
```

The preview answers `{ spec, warnings, result }`; the batch `{ ranAt, results: [result] }`.
A `result` carries `grade: "export"` (refuse one that does not), `axis.keys` /
`axis.labels` (the rows; a null label is a time bucket, a range or an hour to
spell yourself), `measures[]`, `values[measure][row][series]`, `totals` (the
Overall row, keepr's own figure — never re-add the rows), `range`, `tz` and
`notes` (`{ code, count, message }` — say them). The `card_id` is an id here:
look it up in the schema. Values are raw: **money in minor units** (divide by
10 to the currency's exponent — `currencies.exponents` in the contract, § 7),
a share 0–1, a measurement in the unit `measures[].unit`
names (a two-part unit like `ft-in` as a decimal of its first part: 5.5 is
5 ft 6 in — `units.twoPart` in the contract; `units.symbols` writes `C` as
°C). A refused
spec is a 400 with `code` and `path` (the part of the spec to fix); otherwise
a 403, a 429 (with `retryAfter`) or a 503, each with a message saying what to
do. What only a run can find — too many bars, a filter naming
something gone, a formula too costly, the time limit — is a **200** whose
`result` is `{ ok: false, error: { code, message } }`, on the preview as in a
batch; a batch's runs carry the spec's refusals, and a chart that is gone,
the same way.

## 3. Write rows

```bash
curl -s -X POST -H "Authorization: Bearer $KEEPR_API_KEY" \
  -H 'Content-Type: application/json' \
  https://api.keepr.cloud/api/collections/<collectionId>/ingest \
  -d '{
    "mode": "create",
    "dryRun": true,
    "strict": true,
    "source": { "system": "assistant-import", "ref": "books.csv" },
    "items": [
      { "card": "book",
        "elements": { "title": "Piranesi", "author": "Susanna Clarke", "rating": 5 },
        "source": { "externalId": "978-1-63557-563-4" } }
    ]
  }'
```

| field | meaning |
| --- | --- |
| `mode` | `create` (default) or `upsert` — upsert keys on `source.externalId`. What an omitted element does on each is the contract's `emptyValue` |
| `dryRun` | validate and resolve everything, write nothing |
| `strict` | default `true`: an unknown or driven element name fails the row. `false` drops it silently |
| `source.system` | namespaces your external ids; required if any row carries an `externalId` |
| `items` | the rows. How many a call takes is `writeContract.maxBatch` in the schema, and its size limit is `limits` in the contract |

A row may carry **`tags`** — the item's tags, by name, alias, path
(`Genre/Sci-fi`) or id, from the schema's `tags`; an item used as a tag goes by
its id. keepr resolves them and **never creates a tag**: a name that is not a
tag there fails the row, one that could be two tags fails with its
`candidates` (send the path), and a private tag fails. On an upsert the list
replaces the item's tags — leave `tags` out to keep them, `[]` takes them off —
except that a restricted tag is always kept. A row that adds or takes off a
restricted tag fails: only the person, in keepr, may. A row that succeeded but
left a tag off (it was deleted meanwhile) carries a `warnings` entry saying
so.

**Always 200.** Read the rows, not the status code:

```jsonc example
{ "runId": "…",
  "summary": { "created": 12, "updated": 3, "skipped": 0, "failed": 1 },
  "rows": [
    { "index": 0, "status": "created", "id": "…", "displayValue": "Piranesi", "externalId": "978-…" },
    { "index": 1, "status": "failed", "externalId": "978-…",
      "errors": [ { "element": "rating", "code": "type", "message": "expected number, got \"n/a\"" } ] } ] }
```

Statuses are `created` · `updated` · `skipped` · `failed`; a dry run says
`would-create` / `would-update` instead. **`skipped` means the stored item
already matched exactly** — re-running an identical import is a no-op.

Rows are independent and processed in order: one bad row fails that row, not
the batch. That is also why a *committed* batch with failures should stop you —
a later row may `$ref` a row that never landed.

### Linking rows to each other

Anywhere an item lookup element takes a value:

```jsonc
{ "card": "book", "elements": { "shelf": { "$ref": "shelf-scifi" } },
  "source": { "externalId": "978-1" } }
```

`{"$ref": "<externalId>"}` resolves against `source.system` — first among rows
already settled in this same request, then the database. **Parents first.** A
plain 24-hex id works too, and an `allowMultiple` element takes an array mixing
both forms. The target's card must be the element's `lookupCardKey` (or a
descendant of it), and must be readable by this key.

A lookup may carry a `filter` in the schema: KQL over the target card's items
(`status = active`) that the picker offers first. To list what it offers, AND
it into `?q=` and send `q_stored=true` when you read the target's items: the
list then reads the filter exactly as the strict gate does (a tag by its id, a
term naming something since removed matching nothing), so name a tag in your
own terms there by its id too. With `strict: true` a record
outside the filter is refused (`itemIds` names it); without it any record of
the card is accepted. A value the item already holds always
saves, even if it has since left the filter.

A dry run writes nothing, so an import split over several calls cannot find
what an earlier call only validated. So each later call is told which rows the
earlier ones would create (`wouldCreate`, dry runs only) — just the ones that
call names or repeats — so a `$ref` across batches dry-runs as it will commit.
Calling the API yourself, send the same:
`"wouldCreate": [{ "card": "shelf", "externalId": "shelf-scifi" }]`.

### Upsert merges

In `upsert` mode the element keys you send overwrite the stored ones and the
keys you omit are **kept** — as on `PUT /api/items/{id}`, which merges by
default too (since 2026-09-24; `merge: false` replaces the whole map). So a
second pass can enrich records without re-sending everything. The
stored `source` never changes, and `card` cannot change on upsert.
`merge: false` (replace, blanking what a row omits) needs the `delete` scope;
this skill never sends it.

### Me too — the person's own

A **Me too** count is keepr's: never in a row. The person (or a key acting
for them) says it, or takes it back, through its own door — once each:

```bash
curl -s -X POST -H "Authorization: Bearer $KEEPR_API_KEY" \
  "https://api.keepr.cloud/api/items/<itemId>/confirmations/<element>"     # DELETE takes it back
curl -s -H "Authorization: Bearer $KEEPR_API_KEY" \
  "https://api.keepr.cloud/api/items/<itemId>/confirmations"               # the counts, and whether you did
```

Both answer the count keepr holds now. Who confirmed is the collection's
managers' alone; the contract names the doors and what each refusal means.

## 4. Audit

```bash
curl -s -H "Authorization: Bearer $KEEPR_API_KEY" \
  "https://api.keepr.cloud/api/collections/<collectionId>/ingest-runs?limit=20"
```

Every call — dry runs included — writes one ledger row: who, which key, which
mode, the summary, the item ids. This is the answer to "what did the agent put
in here, and when". Needs `manage` on the collection.

## 5. Attach a file to an item

```bash
curl -s -X POST -H "Authorization: Bearer $KEEPR_API_KEY" \
  -F "file=@receipt.pdf" \
  https://api.keepr.cloud/api/items/<itemId>/attachments
```

Only when the collection's `allowAttachments` is true.

**Into a file element.** The upload answers the attachment's `_id`. Bind it
with a merge PUT of the item — the id as a single file element's value, or the
element's list with the id appended:

```bash
curl -s -X PUT -H "Authorization: Bearer $KEEPR_API_KEY" -H 'Content-Type: application/json' \
  https://api.keepr.cloud/api/items/<itemId> \
  -d '{ "elements": { "photo": "<attachmentId>" }, "merge": true }'
```

Replacing a file already in the element deletes the old one (softly), so the
key needs the scope for deleting. A refusal carries `element`, keepr's code
and its sentence (the kind of file, the size, how many the element holds). A
bound file cannot be removed with `DELETE …/attachments/{id}` (a 409): clear
the element with a PUT instead.

## 6. Create a card

Needs **manage** on the collection. Ask the user first — this changes the
shape of their data.

```bash example
curl -s -X POST -H "Authorization: Bearer $KEEPR_API_KEY" \
  -H 'Content-Type: application/json' \
  https://api.keepr.cloud/api/card-definitions \
  -d '{ "name": "Book", "key": "book", "collection_id": "<collectionId>",
        "elements": [
          { "name": "title", "label": { "singular": "Title", "plural": "Titles" },
            "dataType": "text-small", "options": { "isTitle": true, "required": true } },
          { "name": "shelf", "label": { "singular": "Shelf", "plural": "Shelves" },
            "dataType": "card-lookup", "options": { "lookupCardId": "<shelf card id>" } } ] }'
```

Every element needs a `name`, a `label` (`{singular, plural}`) and a `dataType`
the contract's `elementTypes` lists. The server slugifies and de-duplicates the `key` you
ask for, so read the key back from the response rather than assuming.

**Several cards at once — a card blueprint** (keepr 2.1; docs/SCHEMA.md "Card
blueprints"). `POST /api/collections/{id}/blueprints/preview` with
`{ "blueprint": { "cards": [...], "collection": { "savedFilters": [...],
"cardLayouts": [...] } } }` checks it and writes nothing (200 `{ wouldApply,
problems[{path, code, message}], steps, summary }`); `…/blueprints/apply` with the
same body creates it all or nothing (201 with each card's `localId`, `id`,
`key`). Cards are named by reference, never by id: `{ "ref": "<localId>" }` for
one in the blueprint (itself too), `{ "key": "work-item" }` for one the
collection has, `{ "globalKey": "person" }` for a global card — as `parentRef`,
an element's `options.lookupCardId`, a rollup's `options.drivenFrom.sourceCardId`,
a layout's `cardRef`.

A blueprint may also bring **new tags** (keepr 2.2): `"collection": { "tags":
[{ "localId": "late", "name": "Late", "parentRef"?: { "ref": "<another tag's
localId>" }, "color"?, "icon"?, "rule"?: { "cardRef": REF, "where": "status =
open", "strict"?: false } }] }` — each optionally **applied by a rule**. Every
rule arrives **paused**: it tags nothing until the person resumes it in keepr
(Settings → Tags), and the apply answers `rules[{ name, enabled: false,
preview: { total, matching } }]`, what each would tag. Filters and rules name
tags by name. The key needs `write` as well as `cards` for tags. A blueprint tag
is never restricted.

## 6a. Change a card — preview first, then PATCH

Both need the **`cards`** scope and `manage` on the collection. Read the card
as stored first; the schema's element list is flattened for readers, not the
shape PATCH takes back:

```bash
curl -s -H "Authorization: Bearer $KEEPR_API_KEY" \
  https://api.keepr.cloud/api/card-definitions/<cardId>
```

That returns the definition — `name`, `key`, `description`, `options`, and
`elements`: the card's **own** elements as `{ name, label: {singular, plural},
dataType, options }`.

**`PATCH /api/card-definitions/{id}` replaces `elements` whole.** Always send
the full array — every element you are keeping, unchanged, plus your changes.
An element left out of the array is removed, and its stored values with it.
The payload is the same content fields as create (`name`, `description`,
`options`, `color`, `icon`, `elements`); system fields are stripped
server-side, and omitting `key` leaves the key alone (sending it re-derives
it, which breaks saved filters and links — don't).

**`POST /api/card-definitions/{id}/change-preview`** takes the **same payload**,
runs every gate PATCH runs, **writes nothing**, and returns what the PATCH
would do, classified:

```bash
curl -s -X POST -H "Authorization: Bearer $KEEPR_API_KEY" \
  -H 'Content-Type: application/json' \
  https://api.keepr.cloud/api/card-definitions/<cardId>/change-preview \
  -d '{ "elements": [ …the full list… ] }'
```

```jsonc example
{ "card": { "id": "…", "name": "Book", "key": "book", "collectionId": "…" },
  "wouldApply": true,                    // false: the PATCH would be refused, see `refusal`
  "refusal": null,                       // or { "status": 400, "code": "invalid_options", "message": "…" }
  "changes": [
    { "kind": "added",          "element": "isbn",   "dataType": "text-small" },
    { "kind": "removed",        "element": "shelf",  "dataType": "card-lookup", "itemsWithValues": 12, "destructive": true },
    { "kind": "retyped",        "element": "rating", "from": "rating", "to": "number",
                                "conversion": "none", "itemsWithValues": 40, "destructive": true },   // or "measurement"
    { "kind": "optionsChanged", "element": "status", "keys": ["choices"] },
    { "kind": "labelChanged",   "element": "author", "from": "Author", "to": "Writer" },
    { "kind": "reordered" } ],
  "cardFields":  [ { "field": "name", "from": "Book", "to": "Books" } ],
  "sideEffects": [ { "code": "automation_retired", "message": "…" } ],
  "destructive": true,
  "summary": "DESTRUCTIVE — removes shelf (12 items hold a value); …" }
```

`removed` and `retyped` are the destructive kinds; `itemsWithValues` is the
count of items holding a value under that element, from the stored data.
A `retyped` with `conversion: "measurement"` is a number ↔ measurement
conversion the PATCH performs (it then carries `options.convertFrom` /
`convertTo` on the element); `conversion: "currency"` is the same for number ↔
currency (`convertFrom: { "currency": "USD" }`; numbers are major units,
rounded to the currency's decimals); `conversion: "none"` means the stored values are
reinterpreted, not converted.

Then, and only after the user has seen that, the PATCH with the identical
payload:

```bash
curl -s -X PATCH -H "Authorization: Bearer $KEEPR_API_KEY" \
  -H 'Content-Type: application/json' \
  https://api.keepr.cloud/api/card-definitions/<cardId> \
  -d '{ "elements": [ …the same full list… ] }'
```

Answers `{ "status", "payload": <the saved card>, "conversion"?, "conversions"?, "conversionWarning"? }`.
A refusal is the preview's `refusal`: keepr's code and its sentence. A change
that would turn stored single values into lists, or lists into single values,
is refused (409) until the element's options say what to do with them; the
refusal names the answer it waits for, where it goes, the items affected and
a query listing them. An answer that keeps one value and drops the rest is the
user's to choose — ask. A conversion too large to run at once is refused too,
and says so.

`DELETE /api/card-definitions/{id}` exists but this skill does not use it: a
soft delete only an administrator can reverse, done from the web app.

## 7. The live contract (public, no key)

The server publishes what it accepts, for the deployment you are talking to:
element types and what each takes, every error code and what it means, the
limits, the key scopes, currency exponents. This skill states none of it.

```bash
curl -s https://api.keepr.cloud/api/docs            # what documentation exists
curl -s https://api.keepr.cloud/api/docs/contract   # element types, error codes, limits, currency exponents
curl -s https://api.keepr.cloud/api/docs/skill      # this skill, every file inline
```

No `Authorization` header — a client needs these *before* it has a key.

`GET /api/collections/{id}/schema` returns `writeContract.contractVersion` on
every call. Cache it; when it differs from the version you hold, re-fetch
`/api/docs/contract`. While it matches, there is nothing to fetch — the check
costs no extra request.

`/api/docs/contract` is generated from the running server's own constants, so
it always describes *that* deployment.

An older deployment may not have `/api/docs` at all — then a failure's own
message is what it says.

## Failures

A **400** means the envelope was wrong and nothing was written; its message
names the failing rule. Row failures arrive inside a 200: each failed row has
`errors[]`, and each error carries the `element` it is about, keepr's `code`
and its `message`. The message is the explanation; the contract's `errorCodes`
lists every code with its meaning on this deployment. What to do about a
failed row is the same whichever way you reach keepr: `adding.md`, "When a
row fails".

### HTTP statuses

| status | meaning |
| --- | --- |
| 401 | key missing, revoked, expired, or its owner is inactive |
| 403 | a scope the key lacks (`requiredScope` names it), an archived collection, or a surface closed to keys |
| 404 | the collection isn't visible to this key — wrong id, or outside its allowlist |
| 413 | over the per-call size limit (`limits` in the contract); send fewer rows |
| 429 | rate limited; honour `Retry-After` — except a 429 carrying `resetsAt` (a daily budget spent), which is an answer until then and is never retried |
