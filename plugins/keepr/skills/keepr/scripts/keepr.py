#!/usr/bin/env python3
"""keepr — read, add and change records in a keepr collection through the keepr API.

Standard library only (Python 3.8+), so it runs wherever an agent can run a
script: no pip install, no virtualenv, no SDK.

The key
  The PERSON gives this script their key, never the assistant. Either:
    keepr.py login          run in their own terminal; prompts without echo,
                            verifies the key, stores it in ~/.config/keepr/credentials
    KEEPR_API_KEY=kpr_...   an environment variable (KEEPR_KEY is an alias)
  The environment wins when both are set. `keepr.py logout` removes the file.
  KEEPR_URL       API base URL, no trailing slash.
                  Default https://api.keepr.cloud (self-hosters override it).

Commands
  login / logout                         store or forget the key (login needs a terminal)
  check                                  who the key acts as, its scopes, and what it can reach
  collections                            list the collections the key can see
  schema      --collection X             the cards and elements this collection accepts
  items       --collection X [--q KQL]   list items: count first, then one line each
  get         --id ID [--id ID ...]      one or more items in full (up to 100)
  search      --q TEXT                   free-text search across collections, cards and items
  template    --collection X --card K    a skeleton rows file to fill in
  csv         --file F --card K          a CSV/TSV -> rows file
  ingest      --collection X --rows F    validate (--dry-run) or write a rows file
  attach      --item ID --file F ...     upload files onto one item
  attach      --results F --dir D        match a folder of files to the items an ingest created
  create-card --collection X --spec F    propose (or --apply) new card definitions
  change-card --collection X --card K --spec F
                                         propose a change to an existing card (server-made diff + token)
  change-card --apply TOKEN [--confirm "Card name"]
                                         apply a proposal the user has seen
  runs        --collection X             recent ingest runs, for audit
  contract    [--check]                  the live write contract this deployment publishes

The write loop the skill runs: schema -> build rows -> ingest --dry-run ->
fix -> ingest. Rows carrying `source.externalId` are idempotent: re-running
with --mode upsert updates what changed and reports the rest as `skipped`.

Exit status: 0 all good, 2 some rows failed validation, 1 the call itself
failed (bad key, unreachable collection, malformed file).
"""

import argparse
import csv as csvmod
import json
import mimetypes
import os
import re
import secrets
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

DEFAULT_URL = "https://api.keepr.cloud"
MAX_BATCH = 200                 # writeContract.maxBatch — the API refuses the 201st row
HEX24 = re.compile(r"^[0-9a-fA-F]{24}$")
# A real key: the prefix plus 43 base62 characters. `login` insists on the
# whole shape; the environment path only checks the prefix, so a stub key in
# a test can still reach the (stub) server.
KEY_SHAPE = re.compile(r"^kpr_[A-Za-z0-9]{43}$")
TIMEOUT = 120

ITEMS_DEFAULT_LIMIT = 25        # a page an agent can read, not a page the API can serve
ITEMS_MAX_LIMIT = 200           # GET /api/items caps `limit` here
IDS_MAX = 100                   # GET /api/items?ids= ignores the 101st id
PROPOSAL_TTL = 30 * 60          # seconds a change-card proposal stays applicable

# Where `login` keeps the key, and where change-card keeps its proposals.
# ~/.config/keepr is the person's, not the project's: nothing here can be
# committed by accident. HOME is honoured, which is also what the tests use.
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "keepr")
CREDENTIALS_FILE = os.path.join(CONFIG_DIR, "credentials")
PROPOSALS_DIR = os.path.join(CONFIG_DIR, "proposals")
WEB_URL = "https://keepr.cloud"

# Retries are for the transport, never for a refusal: a 4xx is an answer and
# repeating it just burns the user's rate budget.
RETRY_STATUSES = {429, 502, 503, 504}
RETRIES = 3

# What this copy of the skill was written against. The server publishes the
# live vocabulary at /api/docs/contract; when it reports something absent from
# these, this bundle is older than the deployment it is talking to and the
# right move is to go read the contract rather than guess.
KNOWN_ERROR_CODES = {
    "unknown_element", "driven_element", "sequence_element", "type", "required", "invalid_choice",
    "invalid_lookup", "invalid_unit", "invalid_currency", "range", "invalid_phone", "invalid_email",
    "invalid_location", "user_not_found",
    "card_unknown", "card_not_allowed", "forbidden_card", "forbidden_item",
    "source_invalid", "externalId_required", "duplicate", "card_mismatch",
    "ref_unresolved", "ref_wrong_card", "lookup_not_found",
    "private_not_allowed", "account_already_linked", "internal",
    # Not a row status: the hint.code beside a card_not_allowed whose card
    # belongs to a sub-collection (the message names it and its ingest path).
    "card_in_sub_collection",
}
KNOWN_ELEMENT_TYPES = {
    "text-small", "text-large", "rich-text", "choice", "number", "decimal",
    "integer", "boolean", "date", "date-time", "time", "url", "phone", "email",
    "location", "rating", "card-lookup", "measurement", "user", "currency",
}
STALE_HINT = ("This keepr deployment uses %s this skill does not know: %s.\n"
              "  Run `keepr.py contract` — it returns the live contract from the server, "
              "which is always current for that deployment.")


# ------------------------------------------------------------------ http

_CREDENTIALS = None


def stored_credentials():
    """What `login` wrote, or {} — read once. A file another user could read is
    used but named, because the fix is the person's to make, not this script's."""
    global _CREDENTIALS
    if _CREDENTIALS is None:
        _CREDENTIALS = {}
        try:
            with open(CREDENTIALS_FILE, encoding="utf-8") as fh:
                doc = json.load(fh)
            if isinstance(doc, dict):
                _CREDENTIALS = doc
            mode = stat.S_IMODE(os.stat(CREDENTIALS_FILE).st_mode)
            if mode & 0o077:
                print(f"warning: {CREDENTIALS_FILE} is readable by other users (mode {mode:o}); "
                      f"run `chmod 600 {CREDENTIALS_FILE}`.", file=sys.stderr)
        except (FileNotFoundError, ValueError, OSError):
            pass
    return _CREDENTIALS


def base_url():
    url = os.environ.get("KEEPR_URL") or stored_credentials().get("url") or DEFAULT_URL
    return str(url).strip().rstrip("/")


def api_key():
    """The environment first, then the file `login` wrote. Nothing else: the
    key never comes from an argument, a project file, or the conversation."""
    key = (os.environ.get("KEEPR_API_KEY") or os.environ.get("KEEPR_KEY") or "").strip()
    where = "KEEPR_API_KEY"
    if not key:
        key = str(stored_credentials().get("key") or "").strip()
        where = CREDENTIALS_FILE
    if not key:
        die("No keepr API key is set. Two ways to give this script one — both done by YOU, the\n"
            "account holder, never by an assistant:\n"
            "  keepr.py login                 (in your own terminal; the key is never echoed)\n"
            "  export KEEPR_API_KEY='kpr_...' (an environment variable)\n"
            "Create a key in the keepr web app: My Profile -> API keys -> Create key.")
    if not key.startswith("kpr_"):
        die(f"{where} does not hold a keepr API key (it should start with 'kpr_').")
    return key


def die(message, code=1):
    print(message, file=sys.stderr)
    sys.exit(code)


