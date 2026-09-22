# KQL — the query language, for reading

`--q` on `keepr.py items` (and `q` on `keepr_get_items`) is KQL, the Keepr
Query Language: the same text the web app puts in its URLs and saved filters.
It is compiled on the server against the collection's cards, so it can only
narrow what the key can already read — never widen it.

Everything below is what the API accepts today. Where a construct is not
listed, it does not exist; do not extrapolate from SQL.

## Shape

```
path op value
```

joined with `and`, `or`, `not` and parentheses. Precedence is `not` > `and` >
`or`; keywords are case-insensitive.

```
card = book and rating >= 4
(card = progress-note and note ~ scissors) or (card = vitals and "heart rate" > 100)
not status = done
```

## Paths

The **first segment** is either a system field or an element **name** (the
slug the schema prints — `read-on`, not "Read on"):

| system field | what it matches |
| --- | --- |
| `card` | the card, by **key** (`card = book`) or 24-hex id. Matches the card **and its descendants** |
| `id` | the item id |
| `tags` | any tag on the item |
| `notes` | the card-level Notes field |
| `created`, `updated` | the item's timestamps |
| `set` | the element set the item's card carries (by key or id) |

A name with spaces or punctuation is double-quoted: `"heart rate" > 100`. A
quoted first segment always means an element, which is the escape hatch for an
element literally named `card`.

**Dot-walk**: after a `card-lookup` element, a further segment reads the
referenced item — `resident.move-in-date < 2024-01-01`, `truck.depot = salem`.
Up to three hops.

**Facet**: `@<card-key>` asks which items point at that card through *any*
lookup element, whatever it is called: `@person = "Molly Blake"`,
`@truck in (…)`, `@person is empty`. Only `=`, `!=`, `in`, `not in`,
`is empty`, `is not empty` may follow a facet, and it takes no dot-walk.

## Operators

| operator | meaning |
| --- | --- |
| `=`, `!=` | equal / not equal. Text is case-insensitive and anchored (the whole value) |
| `>`, `>=`, `<`, `<=` | numeric, date or lexicographic range |
| `~`, `!~` | contains / does not contain, case-insensitive substring (text; also `tags` and `notes`) |
| `in (a, b, c)`, `not in (…)` | one of / none of |
| `is empty`, `is not empty` | missing, `null`, `""` or `[]` — and the inverse |

`is`, `is not` and `contains` are accepted spellings of `=`, `!=` and `~`.

## Values

| value | written as |
| --- | --- |
| text | `"Blue Bottle"`, or bare when it is one slug-like word: `open`, `molly-blake`. Choice elements take the choice's **value**, card the card's **key** |
| number | `18.5`, `100` |
| date | `2026-03-14`; datetime `2026-03-14T10:00` |
| relative date | `-3d`, `-2w`, `-3mo`, `-1y`, `+7d` (from the start of today, UTC); `today`, `today-30d`; `now`, `now-2h`, `now+15m` (`h`/`m` only from `now`) |
| boolean | `true`, `false` (also `yes`/`no`/`1`/`0` on a boolean element) |
| `me` | the caller's own account (a `user` element) or their linked item (a lookup) |
| another element | `{{reorder-at}}` — compares two elements of the **same** record: `on-hand <= {{reorder-at}}` |
| list | `("Molly", "Leah")`, `(open, blocked)` — for `in` / `not in` |
| measurement | a bare number is the element's default unit (`weight > 20`); with a unit, `weight > 20lb` or `weight > "8 lb 7 oz"` |

A bare run of exactly 24 hex digits is an id, not a number. The words `and`,
`or`, `not`, `is`, `in`, `contains`, `empty` must be quoted to be values.

Equality on a date is the **whole day**: `created = -3d` is the calendar day
three days ago, and `spent-on = 2026-03-14` matches a datetime stored that day.

## Per-type behaviour worth knowing

- **text** (`text-small`, `text-large`, `url`, `phone`, `email`): `=` is the
  whole value, `~` is a substring. `status ~ open` matches "reopened".
- **choice**: compare against the choice **value** the schema lists, not its
  label — `status = in-progress`, not `"In progress"`.
- **number**, `rating`: numeric. A rating is `0` to its max.
- **date**, `date-time`, `time`: ranges compare as dates; blanks are excluded
  from ranges (`due < today` does not match an empty due date — add
  `or due is empty` if you mean that).
- **boolean**: `=` only; `~` and ranges match nothing.
- **card-lookup**: an id matches the stored link; a non-hex string matches the
  **title** of the linked item (`resident = "Molly Blake"`, `resident ~ blake`).
- **user**: an id, or `me`. Names are never resolved — `assignee = "Sam"`
  matches nothing.
- **location**: matches the address text (`where ~ portland`); coordinates
  are not queryable.
- **measurement**: compared in the canonical unit, so `weight = "8 lb 7 oz"`
  finds 8.4375 lb; `~` matches nothing.

## What does not error

An element name the collection does not have, a card key nobody uses, or a
type-incompatible comparison compiles to a **no-match** — the query runs and
answers zero. Only a **parse error** is a 400, and it names the character
position. So a zero from a query you wrote from memory is not evidence of
anything; check the element name against `schema` before you report "none".

Limits: 2000 characters, 50 conditions, three dot-walk hops.

## Worked examples

Written against the showcase collections; the element names are theirs — read
`schema` for the real ones before you copy any.

| question | query |
| --- | --- |
| Books I finished this year, best first | `card = book and status = done and finished >= 2026-01-01` with `--sort rating --desc` |
| Expenses over $50 in the last 90 days | `card = expense and amount > 50 and spent-on > -90d` |
| Unreimbursed meals | `category = meals and reimbursed = false` |
| Anything mentioning Blue Bottle | `merchant ~ "blue bottle"` (or `keepr.py search --q "blue bottle"` across every field) |
| Progress notes about Molly in the last quarter | `card = progress-note and resident = "Molly Blake" and created > -3mo` |
| Residents who moved in before 2024 with no room assigned | `card = resident and move-in-date < 2024-01-01 and room is empty` |
| Trucks whose depot is Salem (a value one hop away) | `card = truck and depot.city = salem` |
| Work orders pointing at truck 14, however the link is named | `@truck = "Truck 14" and status in (open, blocked)` |
| Stock at or below its reorder point | `on-hand <= {{reorder-at}}` |
| Controls assigned to me and due this week | `card = control and owner = me and due <= +7d and due >= today` |
| Items nobody has tagged | `tags is empty` |

Count without listing: `keepr.py items --collection X --q "…" --limit 1` and
read the total on the first line (the MCP tool has `mode: count`).
