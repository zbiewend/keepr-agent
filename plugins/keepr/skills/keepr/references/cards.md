# Cards — creating and changing record types

A card is schema. Creating one changes the shape of the user's data; changing
one changes the shape of data that already exists. Neither is done quietly,
and neither is done from memory: **read the card first**, propose, show the
user exactly what the server says will happen, and apply only what they saw.

Both need **Can change cards** on the key (or the connection) and `manage` on
the collection. Without it keepr refuses, naming what is missing; keepr's
tools print the fix — *create or edit a key with Can change cards turned
on* — and so should you.

## Commands and tools

| | MCP tool |
| --- | --- |
| read the card | `keepr_schema` with `card` |
| propose a new card | `keepr_propose_card` |
| create it | `keepr_apply_card` with the proposal token and the collection name typed back |
| propose a change | `keepr_propose_card` with a `change` argument |
| apply the change | `keepr_apply_card` with the token, the collection name typed back, and — for a destructive change — the card name typed back too |

A proposal token is good for 30 minutes and is used once. The apply step sends
exactly the payload that was previewed; nothing is recomputed between the two.

## Creating a card

`keepr_propose_card` with the card spec as `cards` writes nothing and returns
keepr's preview and a token; `keepr_apply_card` with that token creates it.

Propose first, show the user the elements and their types, and only apply
once they agree. `references/recipes.md` has worked card specs (a reading log,
an expense tracker, a linked contacts + notes pair) to start from. The data
types an element can have, and the options each takes, are keepr's: the
contract (`elementTypes`) lists every type, and keepr's
preview refuses an option it does not know, by name.