def request(method, path, body=None, headers=None, raw=None, key=None, url=None, with_headers=False):
    """One API call. Returns (status, parsed-body) — or (status, body, headers)
    with `with_headers`, for the one endpoint that answers in a header. Never
    raises on an HTTP error: the caller decides whether a 404 is fatal or just
    an answer. `key`/`url` override the configured ones for `login`, which
    verifies a key before anything has been stored."""
    hdrs = {"Authorization": f"Bearer {key or api_key()}", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    if raw is not None:
        data = raw
    hdrs.update(headers or {})
    base = (url or base_url()).rstrip("/")
    full = base + path

    def answer(status, parsed, resp_headers):
        return (status, parsed, resp_headers) if with_headers else (status, parsed)

    for attempt in range(RETRIES):
        req = urllib.request.Request(full, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                text = resp.read().decode("utf-8")
                return answer(resp.status, json.loads(text) if text.strip() else None, resp.headers)
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = text
            if e.code in RETRY_STATUSES and attempt < RETRIES - 1 and not is_final_refusal(e.code, parsed):
                wait = float(e.headers.get("Retry-After") or 0) or 2 ** attempt
                print(f"  HTTP {e.code}; retrying in {wait:.0f}s", file=sys.stderr)
                time.sleep(wait)
                continue
            return answer(e.code, parsed, e.headers)
        except urllib.error.URLError as e:
            if attempt < RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            die(f"Cannot reach {base}: {e.reason}")
    return answer(599, None, {})


# What each status means for a key holder — the ones that actually happen, in
# the words that tell the user what to change.
STATUS_HINTS = {
    401: "the key is missing, revoked, expired, or its owner's account is inactive",
    403: "the key lacks the scope this needs (write for items, cards for card changes, "
         "delete for removing anything), or the collection is archived, or this surface "
         "is closed to keys (sharing, deleting a collection, managing keys)",
    404: "the collection is not visible to this key — wrong id, or outside the key's collection allowlist",
    413: "the payload is over the 5 MB ingest limit; send fewer rows per call",
}

# The server names the missing scope on a 403 (`code: insufficient_scope`,
# `requiredScope`). Four scopes exist; each has one sentence that says what
# the person changes on the key. `delete` (2026-09-24) is off by default and
# no key made before then has it; this script never deletes, but a person
# relaying a refusal from another client should hear the right checkbox.
SCOPE_HINTS = {
    "cards": "This key cannot change cards. Create or edit a key with Can change cards turned on.",
    "write": "This key is read-only. Create or edit a key with Read and write scope.",
    "delete": "This key cannot delete records. Create a key with Can delete records turned on "
              "(keys made before 2026-09-24 do not have it), or delete in the web app.",
    "read": "This key has no read scope.",
}

# A 429 that is an ANSWER, not back-pressure: the key's daily delete budget is
# spent until the next UTC midnight, so retrying in a second only repeats the
# refusal. Said in the words of what happened, with when it comes back.
BUDGET_CODE = "delete_budget_exhausted"


def error_payload(body):
    if not isinstance(body, dict):
        return {}
    return body.get("payload") if isinstance(body.get("payload"), dict) else body


def is_final_refusal(status, body):
    """True for a status in RETRY_STATUSES that must not be retried."""
    return status == 429 and error_payload(body).get("code") == BUDGET_CODE


def budget_hint(status, body):
    """The sentence for a spent delete budget, or None."""
    if not is_final_refusal(status, body):
        return None
    p = error_payload(body)
    return (f"This key has used its daily delete budget ({p.get('used', '?')} of {p.get('limit', '?')}); "
            f"nothing was deleted. It resets at {p.get('resetsAt') or 'the next UTC midnight'}.")


def scope_hint(status, body):
    """The sentence for a scope refusal, or None when the 403 is something else."""
    if status != 403 or not isinstance(body, dict):
        return None
    payload = error_payload(body)
    if payload.get("code") != "insufficient_scope" and body.get("message") != "insufficient_scope":
        return None
    required = str(payload.get("requiredScope") or body.get("requiredScope") or "")
    return SCOPE_HINTS.get(required) or f"This key lacks the '{required or '?'}' scope it needs for this."


def fail_on(status, body, what):
    if status < 400:
        return
    message = body.get("message") if isinstance(body, dict) else body
    hint = scope_hint(status, body) or budget_hint(status, body) or STATUS_HINTS.get(status, "")
    die(f"{what}: HTTP {status} {message or ''}".rstrip() + (f"\n  ({hint})" if hint else ""))


def get(path, what):
    status, body = request("GET", path)
    fail_on(status, body, what)
    return body


# ------------------------------------------------------------------ resolving names

def resolve_collection(value):
    """A 24-hex id passes through; anything else is matched against the names of
    the collections this key can see — exact first (case-insensitive), then a
    unique substring. Ambiguity is an error listing the candidates, never a guess."""
    if not value:
        die("--collection is required (an id, or the collection's name).")
    if HEX24.match(value):
        return value
    collections = get("/api/collections", "listing collections") or []
    named = [(str(c.get("_id")), c.get("name") or "") for c in collections]
    wanted = value.strip().lower()
    exact = [c for c in named if c[1].lower() == wanted]
    if len(exact) == 1:
        return exact[0][0]
    if len(exact) > 1:
        die(f"Several collections are named '{value}'. Use the id:\n" +
            "\n".join(f"  {cid}  {name}" for cid, name in exact))
    partial = [c for c in named if wanted in c[1].lower()]
    if len(partial) == 1:
        print(f"(matched collection '{partial[0][1]}')", file=sys.stderr)
        return partial[0][0]
    if len(partial) > 1:
        die(f"'{value}' matches several collections. Use the id or the full name:\n" +
            "\n".join(f"  {cid}  {name}" for cid, name in partial))
    die(f"No collection named '{value}' is visible to this key. Known:\n" +
        ("\n".join(f"  {cid}  {name}" for cid, name in named) or "  (none — the key may be scoped to no collection)"))


def load_schema(collection_id):
    return get(f"/api/collections/{collection_id}/schema", "reading the collection schema")


def find_card(schema, key):
    """Cards are addressed by key (what a human writes) or id (what is unambiguous)."""
    for card in schema.get("cards", []):
        if card.get("key") == key or card.get("id") == key:
            return card
    keys = ", ".join(c.get("key", "?") for c in schema.get("cards", [])) or "(none)"
    die(f"No card '{key}' in this collection. Cards here: {keys}")


# ------------------------------------------------------------------ check / collections

def access_label(collection):
    """What this key may do in a collection, in one word.

    `myAccess.role` is null for a holder whose only grants are card-scoped or
    filtered — they still read, and sometimes write, just not collection-wide.
    Printing "None" for them would read as no access at all."""
    access = collection.get("myAccess") or {}
    role = access.get("role")
    if role:
        return role
    card_roles = access.get("cardRoles") or {}
    if card_roles:
        return "card-write" if "write" in set(card_roles.values()) else "card-read"
    if access.get("queryGrants"):
        return "filtered"
    return "none"


def describe_scopes(who):
    """One line from user-info's `auth` block — present for a key, absent for a
    session. Older deployments return no block at all; say so rather than
    inventing a scope list."""
    auth = who.get("auth") if isinstance(who.get("auth"), dict) else None
    if not auth:
        return "scopes: not reported by this deployment (write scope is learned on the first write)"
    scopes = [str(s) for s in (auth.get("scopes") or [])]
    can = []
    can.append("read items" if "read" in scopes else "cannot read")
    can.append("write items" if "write" in scopes else "cannot write items")
    can.append("change cards" if "cards" in scopes else "cannot change cards")
    can.append("delete records" if "delete" in scopes else "cannot delete records")
    ids = auth.get("collectionIds")
    where = ("every collection the owner can reach" if ids is None
             else f"{len(ids)} collection(s) on its allowlist")
    return f"scopes: {', '.join(scopes) or '(none)'} — {'; '.join(can)} · {where}"


def cmd_check(a):
    who = get("/api/user-info", "reading the account")
    name = who.get("fullName") or f'{who.get("firstName", "")} {who.get("lastName", "")}'.strip()
    print(f"key OK — acting as {name or '(unnamed)'} <{who.get('email', '?')}> at {base_url()}")
    print(describe_scopes(who))

    collections = get("/api/collections", "listing collections") or []
    if not collections:
        print("\nThis key can reach no collections. Either the account has none, or the key's\n"
              "collection allowlist names collections it can no longer see.")
        return
    print(f"\n{len(collections)} collection(s) reachable:")
    for c in sorted(collections, key=lambda c: (c.get("name") or "").lower()):
        flags = " ARCHIVED" if c.get("status") == "archived" else ""
        print(f"  {str(c.get('_id')):<26} {c.get('name', '')}  [{access_label(c)}]{flags}")
    print("\nA key can only do what its owner can, and only where its allowlist permits.\n"
          "Writing items needs `write` scope; creating or changing cards needs the `cards` scope\n"
          "(Can change cards) and `manage` on the collection. Deleting needs `delete` (Can delete\n"
          "records) beside those — this script never deletes.")


def cmd_collections(a):
    collections = get("/api/collections", "listing collections") or []
    if a.json:
        print(json.dumps(collections, indent=2, default=str))
        return
    for c in sorted(collections, key=lambda c: (c.get("name") or "").lower()):
        print(f"{str(c.get('_id')):<26} {c.get('name', ''):<40} {access_label(c)}"
              + ("  ARCHIVED" if c.get("status") == "archived" else ""))


# ------------------------------------------------------------------ schema

def describe_element(el):
    """One line per element: what the write path will accept for it."""
    bits = [el.get("dataType", "?")]
    if el.get("required"):
        bits.append("required")
    if el.get("requiredWhen"):
        bits.append("conditionally required")
    if el.get("isTitle"):
        bits.append("title")
    if el.get("driven"):
        bits.append("driven — do not send")
    if el.get("allowMultiple"):
        bits.append("list")
    if el.get("choices"):
        bits.append("one of: " + ", ".join(c.get("value", "") for c in el["choices"]))
    if el.get("dataType") == "card-lookup":
        bits.append(f"links to card '{el.get('lookupCardKey') or el.get('lookupCardId')}'")
    if el.get("dataType") == "measurement":
        bits.append(f"{el.get('measure', '')} in {el.get('defaultUnit', '')}"
                    + (f" (allowed: {', '.join(el.get('units') or [])})" if el.get("units") else ""))
    if el.get("dataType") == "currency":
        codes = el.get("currencies") or []
        bits.append("money in " + ", ".join(codes)
                    + (f" (a bare number is {el.get('defaultCurrency')})" if el.get("defaultCurrency") and len(codes) > 1 else ""))
    for bound in ("min", "max"):
        if isinstance(el.get(bound), (int, float)):
            bits.append(f"{bound} {el[bound]}")
    if el.get("help"):
        bits.append(f"help: {el['help']}")
    return f"    {el.get('name', '?'):<26} {' · '.join(bits)}"


def cmd_schema(a):
    collection = resolve_collection(a.collection)
    schema = load_schema(collection)
    if a.json:
        print(json.dumps(schema, indent=2))
        return
    coll = schema.get("collection", {})
    print(f"collection {coll.get('id')} — {coll.get('name')} · {coll.get('status')} · "
          f"attachments {'on' if coll.get('allowAttachments') else 'off'}")
    if coll.get("status") == "archived":
        print("  NOTE: archived collections are read-only for everyone. Writes will 403.")
    cards = schema.get("cards", [])
    if not cards:
        print("\n  No cards are writable here for this key.")
    for card in cards:
        if a.card and card.get("key") != a.card and card.get("id") != a.card:
            continue
        parent = f" (child of {card.get('parentCardId')})" if card.get("parentCardId") else ""
        print(f"\n  card '{card.get('key')}' — {card.get('name')}  [id {card.get('id')}]{parent}")
        for el in card.get("elements", []):
            print(describe_element(el))
    wc = schema.get("writeContract", {})
    print(f"\n  write contract: up to {wc.get('maxBatch', MAX_BATCH)} rows per call · "
          f"idempotent on {wc.get('idempotency')} · unknown element names are refused by default")
    if wc.get("contractVersion"):
        print(f"  contract version {wc['contractVersion']} (published at {wc.get('contract', '/api/docs/contract')})")
    unknown = sorted({el.get("dataType") for card in cards for el in card.get("elements", [])}
                     - KNOWN_ELEMENT_TYPES - {None})
    if unknown:
        print("\n" + STALE_HINT % ("element types", ", ".join(unknown)), file=sys.stderr)


# ------------------------------------------------------------------ template

def placeholder(el):
    """A value that says what the element wants and, left unfilled, fails a dry
    run loudly — better than a plausible default that silently writes nonsense."""
    kind = el.get("dataType")
    if el.get("choices"):
        return "<one of: " + "|".join(c.get("value", "") for c in el["choices"]) + ">"
    one = {
        "number": "<number>", "decimal": "<number>", "integer": "<whole number>",
        "rating": f"<0-{el.get('max', 5)}>", "boolean": "<true|false>",
        "date": "<YYYY-MM-DD>", "date-time": "<YYYY-MM-DDTHH:MM:SSZ>", "time": "<HH:MM>",
        "email": "<name@example.com>", "url": "<https://...>", "phone": "<phone number>",
        "location": "<address, or {\"lat\": 0, \"lng\": 0}>",
        "measurement": f"<number in {el.get('defaultUnit', 'the default unit')}>",
        "currency": f"<amount in {el.get('defaultCurrency') or (el.get('currencies') or ['the default currency'])[0]}, e.g. 12.50, or \"12.50 CAD\">",
        "card-lookup": "<24-hex item id, or {\"$ref\": \"<externalId>\"}>",
        "user": "<24-hex account id>",
    }.get(kind, "<text>")
    return [one] if el.get("allowMultiple") else one


def cmd_template(a):
    collection = resolve_collection(a.collection)
    card = find_card(load_schema(collection), a.card)
    elements = {}
    for el in card.get("elements", []):
        if el.get("driven"):
            continue           # system-owned: sending one is a refused row in strict mode
        elements[el["name"]] = placeholder(el)
    row = {"card": card.get("key"), "elements": elements, "source": {"externalId": "<stable id from your data>"}}
    doc = {
        "collection": collection,
        "source": {"system": a.system or "agent-import"},
        "items": [row for _ in range(max(1, a.rows))],
    }
    text = json.dumps(doc, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {a.out} — fill in the values, delete the elements you have no data for,\n"
              f"then: keepr.py ingest --rows {a.out} --dry-run")
    else:
        print(text)


# ------------------------------------------------------------------ csv

def slug(text):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower())).strip("-")


