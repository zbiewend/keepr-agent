# The keepr API, as the skill uses it

Everything `scripts/keepr.py` does is these calls. Drive them directly when you
cannot run Python. Base URL `https://api.keepr.cloud` unless the user
self-hosts. Every call carries the key:

```
Authorization: Bearer kpr_...
```

## What a key can and cannot do

A key is a credential **for a user**, carrying a subset of that user's
authority — never a new account, never admin.

| | |
| --- | --- |
| scope `read` | every GET |
| scope `write` | item writes too (write implies read) |
| scope `cards` | **Can change cards**: creating and changing card definitions, element sets and card layouts. Needs `read`; does not imply `write`. A key without it gets **403** `insufficient_scope` with `requiredScope: "cards"` on those routes |
| scope `delete` | **Can delete records**, off by default: every DELETE that removes something, bulk `op: delete`/`reject`, an intake reject, a **replace** write that carries `elements` (`PUT /api/items/{id}`, a bulk update or an ingest `upsert` whose effective `merge` is false — it blanks what it leaves out), and a collection `PUT` that drops a card from `cards[]` — asked **beside** `write` (or `cards` on a card route), never instead of it. A key without it gets **403** `insufficient_scope` with `requiredScope: "delete"`. Keys made before 2026-09-24 do not have it. A key with it may hard-delete at most 500 items a UTC day (`limits.deletesPerKeyPerDay` in the contract); past that, **429** `delete_budget_exhausted` with `limit`, `used`, `remaining`, `requested`, `resetsAt` — nothing was deleted, and retrying before `resetsAt` repeats the answer. This skill never deletes |
| collection allowlist | the key sees only the collections it was created for; everything else answers **404**, exactly as an unshared collection would |
| closed to keys entirely | sharing and grants, collection delete/transfer, share links, password/email changes, managing API keys, all `/api/admin/*` — **403** `code: session_required` whatever the key holds; no scope fixes it |
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

```jsonc
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

```jsonc
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
      "jsonSchema": { "type": "object", "properties": { … }, "additionalProperties": false } }
  ],
  "writeContract": { "maxBatch": 200, "idempotency": "source.externalId", "strictDefault": true,
                     "ingestPath": "/api/collections/<id>/ingest" }
}
```

Nothing is cached server-side — ask right before you write. A card marked
`driven` on an element means the platform owns that value; sending one fails
the row.

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
filter — not the page — is the **`X-Total-Count`** header, which is where
`keepr.py items` gets the `N of TOTAL` on its first line.

```jsonc
[
  { "_id": "66b2…", "collection_id": "65a1…", "card_id": "75a1…",
    "elements": { "title": "Dune", "author": "Frank Herbert", "rating": 5, "read-on": "2026-01-10" },
    "displayValue": "Dune",              // the item's title, server-computed
    "tags": ["scifi"], "notes": "…",     // notes only when the card's Notes field is on
    "owner": "…", "createdAt": "2026-01-11T00:00:00.000Z", "updatedAt": "2026-01-12T00:00:00.000Z" }
]
```

A `measurement` element's value is `{ "value": 8.4375, "unit": "lb-oz", "base": 3.8272 }`;
a `currency`'s is `{ "amount": 1250, "currency": "USD" }` — amount in **minor
units** ($12.50); a `location`'s is an address string or `{ "address", "lat", "lng" }`. The web
address of an item is `https://keepr.cloud/collections/<collection_id>/items/<_id>`.

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
`collection_id`, `card_id` and `elements` (no `displayValue`, no timestamps),
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
matched on `tags`, `notes` and text-bearing element values; the response has
every bucket, empty when not searched:

```jsonc
{ "query": "blue bottle",
  "collections": [ { "_id", "name", "status", "myAccess" } ],
  "cards":       [ { "_id", "name", "key", "description", "scope", "collection_id" } ],
  "items":       [ { "_id", "collection_id", "card_id", "elements", "tags", "notes" } ] }
```

## 3. Write rows

```bash
curl -s -X POST -H "Authorization: Bearer $KEEPR_API_KEY" \
  -H 'Content-Type: application/json' \
  https://api.keepr.cloud/api/collections/<collectionId>/ingest \
  -d '{
    "mode": "create",
    "dryRun": true,
    "strict": true,
    "source": { "system": "claude-import", "ref": "books.csv" },
    "items": [
      { "card": "book",
        "elements": { "title": "Piranesi", "author": "Susanna Clarke", "rating": 5 },
        "tags": ["imported"],
        "source": { "externalId": "978-1-63557-563-4" } }
    ]
  }'
```

| field | meaning |
| --- | --- |
| `mode` | `create` (default) or `upsert` — upsert keys on `source.externalId` |
| `dryRun` | validate and resolve everything, write nothing |
| `strict` | default `true`: an unknown or driven element name fails the row. `false` drops it silently |
| `source.system` | namespaces your external ids; required if any row carries an `externalId` |
| `items` | 1–200 rows, 5 MB per call |

**Always 200.** Read the rows, not the status code:

```jsonc
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

Anywhere a `card-lookup` value is expected:

```jsonc
{ "card": "book", "elements": { "shelf": { "$ref": "shelf-scifi" } },
  "source": { "externalId": "978-1" } }
