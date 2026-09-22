# Reading — finding and reporting what is there

"What's in my collection?", "how many books did I finish this year?", "look up
the Northwind contact", "which trucks are due for service?". The discipline
here has the same weight as the write rules in `adding.md`: reading cannot
break a record, but a wrong answer about a record is a wrong answer about the
user's own data, said with confidence.

Read the collection's `schema` first (SKILL.md). It tells you the element
names a query can use, which element is the title, what the card's primary
date is, and what a choice's values are called. A query written from memory
of what the collection "probably" has compiles to a silent no-match, not an
error — you would report "none" for a question that had an answer.

## Commands and tools

| CLI | MCP tool | what it answers |
| --- | --- | --- |
| `keepr.py collections` | `keepr_collections` | which collections this key can see, and its role in each |
| `keepr.py schema --collection X` | `keepr_schema` | the cards and elements — read this first |
| `keepr.py items --collection X [--q KQL] [--card KEY] [--sort F] [--desc] [--limit N] [--skip N]` | `keepr_get_items` with `collection` and `q` | a page of items, count first |
| `keepr.py get --id ID [--id ID …]` | `keepr_get_items` with `ids` (or `item_id`) | one or more items in full, up to 100 |
| `keepr.py search --q TEXT [--types …] [--limit N]` | `keepr_search` | free-text substring search across collections, cards and items |

`--q` is KQL — `references/kql.md` has the grammar and worked examples. It is
the difference between paging a collection into context and asking the server
the actual question. `search` is not a query: it is a case-insensitive
substring match on names and text values, for "is there anything called…".

`--json` on any of them prints the raw response (for `items`, wrapped as
`{total, shown, skip, q, items}` because the total travels in a header), for
when you need a field the human rendering does not show.

## The rules

**Never present a page as the whole.** `items` answers `N of TOTAL items in
"Collection" matching Q` on its first line for a reason: say all three parts
to the user — how many you are showing, how many there are, and what filter
produced them. "Here are your books" is wrong when it is 25 of 340. "Here are
the 25 most recent of your 340 books" is right. If they asked for everything
and there is more than a page, say how many there are and ask how they want
it cut, rather than paging.

**Narrow before you page.** The default page is 25 and the API's ceiling is
200. Never walk a whole collection into context with `--skip` to answer a
question a query would answer. "How many are open?" is `--q "status = open"`
and reading the count line, not fetching every item and counting. "The
newest five" is `--limit 5` (the default sort is each card's primary date,
newest first). If a question really needs every item — "list every author" —
say how many items that is before you start, and stop at a page if the user
did not ask for the walk.

**A short `get` is "not readable by this key", never "deleted".** The API
omits an item it cannot show — wrong id, another collection, a private item,
outside the key's allowlist — and says nothing about which. `get` counts
them: `2 of 3 requested — 1 not readable by this key`. Report exactly that
phrase. Do not say the item is gone, was deleted, or does not exist; you do
not know that, and the user may be looking straight at it in the web app.

**A 404 on a collection means it is not this key's.** Wrong id, or outside
the key's allowlist. Say so and stop; do not go looking through other
collections for one with a similar name.

**Name items by their display title and give the link.** Every item has a
title (the card's title element; `displayValue` on the wire) and a web
address:

```
https://keepr.cloud/collections/<collectionId>/items/<itemId>
```

`items`, `get` and `search` print both. Use the title when you talk about a
record and give the link when the user might want to open it. Never refer to
an item by its id alone, and never invent a title for an untitled item — say
it is untitled and give the id.

**Report numbers as numbers.** Quote the count the server gave. Do not total,
average or otherwise compute over element values unless the user asked; when
they did, say which rows went into it — "the 12 items matching `status = paid
and paid-on > -30d`; 2 had no amount and were left out". A number without its
filter is a number nobody can check.

**Keep their values as they are.** A date is reported as stored (`2026-03-14`,
not "mid-March"); a measurement in the unit it was entered in; a choice by
its value or label as the schema names it. Round or convert only when asked,
and say so.

**Don't answer what you didn't fetch.** If a question needs an element the
schema does not have, say the collection does not track that. If it needs a
join across two cards, `kql.md` shows the dot-walk (`resident.move-in-date`)
and facet (`@person = …`) forms; if neither reaches it, say so rather than
fetching both sides and matching them by eye.

## Reporting

A good read answer has four parts, in this order:

1. **The scope**: which collection, which filter, how many matched, how many
   you are showing.
2. **The records**: title, the two or three values that answer the question,
   the link when useful. Not every element of every item.
3. **What was left out**: items not readable by this key, values that were
   empty, a filter that matched nothing.
4. **How to see more**: the next page, or the narrower query you would run.

```
12 of 12 expenses in "Household" matching merchant ~ "blue bottle" and spent-on > -90d
  2026-03-14  Blue Bottle Coffee   $18.50   https://keepr.cloud/collections/65a1…/items/66b2…
  …
Two of them have no receipt attached.
```
