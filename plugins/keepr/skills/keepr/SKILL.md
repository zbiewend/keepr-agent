---
name: keepr
description: Read, add and change records in keepr — the user's collections of structured items — through its API or its MCP tools. Use whenever keepr is named or the user's data lives there. Reading ("what's in my keepr collection", "look up X in keepr", "find the items where…", "how many…", "show me the latest…"), adding ("add this to keepr", "log this in my collection", "import this CSV into keepr", "track these in keepr", or pasted data plus a collection name), and managing cards ("add an element to my Book card", "change the card", "create a card in keepr", "what fields does the card have"). Covers API-key handling, reading a collection's schema, KQL queries, dry-run validation, idempotent re-runs, linking records to each other, attaching files, and proposing card changes against a server-made diff.
---

# keepr

Read, add and change what a person keeps in keepr. This file is the part every
job shares; the job itself is one of four chapters, loaded when you need it.

keepr's vocabulary, because everything below uses it:

| keepr word | what it is |
| --- | --- |
| **collection** | a workspace. Everything lives in one. |
| **card** | a record *type* — its elements are the fields. "Book", "Expense", "Progress note". |
| **item** | one record of a card. One book, one expense. |
| **element** | one field on a card, with a data type the API enforces. |

You never guess at any of this: **the collection tells you what it accepts.**

## Which transport

There are two ways to reach keepr, and the judgement in every chapter is the
same for both. Only the commands differ; each chapter names both side by side.

**If tools named `keepr_*` are available in this session, use them.** You will
see `keepr_collections`, `keepr_schema`, `keepr_get_items`, `keepr_search`,
`keepr_ingest`, `keepr_propose_card`, `keepr_apply_card` and the rest. They
talk to the same API and take the same care. Nothing needs installing and you
do not need a key — the server already holds it.

**Otherwise run `python3 scripts/keepr.py`** (Python 3.8+, standard library
only), as described throughout.

Use the tools when they are there. Some environments — Claude Cowork is the one
this was built for — run your shell inside a sandbox that cannot reach
`api.keepr.cloud`; a `curl` there fails with
`CONNECT tunnel failed, response 403`. The MCP server runs outside that sandbox
and is not subject to it. **If a shell call to keepr fails that way and no
`keepr_*` tool is available, keepr is not down.** Say that plainly: the sandbox
cannot reach it, and the user needs either the keepr MCP server configured or
this skill run somewhere with network access. Do not report keepr as broken,
and do not retry the call.

One capability differs. The MCP server does not share a filesystem with you, so
`keepr_attach_file` takes the file's bytes (`content_base64`) rather than a
path, and is limited to roughly a megabyte. For a folder of photos matched to
records by external id, `keepr.py attach` is still the better tool and works
wherever a shell can reach the network.

## The key

*(For the MCP tools, skip this section — the server holds the key.)*

The script needs the person's API key (it starts `kpr_`). **You never ask for
it, never echo it, never write it into a file or a command.** It reaches the
script in one of two ways, and the person does both themselves:

- `python3 scripts/keepr.py login` — run **by them, in their own terminal**. It
  prompts without echo, verifies the key, and stores it under `~/.config/keepr/`
  readable only by them. It refuses to run when its input is not a terminal,
  which is what stops an assistant from driving it. When they need to run it,
  give them the command with the **absolute path** of this skill's
  `scripts/keepr.py` (you know where this file is; they may not) and wait.
- `KEEPR_API_KEY` in the environment (the environment wins when both are set).

`KEEPR_URL` is only for self-hosted keepr; the default is `https://api.keepr.cloud`.

```bash
python3 scripts/keepr.py check
```

`check` names the account the key acts as, its scopes, and every collection it
can reach. If it fails, stop and fix that first — every other command needs
it. If no key is set it says so; tell the user to run `login` or export the
variable, and wait. No key yet? `GETTING-STARTED.md` in this skill walks them
through creating one (web app → **My Profile** → **API keys**).

