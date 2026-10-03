# Element types — what each one accepts on write

keepr has 21 element data types. The collection's `schema` tells you which type
each element is; this tells you what to send for it.

Two rules hold for every type:

- **Empty is `null`, `""` or leaving the key out** — except that a CREATE
  starts an element you leave out at its **default**, when the schema gives
  one (see "Defaults" below). Leaving a key out is usually what you want: on
  `upsert`, keys you omit keep their stored value, while `""` overwrites with
  empty.
- **Coercion is lossless or refused.** A numeric string becomes a number, a
  number becomes text, a timestamp into a `date` keeps the date part. Anything
  ambiguous is refused rather than guessed.

| type | send | notes |
| --- | --- | --- |
| `text-small` | `"Piranesi"` | one line, ≤ 255 characters, or the element's own `maxLength` (`too_long` past it — use a long text for more). An element may carry a `pattern` (the schema gives its `regex`, `flags` and `message`; the whole value must match, and a value that doesn't is `pattern` — the message says what fits), and `case` / `trim`, which change what is stored (capitals or small letters, surrounding spaces removed) |
| `text-large` | `"…"` | multi-line; newlines preserved; ≤ 20,000 characters (50,000 when the element has `extendedLength`), or the element's own `maxLength` |
| `rich-text` | `"- **(1)** …"` | markdown, as the web editor stores it; ≤ 100,000 characters (250,000 with `extendedLength`) |
| `choice` | `"reading"` | the choice's **value**, not its label. Anything else is `invalid_choice`. With `allowMultiple` ("Allow multiple"): a list, `["welding", "rigging"]`, or one string separated by `;` — stored once each, in the choices' order; a list sent to a choice without it is `type` |
| `number` | `18.5` or `"18.5"` | `decimals` **rounds** the value; `nonNegative`, `min`, `max` enforced. Text a spreadsheet writes is read too: `"1,234,567.5"` (en-US grouping, commas every three digits) on any number, and `"12.5%"` on a `percent` element (stored as 12.5 — the number shown, never 0.125). A `%` on any other element, or a comma that does not group in threes (`"1,23"`, the decimal comma `"1,5"`), is `type` |
| `decimal` | `18.50` | same as number, with declared precision |
| `integer` | `7` | a fractional value is rounded (half away from zero) |
| `boolean` | `true` | real booleans. `trueLabel`/`falseLabel` are display only |
| `date` | `"2026-03-14"` | see below |
| `date-time` | `"2026-03-14T09:30:00Z"` | a bare `YYYY-MM-DD` becomes midnight UTC |
| `time` | `"09:30"` | `HH:mm` or `HH:mm:ss`; `H:mm` is zero-padded |
| `url` | `"https://example.com/x"` | a bare host (`example.com/x`) is stored as `https://example.com/x`. Allowed schemes: http, https, mailto, tel, sms, geo, facetime, spotify, zoommtg, msteams, slack — anything else, or a space, is `invalid_url`. ≤ 2,048 characters |
| `phone` | `"(503) 555-0142"` or `"+15035550142"` | the element declares a country; stored as E.164 |
| `email` | `"ada@example.com"` | `local@domain.tld`, ≤ 254 chars, domain lower-cased |
| `location` | `"1200 SW 1st Ave, Portland OR"` or `{"lat": 45.5, "lng": -122.67}` | the element's `accept` may allow only one of the two |
| `rating` | `4` | `0` to the element's `max` (2–10, default 5); whole stars unless the element has `allowHalf` (then `3.5` is fine). Past the scale is `range`, between the steps `type` |
| `card-lookup` | `"65a1…"` or `{"$ref": "shelf-scifi"}` | see below |
| `measurement` | `8.5`, `{"value": 8.5, "unit": "lb"}`, or `"8 lb 7 oz"` | unit must be one the element allows |
| `user` | `"65a1…"` | a 24-hex account id of an active account |
| `currency` | `12.5`, `"$12.50"`, `"12.50 CAD"`, `{"value": 12.5, "currency": "CAD"}` or `{"amount": 1250, "currency": "CAD"}` | see below |
| `color` | `"#1f6feb"`, `"#abc"`, `"rgb(31, 111, 235)"` or `"DodgerBlue"` | stored as a lower-case `#rrggbb`. A hex needs its `#`; the names are the 22 choice colors (Olive, ForestGreen, … DarkGray — CSS names, any case). A translucent color, a percentage or any other name is `invalid_color` |
| `file` | nothing — never send one in a row | an attachment of the item (a 24-hex id, or a list of up to 20 with `allowMultiple`). Attach it with the item form or `keepr_attach_file` with `element` (a single element is replaced — the key needs Can delete records — a list is appended to); an import row may only re-send the stored value unchanged — anything else, a blank or a replace that leaves it out included, is `file_not_settable`. `accept: "image"` takes photos only, `maxSizeMb` caps the size |

