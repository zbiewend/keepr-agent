# Charts — totals, counts and averages, worked out by keepr

"How much did I spend on fuel by month?", "how many orders did each customer
place this year?", "what's my average weigh-in this quarter?", "when was the
last service on each truck?". These ask for a total, a count, an average, the
earliest or latest, or a share — usually broken down by month or by category.
**Ask keepr; don't add up a page.** A page is not the whole collection, a
blank or a second currency is easy to add in wrong, and keepr already answers
these questions for its own charts, over every item, in one call.

## Which tool

| the question | ask with |
| --- | --- |
| one plain count with a filter — "how many are open?" | `keepr_get_items` with `mode: "count"` |
| a total, an average, a median, earliest or latest, a share of yes — or anything "by month", "by category", "per customer" | `keepr_chart` |
| a question the person already saved as a chart | `keepr_chart` with `chart: "<name>"` (`list: true` lists them) |
| the records themselves — "show me", "which ones" | `keepr_get_items` (`reading.md`) |

No MCP tools in this session? `api.md`
§ 2d has the two HTTP calls. Every call sends `"grade": "export"`.

## What keepr counts, and what it tells you

- **Only what the person may take out of keepr.** A chart an assistant asks
  for is an export: it counts the items this key may export, which can be
  fewer than the person sees on screen. When it is, a note says how many were
  left out ("4 items you can see may not be exported…") — pass it on.
- **Notes say what was left out**: items with no value, amounts in another
  currency, a measurement in a unit that does not convert, a value that
  cannot be read, values folded into Other. Repeat the ones that change the
  answer.
- **Money is per currency**, never added across codes; the table gives it in
  major units with its code in the column heading. A measurement is in one
  unit, also in the heading.
- **Days are the collection's days**, in its time zone, which the answer
  names.
- On a very large collection keepr **counts a sample** and says so: totals
  and counts are estimates, and the headings say `estimated`. Say "about".

## A saved chart first

If the person refers to a chart they made ("my fuel chart"), or the question
sounds like one they would have saved, list them — `keepr_chart` with
`collection` and `list: true` — then run one by name or id:
`chart: "Fuel by month"`. `range` counts another period without changing the
chart: `{ "preset": "last90d" }`, `{ "from": "2026-01-01", "to": "2026-03-31" }`,
or `null` for all time. A saved chart that no longer fits its collection is
its owner's to fix in keepr; ask the same question as a spec meanwhile.

## Building a spec from the schema

Read `keepr_schema` for the collection first. Every name in a spec — the card,
each element, each choice in a filter — comes from it.

An element field — a measure's `element`, and the `on` of `groupBy`,
`splitBy` and `time` — takes the element's name or its `#id` from
`keepr_schema` (`"element": "#k7f3q2xa"`). keepr may hand the spec back with
ids in those fields, as it stores them; the answer still names the element by
its label. Tell the person the label, never the id.

1. **The card** — `card_id`: its key, name or id (descendant cards are
   counted with it). `null` counts every card, but only by the system fields
   (`count`, and grouping by `created`, `updated`, `created.by`, `card` or
   `collection`).
