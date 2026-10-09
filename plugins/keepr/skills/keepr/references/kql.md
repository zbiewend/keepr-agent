# KQL — the query language, for reading

`q` on `keepr_get_items` is KQL, the Keepr
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
slug the schema prints — `read-on`, not "Read on") or its id (below):

| system field | what it matches |
| --- | --- |
| `card` | the card, by **key** (`card = book`) or 24-hex id. Matches the card **and its descendants** |
| `id` | the item id |
| `tags` | the item's tags: by **name**, alias, **path** (`"Health/Digestive"`) or id — `tags = urgent`, `tags in (urgent, "Genre/Sci-fi")`. Matches the tag **and every tag beneath it**, applied by hand or by a rule, and your own private tags. An **item used as a tag** goes by its id only (`tags = <24-hex>`; the search finds it). A name that is no tag matches nothing; one that names two tags is refused (a 400 listing each tag's path) — write the path or the id. `tags is empty` ignores your private tags. `=`, `!=`, `in`, `not in`, `is empty` only — `~` and `<` `>` are refused (a 400 that says so). Anything keepr stores (a saved filter) keeps ids: keepr rewrites the names when it saves. An access setting (who can see what) may name only *restricted* tags |
| `notes` | the card-level Notes field |
| `created`, `updated` | the item's timestamps |
| `created.by` | who added the item: a 24-hex account id or `me` (see "Who added an item" below) |
| `set` | the element set the item's card carries (by key or id) |

A name with spaces or punctuation is double-quoted: `"heart rate" > 100`. A
quoted first segment always means an element, which is the escape hatch for an
element literally named `card`.

**Dot-walk**: after an item lookup element, a further segment reads the
referenced item — `resident.move-in-date < 2024-01-01`, `truck.depot = salem`.
keepr allows a few hops; past them it refuses the query and says so.

**Facet**: `@<card-key>` asks which items point at that card through *any*
lookup element, whatever it is called: `@person = "Molly Blake"`,
`@truck in (…)`, `@person is empty`. Only `=`, `!=`, `in`, `not in`,
`is empty`, `is not empty` may follow a facet, and it takes no dot-walk.

## Element ids — `#k7f3q2xa`

A filter can name an element by its id instead of its name:
`#k7f3q2xa != done`. An id is `#` and eight lower-case letters or digits, and
it names exactly **one element of one card**, whatever that element is called
and whatever other card has an element of the same name. keepr writes ids into
everything it stores — lookup filters, chart filters, saved filters, rules — and
you can write them in `q` too.

- `schema` lists each element's id beside its name: `status  #k7f3q2xa`.
- The MCP tools print a stored filter as it is and name each id beneath it:
  `where #k7f3q2xa is element status ("State") on card task`.
- A stored filter runs as written. Pass it on as `q` unchanged, and never put
  a name or a label in place of an id to make it readable: tell the person
  the element's label instead.
- Write an id wherever a name could mean more than one element — say two
  cards here have `status` and you mean the task's. Take it from `schema`. It
  stands wherever a name does: after a dot-walk (`#e1e1e1e1.#p4a5e6x7`) and
  before a part of a date (`#d8d8d8d8.weekday`).
- In what you type, a name **one** element answers to still works: keepr reads
  `status = open` as that element's id. A name that more than one element
  answers to is refused — next section.
- Quoted, `"#k7f3q2xa"` is text, not an id.

## When keepr asks which element

A name is unique within one card, not across a collection: a Task and a Bug
can each have a `status`, and a global card can even share its card name with
one of the collection's own. keepr never guesses which one a filter means.
When more than one element answers to a name where the filter reaches, keepr
refuses the filter and lists the candidates: each element's `#id`, its label
and the cards that hold it. The MCP tools print them one per line, with the
rewrite, and return them structured (`elementRefusal`),
and `schema` lists every id.

Then, in this order:

- **If the person has not said which one they mean, ask them.** Show the
  labels and the cards, not the ids. Never pick one yourself, even when one
  looks likelier: the wrong element answers a different question, and nothing
  says so.
- **One element:** its id where the name was — `#k7f3q2xa = open`; past a
  dot-walk, `who.#k7f3q2xa = nurse`; in a reference, `{{#k7f3q2xa}}`.
- **Any of those cards** ("whatever kind it is"): the condition once per id,
  joined by `or` — `(#k7f3q2xa = open or #m2p9r4tb = open)`. Where a missing
  value matches — `!=` (or `is not`), `not in`, `!~`, `is empty` — join them
  with `and`: `(#k7f3q2xa != done and #m2p9r4tb != done)`, so each card's items
  are read by their own element. `is not empty` is not one of those: it joins
  with `or`. A `not` in front stays in front of the whole group. Each copy
  counts as a condition.