## Defaults

An element the schema shows with `defaultValue` (or `defaultToToday` /
`defaultToNow`, which win) starts at that value when a row that CREATES an item
leaves it out — a status that starts at "open", a yes/no that starts at yes, a
due date thirty days out (`{ "kind": "relative", "value": "today+30d" }`,
worked out when the item is created, in the collection's time zone), a fee
that starts at `{ "value": 45, "currency": "USD" }`, a color that starts at
`"#1f6feb"`. So:

- **Leave the key out to take the default.** Send `null` or `""` only when the
  user said the value is blank: an explicit blank is kept as blank.
- **A required element with a default is satisfied by it** when you leave it
  out — don't invent a value for it.
- **An upsert that matches an existing item never takes a default**: it is an
  update, and omitted keys keep what is stored.
- A default that no longer fits the element is simply not applied (the element
  starts blank); it never fails the row.

## Unique elements

An element the schema marks `unique: true` (a short text, a number, an email, a
phone or a url) may not hold the same value on two items of its card: a VIN,
a serial number, a member's email. Text and email are compared ignoring case
and surrounding spaces, a phone as its E.164 number, a number after its
decimals. A row repeating a value another item holds is refused
`duplicate_value` (the error names that item when you can read it) — so look
the record up and update it instead, and re-run an import as an `upsert` keyed
on the source id. An empty value is never refused, and re-sending a value an
item already holds always saves.

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

The element declares a `measure` (mass, length, volume, angle, frequency, fuel
economy…), a `defaultUnit`, and sometimes a `units` allowlist. A bare number
means the default unit. The stored `base` is computed — never send it. A fuel
economy is never zero (`range`); `L/100km` is a consumption, so a bigger number
is a worse economy than a smaller one.

## Currency

The element declares `currencies` (ISO 4217 codes such as `["USD", "CAD"]`) and
sometimes a `defaultCurrency`.

**Making one:** when the user names the currency, or several, put them in
`currencies`. When they don't, leave `currencies` out and keepr picks one. It uses
the collection's currency, else the person's preferred currency, else USD. Don't
guess one, and don't ask just for this. An empty list (`[]`) is refused. This
applies only to a NEW currency element. A stored one keeps its list, and a change
that leaves the list out is refused (`invalid_options`). The card's schema then
shows the currency keepr chose.

A value is stored as `{ "amount": 1250, "currency": "USD" }`
— `amount` is an integer of **minor units** (cents; a yen amount has none, a
Bahraini dinar has three). Send what the user gave you:

- a bare number or `"12.50"` means **major units** in the default currency;
- `"12.50 CAD"`, `"CA$12.50"`, `"$12.50"` or `{"value": 12.5, "currency": "CAD"}`
  name the currency (major units);
- `{"amount": 1250, "currency": "CAD"}` is the stored shape (minor units) — use it
  only when you really have cents.

There are **no exchange rates**: a currency the element does not list is
`invalid_currency`, never converted. More decimals than the currency has
(`"1.234 USD"`, `12.5` into a yen element) is `type` — never rounded, so ask
rather than round. A symbol shared by several currencies (`kr`) is refused;
write the code.

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