A key carries a **subset** of its owner's authority: at most what they can do,
only in the collections they allowed, never admin. Scopes: `read` (every
GET), `write` (items), `cards` (**Can change cards** — creating and changing
cards), and `delete` (**Can delete records** — off by default; keys made before
2026-09-24 do not have it, and this skill never deletes). It cannot share,
delete collections, or manage keys — a 403 on one of those is the design, not
a bug. **A 404 on a collection means it is not this
key's** — the id is wrong, or the key's allowlist does not include it.

## The collection tells you what it accepts

Every job starts the same way, whatever the chapter:

```
CLI                                              MCP tool
keepr.py check                                   keepr_collections
keepr.py schema --collection "<name or id>"      keepr_schema
```

`schema` lists each card with its elements, types, choices, which element is
the title, which are system-owned, and the card's primary date. Read it before
you query, before you write, before you propose a change — element names in
a query, values in a row and the diff of a card change all come from it, never
from memory or from what a similar collection looked like.

If the user named no collection, run `keepr.py collections` and ask which one.
Never pick one for them.

A collection can be a **sub-collection** of another (the listing says
`sub-collection of <parent>`). Its schema includes the cards it inherits from
its parent, and records of those are written to the sub-collection. A parent's
schema lists its sub-collections' cards under `familyCards`, each with the
collection that holds it: a record of one of those is written **there**, never
to the parent — a row sent to the parent fails `card_not_allowed` with a
`hint` naming the right collection.

## Which chapter

Open the one chapter the job needs; each is complete on its own and is read on
demand rather than up front.

| the user wants to… | open |
| --- | --- |
| know what is there — list, look up, count, find, summarise | `references/reading.md` |
| put records in — a sentence, a list, a spreadsheet, a document, files | `references/adding.md` |
| make or change a card — add an element, rename a field, create a card | `references/cards.md` |
| filter with a query — the `--q` / `q` syntax, dates, operators | `references/kql.md` |

A job can cross chapters: "add these, then show me the total" is adding then
reading; "add a field and fill it in for every book" is a card change then an
upsert. Do them in that order, and finish one before starting the next.

Two rules hold in every chapter:

- **Nothing is written without the user seeing what will be written first.** A
  dry run before an ingest; a server-made diff before a card change.
- **Never invent.** Not a value, not a total, not an element name, not the
  contents of a page you did not fetch.

## Staying current

This bundle is a copy. The deployment it talks to may be newer, so:

- `schema` prints the deployment's `contractVersion`.
- If a row fails with an error code, or a card uses an element type, that this
  skill does not document, the script says so and tells you to run:

```bash
python3 scripts/keepr.py contract --check
```

which fetches `GET /api/docs/contract` — the live vocabulary, generated by that
server — and prints exactly what is new. **The live contract wins.** Work from
it for the rest of the run, and tell the user the skill is behind.

## Without Python

Every command is a thin wrapper over a handful of HTTP calls, documented with
`curl` examples in `references/api.md`. If the environment cannot run the
script, drive the API directly — the contract is identical.

## Files

- `scripts/keepr.py` — the client. `login`, `logout`, `check`, `collections`,
  `schema`, `items`, `get`, `search`, `template`, `csv`, `ingest`, `runs`,
  `attach`, `create-card`, `change-card`, `contract`. Stdlib only.
- `references/reading.md` · `adding.md` · `cards.md` — the three chapters.
- `references/kql.md` — the query language, for reading.
- `references/api.md` — the HTTP contract, curl examples, every error code.
- `references/elements.md` — the 19 element types and what each accepts.
- `references/recipes.md` — worked card specs and end-to-end examples.
- `examples/` — sample data and prompts to try each chapter on.
- `GETTING-STARTED.md` — the user-facing setup walkthrough (keys, install, first use).
- `tests/run.sh` — offline suite against a stub API; run it after editing the script.