def cmd_csv(a):
    mapping = {}
    for pair in a.map or []:
        if "=" not in pair:
            die(f"--map expects COLUMN=element, got '{pair}'")
        column, element = pair.split("=", 1)
        mapping[column.strip()] = element.strip()

    known = None
    if a.collection:
        card = find_card(load_schema(resolve_collection(a.collection)), a.card)
        known = {el["name"] for el in card.get("elements", []) if not el.get("driven")}

    delimiter = "\t" if a.file.lower().endswith((".tsv", ".tab")) else a.delimiter
    with open(a.file, newline="", encoding="utf-8-sig") as fh:
        reader = csvmod.DictReader(fh, delimiter=delimiter)
        if not reader.fieldnames:
            die(f"{a.file} has no header row; the first line must name the columns.")
        # Every column resolves to an element name: an explicit --map wins, then
        # the header verbatim, then its slug. A column that matches no element is
        # dropped here with a warning rather than failing every row at the API.
        resolved, dropped = {}, []
        for column in reader.fieldnames:
            name = mapping.get(column) or column
            if known is not None and name not in known:
                name = slug(column)
                if name not in known:
                    dropped.append(column)
                    continue
            elif known is None and column not in mapping:
                name = slug(column)
            resolved[column] = name

        rows = []
        for n, record in enumerate(reader, 1):
            elements = {}
            for column, name in resolved.items():
                value = (record.get(column) or "").strip()
                if value == "":
                    continue          # omitted, not empty: an upsert must not wipe a column the CSV left blank
                elements[name] = value
            if not elements:
                continue
            row = {"card": a.card, "elements": elements}
            if a.id_column:
                external = (record.get(a.id_column) or "").strip()
                if not external:
                    die(f"row {n}: --id-column '{a.id_column}' is empty; every row needs a stable id "
                        f"(or drop --id-column and accept that re-running creates duplicates).")
                row["source"] = {"externalId": external}
            rows.append(row)

    if dropped:
        print(f"note: {len(dropped)} column(s) match no element on card '{a.card}' and were left out: "
              + ", ".join(dropped), file=sys.stderr)
    if not a.id_column:
        print("note: no --id-column, so these rows carry no external id — re-running this import "
              "will create duplicates rather than updating.", file=sys.stderr)

    doc = {"source": {"system": a.system or "csv-import"}, "items": rows}
    if a.collection:
        doc["collection"] = resolve_collection(a.collection)
    if a.ref:
        doc["source"]["ref"] = a.ref
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
    print(f"{len(rows)} row(s) from {a.file} → {a.out}"
          + (f" (dropped {len(dropped)} unmatched column(s))" if dropped else ""))


# ------------------------------------------------------------------ ingest

