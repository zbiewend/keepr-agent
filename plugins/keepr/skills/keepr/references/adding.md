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
- **`tags`** (list of strings) and **`visibility`** (`"shared"` | `"private"`)
  are optional.

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
- **Choice** elements take the choice's `value`, not its label.
- **card-lookup** elements take a 24-hex item id, or `{"$ref": "<externalId>"}`
  pointing at another row — *listed earlier in the same file* or already in
  keepr under the same `source.system`. Parents before children.
- **Driven** elements are system-owned. The schema marks them; never send one.
- **Measurements** take a number in the element's default unit, or
  `{"value": 8.5, "unit": "lb"}`.

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

`skipped` is a good word: it means the item was already exactly right.

## Attachments — files onto the items you just made

Only when the collection has attachments on (`schema` says so; otherwise every
upload is a 403). One item, one or more files:

```bash
python3 scripts/keepr.py attach --item <24-hex item id> --file receipt.pdf --file back.jpg
```

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
| `photos/molly-blake.jpg`, `molly-blake-2.jpg`, `molly blake (3).jpg` | the filename, trailing counter stripped |
| anything else | `--map map.json` — `{"molly-blake": ["IMG_4471.jpg", "IMG_4472.jpg"]}` |

Force one with `--match folder|stem|exact` when the guess is wrong.

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
- **Re-running skips what is already there**, comparing filenames on the item,
  so a re-run after adding three photos uploads three photos.
- Executables and scripts are refused by the platform; images, PDFs and
  documents are fine.

### The whole job, for "a folder of records and photos"

1. Read the records (a CSV, a document, the filenames themselves) and the
   collection's `schema`.
2. Build rows whose `source.externalId` is the thing that also identifies the
   photos — the subject's slug, the file stem, the folder name.
3. `ingest --dry-run`, fix, `ingest`.
4. `attach --results … --dir … --dry-run`, check the pairing, then attach.
5. Report: items created, photos attached, and **anything unmatched**, by name.
