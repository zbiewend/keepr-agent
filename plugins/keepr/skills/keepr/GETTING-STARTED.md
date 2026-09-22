# Using keepr with an AI assistant

This skill teaches an AI assistant — Claude Code, Claude desktop, or any agent
tool that can run a script or call a tool — how to work with your keepr
collections: **read** what is there ("how many books did I finish this
year?"), **add** records from a sentence, a spreadsheet, a PDF or a folder of
photos, and **change cards** ("add an ISBN field to my Book card").

You stay in control. The assistant reads what your collection accepts, shows
you what it plans to do, and only writes after you say yes. Every write is
logged; re-running an import updates your records instead of duplicating them;
and a change to a card is previewed by the server — with the count of records
it would affect — before it happens.

**Three steps: create a key, install the skill, give the key to the script.**

---

## Before you start

- A keepr account with at least one collection.
- A verified email address. Keys cannot be created until your email is verified
  (the banner at the top of the app will tell you if it isn't).
- An AI tool that can run a command or call a tool on your behalf — Claude
  Code is the easiest starting point. See *Will this work in my tool?* below.

---

## Step 1 — Create an API key

An API key lets a program act as you, in the collections you choose, without
your password.

1. Sign in to keepr.
2. Open the account menu (your name, bottom-left) → **My Profile**.
3. Find the **API keys** panel → **Create key**.
4. Fill in the fields:

   | Field | What to choose |
   | --- | --- |
   | **Name** | What it's for, so you recognize it later: *Claude on my laptop* |
   | **Scope** | **Read only** if the assistant should just look things up; **Read and write** to add and update records. |
   | **Can change cards** | Off unless you want the assistant to create or change cards (the record *types* — their fields). Changing a card can remove stored values, so this is a separate switch. |
   | **Collections** | **Only these collections**, naming the ones the assistant should touch, is safer than **All collections I can access**. |
   | **Expires** | Never, 30 days, 90 days or 1 year. 90 days is a good habit; Never means it lasts until you revoke it. |

5. **Copy the key now.** It starts with `kpr_` and is shown exactly once —
   keepr stores only a hash of it. If you lose it, revoke it and make another.
   You can hold up to 25 active keys at a time.

Keep it like a password: never paste it into a chat window, a document, a
screenshot, or a file you commit to git. **The assistant never needs to see
it** — Step 3 shows how the script gets it from you directly.

### What a key can — and can't — do

A key carries a **subset of your own** authority. It can never do more than you
can, and several things it can never do at all:

| It can | It cannot |
| --- | --- |
| Read the collections you allowed | Touch any other collection — they answer "not found" |
| Create and update items there (read and write) | Share anything, or change who has access |
| Create and change cards, with **Can change cards** and where you can manage the collection | Delete a card — that stays in the web app |
| Upload attachments | Delete or transfer a collection |
| | Change your password or email, or create more keys |
| | Act as an administrator, even if your account is one |

Your **API keys** panel shows each key's last-used date. **Revoke** stops it
immediately. If a key is ever exposed, revoke it there and create a new one —
nothing else about your account needs to change.

---

## Step 2 — Install the skill

Three ways. All three give you the same skill, named `keepr`.

### From a sentence (no download)

The server publishes the skill at a public URL, so an assistant that can fetch
a page and write files installs it from one line. Paste this to it:

```
Add the skill defined at https://api.keepr.cloud/api/docs/skill
```

That URL returns every file of the skill inline, plus instructions for where to
put them. Your assistant writes them out and follows `SKILL.md`. Nothing is
downloaded by you, and the copy you get always matches the server it will talk
to. Claude Code can do this; so can most agent tools that fetch URLs.

### Claude Code plugin *(when published)*

```
claude plugin marketplace add keepr/keepr-agent
claude plugin install keepr@keepr-agent
```

The plugin carries the skill and keepr's MCP server together, so Claude Code
gets both the instructions and the tools in one step.

### The zip

Download `keepr-<version>.zip` and unzip it. The folder contains `SKILL.md`,
a `scripts/` folder, references, and sample data.

- **Claude Code**: copy the folder into your skills directory —
  `mkdir -p ~/.claude/skills && cp -R keepr ~/.claude/skills/` for every
  project, or `.claude/skills/keepr` inside one. Start a new session and ask
  *"what skills do you have?"* — `keepr` should be listed.
- **Claude apps (web and desktop)**: where custom skills are supported, open
  **Settings → Capabilities → Skills** and upload the zip. The exact wording
  moves around between versions; look for the place that manages skills or
  custom capabilities. The assistant also needs to reach `api.keepr.cloud`
  and to be given your key — see *Will this work in my tool?* below.
- **Any other agent tool**: there's no magic in the packaging. If your tool can
  read a file of instructions and run a command, point it at `SKILL.md`. If it
  can make HTTP requests but not run scripts, give it `references/api.md` —
  the same workflow as plain `curl` calls.

### Replacing `keepr-add`

If you installed the earlier skill, **remove the `keepr-add` folder** (from
`~/.claude/skills/`, your project's `.claude/skills/`, or the Claude app's
skill list). `keepr` does everything it did; with both present, both would
answer "add this to keepr" and argue.

### No AI at all

The script is usable by itself:

```bash
python3 scripts/keepr.py login
python3 scripts/keepr.py check
python3 scripts/keepr.py items --collection "My Books" --q "rating >= 4"
python3 scripts/keepr.py csv --file books.csv --card book --id-column ISBN --out rows.json
python3 scripts/keepr.py ingest --rows rows.json --dry-run
```

Python 3.8 or newer, no packages to install.

---

## Step 3 — Give the script your key

**Recommended:** in your own terminal, from the skill's folder:

```bash
python3 scripts/keepr.py login
```

It asks for the key without echoing it, checks it against keepr, tells you
which account and scopes it has, and stores it in `~/.config/keepr/credentials`
readable only by you. That's it — every later command finds it there.
`python3 scripts/keepr.py logout` forgets it.

Run `login` yourself. It refuses to run when something other than a person is
typing into it, which is deliberate: the assistant is never the one holding
your key.

**Alternatively**, an environment variable, which wins over the stored key
when both are set:

| Variable | Value |
| --- | --- |
| `KEEPR_API_KEY` | your key, starting `kpr_` |
| `KEEPR_URL` | only if you self-host keepr. Defaults to `https://api.keepr.cloud` |

Export it in the shell you launch your tool from, or in your tool's own
secrets mechanism. Not in a project file — and if you must, make sure it's in
`.gitignore`.

Check it worked — ask your assistant *"can you see my keepr collections?"*, or
run:

```bash
python3 scripts/keepr.py check
```

You should see your name, your email, the key's scopes, and the collections
it can reach.

---

## Step 4 — Try it

**Read.** Start here; nothing can go wrong.

> What's in my Reading log? How many books did I finish this year, and which
> had five stars?

The assistant reads the collection's fields, asks keepr the question with a
query rather than pulling every record, and tells you how many matched out of
how many there are — with a link to each one.

**Add.** The `examples/` folder has data to practise on.

> Import `examples/books.csv` into my Reading log. The ISBN column is the
> unique id.

It maps the columns, **dry-runs the whole thing** — validating every row
without writing anything — and shows you the result before asking to commit.
That dry run is the safety net: a bad mapping shows up as a list of errors,
not as a hundred wrong records.

**Change a card.** Needs a key with **Can change cards**.

> Add an ISBN field to my Book card.

It reads the card, asks keepr to preview the change, and shows you the
server's answer: what is added, what would be removed, and how many records
hold a value under anything that would be lost. It applies only what you saw,
and only after you say yes. Removing a field or changing its type is marked
**DESTRUCTIVE** and asks you to confirm by the card's name.

---

## Things to try

```
What keepr collections can you see?

What fields does my Expenses card have?

How much did I spend at Blue Bottle in the last 90 days? Show me the receipts.

Which residents moved in before 2024 and have no room assigned?

Log in keepr that I finished Piranesi today — five stars.

Add an expense: $18.50 at Blue Bottle Coffee on March 14th, meals,
reimbursable, receipt BB-4471.

Here are my notes from this week's calls. Create a contact for each person and
a note for each conversation, linked to the right contact.

Take the table on page 3 of this PDF and add each row to my Inventory
collection. Show me what you'll write before you write it.

I fixed three rows in the spreadsheet — sync it again without creating duplicates.

Add a "publisher" field to my Book card, then fill it in for the ones you can
find in this list.

Rename the "Notes" field on my Contact card to "Background".
```

More, with sample data, in `examples/prompts.md`.

---

## Records with photos and documents

If the collection has attachments switched on, files can ride along with the
records they came from — and a whole folder can be matched at once.

The assistant creates the items first, then pairs the files to them by the
**unique id** you gave each record. Both of these layouts work without you
doing anything:

```
photos/molly-blake/front.jpg      a folder per subject
photos/molly-blake/back.jpg

photos/leah-park.jpg              or a file per subject, numbered
photos/leah-park-2.jpg
photos/leah-park (3).jpg
```

> Here's a folder of residents and their photos. Add a record for each one and
> attach their photos.

It will show you which files are going to which record **before** uploading
anything, and tell you about any file that matched nothing rather than
attaching it somewhere plausible. Re-running later uploads only what's new.

When the photos are camera names — `IMG_4471.jpg` — nothing connects them to a
subject except you. Say which is which, and the assistant will write the
mapping down and use it.

A few limits worth knowing: executables and scripts can't be attached, there's
a size cap per file and per account, and if attachments are switched off for
the collection every upload is refused — only the collection's owner can change
that, in the web app.

---

## Re-running an import safely

Give each record a **stable id from your own data** — an ISBN, an invoice
number, an order id — and keepr will recognise it next time. Re-run the same
import and you get:

- **updated** — the record changed;
- **skipped** — already exactly right, nothing written;
- **created** — genuinely new.

Tell your assistant which column is the unique id, and it handles the rest.
Without one, a second import creates a second copy of everything.

---

## Changing cards safely

A card is the *shape* of your records. Adding a field is harmless — existing
records simply have it empty. Two kinds of change are not:

- **Removing a field** deletes the values stored under it, on every record.
- **Changing a field's type** keeps the stored values but may make them
  unreadable in the new type (a rating turned into text is fine; text turned
  into a number is not).

So the assistant never does either on its own guess. Before any card change
it asks keepr for a preview — the server counts the records that hold a value
under anything affected — and shows you that. A destructive change is labelled
**DESTRUCTIVE** and applied only when you confirm it by the card's name.
Deleting a whole card isn't available to an assistant at all; that stays on
the card's own page in the web app.

---

## Will this work in my tool?

Three things have to be true:

1. **It can run a command, make HTTP requests, or call keepr's MCP tools** on
   your behalf. A chat that can only produce text cannot reach keepr.
2. **It can reach `api.keepr.cloud`.** Some hosted assistants run in sandboxes
   with no outbound internet; there, the skill can help you prepare the data
   but not send it — unless keepr's MCP server is configured, which runs
   outside the sandbox.
3. **You can give it the key**, through `login`, an environment variable, or
   the MCP server's own settings.

Claude Code on your own machine satisfies all three. If you're unsure about
another tool, run `python3 scripts/keepr.py check` the way that tool would: if
that prints your account, the skill will work there.

---

## When something goes wrong

| What you see | What it means |
| --- | --- |
| *No keepr API key is set* | Run `python3 scripts/keepr.py login` yourself, or export `KEEPR_API_KEY` in the shell the tool runs in. |
| *Run this yourself in a terminal* | `login` was started by something other than you. Open a terminal and run it there. |
| **401** invalid API key | Revoked, expired, mistyped, or truncated on copy. Create a new one. |
| **403** on a write | The key is read-only, or the collection is archived (archived collections are read-only for everyone). |
| **403** *This key cannot change cards* | Create or edit the key with **Can change cards** turned on. |
| **403** on sharing or deleting | By design — keys can't do those. Do it in the web app. |
| **404** on a collection | It isn't in this key's allowlist, or the id is wrong. Check the **Collections** setting on the key. |
| *N not readable by this key* | You asked for items the key can't see — another collection, a private record, a wrong id. Not "deleted". |
| *No collection named X* | The name didn't match. Ask the assistant to list collections and use the exact name. |
| Rows fail with `type` on a date | A date like `12/05/2024` is ambiguous. Tell the assistant which order the source uses. |
| Rows fail with `unknown_element` | The data has a column your card has no field for. Add the field, or leave the column out. |
| Rows fail with `duplicate` | Already imported. Ask for an update run instead of a fresh import. |
| Everything says `skipped` | The records are already exactly right. Nothing needed doing. |
| *That proposal expired* | Card-change previews last 30 minutes. Ask the assistant to propose again and show you the fresh diff. |

---

## Staying current

The skill you install is a copy; keepr keeps moving. So it checks.

Every time it reads a collection it also reads the version of the contract that
server publishes, and if it ever meets an error or a field type it doesn't
recognise, it fetches the current one from
`https://api.keepr.cloud/api/docs/contract` and works from that instead — then
tells you the skill is behind. You don't have to do anything; a stale copy
notices and corrects itself rather than guessing.

If you want to check by hand:

```bash
python3 scripts/keepr.py contract --check
```

---

## Keeping an eye on it

- **History** — every item and every card shows what changed, when, and which
  key did it.
- **Ingest runs** — each import is one ledger row on the collection, with counts
  and the item ids. Ask your assistant *"what did you put in here yesterday?"*
- **API keys panel** — last-used dates, and one-click revoke.

Nothing an assistant reads is beyond what your key allows, nothing it writes
is hidden, and nothing it writes to a record is beyond your reach to undo.

---

## Self-hosting

Point the script at your own API base, without a trailing slash — either at
login (`python3 scripts/keepr.py login --url https://keepr.example.com`) or
with `KEEPR_URL`:

```bash
export KEEPR_URL='https://keepr.example.com'
```

Everything else is identical.
