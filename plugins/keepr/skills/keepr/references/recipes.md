# Recipes

Worked examples. Copy the shapes, not the field names — always read the real
`schema` first.

---

## A. One thing, from a sentence

> "Log that I finished Piranesi today, 5 stars."

```bash
python3 scripts/keepr.py schema --collection "Reading log"
```

tells you the card is `book` with `title`, `author`, `rating`, `finished`,
`status`. So:

```json
{
  "source": { "system": "claude-chat" },
  "items": [
    { "card": "book",
      "elements": { "title": "Piranesi", "rating": 5, "finished": "2026-09-18", "status": "done" },
      "source": { "externalId": "piranesi" } }
  ]
}
```

Note what is *not* there: no author, because the user didn't say one. Today's
date is resolved by you, not left as "today".

```bash
python3 scripts/keepr.py ingest --rows rows.json --dry-run && \
python3 scripts/keepr.py ingest --rows rows.json
```

---

## B. A spreadsheet

```bash
python3 scripts/keepr.py csv --file books.csv --card book \
  --collection "Reading log" --id-column ISBN --system goodreads-export \
  --map "Date Read=finished" --map "My Rating=rating" --out rows.json

python3 scripts/keepr.py ingest --rows rows.json --dry-run
```

Read the dry run before committing. The usual first-pass failures:

| failure | fix |
| --- | --- |
| `type: expected number, got "n/a"` | the column uses `n/a` for blanks — clear those cells, or drop the column |
| `invalid_choice` | the sheet's words aren't the card's choice values — map them in the rows file |
| `type` on a date | the sheet has `12/05/2024`; decide the order and rewrite as ISO |
| `unknown_element` | a column matched no element — drop it, or add the element to the card |

Committed, then the user fixes three rows in the sheet and wants a re-run:

```bash
python3 scripts/keepr.py ingest --rows rows.json --mode upsert
```

Unchanged rows come back `skipped`; the three changed ones come back `updated`.
Nothing is duplicated, because every row carries an ISBN as its external id.

---

## C. Linked records, created together

Contacts and the notes about them. Parents first, children referencing them:

```json
{
  "source": { "system": "crm-import", "ref": "meeting-notes-2026-09.md" },
  "items": [
    { "card": "contact",
      "elements": { "name": "Leah Park", "email": "leah@example.com" },
      "source": { "externalId": "leah-park" } },

    { "card": "contact",
      "elements": { "name": "Sam Ortiz", "email": "sam@example.com" },
      "source": { "externalId": "sam-ortiz" } },

    { "card": "note",
      "elements": { "about": { "$ref": "leah-park" }, "on": "2026-09-14",
                    "body": "Wants the Q4 numbers before the 20th." },
      "source": { "externalId": "note-2026-09-14-leah" } }
  ]
}
```

The note's `about` element is a `card-lookup` at the `contact` card. If a
contact already exists in keepr under the same `system` and `externalId`, the
`$ref` finds it there — so a second import that adds only notes still links
correctly.

---

## D. A folder of records and their photos

The shape: a directory of subjects, each with one or more images, plus a list
of the records themselves (a CSV, a document, or the filenames).

```
intake/
  residents.csv
  photos/
    molly-blake/front.jpg
    molly-blake/back.jpg
    leah-park.jpg
    leah-park-2.jpg
```

**The external id is the hinge.** It has to identify the record *and* be
derivable from the file layout. Here the folder and file names are slugs, so
slugs are the ids:

```bash
python3 scripts/keepr.py csv --file intake/residents.csv --card resident \
  --collection "Intake" --id-column slug --system intake-2026 --out rows.json

python3 scripts/keepr.py ingest --rows rows.json --dry-run
python3 scripts/keepr.py ingest --rows rows.json
```

`rows.results.json` now maps every external id to the item it created. Pair the
photos against it, look, then upload:

```bash
python3 scripts/keepr.py attach --results rows.results.json --dir intake/photos --dry-run
# 4 file(s) → 2 item(s)
#   leah-park: leah-park.jpg, leah-park-2.jpg
#   molly-blake: front.jpg, back.jpg

python3 scripts/keepr.py attach --results rows.results.json --dir intake/photos
```

When the CSV has no slug column, derive one and put it in the rows yourself —
the same string the photos use. When the photos are camera names
(`IMG_4471.jpg`) and nothing connects them to a subject but the user's
knowledge, **ask**: either they tell you the mapping, or you write it down as
`--map map.json` from whatever the document says.

```json
{ "molly-blake": ["IMG_4471.jpg", "IMG_4472.jpg"],
  "leah-park":   ["IMG_4488.jpg"] }
```

