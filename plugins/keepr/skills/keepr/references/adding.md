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
1.  keepr_collections                 what you can reach
2.  keepr_schema                      what this collection accepts
3.  build the rows argument           your judgement — see below
4.  keepr_ingest  dry_run: true       validated, nothing written
5.  fix, repeat 4 until failed 0
6.  keepr_ingest  dry_run: false      commit
7.  report counts + the collection URL to the user
```

With the MCP tools, step 4 is not skippable by accident: `dry_run` has no
default and every call must state it. A dry run reports `NOTHING WAS WRITTEN`
in its first line — if you do not see that phrase or a `WROTE n items` line,
read the result again before telling the user anything.

If the user named no collection, list them with `keepr_collections` and ask which one.
Never pick one for them.

## Rows

A rows file is JSON. Minimum viable:

```json
{
  "source": { "system": "assistant-import", "ref": "receipts-2026-03.pdf" },
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
  idempotent: re-running as an upsert updates what changed and reports
  the rest as `skipped`. Without it, re-running duplicates everything.
- **`source.createdAt`** is when the record was made in the system it comes
  from — `"2019-04-02"`, or a date and time with an offset. Only beside an
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
  `keepr_search` finds it by title (add `types: ["tags"]`
  to search tags alone). On an upsert the list **replaces** the item's tags:
  leave `tags` out to keep them, `[]` takes them off. A tag marked
  *restricted* decides who can see what: **only the person, signed in to
  keepr, can put one on or take one off** — you never can, whatever the key
  holds (keepr refuses the row). Leave it out (an upsert keeps it) and tell
  the person to add or remove it in keepr. One *applied by a rule
  only* is never sent.

## Getting the values right

What each element takes is on its line in the schema, in keepr's words — the
type, the choices, the unit, the bounds, whether it holds a list. Build each
value from that line, never from what a similar element took somewhere else.
keepr refuses what it cannot read rather than guessing, and the dry run says
why for each row.

When the data is ambiguous — a date that reads two ways, a number written for
people, a word that is nearly a choice, money in another currency — the
decision is yours and the person's, not keepr's: `references/elements.md`
says what to do and when to ask. Links between rows (parents first) are there
too.

## When a row fails

Each failed row comes back with keepr's code and its sentence for every
problem. Read the sentence; it says what is wrong and usually what fits. Then:

- **Fix the row, not the card.** A value the element cannot take means the
  value was built wrong, or the person's data needs a question — never a
  reason to change the element's type.
- **Never drop a value to make a row pass.** If a value cannot be written as
  it is, ask the person, and say which rows wait on the answer.
- **The record already exists** (same source id in `create` mode, or a unique
  value another item holds): don't create a second one. Re-run as an `upsert`,
  or update the item keepr names.
- **A link that found nothing**: the parent failed, comes later in the file,
  or is under another `source.system`. Fix that, then the children.
- **Refused because only a person may do it** (some tags, some account
  links): leave that value out and tell the person to do it in keepr.
- **A card this collection does not take**: keepr's hint names the collection
  that does (a sub-collection). Send the row there.
- **keepr failed on its side**: send that row again once. If it fails again,
  stop and tell the person.

A failure you do not understand from its sentence: `GET /api/docs/contract`
lists every code with its meaning on the deployment
you are talking to.

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
  the row. When the user's data has a label the collection
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

Every call — dry or not — is ledgered.
Report to the user:

- how many were **created / updated / skipped / failed**, and into which collection;
- the failures by their external id and error code, not just a count;

**One import, one id.** Every batch of an import carries the same `importId`,
so keepr lists them as one import and someone who manages the collection can
**undo** it from the collection's **Settings → Imports** in the web app: the
items it created are deleted and the ones it updated are put back, except any
changed since. `keepr_ingest` returns it — pass it back as `import_id` on every
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
only the collection's own items, and it never deletes.
Items with an external id are better changed with `keepr_ingest` in `upsert`
mode.

## Attachments — files onto the items you just made

Only when the collection has attachments on (`schema` says so; otherwise every
upload is a 403).

**Files on the person's computer: keepr's local file tools.** In the keepr
plugin they run beside the connector in Claude Code, and in Cowork on the
person's computer: `keepr_attach_local_file` puts files at a path onto one
item (`item_id`), and `keepr_attach_folder` matches a whole folder to its
items, shows you the match, and then uploads the originals in the background,
streamed from disk, nothing through the conversation (each description says
how large a file it takes):

```
keepr_attach_local_file  { item_id: "<24-hex>", files: [{ path: "/Users/…/receipt.pdf" }] }
keepr_attach_folder  { folder: "/Users/…/receipts", collection: "Expenses", match_element: "receipt", dry_run: true }   # show this to the person → confirm
keepr_attach_folder  { …the same arguments…, dry_run: false, confirm: "…" }       # → job id
keepr_attach_status  { job_id: "att-…" }                                   # every minute or so, then once at the end
```

The local file tools cannot see an import you made through the connector, so
`keepr_attach_folder` needs to be told how the files match: `collection` +
`match_element` (an element whose value the filenames carry, such as a
receipt number or a name) or a `map` of item ids to files
(`{"<item id>": ["IMG_4471.jpg"]}`; `keepr_ingest`'s result has each row's
item id). Where one server carries every tool (the desktop extension),
the folder tool also matches this session's `keepr_ingest` external ids by
default; its description says so. The folder must be one keepr's file tools
can read: a path on the computer they run on, one the person names or chose
for this session. If it cannot read it, it says why — then ask the person for
the files instead (below).

These land among the item's **other attachments**. A card may also have a
**file element** (the schema lists it, with what kind of file and how large a
one it takes, and whether it holds one or several): a file that belongs IN
that field — the vehicle's photo, the signed form — is put there with
`keepr_attach_file` and its `element` argument, which uploads the file and
then binds it to the element. Its description says what a single file element
does with the file already there. An import row never sets a file element.

**A folder of files, matched to the records you just created** — the common
case: a directory of subjects and their photos. `keepr_attach_folder` does it,
as above.

Files find their record — by **external id**, or by the value of the element
`match_element` names — in whichever layout the user has:

| layout | matches |
| --- | --- |
| `photos/molly-blake/front.jpg`, `.../back.jpg` | the subfolder names the record |
| `receipts/R-1042.pdf` | the whole filename names the record |
| `photos/molly-blake.jpg`, `molly-blake-2.jpg`, `molly blake (3).jpg` | the filename, trailing counter stripped |
| anything else | a `map` — `{"molly-blake": ["IMG_4471.jpg", "IMG_4472.jpg"]}` |

By default a file in a subfolder belongs to the record that folder names —
and to nothing else: a folder that names no record leaves its files
unmatched (`Unit 12/1.jpg` is never unit 1). A file at the top tries its
whole filename, then its filename without a counter, so `R-1042.pdf` finds
the record `R-1042`. Force one with `match` — `folder`, `stem` or `exact` —
when the guess is wrong — `exact` reads the filename whatever folder
it is in.

This is why the external id matters for an import with photos: it is the
only thing linking a file on disk to a record in keepr. **Choose ids the
filenames can actually produce** — if the photos are `IMG_4471.jpg`, either
build a `map`, or use the photo names as the external ids when you create
the items.

Rules the folder tool already follow, so you don't have to:

- **Dry-run first.** It prints which files go to which record and what matched
  nothing. Show that to the user before uploading.
- **A file matching no record is never guessed at** — it is reported.
- **Re-running skips what is already there** (`keepr_attach_folder`: the same
  name AND size on the item), so a re-run after
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
3. `keepr_ingest` with `dry_run: true`, fix, then `dry_run: false`.
4. `keepr_attach_folder` with `dry_run: true` — matching on an element the
   filenames carry (`match_element`), or a `map` of the item ids the ingest
   returned; check the pairing
   with the person, then run it.
5. Report: items created, photos attached, and **anything unmatched**, by name.

### When the files are the person's, not yours

The folder is on their phone, or on a computer you cannot read, or the files
are too big to send: ask for them instead of uploading them.
`keepr_request_upload` takes the collection and the items waiting — each by
`item_id`, with a file `name` or a `pattern` when you know it, and an `element`
when the file goes in one — and returns a link to give the person;
`keepr_upload_status` says what has arrived.

One request covers one collection; an item may appear
more than once (front and back). It is all or nothing: an item the person
cannot change, a locked record, or an `element` that is not a file element
refuses the request, each by its entry's index. The link works only for the
person, signed in, and for as long as keepr says when it makes it. Report what
arrived, and what is still waiting, by name.
