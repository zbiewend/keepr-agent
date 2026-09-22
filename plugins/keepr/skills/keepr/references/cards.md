# Cards — creating and changing record types

A card is schema. Creating one changes the shape of the user's data; changing
one changes the shape of data that already exists. Neither is done quietly,
and neither is done from memory: **read the card first**, propose, show the
user exactly what the server says will happen, and apply only what they saw.

Both need a key with the **`cards`** scope (**Can change cards** on the key)
and `manage` on the collection. A key without it gets `403 insufficient_scope`
with `requiredScope: "cards"`; the script prints the fix — *create or edit a
key with Can change cards turned on* — and so should you.

## Commands and tools

| | CLI | MCP tool |
| --- | --- | --- |
| read the card | `keepr.py schema --collection X --card KEY` | `keepr_schema` with `card` |
| propose a new card | `keepr.py create-card --collection X --spec card.json` (prints, writes nothing) | `keepr_propose_card` |
| create it | `keepr.py create-card … --apply` | `keepr_apply_card` with the proposal token and the collection name typed back |
| propose a change | `keepr.py change-card --collection X --card KEY --spec change.json` (server diff + a token, writes nothing) | `keepr_propose_card` with a `change` argument |
| apply the change | `keepr.py change-card --apply TOKEN [--confirm "Card name"]` | `keepr_apply_card` with the token, the collection name typed back, and — for a destructive change — the card name typed back too |

A proposal token is good for 30 minutes and is used once. The apply step sends
exactly the payload that was previewed; nothing is recomputed between the two.

## Creating a card

```bash
python3 scripts/keepr.py create-card --collection "My Books" --spec card.json
# prints exactly what it would create, writes nothing
python3 scripts/keepr.py create-card --collection "My Books" --spec card.json --apply
```

Propose first, show the user the elements and their types, and only `--apply`
once they agree. `references/recipes.md` has worked card specs (a reading log,
an expense tracker, a linked contacts + notes pair) to start from;
`references/elements.md` says what each of the 19 data types accepts. The
server slugifies and de-duplicates the key you ask for — read it back from
the result rather than assuming.

A spec is one card or a list of them:

```json
{ "name": "Plant", "key": "plant",
  "elements": [
    { "name": "species", "label": "Species", "dataType": "text-small", "isTitle": true, "required": true },
    { "name": "room", "label": "Room", "dataType": "choice",
      "choices": [ { "value": "kitchen", "label": "Kitchen" }, { "value": "study", "label": "Study" } ] },
    { "name": "water-every", "label": "Water every", "dataType": "integer", "help": "days" },
    { "name": "last-watered", "label": "Last watered", "dataType": "date" } ] }
```

Only what the user described goes in. Do not add "useful" elements they did
not ask for; ask.

## Changing a card

### The hazard, stated once

`PATCH /api/card-definitions/{id}` **replaces the card's element list whole.**
A payload that carries only the element you meant to touch removes every other
one, and their stored values with them. So neither the script nor the tool
ever sends a partial list: they read the card's own elements, lay your change
over them, and send all of them — and then the server's **change-preview**
says, from the real stored data, what that payload would do. You do not get
to skip the preview: it is where the token comes from.

### The flow

```
1. keepr.py schema --collection X --card KEY          read the card as it is
2. write change.json                                  only what the user asked for
3. keepr.py change-card --collection X --card KEY --spec change.json
     the server's diff, item counts, side effects — and a token. Nothing written.
4. show the diff to the user, in their words, destructive parts first
5. keepr.py change-card --apply TOKEN                 once they say yes
     --confirm "Card name"  when step 3 said DESTRUCTIVE
```

### The change spec

```json
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

The server answers with a classified diff. The script prints it one line per
change and leads the summary with `DESTRUCTIVE —` when anything is:

| kind | what it means | destructive |
| --- | --- | --- |
| `added` | a new element; existing items have it empty | no |
| `labelChanged`, `optionsChanged`, `reordered` | display and validation changes; stored values untouched | no |
| `removed` | the element goes and **its stored values with it**. The preview reports how many items hold a value | **yes** |
| `retyped` | the data type changes. A number ↔ measurement move is a `conversion: measurement` (values converted); anything else is `conversion: none` — the stored values are **reinterpreted, not converted**, and may stop matching or sorting | **yes** |

Plus `cardFields` (name, description…) and `sideEffects` the server knows
about — an account link that would be un-linked, automation rules that would
retire, a primary date that would stop resolving. Read them out.

### Say aloud what cannot be undone

Before asking for a yes, name the destructive parts in plain words, with the
server's numbers: *"Removing `shelf` loses the shelf on 12 books. There is no
undo for that from here."* *"Changing `rating` from a rating to a number keeps
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