def load_rows(path):
    """Three shapes are accepted, because three are what agents actually produce:
    a bare list of rows, {source, items}, or {collection, source, batches}."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        die(f"No such rows file: {path}")
    except ValueError as e:
        die(f"{path} is not valid JSON: {e}")

    if isinstance(doc, list):
        return None, {}, doc
    if not isinstance(doc, dict):
        die(f"{path} must hold a list of rows or an object with an 'items' list.")
    source = doc.get("source") or {}
    if isinstance(doc.get("batches"), list):
        rows = [row for batch in doc["batches"] for row in batch]
    elif isinstance(doc.get("items"), list):
        rows = doc["items"]
    else:
        die(f"{path} has no 'items' (or 'batches') list.")
    return doc.get("collection"), source, rows


def unfilled(rows):
    """Placeholders from `template` that were never replaced. Catching them here
    beats reading 200 identical dry-run errors."""
    bad = []
    for i, row in enumerate(rows):
        for name, value in (row.get("elements") or {}).items():
            flat = value[0] if isinstance(value, list) and value else value
            if isinstance(flat, str) and flat.startswith("<") and flat.endswith(">"):
                bad.append(f"row {i}: {name} = {flat}")
    return bad


def cmd_ingest(a):
    file_collection, source, rows = load_rows(a.rows)
    collection = resolve_collection(a.collection or file_collection)
    if not rows:
        die(f"{a.rows} holds no rows.")
    if a.system:
        source = dict(source, system=a.system)
    if a.ref:
        source = dict(source, ref=a.ref)

    placeholders = unfilled(rows)
    if placeholders:
        die("These values are still template placeholders — fill them in or delete the keys:\n  "
            + "\n  ".join(placeholders[:20])
            + (f"\n  … and {len(placeholders) - 20} more" if len(placeholders) > 20 else ""))
    if a.mode == "upsert":
        missing = [i for i, row in enumerate(rows)
                   if not (row.get("source") or {}).get("externalId")]
        if missing:
            die(f"--mode upsert needs source.externalId on every row; {len(missing)} row(s) have none "
                f"(first: row {missing[0]}).")
    if (any((row.get("source") or {}).get("externalId") for row in rows) and not source.get("system")
            and not all((row.get("source") or {}).get("system") for row in rows)):
        die("Rows carry an externalId but no source.system is set. Pass --system <name> "
            "(it namespaces your external ids so two imports never collide).")

    batches = [rows[i:i + MAX_BATCH] for i in range(0, len(rows), MAX_BATCH)]
    totals = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
    results = {"collection": collection, "dryRun": a.dry_run, "mode": a.mode,
               "runs": [], "items": {}, "failures": []}

    for n, batch in enumerate(batches, 1):
        body = {"mode": a.mode, "dryRun": a.dry_run, "strict": not a.lenient, "items": batch}
        if source:
            body["source"] = source
        status, res = request("POST", f"/api/collections/{collection}/ingest", body)
        fail_on(status, res, f"ingest batch {n}")
        summary = res.get("summary", {})
        for key in totals:
            totals[key] += summary.get(key, 0)
        results["runs"].append({"batch": n, "runId": res.get("runId"), "summary": summary})
        for row in res.get("rows", []):
            external = row.get("externalId")
            if row.get("status") == "failed":
                results["failures"].append({"batch": n, "index": row.get("index"),
                                            "externalId": external, "errors": row.get("errors", [])})
            elif row.get("id"):
                results["items"][external or f"{n}:{row.get('index')}"] = row["id"]
        print(f"batch {n}/{len(batches)}: "
              + " · ".join(f"{k} {summary.get(k, 0)}" for k in totals)
              + f" · runId {res.get('runId')}")
        # A committed batch with failures stops here: later rows may reference a
        # row that never landed, and half-linked data is worse than a short import.
        if summary.get("failed") and not a.dry_run:
            print("  stopping — a failed row may be the parent of later rows. "
                  "Fix the rows and re-run with --mode upsert.", file=sys.stderr)
            break

    out = re.sub(r"\.json$", "", a.rows) + ".results.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)

    print(("DRY RUN — nothing was written. " if a.dry_run else "")
          + "totals: " + " · ".join(f"{k} {v}" for k, v in totals.items()) + f" → {out}")
    for failure in results["failures"][:25]:
        codes = "; ".join(f"{e.get('element') or '-'}: {e.get('code')} — {e.get('message')}"
                          for e in failure["errors"])
        label = failure["externalId"] or f"batch {failure['batch']} row {failure['index']}"
        print(f"  FAILED {label}: {codes}")
    if len(results["failures"]) > 25:
        print(f"  … {len(results['failures']) - 25} more in {out}")

    # A code this bundle does not document means the deployment has moved on.
    # Say so once, loudly, rather than letting the agent guess at the meaning.
    seen = {e.get("code") for f in results["failures"] for e in f["errors"]}
    unknown = sorted(c for c in seen if c and c not in KNOWN_ERROR_CODES)
    if unknown:
        print("\n" + STALE_HINT % ("error codes", ", ".join(unknown)), file=sys.stderr)

    if a.json:
        print(json.dumps(results, indent=2))
    if totals["failed"]:
        sys.exit(2)


def cmd_runs(a):
    collection = resolve_collection(a.collection)
    runs = get(f"/api/collections/{collection}/ingest-runs?limit={a.limit}", "listing ingest runs") or []
    if a.json:
        print(json.dumps(runs, indent=2, default=str))
        return
    if not runs:
        print("no ingest runs recorded for this collection")
    for run in runs:
        summary = run.get("summary", {})
        print(f"{run.get('createdAt', '')}  {str(run.get('_id'))}  mode {run.get('mode')}"
              f"{' DRY' if run.get('dryRun') else ''}  "
              + " · ".join(f"{k} {v}" for k, v in summary.items()))


# ------------------------------------------------------------------ attach

# Several photos of one subject are usually named for it with a counter:
# molly-blake.jpg, molly-blake-2.jpg, molly-blake_3.JPG, "molly blake (4).jpg".
# Everything after the last separator, if it is only digits, is the counter.
COUNTER_SUFFIX = re.compile(r"[\s._-]*(?:\(\s*\d+\s*\)|\d+)$")


def external_id_for(file_path, base, mode):
    """Which record a file belongs to. `folder` uses the containing directory
    (photos/molly-blake/*.jpg), `exact` the whole filename stem, `stem` the stem
    with a trailing counter removed. Default tries folder first, then stem —
    the two layouts people actually have."""
    rel = os.path.relpath(file_path, base)
    parent = os.path.dirname(rel)
    stem = os.path.splitext(os.path.basename(file_path))[0]
    if mode == "folder":
        return parent.split(os.sep)[0] if parent else None
    if mode == "exact":
        return stem
    if mode == "stem":
        return COUNTER_SUFFIX.sub("", stem) or stem
    # auto
    if parent:
        return parent.split(os.sep)[0]
    return COUNTER_SUFFIX.sub("", stem) or stem


def list_files(directory):
    found = []
    for root, dirs, names in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(names):
            if name.startswith("."):
                continue
            found.append(os.path.join(root, name))
    return found


def existing_attachment_names(item_id):
    """Filenames already on the item. Re-running a folder import must not upload
    the same photo twice — there is no unique key on attachments to lean on."""
    status, body = request("GET", f"/api/items/{item_id}/attachments")
    if status >= 400:
        return None                      # unknown: let the upload decide
    rows = body if isinstance(body, list) else (body or {}).get("attachments") or []
    return {str(r.get("filename") or r.get("name") or "") for r in rows if isinstance(r, dict)}


def upload(item_id, file_path):
    boundary = "----keepr" + uuid.uuid4().hex
    name = os.path.basename(file_path)
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    with open(file_path, "rb") as fh:
        content = fh.read()
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return request("POST", f"/api/items/{item_id}/attachments", raw=body,
                   headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}) + (len(content),)


def attach_plan(a):
    """-> [(externalId or None, itemId, filePath)], plus the unmatched files."""
    if a.item:
        if not a.file:
            die("--item needs at least one --file.")
        return [(None, a.item, f) for f in a.file], []

    if not a.results:
        die("Give either --item with --file, or --results (from an ingest) with --dir or --map.")
    try:
        with open(a.results, encoding="utf-8") as fh:
            results = json.load(fh)
    except (FileNotFoundError, ValueError) as e:
        die(f"cannot read {a.results}: {e}")
    items = results.get("items") or {}
    if not items:
        die(f"{a.results} records no item ids. Commit the ingest first (a dry run writes nothing).")

    pairs, unmatched = [], []
    if a.map:
        base = a.dir or os.path.dirname(os.path.abspath(a.map))
        try:
            with open(a.map, encoding="utf-8") as fh:
                mapping = json.load(fh)
        except (FileNotFoundError, ValueError) as e:
            die(f"cannot read {a.map}: {e}")
        for external, files in mapping.items():
            for name in ([files] if isinstance(files, str) else files):
                full = name if os.path.isabs(name) else os.path.join(base, name)
                if external not in items:
                    unmatched.append((full, f"no item with external id {external!r}"))
                elif not os.path.isfile(full):
                    unmatched.append((full, "no such file"))
                else:
                    pairs.append((external, items[external], full))
        return pairs, unmatched

    if not a.dir:
        die("--results needs --dir (a folder of files) or --map (an explicit mapping).")
    if not os.path.isdir(a.dir):
        die(f"No such folder: {a.dir}")
    for full in list_files(a.dir):
        external = external_id_for(full, a.dir, a.match)
        if external and external in items:
            pairs.append((external, items[external], full))
        else:
            unmatched.append((full, f"no item matches {external!r}" if external else "could not derive an id"))
    return pairs, unmatched


def cmd_attach(a):
    pairs, unmatched = attach_plan(a)
    if not pairs and not unmatched:
        die("Nothing to attach.")

    by_item = {}
    for external, item_id, full in pairs:
        by_item.setdefault((external, item_id), []).append(full)

    print(f"{len(pairs)} file(s) → {len(by_item)} item(s)"
          + (f" · {len(unmatched)} unmatched" if unmatched else ""))
    for full, why in unmatched[:20]:
        print(f"  UNMATCHED {os.path.basename(full)}: {why}", file=sys.stderr)
    if len(unmatched) > 20:
        print(f"  … {len(unmatched) - 20} more unmatched", file=sys.stderr)

    if a.dry_run:
        for (external, item_id), files in sorted(by_item.items(), key=lambda kv: str(kv[0][0])):
            print(f"  {external or item_id}: " + ", ".join(os.path.basename(f) for f in files))
        print("DRY RUN — nothing was uploaded.")
        return

    attached = skipped = failed = 0
    for (external, item_id), files in sorted(by_item.items(), key=lambda kv: str(kv[0][0])):
        have = existing_attachment_names(item_id)
        for full in files:
            name = os.path.basename(full)
            if have is not None and name in have:
                skipped += 1
                print(f"  skipped {name} → {external or item_id} (already attached)")
                continue
            status, res, size = upload(item_id, full)
            if status >= 400:
                failed += 1
                message = res.get("message") if isinstance(res, dict) else res
                hint = ""
                if status == 403:
                    hint = " — attachments may be off for this collection, or the key lacks write"
                elif status == 413:
                    hint = " — over the per-file or per-account storage cap"
                elif status == 415:
                    hint = " — that file type cannot be attached"
                print(f"  FAILED {name} → {external or item_id}: HTTP {status} {message or ''}{hint}",
                      file=sys.stderr)
                continue
            attached += 1
            print(f"  attached {name} ({size:,} bytes) → {external or item_id}")

    print(f"totals: attached {attached} · skipped {skipped} · failed {failed}"
          + (f" · unmatched {len(unmatched)}" if unmatched else ""))
    if failed or unmatched:
        sys.exit(2)


# ------------------------------------------------------------------ contract

def cmd_contract(a):
    status, body = request("GET", "/api/docs/contract")
    if status == 404:
        die("This keepr deployment does not publish /api/docs/contract (it predates that endpoint).\n"
            "  The bundled references/api.md is the contract for it.")
    fail_on(status, body, "reading the contract")

    if not a.check:
        print(json.dumps(body, indent=2))
        return

    live_types = {t["name"] for t in body.get("elementTypes", [])}
    live_codes = {e["code"] for group in (body.get("errorCodes") or {}).values() for e in group}
    new_types = sorted(live_types - KNOWN_ELEMENT_TYPES)
    new_codes = sorted(live_codes - KNOWN_ERROR_CODES)
    gone_types = sorted(KNOWN_ELEMENT_TYPES - live_types)

    print(f"contract version {body.get('version')} · {len(live_types)} element types · {len(live_codes)} error codes")
    if not (new_types or new_codes or gone_types):
        print("This skill is current with the deployment.")
        return
    for label, values in (("element types", new_types), ("error codes", new_codes)):
        if values:
            print(f"\nNEW {label} this skill does not document: " + ", ".join(values))
            for entry in body.get("elementTypes", []) if label == "element types" else []:
                if entry["name"] in values:
                    print(f"  {entry['name']}: send {entry.get('send')}"
                          + (f" — {entry['note']}" if entry.get("note") else ""))
            for group in (body.get("errorCodes") or {}).values():
                for entry in group:
                    if label == "error codes" and entry["code"] in values:
                        print(f"  {entry['code']}: {entry.get('means')}")
    if gone_types:
        print("\nThis skill documents element types the deployment no longer lists: " + ", ".join(gone_types))
    print("\nThe live contract above wins. Work from it for this run, and report the drift.")


# ------------------------------------------------------------------ create-card

# The option keys that belong under element.options, so a spec can write them
# flat and stay readable.
ELEMENT_OPTION_KEYS = {
    "isTitle", "required", "requiredWhen", "help", "choices", "allowMultiple",
    "lookupCardId", "measure", "defaultUnit", "units", "decimals", "leadingZeros",
    "nonNegative", "min", "max", "trueLabel", "falseLabel", "country", "accept",
    "rangeEnd", "minuteStep", "weekdays", "precision", "identity", "drivenFrom",
    "currencies", "defaultCurrency", "display",
}
KNOWN_TYPES = {
    "text-small", "text-large", "rich-text", "choice", "number", "decimal", "integer",
    "boolean", "date", "date-time", "time", "url", "phone", "email", "location",
    "rating", "card-lookup", "measurement", "user", "currency",
}


def normalize_element(el, card_ids):
    """A spec element -> the card-definition wire shape. `label` may be a string;
    `lookupCard` may name another card in the same spec by key."""
    if not el.get("name") and not el.get("label"):
        die("every element needs a name (or a label to derive one from)")
    data_type = el.get("dataType")
    if data_type not in KNOWN_TYPES:
        die(f"element '{el.get('name') or el.get('label')}': dataType '{data_type}' is not one of "
            + ", ".join(sorted(KNOWN_TYPES)))
    label = el.get("label") or el.get("name")
    if isinstance(label, str):
        label = {"singular": label, "plural": label + "s"}
    options = dict(el.get("options") or {})
    for key in ELEMENT_OPTION_KEYS:
        if key in el:
            options[key] = el[key]
    if el.get("lookupCard"):
        target = card_ids.get(el["lookupCard"])
        if not target:
            die(f"element '{el.get('name')}' looks up card '{el['lookupCard']}', which is neither "
                "already in the collection nor earlier in this spec")
        options["lookupCardId"] = target
    if data_type == "card-lookup" and not options.get("lookupCardId"):
        die(f"element '{el.get('name')}': a card-lookup needs lookupCard (a key) or lookupCardId")
    return {"name": el.get("name") or slug(label["singular"]), "label": label,
            "dataType": data_type, "options": options}


def cmd_create_card(a):
    collection = resolve_collection(a.collection)
    schema = load_schema(collection)
    card_ids = {c.get("key"): c.get("id") for c in schema.get("cards", [])}

    try:
        with open(a.spec, encoding="utf-8") as fh:
            spec = json.load(fh)
    except (FileNotFoundError, ValueError) as e:
        die(f"cannot read {a.spec}: {e}")
    cards = spec if isinstance(spec, list) else spec.get("cards", [spec])

    existing = [c.get("key") for c in cards if c.get("key") in card_ids]
    if existing:
        print(f"already in this collection, skipping: {', '.join(existing)}")
    todo = [c for c in cards if c.get("key") not in card_ids]
    if not todo:
        print("nothing to create.")
        return

    for card in todo:
        payload = {
            "name": card.get("name") or card.get("key"),
            "key": card.get("key") or slug(card.get("name", "")),
            "description": card.get("description", ""),
            "collection_id": collection,
            "elements": [normalize_element(el, card_ids) for el in card.get("elements", [])],
        }
        if card.get("parentCard"):
            payload["parentCardId"] = card_ids.get(card["parentCard"]) or card["parentCard"]
        if card.get("options"):
            payload["options"] = card["options"]

        if not a.apply:
            print(f"\n--- would create card '{payload['key']}' "
                  f"({len(payload['elements'])} elements) ---")
            print(json.dumps(payload, indent=2))
            card_ids[payload["key"]] = f"<{payload['key']} card id>"
            continue

        status, res = request("POST", "/api/card-definitions", payload)
        fail_on(status, res, f"creating card '{payload['key']}'")
        doc = res.get("payload", res) if isinstance(res, dict) else {}
        new_id = str(doc.get("_id") or doc.get("id") or "")
        assigned = doc.get("key") or payload["key"]
        card_ids[assigned] = new_id
        card_ids[payload["key"]] = new_id
        print(f"created card '{assigned}' → {new_id}"
              + ("" if assigned == payload["key"] else f"  (the server renamed the key from '{payload['key']}')"))

    if not a.apply:
        print("\nNothing was created. Show this to the user, and re-run with --apply once they agree —\n"
              "a card definition is schema, and creating one needs `manage` on the collection.")


# ------------------------------------------------------------------ change-card

# PATCH /api/card-definitions/{id} replaces `elements` WHOLE. A payload that
# carries only the element the user mentioned silently removes every other
# one. So this command never sends a partial list: it reads the card's own
# elements, applies the spec on top, and sends all of them — and the server's
# change-preview is what says whether that is what the user meant.

CARD_FIELDS = ("name", "description", "color", "icon", "displayTemplate", "parentCardId")


def deep_copy(value):
    return json.loads(json.dumps(value))


def merge_element_change(existing, change, card_ids):
    """One existing own element with a spec entry laid over it: label and
    dataType only when given, options merged key by key (flat keys and an
    `options` block alike). Nothing the spec does not mention moves."""
    el = deep_copy(existing)
    if "label" in change:
        label = change["label"]
        el["label"] = {"singular": label, "plural": label + "s"} if isinstance(label, str) else label
    if "dataType" in change:
        if change["dataType"] not in KNOWN_TYPES:
            die(f"element '{el.get('name')}': dataType '{change['dataType']}' is not one of "
                + ", ".join(sorted(KNOWN_TYPES)))
        el["dataType"] = change["dataType"]
    options = dict(el.get("options") or {})
    options.update(change.get("options") or {})
    for key in ELEMENT_OPTION_KEYS:
        if key in change:
            options[key] = change[key]
    if change.get("lookupCard"):
        target = card_ids.get(change["lookupCard"])
        if not target:
            die(f"element '{el.get('name')}' looks up card '{change['lookupCard']}', which is not in this collection")
        options["lookupCardId"] = target
    el["options"] = options
    return el


def build_card_patch(definition, spec, card_ids):
    """The FULL patch payload from a change spec. Elements named in the spec
    are updated or, when new, appended; elements not named are sent back
    unchanged; removal happens only through an explicit `remove` list."""
    if not isinstance(spec, dict):
        die("A change spec is a JSON object: {\"elements\": [...], \"remove\": [...], \"name\": ...}.")
    if "key" in spec:
        die("The spec names `key`. A card's key is its stable handle — saved filters and links break "
            "when it changes — so this command does not re-derive it. Remove `key` from the spec.")
    own = [deep_copy(e) for e in (definition.get("elements") or []) if isinstance(e, dict)]
    own_names = [e.get("name") for e in own]

    remove = spec.get("remove") or []
    if not isinstance(remove, list) or not all(isinstance(n, str) for n in remove):
        die("`remove` must be a list of element names.")
    for name in remove:
        if name not in own_names:
            die(f"'{name}' is not one of this card's own elements, so it cannot be removed here. "
                f"Own elements: {', '.join(own_names) or '(none)'}. An inherited element is changed on the card that declares it.")

    changes = spec.get("elements") or []
    if not isinstance(changes, list):
        die("`elements` must be a list of element changes.")
    touched, added = [], []
    for change in changes:
        if not isinstance(change, dict):
            die("Each element change is an object with at least a name.")
        label = change.get("label")
        name = change.get("name") or (slug(label if isinstance(label, str) else (label or {}).get("singular", "")))
        if not name:
            die("An element change needs a name (or a label to derive one from).")
        if name in remove:
            die(f"'{name}' is both changed and removed. Pick one.")
        if name in own_names:
            own[own_names.index(name)] = merge_element_change(own[own_names.index(name)], change, card_ids)
            touched.append(name)
        else:
            if not change.get("dataType"):
                die(f"'{name}' is not on this card; adding it needs a dataType.")
            own.append(normalize_element(dict(change, name=name), card_ids))
            own_names.append(name)
            added.append(name)

    payload = {"elements": [e for e in own if e.get("name") not in set(remove)]}
    for field in CARD_FIELDS:
        if field in spec:
            payload[field] = spec[field]
    if isinstance(spec.get("options"), dict):
        payload["options"] = dict(definition.get("options") or {}, **spec["options"])
    if not (touched or added or remove or any(f in spec for f in CARD_FIELDS) or "options" in spec):
        die("The spec changes nothing: no elements, no remove list, no card fields.")
    return payload, {"updated": touched, "added": added, "removed": list(remove)}


def print_preview(preview, collection_name):
    """The server's classified diff, one line per change, destructive first."""
    card = preview.get("card") or {}
    print(f"card \"{card.get('name')}\" ({card.get('key')}) in \"{collection_name}\"")
    summary = preview.get("summary") or ""
    if preview.get("destructive") and not summary.startswith("DESTRUCTIVE"):
        summary = "DESTRUCTIVE — " + summary
    print(summary or ("DESTRUCTIVE — this change loses stored values" if preview.get("destructive") else "no destructive changes"))

    for change in preview.get("changes") or []:
        kind = change.get("kind")
        el = change.get("element")
        held = change.get("itemsWithValues")
        if kind == "added":
            print(f"  + added      {el} ({change.get('dataType')})")
        elif kind == "removed":
            print(f"  - REMOVED    {el} ({change.get('dataType')}) — {held} item(s) hold a value; "
                  "those values are lost and cannot be recovered from here")
        elif kind == "retyped":
            how = ("converted" if change.get("conversion") in ("measurement", "currency")
                   else "reinterpreted, not converted")
            print(f"  ~ RETYPED    {el}: {change.get('from')} -> {change.get('to')} — "
                  f"{held} item(s) hold a value; they are {how}")
        elif kind == "optionsChanged":
            print(f"  ~ options    {el}: {', '.join(change.get('keys') or [])}")
        elif kind == "labelChanged":
            print(f"  ~ label      {el}: \"{change.get('from')}\" -> \"{change.get('to')}\"")
        elif kind == "reordered":
            print("  ~ reordered  the element order changes")
        else:
            print(f"  ? {json.dumps(change)}")
    for field in preview.get("cardFields") or []:
        print(f"  ~ card       {field.get('field')}: {json.dumps(field.get('from'))} -> {json.dumps(field.get('to'))}")
    for effect in preview.get("sideEffects") or []:
        print(f"  ! side effect ({effect.get('code')}): {effect.get('message')}")


def proposal_path(token):
    if not re.match(r"^[0-9a-f]{16}$", token or ""):
        die("A proposal token is 16 hex characters, as change-card printed it.")
    return os.path.join(PROPOSALS_DIR, token + ".json")


def store_proposal(doc):
    os.makedirs(PROPOSALS_DIR, mode=0o700, exist_ok=True)
    os.chmod(PROPOSALS_DIR, 0o700)
    token = secrets.token_hex(8)
    path = proposal_path(token)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(dict(doc, token=token), fh, indent=2)
    return token


def propose_card_change(a):
    collection = resolve_collection(a.collection)
    schema = load_schema(collection)
    collection_name = (schema.get("collection") or {}).get("name") or collection
    card_ids = {c.get("key"): c.get("id") for c in schema.get("cards", [])}
    card = find_card(schema, a.card)

    # The schema flattens ancestors and reshapes options for readers; the
    # PATCH wants the card's OWN elements in their stored form. Read those.
    definition = get(f"/api/card-definitions/{card.get('id')}", f"reading card '{a.card}'")
    try:
        with open(a.spec, encoding="utf-8") as fh:
            spec = json.load(fh)
    except (FileNotFoundError, ValueError) as e:
        die(f"cannot read {a.spec}: {e}")

    payload, plan = build_card_patch(definition, spec, card_ids)
    status, preview = request("POST", f"/api/card-definitions/{card.get('id')}/change-preview", payload)
    if status == 404:
        # The card was readable a moment ago, so this is the endpoint: an older
        # deployment that predates change-preview. Without the server's diff
        # there is no honest way to show the user what the PATCH would do.
        die(f"This keepr deployment does not offer change-preview for card '{a.card}' (HTTP 404). "
            "It predates card changes by agent; nothing was changed. Change the card in the web app.")
    fail_on(status, preview, f"previewing the change to card '{a.card}'")
    if not isinstance(preview, dict):
        die("The server answered the preview with something other than a diff. Nothing was changed.")

    print_preview(preview, collection_name)
    print(f"\n  elements sent: {len(payload['elements'])} (updated {len(plan['updated'])}, "
          f"added {len(plan['added'])}, removed {len(plan['removed'])}, unchanged "
          f"{len(payload['elements']) - len(plan['updated']) - len(plan['added'])})")

    if not preview.get("wouldApply", True):
        refusal = preview.get("refusal") or {}
        die(f"\nThe server would refuse this change: {refusal.get('code') or ''} {refusal.get('message') or ''}".rstrip()
            + "\nNothing was changed and no proposal was stored. Fix the spec and propose again.")

    now = time.time()
    token = store_proposal({
        "createdAt": now, "expiresAt": now + PROPOSAL_TTL,
        "collectionId": collection, "collectionName": collection_name,
        "cardId": str(preview.get("card", {}).get("id") or card.get("id")),
        "cardName": str(preview.get("card", {}).get("name") or card.get("name")),
        "cardKey": str(preview.get("card", {}).get("key") or card.get("key")),
        "destructive": bool(preview.get("destructive")),
        "summary": preview.get("summary"),
        "payload": payload,
    })
    print(f"\nNothing was changed. Proposal {token} is stored for 30 minutes.")
    print("Show the diff above to the user. Once they agree, apply exactly this with:")
    if preview.get("destructive"):
        print(f"  keepr.py change-card --apply {token} --confirm \"{preview.get('card', {}).get('name') or card.get('name')}\"")
        print("  (destructive: --confirm takes the card's name typed back, as the user's acknowledgement)")
    else:
        print(f"  keepr.py change-card --apply {token}")


def apply_card_change(a):
    path = proposal_path(a.apply)
    try:
        with open(path, encoding="utf-8") as fh:
            proposal = json.load(fh)
    except FileNotFoundError:
        die(f"No proposal {a.apply}. Propose again (change-card --collection ... --card ... --spec ...) "
            "and show the user the fresh diff.")
    except ValueError:
        die(f"Proposal {a.apply} is unreadable. Propose again.")

    if time.time() > float(proposal.get("expiresAt") or 0):
        os.remove(path)
        die("That proposal expired (they last 30 minutes) and has been discarded. Propose again, "
            "show the user the fresh diff, and apply that one.")
    if proposal.get("destructive"):
        if not a.confirm:
            die(f"This proposal is destructive — {proposal.get('summary') or 'it removes or retypes an element'} — "
                f"and nothing was changed. Apply it with --confirm \"{proposal.get('cardName')}\" (the card's "
                "name typed back) once the user has seen the diff and agreed.")
        if a.confirm.strip() != str(proposal.get("cardName") or ""):
            die(f"--confirm does not match. The proposal is for card \"{proposal.get('cardName')}\"; "
                f"you sent \"{a.confirm}\". Nothing was changed.")

    # One shot: the file goes whatever the server says, so a failed apply is
    # re-proposed against the card as it is now, never retried blind.
    try:
        status, res = request("PATCH", f"/api/card-definitions/{proposal['cardId']}", proposal["payload"])
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    fail_on(status, res, f"changing card '{proposal.get('cardKey')}'")
    doc = res.get("payload", res) if isinstance(res, dict) else {}
    print(f"changed card '{doc.get('key') or proposal.get('cardKey')}' — "
          f"{len(doc.get('elements') or proposal['payload']['elements'])} own element(s) now")
    for conv in (res.get("conversions") or ([res["conversion"]] if res.get("conversion") else [])) if isinstance(res, dict) else []:
        print(f"  converted {conv.get('element')}: {conv.get('from')} -> {conv.get('to')}"
              + (f", {conv.get('count')} item(s)" if conv.get("count") is not None else ""))
    if isinstance(res, dict) and res.get("conversionWarning"):
        print(f"  WARNING: {res['conversionWarning']}", file=sys.stderr)
    print(f"  {WEB_URL}/collections/{proposal.get('collectionId')}")


def cmd_change_card(a):
    if a.apply:
        return apply_card_change(a)
    if not (a.collection and a.card and a.spec):
        die("To propose: change-card --collection X --card KEY --spec change.json\n"
            "To apply:   change-card --apply TOKEN [--confirm \"Card name\"]")
    propose_card_change(a)


# ------------------------------------------------------------------ login / logout

def write_credentials(url, key):
    """0700 directory, 0600 file, created with the mode rather than chmod'd
    after — there is no instant where the key sits world-readable."""
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)
    fd = os.open(CREDENTIALS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"url": url, "key": key}, fh)
        fh.write("\n")
    os.chmod(CREDENTIALS_FILE, 0o600)


def cmd_login(a):
    # The whole point of this command is that the PERSON types the key, in a
    # terminal, with no echo. Piped stdin means something else is supplying
    # it — an assistant, a script — and that is the one path this skill forbids.
    if not sys.stdin.isatty():
        die("Run this yourself in a terminal; an assistant must never handle your key.")
    import getpass
    url = (a.url or os.environ.get("KEEPR_URL") or DEFAULT_URL).strip().rstrip("/")
    print(f"keepr at {url}. Paste the key from the web app (My Profile -> API keys); nothing is echoed.")
    key = getpass.getpass("API key: ").strip()
    if not KEY_SHAPE.match(key):
        die("That is not a keepr API key: it should be kpr_ followed by 43 letters and digits.\n"
            "Keys are shown once, when created; if this one was truncated on copy, revoke it and create another.")
    status, who = request("GET", "/api/user-info", key=key, url=url)
    fail_on(status, who, "verifying the key")
    write_credentials(url, key)
    print(f"key OK — acting as {who.get('email', '?')}")
    print(describe_scopes(who))
    print(f"stored in {CREDENTIALS_FILE} (mode 600). `keepr.py logout` removes it.")
    if os.environ.get("KEEPR_API_KEY") or os.environ.get("KEEPR_KEY"):
        print("note: KEEPR_API_KEY is set in this shell and takes precedence over the stored key.",
              file=sys.stderr)


def cmd_logout(a):
    try:
        os.remove(CREDENTIALS_FILE)
        print(f"removed {CREDENTIALS_FILE}. The key itself is still valid — revoke it in the web app if it should not be.")
    except FileNotFoundError:
        print(f"nothing stored at {CREDENTIALS_FILE}.")
    if os.environ.get("KEEPR_API_KEY") or os.environ.get("KEEPR_KEY"):
        print("note: KEEPR_API_KEY is still set in this shell.", file=sys.stderr)


# ------------------------------------------------------------------ reading

_SCHEMAS = {}   # collectionId -> schema, so a page of items reads its cards once


def schema_for(collection_id):
    """The schema, or None when this key cannot read the collection — a
    listing across collections must not die on the first one it cannot see."""
    if collection_id not in _SCHEMAS:
        status, body = request("GET", f"/api/collections/{collection_id}/schema")
        _SCHEMAS[collection_id] = body if status < 400 and isinstance(body, dict) else None
    return _SCHEMAS[collection_id]


def cards_by_id(schema):
    return {c.get("id"): c for c in (schema or {}).get("cards", [])}


# ISO 4217 minor-unit exponents that are not 2 (keepr-api utils/currency/
# registry.js is the source; a stored amount is an integer of minor units).
CURRENCY_EXPONENTS = {
    **{c: 0 for c in ("BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG",
                      "RWF", "UGX", "UYI", "VND", "VUV", "XAF", "XOF", "XPF")},
    **{c: 3 for c in ("BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND")},
    "CLF": 4, "UYW": 4,
}


def render_money(amount, code):
    """{amount: 1250, currency: 'USD'} -> '12.50 USD' (major units, the code)."""
    places = CURRENCY_EXPONENTS.get(code, 2)
    sign = "-" if amount < 0 else ""
    digits = str(abs(int(amount))).rjust(places + 1, "0")
    major = digits[:-places] + "." + digits[-places:] if places else digits
    return f"{sign}{major} {code}"


def render_value(value):
    """A stored value as one line. Measurements print as entered; money as
    its major amount and code; a location as its address; a list member-wise.
    Nothing is reformatted beyond that — the number of decimals, the date
    form, the casing are the user's."""
    if value is None or value == "" or value == [] or value == {}:
        return "(empty)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(render_value(v) for v in value)
    if isinstance(value, dict):
        if "value" in value and "unit" in value:
            return f"{value['value']} {value['unit']}"
        if isinstance(value.get("amount"), int) and isinstance(value.get("currency"), str):
            return render_money(value["amount"], value["currency"])
        if value.get("address"):
            return str(value["address"])
        if "lat" in value and "lng" in value:
            return f"{value['lat']}, {value['lng']}"
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def item_title(item, card):
    """displayValue is the server's own title; the batch-resolve projection
    omits it, so fall back to the card's title element, then the id."""
    if item.get("displayValue"):
        return str(item["displayValue"])
    elements = item.get("elements") or {}
    for el in (card or {}).get("elements", []):
        if el.get("isTitle") and elements.get(el.get("name")) not in (None, "", []):
            return render_value(elements[el["name"]])
    return f"(untitled) {item.get('_id')}"


def primary_date(item, card):
    """The card's resolved primary date, exactly as the schema reports it:
    created / updated / one element / an ordered list ending in a terminal."""
    pd = (card or {}).get("primaryDate") or {}
    entries = pd.get("entries") or ([pd] if pd.get("kind") else [{"kind": "created"}])
    elements = item.get("elements") or {}
    for entry in entries:
        kind = entry.get("kind")
        if kind == "created":
            value = item.get("createdAt")
        elif kind == "updated":
            value = item.get("updatedAt")
        elif kind == "element":
            value = elements.get(entry.get("name"))
        else:
            value = None
        if isinstance(value, list):
            value = next((v for v in value if v), None)
        if value:
            return str(value)[:10]
    return str(item.get("createdAt") or "")[:10]


def item_link(item):
    return f"{WEB_URL}/collections/{item.get('collection_id')}/items/{item.get('_id')}"


def kql_value(text):
    """A card key or id goes bare; anything the grammar could misread is quoted."""
    return text if re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*$", text) else '"' + text.replace('"', '\\"') + '"'


def cmd_items(a):
    collection = resolve_collection(a.collection)
    schema = schema_for(collection)
    if schema is None:
        die(f"Cannot read collection {collection}: it is not visible to this key "
            "(wrong id, or outside the key's collection allowlist).")
    cards = cards_by_id(schema)

    # --card becomes a KQL conjunct rather than card_id: a key needs no lookup
    # round-trip, and `card = key` also matches the card's descendants, which
    # is what a person means by "the books".
    q = (a.q or "").strip()
    if a.card:
        clause = f"card = {kql_value(a.card)}"
        q = f"({q}) and {clause}" if q else clause
    limit = max(1, min(a.limit, ITEMS_MAX_LIMIT))
    params = {"collection_id": collection, "limit": limit, "skip": max(0, a.skip)}
    if q:
        params["q"] = q
    if a.sort:
        params["sort_field"] = a.sort
    if a.desc:
        params["sort_direction"] = "desc"
    elif a.sort:
        params["sort_direction"] = "asc"
    status, items, headers = request("GET", "/api/items?" + urllib.parse.urlencode(params), with_headers=True)
    fail_on(status, items, "listing items")
    items = items or []
    try:
        total = int(headers.get("X-Total-Count"))
    except (TypeError, ValueError):
        total = len(items)

    if a.json:
        print(json.dumps({"total": total, "shown": len(items), "skip": params["skip"],
                          "q": q or None, "items": items}, indent=2, default=str))
        return

    name = (schema.get("collection") or {}).get("name") or collection
    head = f'{len(items)} of {total} items in "{name}"'
    if a.q:
        head += f" matching {a.q.strip()}"
    if a.card:
        head += f" card {a.card}"
    if params["skip"]:
        head += f" (skipping {params['skip']})"
    print(head)
    for item in items:
        card = cards.get(str(item.get("card_id")))
        key = card.get("key") if card else str(item.get("card_id"))
        print(f"  {item_title(item, card):<40} {key:<16} {str(item.get('_id')):<26} {primary_date(item, card)}")
    if total > params["skip"] + len(items):
        print(f"\n{total - params['skip'] - len(items)} more not shown. Next page: --skip {params['skip'] + len(items)}"
              " — or narrow with --q rather than paging a whole collection.")
    if items:
        print(f"Open one: {WEB_URL}/collections/{collection}/items/<id>")


def cmd_get(a):
    ids = [i.strip() for i in (a.id or []) if i.strip()]
    if not ids:
        die("--id is required (repeat it for several items).")
    bad = [i for i in ids if not HEX24.match(i)]
    if bad:
        die("Not item ids (24 hex characters): " + ", ".join(bad))
    if len(ids) > IDS_MAX:
        die(f"At most {IDS_MAX} ids per call; you gave {len(ids)}. Split them.")

    if len(ids) == 1:
        status, body = request("GET", f"/api/items/{ids[0]}")
        if status in (403, 404):
            found = []
        else:
            fail_on(status, body, "reading the item")
            found = [body] if isinstance(body, dict) else []
    else:
        status, body = request("GET", "/api/items?ids=" + ",".join(ids))
        fail_on(status, body, "reading the items")
        found = body if isinstance(body, list) else []

    if a.json:
        print(json.dumps(found, indent=2, default=str))
        return

    got = {str(i.get("_id")) for i in found}
    missing = [i for i in ids if i not in got]
    line = f"{len(found)} of {len(ids)} requested"
    if missing:
        # The API omits what the key cannot read and says nothing about why:
        # a wrong id, another collection, a private item. None of those is
        # "deleted", and the script must not let that word in.
        line += f" — {len(missing)} not readable by this key: " + ", ".join(missing)
    print(line)

    for item in found:
        card = cards_by_id(schema_for(str(item.get("collection_id")))).get(str(item.get("card_id")))
        key = card.get("key") if card else str(item.get("card_id"))
        print(f"\n{item_title(item, card)}  [{key}]  {item.get('_id')}")
        print(f"  {item_link(item)}")
        elements = dict(item.get("elements") or {})
        order = [el.get("name") for el in (card or {}).get("elements", [])]
        for name in order + [n for n in elements if n not in order]:
            if name in elements:
                print(f"  {name}: {render_value(elements.pop(name))}")
        if item.get("tags"):
            print(f"  tags: {', '.join(str(t) for t in item['tags'])}")
        if item.get("notes"):
            print(f"  notes: {item['notes']}")
        if isinstance(item.get("attachments"), list):
            print(f"  attachments: {len(item['attachments'])}")
        # The batch projection carries no timestamps; a single get does.
        stamps = [f"{k} {str(item[f])[:10]}" for k, f in (("created", "createdAt"), ("updated", "updatedAt")) if item.get(f)]
        if stamps:
            print("  " + " · ".join(stamps))


def cmd_search(a):
    q = (a.q or "").strip()
    if len(q) < 2:
        die("--q needs at least 2 characters.")
    params = {"q": q, "limit": max(1, min(a.limit, 50))}
    if a.types:
        params["types"] = a.types
    body = get("/api/search?" + urllib.parse.urlencode(params), "searching")
    if a.json:
        print(json.dumps(body, indent=2, default=str))
        return
    buckets = {k: body.get(k) or [] for k in ("collections", "cards", "items")}
    print(f'"{q}": ' + " · ".join(f"{k} {len(v)}" for k, v in buckets.items())
          + f" (each bucket capped at {params['limit']}; search is a substring match, not a query)")
    for c in buckets["collections"]:
        print(f"  collection  {str(c.get('_id')):<26} {c.get('name', '')}  [{access_label(c)}]")
    for c in buckets["cards"]:
        where = f" in collection {c.get('collection_id')}" if c.get("collection_id") else " (global)"
        print(f"  card        {str(c.get('_id')):<26} {c.get('name', '')} (key {c.get('key')}){where}")
    for item in buckets["items"]:
        card = cards_by_id(schema_for(str(item.get("collection_id")))).get(str(item.get("card_id")))
        key = card.get("key") if card else str(item.get("card_id"))
        print(f"  item        {str(item.get('_id')):<26} {item_title(item, card)}  [{key}]  {item_link(item)}")
    if buckets["items"]:
        print("Full values: keepr.py get --id <id>")


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(
        prog="keepr.py", description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Loop: schema → build rows → ingest --dry-run → fix → ingest")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="verify the key and list what it can reach")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("collections", help="list reachable collections")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_collections)

    p = sub.add_parser("schema", help="what this collection accepts")
    p.add_argument("--collection", required=True, help="id or name")
    p.add_argument("--card", help="only this card key")
    p.add_argument("--json", action="store_true", help="raw response, including the JSON Schema per card")
    p.set_defaults(fn=cmd_schema)

    p = sub.add_parser("template", help="a skeleton rows file for a card")
    p.add_argument("--collection", required=True)
    p.add_argument("--card", required=True)
    p.add_argument("--rows", type=int, default=1, help="how many blank rows")
    p.add_argument("--system", help="source.system for the rows")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_template)

    p = sub.add_parser("csv", help="CSV/TSV → rows file")
    p.add_argument("--file", required=True)
    p.add_argument("--card", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--collection", help="id or name — lets unmatched columns be reported now, not at the API")
    p.add_argument("--map", action="append", metavar="COLUMN=element", help="repeatable")
    p.add_argument("--id-column", help="the column holding a stable id, for idempotent re-runs")
    p.add_argument("--system", help="source.system (default csv-import)")
    p.add_argument("--ref", help="where the data came from (a URL or filename)")
    p.add_argument("--delimiter", default=",")
    p.set_defaults(fn=cmd_csv)

    p = sub.add_parser("ingest", help="validate or write a rows file")
    p.add_argument("--rows", required=True)
    p.add_argument("--collection", help="id or name; optional when the rows file names one")
    p.add_argument("--dry-run", action="store_true", help="validate everything, write nothing")
    p.add_argument("--mode", choices=["create", "upsert"], default="create")
    p.add_argument("--system", help="override source.system")
    p.add_argument("--ref", help="override source.ref")
    p.add_argument("--lenient", action="store_true",
                   help="drop unknown element names instead of failing the row")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("runs", help="recent ingest runs (audit)")
    p.add_argument("--collection", required=True)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_runs)

    p = sub.add_parser("attach", help="upload files onto items")
    p.add_argument("--item", help="attach to this one item id")
    p.add_argument("--file", action="append", help="repeatable; with --item")
    p.add_argument("--results", help="a <rows>.results.json from a committed ingest")
    p.add_argument("--dir", help="folder of files to match against those items")
    p.add_argument("--map", metavar="MAP.json", help='explicit {"externalId": ["file.jpg", ...]}')
    p.add_argument("--match", choices=["auto", "folder", "stem", "exact"], default="auto",
                   help="how a filename names its record (default auto: subfolder name, else filename)")
    p.add_argument("--dry-run", action="store_true", help="show the pairing, upload nothing")
    p.set_defaults(fn=cmd_attach)

    p = sub.add_parser("contract", help="the live write contract this deployment publishes")
    p.add_argument("--check", action="store_true",
                   help="compare it against what this skill documents and report the difference")
    p.set_defaults(fn=cmd_contract)

    p = sub.add_parser("create-card", help="propose or create card definitions")
    p.add_argument("--collection", required=True)
    p.add_argument("--spec", required=True)
    p.add_argument("--apply", action="store_true", help="actually create them (ask the user first)")
    p.set_defaults(fn=cmd_create_card)

    p = sub.add_parser("change-card", help="propose a change to an existing card, then apply it by token")
    p.add_argument("--collection", help="id or name (to propose)")
    p.add_argument("--card", help="the card's key or id (to propose)")
    p.add_argument("--spec", help='change.json: {"elements": [...], "remove": [...], "name": ...} (to propose)')
    p.add_argument("--apply", metavar="TOKEN", help="apply a stored proposal the user has seen")
    p.add_argument("--confirm", metavar="CARD_NAME",
                   help="the card's name typed back; required with --apply when the proposal is destructive")
    p.set_defaults(fn=cmd_change_card)

    p = sub.add_parser("login", help="store your key (run this yourself, in a terminal)")
    p.add_argument("--url", help="API base URL for self-hosted keepr (default https://api.keepr.cloud)")
    p.set_defaults(fn=cmd_login)

    p = sub.add_parser("logout", help="forget the stored key")
    p.set_defaults(fn=cmd_logout)

    p = sub.add_parser("items", help="list items: a count line, then one line per item")
    p.add_argument("--collection", required=True, help="id or name")
    p.add_argument("--q", help="a KQL filter, e.g. 'status = open and created > -30d' (references/kql.md)")
    p.add_argument("--card", help="only this card (key or id); also matches its descendants")
    p.add_argument("--sort", metavar="FIELD", help="primaryDate, createdAt, updatedAt, or an element name")
    p.add_argument("--desc", action="store_true", help="newest/largest first (the API default when --sort is absent)")
    p.add_argument("--limit", type=int, default=ITEMS_DEFAULT_LIMIT, help=f"default {ITEMS_DEFAULT_LIMIT}, max {ITEMS_MAX_LIMIT}")
    p.add_argument("--skip", type=int, default=0)
    p.add_argument("--json", action="store_true", help="raw: {total, shown, skip, q, items}")
    p.set_defaults(fn=cmd_items)

    p = sub.add_parser("get", help="one or more items in full")
    p.add_argument("--id", action="append", help=f"repeatable, up to {IDS_MAX}")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_get)

    p = sub.add_parser("search", help="free-text search across collections, cards and items")
    p.add_argument("--q", required=True, help="at least 2 characters; a substring, not a query")
    p.add_argument("--types", help="comma-separated subset of collections,cards,items")
    p.add_argument("--limit", type=int, default=20, help="per bucket, max 50")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_search)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