2. **The measures** — each `{ "key": "m1", "op": "…", "element": "…" }`
   (`keepr_chart`'s description says how many, and every op)
   (`key` is your name for it: a letter, then letters, digits or `_` — no
   hyphens).
   `count` counts items and takes no element. What else an element allows
   depends on its type, and keepr is the authority — the table is
   docs/SCHEMA.md, "Charts" › "What a chart may ask of each data type". The
   gist: numbers, money and measurements `sum`, `avg`, `median`, `min`, `max`
   (a rating and a temperature are never summed); a yes/no `countYes` or
   `shareYes`; a date its earliest (`min`) or latest (`max`); a choice or text
   `countNonBlank` or `distinct`; an item lookup or a person `distinct` only.
   Anything else keepr refuses, naming the op — change the op, never the
   element's meaning.
   `blanks: "zero"` counts a blank as 0 where that makes sense; the default
   leaves blanks out and says how many.
3. **The time** — `time: { "on": "<date element>" | "created" | "updated",
   "range": { "preset": "thisYear" } }`. A preset is a named period
   (`keepr_chart`'s description lists them; a `this…` preset runs from its
   start to today, not to its end); or `{ "from", "to" }` as `YYYY-MM-DD`, both
   days included.
4. **The rows** — `groupBy: { "on": "<element>" }`. A date needs a `bucket`:
   `day`, `week`, `month`, `quarter`, `year` (a date and time adds `hour`); or a
   part that repeats — `weekday`, `monthOfYear`, and on `created`, `updated`
   or a date and time `hourOfDay` — one row for each day of the week (Sunday
   first), month or hour, every one listed, read in the collection's time
   zone ("which day do I log the most?"); a time-of-day element `hourOfDay`
   or `halfHour`. `"on": "created.by"` makes a row per person who added the
   items (those who added most, the rest in Other; Not set for an item with
   no author). A number, an amount or a
   measurement needs ranges: `bins: { "size": 50 }` or `{ "count": 8 }`. A
   choice, yes/no, rating, item lookup or person is grouped by its values
   (`top` keeps the largest, the rest fold into Other). `splitBy`, the same
   shape, makes columns inside each row.
5. **Calculations.** A per-item formula instead of an element:
   `{ "key": "pace", "op": "avg", "perItem": "{{minutes}} / {{miles}}" }`. A
   formula across the measures above it: `{ "key": "avg_order", "formula":
   "{{m1}} / {{m2}}" }` (mark an input it reads `"hidden": true` if it should
   not be its own column). A formula keepr cannot chart yet is refused with a
   sentence saying so — tell the person keepr cannot chart it yet; don't work
   it out from a page.
6. **The form** — leave `show` out: you get a table. To compare with the
   previous period, add `"compare": "previous"` to `time` and
   `"show": { "type": "number" }` (one figure) or `{ "type": "line" }` (by a
   date bucket).
7. A `filter` narrows the items, in the KQL `kql.md` describes. keepr stores
   it with element ids, so the answer may show your `status != lost` as
   `#k7f3q2xa != lost`, with the element named beneath it (`kql.md`,
   "Element ids"). An id in a chart's filter must be one of its card's own
   elements. A name is read on the chart's card and the cards beneath it;
   with `card_id: null`, or where a card beneath restates it, a name more than
   one element answers to is refused with each one's `#id`. If the person has
   not said which one they mean, ask them, never pick, and ask again with the
   `#id` (`kql.md`, "When keepr asks which element").

## A worked example

A **Car** collection has a **Fill-up** card (key `fill-up`) whose elements
include `cost` (money, USD), `gallons` (a measurement in gal) and `filled-on`
(a date). The person asks: *"How much did I spend on fuel each month this
year, and how many gallons?"*

```json
{
  "collection": "Car",
  "spec": {
    "card_id": "fill-up",
    "time": { "on": "filled-on", "range": { "preset": "thisYear" } },
    "measures": [
      { "key": "spent", "op": "sum", "element": "cost" },
      { "key": "gal", "op": "sum", "element": "gallons" }
    ],
    "groupBy": { "on": "filled-on", "bucket": "month" }
  }
}
```

keepr answers a table and its notes:

```
CHART (a question, not saved) in "Car", card "Fill-up" — keepr counted 41 items, only what this key may export.
Range: 2026-01-01 to 2026-10-03.
Days are counted in America/Los_Angeles.

| Month | Total of Cost (USD) | Total of Gallons (gal) |
|---|---:|---:|
| Jan 2026 | 182.40 | 51.3 |
| Feb 2026 | 154.10 | 44.8 |
…
| Overall | 1,402.77 | 391.8 |

NOTES — what keepr left out or could not read:
  - 2 items have no cost, so they aren't counted in Total of Cost.
```

Say: *"You've spent $1,402.77 on fuel so far this year (January 1 to today) —
391.8 gallons. The month-by-month figures are above. Two fill-ups had no cost
recorded, so they aren't in the total."* The Overall row is keepr's own figure
over every item; never add the rows up yourself (an average's Overall is the
average of all the items, not of the rows).

## When keepr refuses

The tool answers `FAILED —`, keepr's own sentence, and a `NEXT:` line. A spec
refusal names the part to fix (`at spec.measures[0].element`): read
`keepr_schema` again and fix that part — never send the same spec twice. An
unconfirmed email address, a chart that is gone, a budget to wait out
(`Wait 9 seconds`) or keepr being busy each say what to do. A plain count is
still `keepr_get_items` `mode: "count"` if charts are not offered.

## Reporting

As `reading.md` says for any read: the scope (collection, range, filter), the
numbers that answer the question, what was left out, and the time zone when
the answer is by day. Quote keepr's figures as given, with their currency or
unit.
