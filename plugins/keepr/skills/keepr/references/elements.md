# Element types — what each one accepts on write

keepr has 19 element data types. The collection's `schema` tells you which type
each element is; this tells you what to send for it.

Two rules hold for every type:

- **Empty is `null`, `""` or leaving the key out.** Leaving it out is usually
  what you want: on `upsert`, keys you omit keep their stored value, while `""`
  overwrites with empty.
- **Coercion is lossless or refused.** A numeric string becomes a number, a
  number becomes text, a timestamp into a `date` keeps the date part. Anything
  ambiguous is refused rather than guessed.

| type | send | notes |
| --- | --- | --- |
| `text-small` | `"Piranesi"` | one line |
| `text-large` | `"…"` | multi-line; newlines preserved |
| `rich-text` | `"- **(1)** …"` | markdown, as the web editor stores it |
| `choice` | `"reading"` | the choice's **value**, not its label. Anything else is `invalid_choice` |
| `number` | `18.5` or `"18.5"` | `decimals` **rounds** the value; `nonNegative`, `min`, `max` enforced |
| `decimal` | `18.50` | same as number, with declared precision |
| `integer` | `7` | a fractional value is rounded (half away from zero) |
| `boolean` | `true` | real booleans. `trueLabel`/`falseLabel` are display only |
| `date` | `"2026-03-14"` | see below |
| `date-time` | `"2026-03-14T09:30:00Z"` | a bare `YYYY-MM-DD` becomes midnight UTC |
| `time` | `"09:30"` | `HH:mm` or `HH:mm:ss`; `H:mm` is zero-padded |
| `url` | `"https://example.com/x"` | stored verbatim, never validated |
| `phone` | `"(503) 555-0142"` or `"+15035550142"` | the element declares a country; stored as E.164 |
| `email` | `"ada@example.com"` | `local@domain.tld`, ≤ 254 chars, domain lower-cased |
| `location` | `"1200 SW 1st Ave, Portland OR"` or `{"lat": 45.5, "lng": -122.67}` | the element's `accept` may allow only one of the two |
| `rating` | `4` | `0` to the element's `max` |
| `card-lookup` | `"65a1…"` or `{"$ref": "shelf-scifi"}` | see below |
| `measurement` | `8.5`, `{"value": 8.5, "unit": "lb"}`, or `"8 lb 7 oz"` | unit must be one the element allows |
| `user` | `"65a1…"` | a 24-hex account id of an active account |

## Dates

`YYYY-MM-DD`. That is the whole rule, and it is strict on purpose:

- **`12/05/2024` is refused.** December 5th and May 12th are both plausible
  readings and the API will not pick one. Work out which the source means and
  write `2024-12-05` or `2024-05-12`.
- **Epoch numbers are refused.** Convert them.
- An element with `precision: "month"` also accepts `"2026-09"` and floors
  anything longer to the first of that month; `"year"` accepts `"2026"`.
- `allowMultiple` takes an array; values come back de-duplicated, earliest first.
- An element may declare `min`/`max` bounds (absolute, relative like `today`, or
  another element) and `weekdays`. Breaking one is a `range` error naming the
  bound.
- A `rangeEnd` pairs two date elements; the end may not precede the start.

Relative dates in the user's words ("yesterday", "last Tuesday") are **yours**
to resolve, against today's date, before you write. If you cannot resolve one
confidently, ask.

## card-lookup — linking items

Three forms:

```jsonc
"shelf": "65a1b2c3d4e5f6a7b8c9d0e1"        // an item id you already know
"shelf": { "$ref": "shelf-scifi" }          // another row's source.externalId
"related": ["65a1…", { "$ref": "shelf-scifi" }]   // only when allowMultiple
```

A `$ref` resolves against the request's `source.system` — first among rows
already settled in the same request, then items already in the collection. So:

- **list parents before children**, always;
- a row that failed never settles its external id, and later `$ref`s to it fail
  with `ref_unresolved`;
- the target's card must be the element's `lookupCardKey` or a descendant, or
  it is `ref_wrong_card`.

To link to something already in keepr whose id you don't know, either import it
with the same `system` + `externalId` first (an `upsert` of an identical row is
a free no-op) or look the id up and send it plain.

## Measurements

The element declares a `measure` (mass, length, volume…), a `defaultUnit`, and
sometimes a `units` allowlist. A bare number means the default unit. The stored
`base` is computed — never send it.

## Driven elements

`"driven": true` in the schema means the platform computes that value. In strict
mode, sending one fails the row (`driven_element`). Leave them out; the
`template` command already does.

## Required elements

`"required": true` is enforced on every write path, so a row missing one fails
with `required`. `requiredWhen` means required only while its clauses hold —
e.g. a reason field required only while status is not "Given".

Do not satisfy a required element by inventing a value. If the user's data
genuinely lacks it, tell them the row cannot be written and ask what belongs
there.