Things that will happen on a real folder, and what to do:

| what you see | what it means |
| --- | --- |
| `UNMATCHED IMG_4471.jpg` | no record has that external id. Never attach it to a nearby record — report it. |
| `already attached` on a re-run | the file is there from last time. Correct behaviour, not an error. |
| `HTTP 403 … attachments may be off` | the collection has `allowAttachments` false. Only the owner can change that, in the web app. |
| `HTTP 415` | an executable or script. The platform refuses those. |
| `HTTP 413` | over the per-file or per-account storage cap. |

A single document that produced one item (a receipt, a contract) is the same
command with `--item`:

```bash
python3 scripts/keepr.py attach --item 65a1b2c3d4e5f6a7b8c9d0e1 --file invoice-4471.pdf
```

Keep the extracted values and the original together — the attachment is the
provenance for every number you pulled out of it.

---

## E. Card specs to start from

Pass any of these to `create-card --spec` (list form creates several in order;
`lookupCard` names another card by key, in this spec or already in the
collection). **Show the user before `--apply`.**

### Reading log

```json
[
  { "name": "Shelf", "key": "shelf",
    "elements": [
      { "name": "name", "label": "Name", "dataType": "text-small", "isTitle": true, "required": true }
    ] },
  { "name": "Book", "key": "book",
    "elements": [
      { "name": "title",  "label": "Title",  "dataType": "text-small", "isTitle": true, "required": true },
      { "name": "author", "label": "Author", "dataType": "text-small" },
      { "name": "isbn",   "label": "ISBN",   "dataType": "text-small" },
      { "name": "status", "label": "Status", "dataType": "choice",
        "choices": [ { "value": "want", "label": "Want to read" },
                     { "value": "reading", "label": "Reading" },
                     { "value": "done", "label": "Finished" } ] },
      { "name": "rating",   "label": "Rating",   "dataType": "rating", "max": 5 },
      { "name": "finished", "label": "Finished", "dataType": "date" },
      { "name": "shelf",    "label": "Shelf",    "dataType": "card-lookup", "lookupCard": "shelf" },
      { "name": "notes",    "label": "Notes",    "dataType": "text-large" }
    ] }
]
```

### Expenses

```json
{
  "name": "Expense", "key": "expense",
  "elements": [
    { "name": "merchant", "label": "Merchant", "dataType": "text-small", "isTitle": true, "required": true },
    { "name": "amount",   "label": "Amount",   "dataType": "decimal", "decimals": 2, "nonNegative": true, "required": true },
    { "name": "spent-on", "label": "Spent on", "dataType": "date", "required": true },
    { "name": "category", "label": "Category", "dataType": "choice",
      "choices": [ { "value": "travel", "label": "Travel" }, { "value": "meals", "label": "Meals" },
                   { "value": "software", "label": "Software" }, { "value": "other", "label": "Other" } ] },
    { "name": "reimbursable", "label": "Reimbursable", "dataType": "boolean",
      "trueLabel": "Reimbursable", "falseLabel": "Personal" },
    { "name": "receipt-no", "label": "Receipt number", "dataType": "text-small",
      "help": "Use this as the external id so a re-import updates instead of duplicating." }
  ]
}
```

### Contacts and notes

```json
[
  { "name": "Contact", "key": "contact",
    "elements": [
      { "name": "name",  "label": "Name",  "dataType": "text-small", "isTitle": true, "required": true },
      { "name": "email", "label": "Email", "dataType": "email" },
      { "name": "phone", "label": "Phone", "dataType": "phone", "country": "US" },
      { "name": "org",   "label": "Organization", "dataType": "text-small" }
    ] },
  { "name": "Note", "key": "note",
    "elements": [
      { "name": "about", "label": "About", "dataType": "card-lookup", "lookupCard": "contact", "required": true },
      { "name": "on",    "label": "Date",  "dataType": "date", "required": true },
      { "name": "body",  "label": "Note",  "dataType": "text-large" }
    ] }
]
```

---

## F. Picking external ids

The external id is what makes a re-run safe. Good ones already exist in the
data and never change: an ISBN, an invoice number, an order id, a rule number,
a `YYYY-MM-DD` plus a stable name.

When nothing natural exists, derive one that is reproducible from the row
itself — `2026-09-14-leah-park` — so the *same* source row derives the *same*
id next time. Never use a row counter: inserting a line at the top of the
spreadsheet would then renumber everything and update the wrong records.

If the data genuinely has no stable identity, say so and import without external
ids, telling the user plainly that re-running will duplicate.