```

`{"$ref": "<externalId>"}` resolves against `source.system` — first among rows
already settled in this same request, then the database. **Parents first.** A
plain 24-hex id works too, and an `allowMultiple` element takes an array mixing
both forms. The target's card must be the element's `lookupCardKey` (or a
descendant of it), and must be readable by this key.

### Upsert merges

In `upsert` mode the element keys you send overwrite the stored ones and the
keys you omit are **kept** — as on `PUT /api/items/{id}`, which merges by
default too (since 2026-09-24; `merge: false` replaces the whole map). So a
second pass can enrich records without re-sending everything. The
stored `source` never changes, and `card` cannot change on upsert.
`merge: false` (replace, blanking what a row omits) needs the `delete` scope;
this skill never sends it.

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

## 6. Create a card

Needs **manage** on the collection. Ask the user first — this is schema.

```bash
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
from the 19 known ones. The server slugifies and de-duplicates the `key` you
ask for, so read the key back from the response rather than assuming.

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

```jsonc
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
The 400 codes are the preview's `refusal.code`s: `invalid_element_type`,
`invalid_options`, `measure_immutable`, `conversion_unit_required`,
`invalid_unit`; **409** `backfill_too_large` when a conversion would touch
more than 50 000 items.

`DELETE /api/card-definitions/{id}` exists but this skill does not use it: a
soft delete only an administrator can reverse, done from the web app.

## 7. The live contract (public, no key)

This bundle is a copy of the contract; the server publishes the current one.

```bash
curl -s https://api.keepr.cloud/api/docs            # what documentation exists
curl -s https://api.keepr.cloud/api/docs/contract   # element types, error codes, limits
curl -s https://api.keepr.cloud/api/docs/skill      # this skill, every file inline
```

No `Authorization` header — a client needs these *before* it has a key.

`GET /api/collections/{id}/schema` returns `writeContract.contractVersion` on
every call. Cache it; when it differs from the version you hold, re-fetch
`/api/docs/contract`. While it matches, there is nothing to fetch — the check
costs no extra request.

`/api/docs/contract` is generated from the running server's own constants, so
it always describes *that* deployment. If it disagrees with this file, it wins.

```bash
python3 scripts/keepr.py contract --check   # diffs the live contract against this bundle
```

An older deployment may not have `/api/docs` at all — then this file is the
contract for it.

## Error codes

A **400** means the envelope was wrong and nothing was written; its message
names the failing rule. Row errors arrive inside a 200.

### Shape — the value is wrong for the element

| code | what happened |
| --- | --- |
| `unknown_element` | no element of that name on the card (strict mode) |
| `driven_element` | that element is system-owned; don't send it |
| `sequence_element` | that element is numbered by the server (`options.sequence`); don't send it |
| `type` | the value won't coerce — `expected number, got "n/a"` |
| `required` | a required element was left empty |
| `invalid_choice` | not one of the element's choice values |
| `invalid_lookup` | not a 24-hex id or `{"$ref"}`, or a list on a single-valued element |
| `range` | a rating outside 0..max, a number past min/max, a date outside its bounds or on a disallowed weekday |
| `invalid_unit` | not a unit of that measurement's measure, or outside its allowlist |
| `invalid_currency` | not a currency keepr knows, an ambiguous symbol (`kr`), or not one of the element's currencies — there are no exchange rates |
| `invalid_phone` / `invalid_email` / `invalid_location` | unparseable for that type |
| `user_not_found` | no active account with that id |

### Row — the row itself cannot be written

| code | what happened | what to do |
| --- | --- | --- |
| `card_unknown` | no card with that key or id | read `schema` again; keys are per collection |
| `card_not_allowed` | the card exists but isn't writable in this collection | pick one the schema listed |
| `forbidden_card` | this key's grants don't cover that card | the user must widen the grant |
| `forbidden_item` | upsert matched an item this key may not modify | leave it alone |
| `duplicate` | `create` mode, and that `(system, externalId)` already exists | switch to `--mode upsert` |
| `externalId_required` | `upsert` with no external id on the row | give every row a stable id |
| `card_mismatch` | upsert matched an item of a different card | the id is being reused across card types |
| `source_invalid` | an `externalId` with no `system` in effect | set `source.system` |
| `ref_unresolved` | a `$ref` matched nothing — or its target row failed | order parents first; check the system matches |
| `ref_wrong_card` | the target is the wrong card type for that element | link to the card the element expects |
| `lookup_not_found` | a plain id isn't a readable item of this collection | wrong id, or not readable by this key |
| `private_not_allowed` | private items aren't allowed on that card | drop `visibility` |
| `account_already_linked` | another item already links that account | the identity is taken |
| `internal` | server-side failure; the row was not written | retry that row |

### HTTP statuses

| status | meaning |
| --- | --- |
| 401 | key missing, revoked, expired, or its owner is inactive |
| 403 | wrong scope (`code: insufficient_scope`, with `requiredScope` naming `write`, `cards` or `delete`), archived collection, or a surface closed to keys |
| 404 | the collection isn't visible to this key — wrong id, or outside its allowlist |
| 413 | over the 5 MB per-call limit; send fewer rows |
| 429 | rate limited; honour `Retry-After` — except `code: delete_budget_exhausted`, the key's daily delete budget, which is an answer until `resetsAt` and is never retried |
