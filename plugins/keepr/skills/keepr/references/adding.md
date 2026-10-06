# Adding — records into a collection

Turn whatever the user has — a sentence, a spreadsheet, a photographed
receipt, a pile of notes — into items in one of their keepr collections.
`SKILL.md` covers the transport, the key and the vocabulary; this is the
loop. Read the collection's `schema` first (SKILL.md says how); nothing
here works without it.

## The loop

Run every step. The dry run is not optional — it is what keeps a bad mapping
from becoming 200 wrong items.

```
                CLI                                  MCP tool
1.  keepr.py check                                   keepr_collections
      the key works, and what it can reach
2.  keepr.py schema --collection "<name or id>"      keepr_schema
      what this collection accepts
3.  build a rows file                                build the rows argument
      your judgement — see below
4.  keepr.py ingest --rows rows.json --dry-run       keepr_ingest  dry_run: true
      validated, nothing written
5.  fix, repeat 4 until failed 0
6.  keepr.py ingest --rows rows.json                 keepr_ingest  dry_run: false
      commit
7.  report counts + the collection URL to the user
```

With the MCP tools, step 4 is not skippable by accident: `dry_run` has no
default and every call must state it. A dry run reports `NOTHING WAS WRITTEN`
in its first line — if you do not see that phrase or a `WROTE n items` line,
read the result again before telling the user anything.

If the user named no collection, run `keepr.py collections` and ask which one.
Never pick one for them.

## Rows

A rows file is JSON. Minimum viable:

```json
{
  "source": { "system": "claude-import", "ref": "receipts-2026-03.pdf" },
  "items": [
    { "card": "expense",
      "elements": { "merchant": "Blue Bottle", "amount": 18.5, "spent-on": "2026-03-14" },
      "source": { "externalId": "receipt-2026-03-14-blue-bottle" } }
  ]
}
```

- **`card`** is the card's key (from `schema`), per row — one file may mix cards.
- **`elements`** uses the element **names** the schema printed. Anything else
  fails the row; that is deliberate.
- **`source.externalId`** is a stable id from the user's own data (an invoice
  number, an ISBN, a slug you derive). With `source.system` it makes the import
  idempotent: re-running with `--mode upsert` updates what changed and reports
  the rest as `skipped`. Without it, re-running duplicates everything.
- **`source.createdAt`** is when the record was made in the system it comes
  from — `"2019-04-02"`, or a date-time with an offset. Only beside an
  `externalId`, only from the data (a sheet's "Created" column, an export's
  timestamp), never guessed or set to today. keepr shows it as provenance
  ("Created in … on …"); its own created date stays the day of the import.
  It is set once, when the item is created: an upsert that sends a different
  one still writes the row, and the row's note says the date was not changed
  (`keepr_ingest` calls the field `created_at`).
- **`visibility`** (`"shared"` | `"private"`) is optional.
- **`tags`** is the item's tags, by the names `schema` lists under TAGS — a
  name, or the path when two tags share a name (`"Genre/Sci-fi"`), or an id.
  An item used as a tag (a card whose items are tags) goes by its id:
  `keepr.py search` / `keepr_search` finds it by title (add `--types tags` /
  `types: ["tags"]` to search tags alone). On an upsert the list **replaces** the item's tags:
  leave `tags` out to keep them, `[]` takes them off. A tag marked
  *restricted* decides who can see what: **only the person, signed in to
  keepr, can put one on or take one off** — you never can, whatever the key
  holds (the row fails `session_required`). Leave it out (an upsert keeps it)
  and tell the person to add or remove it in keepr. One *applied by a rule
  only* is never sent.

`scripts/keepr.py template --collection X --card book --out rows.json` gives
you a skeleton with every writable element and a placeholder saying what each
one wants. Fill it in and **delete the keys you have no data for** — an
unfilled placeholder is caught before any call is made.

For a spreadsheet, skip the hand-writing:

```bash
python3 scripts/keepr.py csv --file books.csv --card book \
  --collection "My Books" --id-column ISBN --system books-csv --out rows.json
```

It matches columns to elements by name (and `--map "Sales rank=rank"` for the
ones that differ), reports the columns that match nothing, and leaves blank
cells out rather than writing empty strings over existing values.

## Getting the values right

The API validates types and refuses rather than guessing, so:

- **Dates** are `YYYY-MM-DD`; timestamps are ISO-8601. `12/05/2024` is refused
  (nobody can tell December 5th from May 12th), so resolve it yourself from
  context and write the unambiguous form.
- **Choice** elements take the choice's `value`, not its label. A choice the
  schema marks `allowMultiple` takes a **list** of values (`["welding",
  "rigging"]`) — or one string separated by `;` (`"welding; rigging"`, what
  `keepr.py csv` sends as a list) — and keepr stores each value once, in the
  order of the choices list.
- **card-lookup** elements take a 24-hex item id, or `{"$ref": "<externalId>"}`
  pointing at another row — *listed earlier in the same file* or already in
  keepr under the same `source.system`. Parents before children. A lookup
  whose schema says `strict: true` takes only a record its `filter` matches.