The whole spec goes to keepr as **one card blueprint** (keepr 2.1): keepr checks
it without writing anything — the proposal step prints its summary, or the
problems, one per line, each with where it is (`cards[1].key`) and keepr's
reason — and
Applying creates it **all or nothing**: parents first, then the lookups and
rollups once every card exists. If anything is refused part-way, keepr removes
what that apply had made and says so. So a card can look up **another card in
the same spec, or itself** (`"lookupCard": "task"` on the Task card — "depends
on"), and a rollup can read from one (`"sourceCard"` beside a `drivenFrom`),
none of which needs an id. A lookup to a **global card** the collection does
not have yet (`"lookupCard": "person"`) adds that card to the collection —
the proposal says so, and the key needs write as well. Keys are stored as
slugs (`Work_Item` becomes `work-item`); the proposal shows the key keepr will
use.

A spec is one card, a list of them, or `{ "cards": [...], "filters": [...],
"layouts": [...] }` — filters saved for the whole collection
(`{ "name": "Ready", "query": "card = task and status = ready" }`, the key needs
write as well) and table layouts for cards in the spec. Write a filter's cards
by key and its choices by value or label, as a person types them: keepr saves
each one by id and value once the spec's cards exist. Name an element on its
card, as there, or by its `#id` from `schema`: a name more than one element
answers to is refused with each one's `#id`, and you ask the person which
(`kql.md`, "When keepr asks which element"). A record goes in by its
id, never its title — `owner = Jane` is refused, with the matching records,
and the whole apply is undone; so is a key nothing in the
collection has. Table layouts are for cards in the spec
(`{ "card": "task", "columns": ["kpr", "title", "status"] }`). A card may also
carry `icon`, `color`, `displayTemplate` (`"{{kpr}} {{title}}"`),
`elementSets` (set keys) and `options` (`primaryDate`…).

A spec may also bring **new tags** — `"tags": [{ "name": "Work" }, { "name":
"Late", "parent": "Work", "rule": { "card": "task", "where": "status = open" }
}]` (`tags` on `keepr_propose_card`). A tag with a `rule` is applied
automatically to the items of that card the rule holds for — but it arrives
**paused**: nothing is tagged until the person resumes it in keepr (Settings →
Tags), and the proposal and the apply say so, with how many items it would tag.
Say that to the user in those words. `parent` names another tag in the spec;
filters name tags by name. Only tags the user asked for; the key needs write as
well.

One card, for example:

```json example
{ "name": "Plant", "key": "plant",
  "elements": [
    { "name": "species", "label": "Species", "dataType": "text-small", "isTitle": true, "required": true },
    { "name": "room", "label": "Room", "dataType": "choice",
      "choices": [ { "value": "kitchen", "label": "Kitchen" }, { "value": "study", "label": "Study" } ] },
    { "name": "water-every", "label": "Water every", "dataType": "integer", "help": "days" },
    { "name": "last-watered", "label": "Last watered", "dataType": "date" } ] }
```

Options go beside the element's name in the spec — whatever keepr's schema
shows on an element like it (`allowMultiple` for "Allow multiple", say). An
option the element's type does not take is refused by the preview, by name;
read the refusal rather than guessing another.

**A change to the shape of stored values waits for an answer.** Turning
"Allow multiple" on or off on a card whose items hold values (or another
change that would turn single values into lists, or lists into single values)
is refused until the change says what to do with them. keepr's refusal says
which answer it waits for, where it goes in the element's options, how many
items are affected, and a query that lists them. Tell the person what each
answer does to their data in those words. When the answer keeps one value and
drops the rest, ask the person before you send it; never pick it for them.

Only what the user described goes in. Do not add "useful" elements they did
not ask for; ask.

A card can **inherit** another card's elements — "a Bug is a Work item plus a
severity". Name the parent by key: `parentCardKey` on `keepr_propose_card`.
It may be a card in
the same spec (anywhere in it — keepr creates parents first), a card the
collection already has, or a global card. A parent that names nothing is
refused before anything is created — never created without its parent. An
item cannot move to another card later, so settle the parents before any rows
are written.

## Changing a card

### The hazard, stated once

`PATCH /api/card-definitions/{id}` **replaces the card's element list whole.**
A payload that carries only the element you meant to touch removes every other
one, and hides their stored values on every item. So a partial list is never
sent: keepr's tools read the card's own elements, lay your change
over them, and send all of them — and then the server's **change-preview**
says, from the real stored data, what that payload would do. You do not get
to skip the preview: it is where the token comes from.

### The flow

```
1. keepr_schema with card                             read the card as it is
2. write the change                                   only what the user asked for
3. keepr_propose_card with change
     the server's diff, item counts, side effects — and a token. Nothing written.
4. show the diff to the user, in their words, destructive parts first
5. keepr_apply_card with the token                    once they say yes
     confirm_card_name too  when step 3 said DESTRUCTIVE
```

### The change spec

```json example
{
  "elements": [
    { "name": "rating", "max": 10 },
    { "name": "isbn", "label": "ISBN", "dataType": "text-small" }
  ],
  "remove": ["shelf"],
  "name": "Books"
}
```

- An element **named in `elements`** that the card already has is **updated**:
  only the keys you give move (`label`, `dataType`, any option). Everything
  else about it stays.
- A name the card does not have is **added**, and needs a `dataType`.
- An element **not mentioned is kept unchanged**. Leaving one out of the spec
  is not a removal.
- **Removal only through `remove`**, by name, and only for the card's own
  elements. An inherited element belongs to the parent card; say so and stop.
- `name`, `description`, `options` (merged), `color`, `icon` are card fields
  and pass through. **`key` is refused**: it is the card's stable handle, and
  saved filters and links break when it changes.

### Reading the preview

The server answers with a classified diff:

| kind | what it means | destructive |
| --- | --- | --- |
| `added` | a new element; existing items have it empty | no |
| `labelChanged`, `optionsChanged`, `reordered` | display and validation changes; stored values untouched | no |
| `removed` | the element goes and **its stored values are hidden** on every item — kept, but no list, form, export, search or title shows them — until an element of the same name is added back (they all return) or a manager purges them from the card's settings in the web app. The preview reports how many items hold a value | **yes** |
| `retyped` | the data type changes. A number ↔ measurement move is a `conversion: measurement` and a number ↔ currency move a `conversion: currency` (values converted); anything else is `conversion: none` — the stored values are **reinterpreted, not converted**, and may stop matching or sorting | **yes** |

Plus `cardFields` (name, description…) and `sideEffects` the server knows
about — an account link that would be un-linked, automation rules that would
retire, rules and notifications that read a removed element and will see it
as unset (each by name), a primary date that would stop resolving. Read them
out.

### Say aloud what cannot be undone

Before asking for a yes, name the destructive parts in plain words, with the
server's numbers: *"Removing `shelf` hides the shelf on 12 books. They come
back only if `shelf` is added again, and a manager can purge them for good."* *"Changing `rating` from a rating to a number keeps
the 40 stored numbers but they are no longer a 0–10 scale."* Do not soften it,
and do not bundle it: a destructive change is its own question, separate from
the safe ones in the same spec, and the user may say yes to one and no to the
other — in which case, propose again with only what they agreed to.

### Rules

- **Read the card first.** A spec written from what the card "probably" has
  proposes the wrong thing, and the diff will say so — but the user should not
  be the one to catch it.
- **A card change is a proposal until the user has seen the diff.** Never
  apply in the same breath as proposing. The token exists so that what they
  saw and what gets applied are the same bytes.
- **Never remove an element the user did not name.** "Clean up the card" is
  a question ("which of these seven should go?"), not a removal.
- **Never retype to make a value fit.** If the data has "n/a" in a number
  element, the row is wrong, not the card.
- **Apply only what they saw.** If anything changed after the preview — they
  added a request, the token expired, the preview reported a refusal —
  propose again. An expired or used token is refused, on purpose.
- **A `wouldApply: false` preview is the server saying no** (an invalid
  option, a duplicate name, a scope problem). Nothing is stored; fix the spec
  and propose again. Do not try the PATCH directly.

### What is not here

**Deleting a card is not available from this skill or the MCP tools**, by
design: it is a soft delete only an administrator can reverse, it drops the
collection's membership settings for that card, and it retires the card's
automations. If the user wants a card gone, say that it is done from the
card's own page in the web app (the card's menu there), and leave it to them.

Renaming a card's **key**, moving a card between collections, and changing
its scope are likewise web-app operations.

A card's **layouts** (tile, table, form, page) and the **rules** that run on its
records are not here either — they are a setup: `references/setup.md`. Rules are
no longer out of reach for an assistant; a rule that notifies, changes other
records or runs on a schedule arrives paused, and the person turns it on.