- **One card's items only:** pin the card in the same `and` —
  `card = task and status = open`. The name is read on that card **and the
  cards beneath it**, so where a child card restates the name keepr asks
  again. A filter keepr already reads on one card — a lookup's filter, a
  chart with a card, `keepr_get_items` with its own `card` (which reads that
  card alone) — gains nothing from a pin: there the question comes from a card
  beneath it.

What you type may name a card by its key: keepr turns `card = task` into the
card's id. In a filter keepr **stores** — a saved filter, a rule's condition,
a lookup's filter, a chart's filter — write each element by its `#id` from
`schema`. A name works there only where keepr reads it on one card — the
rule's card, the lookup's target card, the chart's card, or a `card =` in the
same `and` — and keepr stores its id. An element of a card the same setup or
proposal creates has no id yet: name it on its card,
`card = <new card's key> and <name> = …`, and keepr writes both ids as it
saves.

A name **no** element answers to is refused in a filter keepr stores; in what
you type it matches nothing (below). A group can also take a filter past
keepr's cap of conditions, or past its length once every name is an id: name
fewer elements (ask which cards), pin one card, or split the question.

In a filter that decides who sees what (the person's own sharing settings,
never one an assistant writes), keepr may take only the whole group, or say
that nobody here can write it. The refusal says which; the person settles it
in keepr.

## Operators

| operator | meaning |
| --- | --- |
| `=`, `!=` | equal / not equal. Text is case-insensitive and anchored (the whole value) |
| `>`, `>=`, `<`, `<=` | numeric, date or lexicographic range |
| `~`, `!~` | contains / does not contain, case-insensitive substring (text; also `notes`) |
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
| `me` | the caller's own account (a person element) or their linked item (a lookup) |
| another element | `{{reorder-at}}` — compares two elements of the **same** record: `on-hand <= {{reorder-at}}` |
| list | `("Molly", "Leah")`, `(open, blocked)` — for `in` / `not in` |
| measurement | a bare number is the element's default unit (`weight > 20`); with a unit, `weight > 20lb` or `weight > "8 lb 7 oz"` |
| currency | on a one-currency element a bare number is that currency (`price > 20`); otherwise name it — `total > 20USD`, `total > "20 USD"`, `total >= "CA$12.50"`; quote any amount with a decimal point (`"12.50 USD"` — unquoted `12.50USD` is a parse error). A bare number on an element that takes several currencies is refused (400): name the currency |

A bare run of exactly 24 hex digits is an id, not a number. The words `and`,
`or`, `not`, `is`, `in`, `contains`, `empty` must be quoted to be values.

Equality on a date is the **whole day**: `created = -3d` is the calendar day
three days ago, and `spent-on = 2026-03-14` matches a datetime stored that day.

## Parts of a date

A date's day of the week, hour of the day or month, as a segment after it:

| path | parts |
| --- | --- |
| `created.weekday`, `created.hour`, `created.month` — and the same on `updated` | all three |
| `<date element>.weekday`, `<date element>.month` | a date has no hour |
| `<date and time element>.weekday`, `.hour`, `.month` | all three |

- **A weekday is a name**: `sun` … `sat` or the full word, any case — never a
  number.
- **An hour** is `0` to `23`.
- **A month** is `1` to `12`, `jan` … `dec`, or the full word.
- **Ranges run Sunday first**: `created.weekday <= wed` is Sunday to Wednesday.
  A range bound is compared where it lies: `created.hour < 24` matches every
  hour.
- **In a list each member counts on its own**: `created.weekday not in (mon,
  3)` is every day but Monday (`3` is no weekday, so it rules nothing out).
- **Time zone**: `created`, `updated` and a date and time are read in the
  collection's time zone; a date element is a calendar day with no zone.
- **A date list** (an element allowing several dates) matches if any entry
  does.

`created.weekday in (sat, sun)`, `created.hour >= 9 and created.hour < 17`,
`due.month = dec`.

## Who added an item

`created.by` takes a 24-hex account id or `me` — `created.by = me`. A name
never resolves: `created.by = "Sam"` matches nothing. Items in a collection
reached only through publishing or a link have no author, so
`created.by is empty` matches them.

## Per-type behaviour worth knowing

- **text** (short and long text, a link, a phone, an email, a color): `=`
  is the whole value, `~` is a substring. `status ~ open` matches "reopened".
  A color is its stored `#rrggbb` — quote it, `trim = "#1f6feb"`; a color name
  in a filter is matched as text, not read as a color.