- **Numbers** take a number, or the text a spreadsheet writes: `"1,234,567.5"`
  (en-US commas every three digits) on any number, and `"12.5%"` on an
  element whose schema says `percent: true` — stored as 12.5, the number
  shown, never 0.125. `keepr.py csv` sends cells as they are, and keepr reads
  them. A `%` on any other element, a decimal comma (`"1,5"`) or a comma out
  of place (`"1,23"`) is refused as `type`: write the plain number instead,
  and ask the user what `"1,5"` meant rather than guessing.
- **Driven** elements are system-owned. The schema marks them; never send one.
- **Measurements** take a number in the element's default unit, or
  `{"value": 8.5, "unit": "lb"}`.
- **Currency** elements take a number in MAJOR units (`12.50`, the default
  currency) or a string naming the currency (`"12.50 CAD"`); there are no
  exchange rates, and extra decimals are refused, not rounded.

The full type-by-type reference is `references/elements.md`; every error code
and what to do about it is in `references/api.md`.

## Judgement — the part no script can do

- **Never invent a value.** If the user's data has no author, no date, no
  amount, leave the element out. An omitted element stays empty; a guessed one
  is a lie you have just written into their records.
- **Keep their words.** Don't summarize, re-title, reflow, or "tidy" text that
  goes into an element. Fix an obvious typo only if asked.
- **One row per real thing.** Don't merge two receipts because they share a
  merchant, or split one book into two because it has two authors.
- **Data that fits nowhere** is a question for the user, not something to stuff
  into a notes field. Ask whether to add an element, drop it, or put it in notes.
- **Never invent a tag.** Use the collection's own tags, as `schema` lists
  them — keepr never creates one from a row, and a name it does not know fails
  the row (`unknown_tag`). When the user's data has a label the collection
  has no tag for, or you think one would help, **ask the person**: they can
  add the tag in keepr, or you leave it out. Never fold a tag into another
  element to keep it, and never pick a near-miss ("Scifi" for "Sci-fi") without
  saying so. A name that could be two tags fails with the candidates — send the
  path of the one the user means.
- **Confirm before you write.** Show what the dry run found — how many rows, of
  which cards, into which collection — and get a yes before committing. Always,
  and especially past a handful of rows.
- **A 404 on a collection means it is not this key's** — the id is wrong, or the
  key's allowlist does not include it. Do not go looking through other
  collections for somewhere the data fits.

## When no card fits

Cards are schema. Creating one changes the shape of the user's data and is not
something to do quietly — and adding an element to an existing card is a card
change, with stored values at stake. Both are `references/cards.md`. Propose,
show the user, apply only what they saw, then come back here for the rows.

## Reading the results

Every call — dry or not — is ledgered, and `ingest` writes
`<rows>.results.json` next to your rows file with the `runId`s, the new item
ids by external id, and every failure. Report to the user:

- how many were **created / updated / skipped / failed**, and into which collection;
- the failures by their external id and error code, not just a count;
- `keepr.py runs --collection X` shows the audit trail afterwards.

**One import, one id.** Every batch of an import carries the same `importId`,
so keepr lists them as one import and someone who manages the collection can
**undo** it from the collection's **Settings → Imports** in the web app: the
items it created are deleted and the ones it updated are put back, except any
changed since. `keepr.py ingest` makes the id and keeps it from a dry run to its
commit, and through a re-send of the rows a commit refused (`--import-id` names
it yourself); `keepr_ingest` returns it — pass it back as `import_id` on every
later call of the same import. There is no undo for a key: tell the user where
it is, if an import went wrong.

`skipped` is a good word: it means the item was already exactly right.

## Changing items that are already there

`keepr_update_item` changes the elements you name on one item by id, and leaves
the rest alone. To make **one change to many items** — "mark all of these done",
"set the site on every open order" — give it `ids` (up to 100) or a KQL `q`,
with `collection`:

1. Call it with `dry_run: true`. keepr says how many items the change would
   touch and names a few. Show the person that, and the change.
2. Only when they agree, call it again with **exactly the same change**,
   `dry_run: false`, and the `confirm` token the dry run gave. A different
   change, or no token, is refused; a filter that matches a different number
   of items by then is refused by keepr, and you dry-run again.

It is all or nothing — if keepr ever says it stopped part-way, tell the person
how many changed and that the collection's history shows which — it touches
only the collection's own items, and it never deletes. There is no command-line
equivalent for a change to many items. Items with an external id are better changed with `keepr_ingest` in
`upsert` mode (on the command line, `keepr.py ingest --mode upsert`).

## Attachments — files onto the items you just made

Only when the collection has attachments on (`schema` says so; otherwise every
upload is a 403).

**A folder on the person's computer: `keepr_attach_folder`.** It matches the
files to their items, shows you the match, and then uploads the originals in
the background, streamed from disk — up to 100 MB a file, nothing through the
conversation:

