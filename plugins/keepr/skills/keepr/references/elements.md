# Element values — what to send, and when to ask

What each element accepts is keepr's to say, not this chapter's. `keepr_schema`
gives every element its type, the options that limit it (choices, required,
bounds, units, currencies, length, list or single, unique, a default) and
A value keepr cannot read is refused with a sentence saying why, never stored as a guess.

This chapter is the part keepr cannot do for you: deciding what the person
meant, and asking when you cannot tell.

## Leave out what you were not given

- **An element the person's data does not have is left out of the row.** On a
  new item it then starts at its default when the schema shows one, or empty.
  On an update it keeps what is stored. The contract's `emptyValue` says
  exactly what a missing key, `null` and `""` each do.
- **Send a blank only when the person said the value is blank.** An explicit
  blank overwrites what is stored.
- **A required element is never satisfied by inventing a value.** If the data
  lacks it and the schema gives no default, tell the person the record cannot
  be written as it is, and ask what belongs there.
- **Elements keepr writes itself** (the schema marks them as never sent:
  computed, numbered) stay out of every row.

## Values that could mean two things

keepr refuses an ambiguous value rather than guessing, and so do you.

- **Dates.** `12/05/2024` is December 5th or May 12th. Work out which the source
  means from its other dates, its country, the person — and write the
  unambiguous form the schema line asks for. If you cannot tell, ask.
- **Relative dates** in the person's words ("yesterday", "last Tuesday") are
  yours to resolve, against today's date, before you write. If you cannot
  resolve one confidently, ask.
- **Numbers written for people** — `"1,5"`, `"n/a"`, a percent sign where the
  element is not a percent: ask what was meant rather than rewrite it into a
  number you chose.
- **Choices.** Send the value the schema lists. When the person's word is close
  to one but not it ("Scifi" for "sci-fi"), say which you used, or ask.
- **Colors, units, countries** that the schema line cannot read from what you
  have: ask for the precise form. Never pick a near one.

## Money

- **Never convert between currencies.** keepr has no exchange rates; an amount
  in a currency the element does not take is refused, and that is right. Ask
  the person what they want.
- **Never round to make an amount fit.** More decimals than a currency has is
  refused, not rounded; ask.
- **Making a money element:** when the person names the currency, or several,
  put them in the element's `currencies`. When they do not, leave it out and
  keepr chooses (the collection's currency, else the person's). Don't guess one,
  and don't ask just for this. The proposal shows what keepr chose.

## One value, one record

- **An element marked unique** may hold a value on one item only. When a row
  repeats a value another item holds, keepr names that item when this key can
  read it: don't create a second record — update the one that holds it (an
  `upsert` keyed on your source id re-runs cleanly), or ask which value is
  right.
- **Lists** (an element that holds several values): send everything the
  person gave, and nothing more. When keepr says a list is longer than the
  element holds, ask which to keep — never drop entries silently.

## Linking items

A lookup element points at another item: by its id when you know it, or by
`{"$ref": "<externalId>"}` at a row of the same import (or an item already in
keepr under the same `source.system`). So:

- **list parents before children**, always;
- a row that failed never settles its external id, so a later link to it
  fails too — fix the parent first;
- the target must be an item of the card the element looks up (the schema
  names it). A lookup the schema marks strict takes only a record its filter
  offers: choose one of those, or ask — never drop the link silently.

To link to something already in keepr whose id you don't know, either import it
with the same `system` + `externalId` first (an `upsert` of an identical row is
a free no-op) or look the id up and send it plain.

## Files

A file element is never filled by a row. Upload the file onto the item and put
it in the element with `keepr_attach_file` and its `element` (`adding.md`,
"Attachments"); a row may only carry the element's stored value back
unchanged, or leave it out.