- **choice**: compare against the choice **value** the schema lists —
  `status = in-progress`. A label is read as its value too
  (`status = "In progress"`), but the value is what keepr stores and never
  changes when a label is renamed, so prefer it. A choice that allows
  multiple values (the schema says it holds a list) holds a list, and a condition
  asks **any entry**: `skills = welding` matches an item holding welding among
  others, `skills in (welding, rigging)` any of them. A negation asks **no
  entry**: `skills != welding` matches only items with no welding at all (and
  blank ones). For "has welding but not rigging" write
  `skills = welding and skills != rigging`.
- **number**, **rating**: numeric. A rating is `0` to its max.
- **Me too** (a count of confirmations): numeric, and an item nobody has
  confirmed reads as `0` — `me-too > 10` is the well-backed ones,
  `me-too = 0` the ones nobody has backed yet. `~` is refused.
- **date**, **date and time**, **time**: ranges compare as dates; blanks are excluded
  from ranges (`due < today` does not match an empty due date — add
  `or due is empty` if you mean that).
- **boolean**: `=` only; `~` and ranges match nothing.
- **item lookup**: an id matches the stored link; a non-hex string matches the
  **title** of the linked item (`resident = "Molly Blake"`, `resident ~ blake`).
- **person**: an id, or `me`. Names are never resolved — `assignee = "Sam"`
  matches nothing.
- **location**: matches the address text (`where ~ portland`); coordinates
  are not queryable.
- **measurement**: compared in the canonical unit, so `weight = "8 lb 7 oz"`
  finds 8.4375 lb; `~` matches nothing. A bound reads the way it is written:
  `mileage < "8 L/100km"` finds the items using LESS than 8 L/100km (the
  better economies), even though fuel economy is stored as km/L.
- **currency**: compared only within one currency — `total > 20USD` never
  matches a CAD amount, and a CAD amount IS `!= 20USD`. `~` matches nothing.

## What does not error

An element name or id the collection does not have, a card key nobody uses, or a
type-incompatible comparison compiles to a **no-match** — the query runs and
answers zero. So does a value a date part cannot read: `created.weekday =
funday` and `created.hour = 24` match nothing (and `!=` them, everything).
A **parse error** is a 400, and it names the character position — a
number of about 309 digits is one (quote it to use it as text). A name that
more than one element or more than one tag answers to is a 400 too (above).
So a zero
from a query you wrote from memory is not evidence of anything; check the
element name against `schema` before you report "none".

keepr caps a query's length, its number of conditions and its dot-walk hops;
a query past a cap is refused with a sentence naming it. Split the question,
or narrow it. An element group counts one condition per id, and in a filter
keepr stores the length is counted with every name written as its id.

## Worked examples

Written against the showcase collections; the element names are theirs — read
`schema` for the real ones before you copy any.

| question | query |
| --- | --- |
| Books I finished this year, best first | `card = book and status = done and finished >= 2026-01-01` sorted by `rating`, highest first |
| Expenses over $50 in the last 90 days | `card = expense and amount > 50 and spent-on > -90d` |
| Unreimbursed meals | `category = meals and reimbursed = false` |
| Anything mentioning Blue Bottle | `merchant ~ "blue bottle"` (or `keepr_search` across every field) |
| Progress notes about Molly in the last quarter | `card = progress-note and resident = "Molly Blake" and created > -3mo` |
| Residents who moved in before 2024 with no room assigned | `card = resident and move-in-date < 2024-01-01 and room is empty` |
| Trucks whose depot is Salem (a value one hop away) | `card = truck and depot.city = salem` |
| Work orders pointing at truck 14, however the link is named | `@truck = "Truck 14" and status in (open, blocked)` |
| Stock at or below its reorder point | `on-hand <= {{reorder-at}}` |
| Controls assigned to me and due this week | `card = control and owner = me and due <= +7d and due >= today` |
| Everything tagged Urgent that is still open | `tags = urgent and status != done` |
| Notes about Mom (an item used as a tag), by its id | `card = note and tags = 66f1a2b3c4d5e6f708192a3b` |
| Items with no tags at all | `tags is empty` |
| Things I added at the weekend | `created.by = me and created.weekday in (sat, sun)` |
| Expenses logged during working hours | `card = expense and created.hour >= 9 and created.hour < 17` |
| Renewals due in December, any year | `card = policy and renews-on.month = dec` |

Count without listing: `keepr_get_items` with `mode: count`.