```
keepr_attach_folder  { folder: "/Users/…/photos", dry_run: true }                      # show this to the person → confirm
keepr_attach_folder  { folder: "/Users/…/photos", dry_run: false, confirm: "…" }       # same arguments → job id
keepr_attach_status  { job_id: "att-…" }                                   # every minute or so, then once at the end
```

It matches against this session's `keepr_ingest` external ids by default, or a
`map`, or `collection` + `match_element` for records that already exist (the
filenames carry, say, a receipt number). The folder must be one the server can
read: from Claude Code, a path on the person's computer; in Cowork, a folder
the person selected for the session. If it cannot read it, it says why — then
ask the person for the files instead (below). Without MCP:

```bash
python3 scripts/keepr.py attach --item <24-hex item id> --file receipt.pdf --file back.jpg
```

These land among the item's **other attachments**. A card may also have a
**file element** (`dataType: "file"` in `schema`, with `accept`, `maxSizeMb`
and `allowMultiple`): a file that belongs IN that field — the vehicle's photo,
the signed form — is put there with `keepr_attach_file` and its `element`
argument, which uploads the file and then binds it with one merge PUT. A
single file element takes one file and **replaces** the one there (the old
file is deleted softly, so the key needs Can delete records); a list appends,
20 files at most. `accept: "image"` takes photos only (never a PDF). An import
row can never set a file element (`file_not_settable`).

**A folder of files, matched to the records you just created** — the common
case: a directory of subjects and their photos.

```bash
# 1. create the items first; the results file records every external id -> item id
python3 scripts/keepr.py ingest --rows rows.json

# 2. see the pairing before uploading anything
python3 scripts/keepr.py attach --results rows.results.json --dir photos/ --dry-run

# 3. upload
python3 scripts/keepr.py attach --results rows.results.json --dir photos/
```

Files find their record by **external id**, in whichever layout the user has:

| layout | matches |
| --- | --- |
| `photos/molly-blake/front.jpg`, `.../back.jpg` | the subfolder names the record |
| `receipts/R-1042.pdf` | the whole filename names the record |
| `photos/molly-blake.jpg`, `molly-blake-2.jpg`, `molly blake (3).jpg` | the filename, trailing counter stripped |
| anything else | `--map map.json` (MCP: `map`) — `{"molly-blake": ["IMG_4471.jpg", "IMG_4472.jpg"]}` |

By default a file in a subfolder belongs to the record that folder names —
and to nothing else: a folder that names no record leaves its files
unmatched (`Unit 12/1.jpg` is never unit 1). A file at the top tries its
whole filename, then its filename without a counter, so `R-1042.pdf` finds
the record `R-1042`. Force one with `--match folder|stem|exact` (MCP:
`match`) when the guess is wrong — `exact` reads the filename whatever folder
it is in.

This is why the external id matters for an import with photos: it is the
only thing linking a file on disk to a record in keepr. **Choose ids the
filenames can actually produce** — if the photos are `IMG_4471.jpg`, either
build a `--map`, or use the photo names as the external ids when you create
the items.

Rules the command already follows, so you don't have to:

- **Dry-run first.** It prints which files go to which record and what matched
  nothing. Show that to the user before uploading.
- **A file matching no record is never guessed at** — it is reported and the
  command exits non-zero.
- **Re-running skips what is already there** (`keepr_attach_folder`: the same
  name AND size on the item; `keepr.py`: the same name), so a re-run after
  adding three photos uploads three photos.
- **A file that changes or disappears while it runs** fails by name, and the
  rest still go.
- Executables and scripts are refused by the platform; images, PDFs and
  documents are fine.

### The whole job, for "a folder of records and photos"

1. Read the records (a CSV, a document, the filenames themselves) and the
   collection's `schema`.
2. Build rows whose `source.externalId` is the thing that also identifies the
   photos — the subject's slug, the file stem, the folder name.
3. `ingest --dry-run`, fix, `ingest`.
4. `keepr_attach_folder` with `dry_run: true` (or `attach --results … --dir …
   --dry-run`), check the pairing with the person, then run it.
5. Report: items created, photos attached, and **anything unmatched**, by name.

### When the files are the person's, not yours

The folder is on their phone, or on a computer you cannot read, or the files
are too big to send: ask for them instead of uploading them.

```bash
# entries.json: [{"item_id": "…", "name": "R-1042.pdf"}, {"item_id": "…", "pattern": "IMG_*.HEIC", "element": "photos"}]
python3 scripts/keepr.py request-upload --collection "Expenses" --entries entries.json --note "March receipts"
#   give the person this link: https://keepr.cloud/collections/…/items?attach=…
python3 scripts/keepr.py upload-status --id <request id>
#   1 of 2 file(s) attached
#     waiting  R-2  IMG_*.HEIC
```

Through MCP the same is `keepr_request_upload` and `keepr_upload_status`. One
request covers one collection, up to 1,000 entries; an item may appear more than
once (front and back). It is all or nothing: an item the person cannot change, a
locked record, or an `element` that is not a file element refuses the request,
each by its entry's index. The link works for 7 days (1–30) and only for the
person, signed in. Report what arrived, and what is still waiting, by name.
