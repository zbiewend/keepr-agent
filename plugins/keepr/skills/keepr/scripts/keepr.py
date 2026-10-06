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
  setup       --collection X --spec F    preview a setup (layouts, filters, quick adds, rules,
                                         notifications) and print its fingerprint; nothing changes
  setup       --collection X --spec F --apply --expect FINGERPRINT
                                         apply exactly what the person saw
  automations --collection X [--runs RULE] [--pause RULE]
                                         the collection's rules: state, maker, runs; pause one
  history     --item ID | --card KEY --collection X | --collection X
                                         who changed what, newest first (reads only)
  runs        --collection X             recent ingest runs, for audit
  request-upload --collection X --entries F
                                         ask the person for files through a link (they upload them)
  upload-status --id REQUEST             what has arrived for an upload request
  contract    [--check]                  the live write contract this deployment publishes
  update                                 update this skill to the latest release, or say how

The write loop the skill runs: schema -> build rows -> ingest --dry-run ->
fix -> ingest. Rows carrying `source.externalId` are idempotent: re-running
with --mode upsert updates what changed and reports the rest as `skipped`.

Exit status: 0 all good, 2 some rows failed validation, 1 the call itself
failed (bad key, unreachable collection, malformed file).

Staying current
  Every request names this copy (X-Keepr-Client: keepr-skill/<version> (<channel>)).
  Once a day the script asks the deployment which release is current, and when
  this copy is behind it prints a `KEEPR UPDATE:` note on stderr saying what to
  do. `keepr.py update` does it: a copy installed from the skill link rewrites
  itself from the deployment; a plugin or an upload to Claude says how instead.
  KEEPR_UPDATE_CHECK=off turns the daily check off.
"""

import argparse
import csv as csvmod
import hashlib
import json
import mimetypes
import os
import re
import secrets
import shutil
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import unicodedata
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

# This copy of the skill: its folder, its version, and how it reached the
# person — which decides how it is updated (utils/agentClients.js in keepr-api).
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
CHANNELS = ("plugin", "skill", "claude-ai", "extension", "local")
UPDATE_CHECK_FILE = os.path.join(CONFIG_DIR, "update-check.json")
UPDATE_BACKUPS_DIR = os.path.join(CONFIG_DIR, "skill-backups")
UPDATE_CHECK_EVERY = 24 * 3600
UPDATE_TIMEOUT = 5
# What `update` will write: the deployment's own allowlist (utils/docsUtils.js
# SERVABLE), and its caps.
UPDATE_EXTENSIONS = {".md", ".py", ".json", ".csv", ".sh", ".txt", ""}
UPDATE_MAX_FILE = 256 * 1024
UPDATE_MAX_TOTAL = 2 * 1024 * 1024
# What may sit in the skill folder beside the bundle without stopping an update.
UPDATE_TOLERATED = {"tests", "__pycache__", ".DS_Store"}


def is_keepr_skill():
    """Is the folder two levels above this script a keepr skill? Everything
    that names this copy, checks for updates or rewrites files hangs on this:
    a keepr.py copied into somebody's project (`myproject/scripts/keepr.py`
    beside `myproject/VERSION`) must never mistake that project for itself."""
    here = os.path.realpath(__file__)
    if here != os.path.realpath(os.path.join(SKILL_DIR, "scripts", "keepr.py")):
        return False
    try:
        with open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as fh:
            head = fh.read(4096)
    except OSError:
        return False
    return bool(re.match(r"^---\s*\n(?:.*\n)*?name:\s*keepr\s*\n", head))


def skill_version():
    if not is_keepr_skill():
        return None
    try:
        with open(os.path.join(SKILL_DIR, "VERSION"), encoding="utf-8") as fh:
            v = fh.read().strip()
        return v if re.match(r"^\d{1,4}\.\d{1,4}\.\d{1,4}$", v) else None
    except OSError:
        return None


def client_channel():
    """How this copy was installed. The launcher may say (KEEPR_CLIENT_CHANNEL);
    otherwise the folder does: a plugin's skill sits two levels below the
    plugin's own .claude-plugin/plugin.json (wherever CLAUDE_CONFIG_DIR puts
    it), and Claude mounts an uploaded skill under /mnt/skills/."""
    named = (os.environ.get("KEEPR_CLIENT_CHANNEL") or "").strip()
    if named in CHANNELS:
        return named
    plugin_root = os.path.dirname(os.path.dirname(SKILL_DIR))
    if os.path.isfile(os.path.join(plugin_root, ".claude-plugin", "plugin.json")):
        return "plugin"
    parts = SKILL_DIR.replace("\\", "/")
    if "/.claude/plugins/" in parts:
        return "plugin"
    if parts.startswith("/mnt/skills/"):
        return "claude-ai"
    return "skill"


def client_header():
    v = skill_version()
    return f"keepr-skill/{v} ({client_channel()})" if v else None


def version_tuple(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


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
    "private_not_allowed", "account_already_linked", "account_link_needs_access",
    "internal",
    # Tags: a row's `tags` by name, path or id (keepr resolves them and never
    # creates one), and the gate every tag passes.
    "unknown_tag", "ambiguous_tag", "private_tag_not_allowed",
    "restricted_tag", "rule_owned_tag", "too_many_tags", "invalid_tag_ids",
    # An upsert row that changes a locked record's tags, or whose tag write
    # lost a race twice (T2b's security review).
    "item_locked", "stale",
    # Only a person signed in to keepr may (a key never can) — a row that adds
    # or takes off a RESTRICTED tag, or sets an account link (or a field a
    # group built from records reads) that decides who is in such a group.
    # Ask them to do it in the app.
    "session_required",
    # Another item already holds the row's value of a unique element.
    "duplicate_value",
    # The data types second pass: a link off the URL rule, a value past its
    # element's length limit, a short text that does not fit its pattern.
    "invalid_url", "too_long", "pattern",
    # A strict lookup's filter does not offer the record the row names.
    "lookup_filtered_out",
    # A string a color element cannot read as a color (PR 9).
    "invalid_color",
    # The file element (PR 10b): an import row may only re-send a file value
    # unchanged (file_not_settable); the rest are the item form's binding codes.
    "file_not_settable", "file_not_found", "file_already_used", "attachments_disabled",
    "file_too_large", "file_wrong_kind", "too_many_files",
    # A bound attachment's ✕ (409): the value is cleared with an item write.
    "attachment_in_use",
    # A date or date-time list past 1,000 entries (keepr-api PR AK, review F2).
    "too_many_dates",
    # Not a row status: the hint.code beside a card_not_allowed whose card
    # belongs to a sub-collection (the message names it and its ingest path).
    "card_in_sub_collection",
}
KNOWN_ELEMENT_TYPES = {
    "text-small", "text-large", "rich-text", "choice", "number", "decimal",
    "integer", "boolean", "date", "date-time", "time", "url", "phone", "email",
    "location", "rating", "card-lookup", "measurement", "user", "currency",
    "color", "file",
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


def request(method, path, body=None, headers=None, raw=None, key=None, url=None, with_headers=False,
            anonymous=False, timeout=None):
    """One API call. Returns (status, parsed-body) — or (status, body, headers)
    with `with_headers`, for the one endpoint that answers in a header. Never
    raises on an HTTP error: the caller decides whether a 404 is fatal or just
    an answer. `key`/`url` override the configured ones for `login`, which
    verifies a key before anything has been stored."""
    hdrs = {"Accept": "application/json"}
    if not anonymous:
        hdrs["Authorization"] = f"Bearer {key or api_key()}"
    if client_header():
        hdrs["X-Keepr-Client"] = client_header()
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
            with urllib.request.urlopen(req, timeout=timeout or TIMEOUT) as resp:
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
    426: "this copy of the skill is too old for keepr (client_too_old); run `keepr.py update`, "
         "or follow the guide link in the message",
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

def _clause_value(v):
    if isinstance(v, list):
        return "(" + ", ".join(_clause_value(x) for x in v) + ")"
    if isinstance(v, dict) and "amount" in v:
        return f"{v.get('amount')} {v.get('currency', '')}".strip()
    return v if isinstance(v, str) else json.dumps(v)


def describe_required_when(clauses):
    """`requiredWhen` as the condition it is — every clause must hold (required.js)."""
    ops = {"eq": "=", "ne": "!=", "gt": ">", "lt": "<"}
    out = []
    for c in clauses:
        el, op, v = c.get("element", "?"), c.get("op"), c.get("value")
        if op in ops:
            out.append(f"{el} {ops[op]} {_clause_value(v)}")
        elif op in ("in", "not-in"):
            vals = _clause_value(v if isinstance(v, list) else [v])
            out.append(f"{el} {'in' if op == 'in' else 'not in'} {vals}")
        elif op == "empty":
            out.append(f"{el} is empty")
        elif op == "not-empty":
            out.append(f"{el} is not empty")
        else:
            out.append(f"{el} {op} {_clause_value(v)}")
    return " and ".join(out)


def is_multi_choice(el):
    """A choice element set to "Allow multiple": its value is a list of choice values."""
    return el.get("dataType") == "choice" and bool(el.get("allowMultiple"))


def split_choices(value):
    """One CSV cell as the list a multi-choice element takes: split on ";", each
    piece trimmed, empties dropped — the same reading ingest gives the string."""
    return [piece.strip() for piece in str(value).split(";") if piece.strip()]


def shown_as(el, n=42):
    """How a number element spells n: its prefix, then zero-padded digits (elementFormat/number.js)."""
    width = el.get("leadingZeros")
    digits = str(n).zfill(width) if isinstance(width, int) and width > 0 else str(n)
    return f"{el.get('prefix') or ''}{digits}"


# An element's id (KPR-168): eight [a-z0-9] characters, minted by keepr and
# unique across the platform. Stored KQL names an element by it, `#k7f3q2xa` —
# a lookup's filter, a chart's, a saved filter — whatever the element is called
# now. `schema` prints each element's id, and names the ids a lookup's filter
# holds (KPR-238): the filter as keepr stores it, the element beneath it.
ELEMENT_ID_RE = re.compile(r"[a-z0-9]{8}")
_ELEMENT_ID_RUN_RE = re.compile(r"[A-Za-z0-9_-]*")


def element_ids_in(kql):
    """The `#id`s a KQL text names, in order, once each. Never inside quoted
    text — a quoted "#k7f3q2xa" is text, and \\" and \\\\ are its only
    escapes — and never a `#` that does not open exactly eight lower-case
    letters or digits (utils/kql/kql.js reads the same)."""
    if not isinstance(kql, str) or "#" not in kql:
        return []
    out, i, n = [], 0, len(kql)
    while i < n:
        ch = kql[i]
        if ch == '"':
            i += 1
            while i < n and kql[i] != '"':
                i += 2 if kql[i] == "\\" else 1
            i += 1
            continue
        if ch == "#":
            run = _ELEMENT_ID_RUN_RE.match(kql, i + 1).group(0)
            if ELEMENT_ID_RE.fullmatch(run) and "#" + run not in out:
                out.append("#" + run)
            i += 1 + len(run)
            continue
        i += 1
    return out


def element_vocabulary(cards):
    """Element id -> {name, label, cards}: every id the schema's cards hold. One
    id on several cards (a parent's element, a set's) is one element."""
    vocab = {}
    for card in cards or []:
        holder = card.get("key") or card.get("id") or "?"
        for el in card.get("elements") or []:
            el_id = el.get("id")
            if not isinstance(el_id, str) or not ELEMENT_ID_RE.fullmatch(el_id):
                continue
            if el_id in vocab:
                if holder not in vocab[el_id]["cards"]:
                    vocab[el_id]["cards"].append(holder)
                continue
            name = el.get("name") or ""
            label = el["label"] if isinstance(el.get("label"), str) and el["label"] else name
            vocab[el_id] = {"name": name, "label": label, "cards": [holder]}
    return vocab


def describe_element_id(el_id, vocab):
    """`#k7f3q2xa is element status ("State") on card task` — the label only
    where it says more than the name; an id the schema lacks said as such."""
    bare = el_id.lstrip("#")
    hit = vocab.get(bare)
    if not hit:
        return f"#{bare} is no element this collection's schema lists (removed, or on a card this key cannot read)"
    label = f' ("{hit["label"]}")' if hit["label"].strip().lower() != hit["name"].strip().lower() else ""
    cards = hit["cards"]
    held = ", ".join(cards[:4]) + (f" and {len(cards) - 4} more" if len(cards) > 4 else "")
    return f"#{bare} is element {hit['name']}{label} on card{'' if len(cards) == 1 else 's'} {held}"


def describe_element(el, vocab=None):
    """One line per element: what the write path will accept for it — and,
    given the schema's ids, a line naming each element its lookup filter names."""
    el_id = el.get("id")
    bits = ([f"#{el_id}"] if isinstance(el_id, str) and ELEMENT_ID_RE.fullmatch(el_id) else []) + [el.get("dataType", "?")]
    if el.get("required"):
        bits.append("required")
    elif el.get("requiredWhen"):
        # The condition, never just "conditionally": a row the condition holds
        # for is refused without it, and a writer has to know which rows those are.
        bits.append("required when " + describe_required_when(el["requiredWhen"]))
    if el.get("isTitle"):
        bits.append("title")
    if el.get("sequence"):
        bits.append(f"numbered by keepr — do not send; shown as {shown_as(el)}, matched by the number (42)")
    elif el.get("driven"):
        bits.append("driven — do not send")
    elif el.get("prefix") or el.get("leadingZeros"):
        bits.append(f"shown as {shown_as(el)} for 42 — send the number")
    # A percent element stores the number a person reads (ruling D9): 12.5
    # means 12.5 %, so a fraction would land 100 times too small.
    if el.get("percent") is True:
        bits.append("a percent — send the number shown (12.5 for 12.5 %), never a fraction")
    if el.get("thousands") is True:
        bits.append("shown grouped (1,234,567) — send the plain number")
    if el.get("allowMultiple"):
        bits.append("list")
    if el.get("choices"):
        def choice(c):
            value, label = c.get("value", ""), c.get("label")
            return f'{value} ("{label}")' if label and label.strip().lower() != str(value).strip().lower() else value
        # A choice that allows multiple values takes a list of them (or one
        # string separated by ";"), stored in the order of this list.
        lead = "any of" if is_multi_choice(el) else "one of"
        bits.append(f"{lead}: " + ", ".join(choice(c) for c in el["choices"]))
    if el.get("dataType") == "card-lookup":
        bits.append(f"links to card '{el.get('lookupCardKey') or el.get('lookupCardId')}'")
        # The picker's filter: KQL over that card's items. Strict means a
        # record outside it is refused (lookup_filtered_out); a value the item
        # already holds is kept either way.
        if el.get("filter"):
            bits.append(("only records where " if el.get("strict") else "preferring records where ") + el["filter"])
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
    if isinstance(el.get("decimals"), int):
        bits.append(f"{el['decimals']} decimals")
    if el.get("nonNegative"):
        bits.append("not negative")
    if el.get("precision"):
        bits.append(f"precision {el['precision']}")
    if el.get("help"):
        bits.append(f"help: {el['help']}")
    line = f"    {el.get('name', '?'):<26} {' · '.join(bits)}"
    if vocab is not None and el.get("filter"):
        line += "".join(f"\n      where {describe_element_id(i, vocab)}" for i in element_ids_in(el["filter"]))
    return line


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
    vocab = element_vocabulary(cards)
    if not cards:
        print("\n  No cards are writable here for this key.")
    for card in cards:
        if a.card and card.get("key") != a.card and card.get("id") != a.card:
            continue
        parent_card = next((c for c in cards if c.get("id") == card.get("parentCardId")), None)
        parent = (f" (child of '{parent_card.get('key')}')" if parent_card
                  else f" (child of {card.get('parentCardId')})") if card.get("parentCardId") else ""
        print(f"\n  card '{card.get('key')}' — {card.get('name')}  [id {card.get('id')}]{parent}")
        if card.get("itemTags") in ("chosen", "every"):
            # Items used as tags are never listed by name (a title is only for
            # readers of that item): say how to find one.
            print(f"    {'every item' if card['itemTags'] == 'every' else 'chosen items'} of this card can be used as tags — "
                  "find one with `search --q <title> --types tags` and send its id in a row's \"tags\"")
        for el in card.get("elements", []):
            print(describe_element(el, vocab))
    print_tag_vocabulary(schema.get("tags"))
    wc = schema.get("writeContract", {})
    print(f"\n  write contract: up to {wc.get('maxBatch', MAX_BATCH)} rows per call · "
          f"idempotent on {wc.get('idempotency')} · unknown element names are refused by default")
    if wc.get("contractVersion"):
        print(f"  contract version {wc['contractVersion']} (published at {wc.get('contract', '/api/docs/contract')})")
    unknown = sorted({el.get("dataType") for card in cards for el in card.get("elements", [])}
                     - KNOWN_ELEMENT_TYPES - {None})
    if unknown:
        print("\n" + STALE_HINT % ("element types", ", ".join(unknown)), file=sys.stderr)


def print_tag_vocabulary(tags):
    """The collection's tags, as a row's `tags` names them. Absent on an older
    keepr, which lists none."""
    if not isinstance(tags, list):
        return
    if not tags:
        print("\n  tags: none. keepr never creates a tag from a row — if the user wants one, they add it in keepr.")
        return
    print("\n  tags — name them in a row's \"tags\" like this (the path when two share a name); keepr never creates one:")
    for tag in tags:
        bits = []
        if tag.get("aliases"):
            bits.append("also: " + ", ".join(tag["aliases"]))
        if tag.get("restricted"):
            bits.append("restricted — only a manager, signed in to keepr, puts it on or takes it off; never from here")
        rule = tag.get("rule") or {}
        if rule.get("strict"):
            bits.append("applied by a rule only — never send it")
        elif tag.get("rule"):
            bits.append("a rule applies it too")
        if tag.get("inheritedFrom"):
            bits.append(f"from \"{tag['inheritedFrom'].get('name')}\", the collection above")
        print(f"    {tag.get('path') or tag.get('name')}  [id {tag.get('id')}]" + (f"  ({'; '.join(bits)})" if bits else ""))


# ------------------------------------------------------------------ template

def placeholder(el):
    """A value that says what the element wants and, left unfilled, fails a dry
    run loudly — better than a plausible default that silently writes nonsense."""
    kind = el.get("dataType")
    if el.get("choices"):
        values = "|".join(c.get("value", "") for c in el["choices"])
        return [f"<any of: {values}>"] if is_multi_choice(el) else f"<one of: {values}>"
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
        "color": "<#rrggbb, e.g. #1f6feb>",
    }.get(kind, "<text>")
    return [one] if el.get("allowMultiple") else one


def cmd_template(a):
    collection = resolve_collection(a.collection)
    card = find_card(load_schema(collection), a.card)
    elements = {}
    for el in card.get("elements", []):
        if el.get("driven"):
            continue           # system-owned: sending one is a refused row in strict mode
        if el.get("dataType") == "file":
            continue           # files are attached (attach-file), never imported: file_not_settable
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
    multi = set()
    if a.collection:
        card = find_card(load_schema(resolve_collection(a.collection)), a.card)
        known = {el["name"] for el in card.get("elements", []) if not el.get("driven")}
        # A choice that allows multiple values takes a list: a cell holding
        # "welding; rigging" is sent as ["welding", "rigging"].
        multi = {el["name"] for el in card.get("elements", []) if is_multi_choice(el)}

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
                elements[name] = split_choices(value) if name in multi else value
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


def bad_tags(rows):
    """Rows whose `tags` keepr would refuse for its shape: not a list of
    non-empty strings (names, paths or ids). What the names MEAN is keepr's to
    judge, per row — it resolves them and never creates a tag."""
    bad = []
    for i, row in enumerate(rows):
        tags = row.get("tags")
        if tags is None:
            continue
        if not isinstance(tags, list) or any(not isinstance(t, str) or not t.strip() for t in tags):
            bad.append(i)
    return bad


def choose_import_id(a, results_path):
    """One import, one id (keepr lists its batches as one and a person can undo
    it from Settings → Imports). --import-id wins; otherwise an import that is
    not finished — the last run of these rows was a dry run, or a commit with
    failures to fix and re-send — keeps its id; anything else is a new import."""
    if a.import_id:
        if not re.match(r"^[A-Za-z0-9._-]{1,64}$", a.import_id):
            die("--import-id is 1-64 letters, digits, dots, dashes or underscores")
        return a.import_id
    try:
        with open(results_path, encoding="utf-8") as fh:
            last = json.load(fh)
        if last.get("importId") and (last.get("dryRun") or last.get("failures")):
            return last["importId"]
    except (OSError, ValueError, AttributeError):
        pass
    return f"imp-{time.strftime('%Y%m%d')}-{secrets.token_hex(3)}"


def refs_in(value, out):
    """Every {"$ref": id} in a row's elements — arrays and nested values
    included — into `out`, a dict used as an ordered set."""
    if isinstance(value, list):
        for v in value:
            refs_in(v, out)
    elif isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            out[ref.strip()] = None
        else:
            for v in value.values():
                refs_in(v, out)
    return out


def carried_for(batch, would_create):
    """The rows earlier batches of this dry run would create that this batch
    refers to or repeats — never the whole import, which keepr caps and does
    not need."""
    if not would_create:
        return []
    wanted = {}
    for row in batch:
        refs_in(row.get("elements") or {}, wanted)
        external = (row.get("source") or {}).get("externalId")
        if external:
            wanted[str(external).strip()] = None
    # would_create: externalId -> {system: entry}, so a batch costs its own
    # size, not the whole import's.
    return [entry for external in wanted for entry in would_create.get(external, {}).values()]


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
    shapeless = bad_tags(rows)
    if shapeless:
        die(f"{len(shapeless)} row(s) have \"tags\" that are not a list of tag names, paths or ids "
            f"(first: row {shapeless[0]}). Write them like [\"Urgent\", \"Genre/Sci-fi\"], from the tags `schema` lists.")
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

    out = re.sub(r"\.json$", "", a.rows) + ".results.json"
    import_id = choose_import_id(a, out)
    batches = [rows[i:i + MAX_BATCH] for i in range(0, len(rows), MAX_BATCH)]
    totals = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
    results = {"collection": collection, "dryRun": a.dry_run, "mode": a.mode, "importId": import_id,
               "runs": [], "items": {}, "failures": [], "notes": [], "warnings": []}

    # A dry run writes nothing, so a later batch cannot see the rows an earlier
    # one only validated: every $ref to one would come back ref_unresolved.
    # keepr is told which (wouldCreate) — only the ones a batch refers to or
    # repeats.
    carry = a.dry_run and len(batches) > 1
    would_create = {}

    for n, batch in enumerate(batches, 1):
        body = {"mode": a.mode, "dryRun": a.dry_run, "strict": not a.lenient, "items": batch}
        if source:
            body["source"] = source
        if import_id:
            body["importId"] = import_id
        carried = carried_for(batch, would_create) if carry else []
        if carried:
            body["wouldCreate"] = carried
        status, res = request("POST", f"/api/collections/{collection}/ingest", body)
        if status == 400:
            # A keepr older than this skill: its envelope refuses a field it does
            # not know. Send the batch without the ones it named.
            said = res.get("message", "") if isinstance(res, dict) else str(res)
            drop_id = bool(import_id) and "importId" in json.dumps(res)
            drop_carried = bool(carried) and '"wouldCreate" is not allowed' in said
            if drop_id:
                import_id = results["importId"] = None
                del body["importId"]
            if drop_carried:
                carry = False
                del body["wouldCreate"]
            if drop_id or drop_carried:
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
            if row.get("notes"):
                results["notes"].append({"batch": n, "index": row.get("index"),
                                         "externalId": external, "notes": row["notes"]})
            # A row that landed but left a tag off (tag_dropped: deleted since).
            if row.get("warnings") and row.get("status") != "failed":
                results["warnings"].append({"batch": n, "index": row.get("index"),
                                            "externalId": external, "warnings": row["warnings"]})
            index = row.get("index")
            if carry and row.get("status") == "would-create" and external and isinstance(index, int) and index < len(batch):
                sent = batch[index]
                system = (sent.get("source") or {}).get("system")
                created_at = (sent.get("source") or {}).get("createdAt")
                entry = {"card": sent.get("card"), "externalId": external}
                if system:
                    entry["system"] = system
                if created_at:
                    entry["createdAt"] = created_at
                would_create.setdefault(external, {})[system or source.get("system")] = entry
        print(f"batch {n}/{len(batches)}: "
              + " · ".join(f"{k} {summary.get(k, 0)}" for k in totals)
              + f" · runId {res.get('runId')}")
        # A committed batch with failures stops here: later rows may reference a
        # row that never landed, and half-linked data is worse than a short import.
        if summary.get("failed") and not a.dry_run:
            print("  stopping — a failed row may be the parent of later rows. "
                  "Fix the rows and re-run with --mode upsert.", file=sys.stderr)
            break

    with open(out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)

    print(("DRY RUN — nothing was written. " if a.dry_run else "")
          + "totals: " + " · ".join(f"{k} {v}" for k, v in totals.items()) + f" → {out}")
    if import_id:
        if a.dry_run:
            print(f"import {import_id} — the commit of these rows reuses it.")
        elif totals["created"] or totals["updated"]:
            print(f"import {import_id} — if it was a mistake, someone who manages the collection can undo it "
                  "from its Settings → Imports in the web app.")
    for failure in results["failures"][:25]:
        codes = "; ".join(f"{e.get('element') or '-'}: {e.get('code')} — {e.get('message')}" + candidates_note(e)
                          for e in failure["errors"])
        label = failure["externalId"] or f"batch {failure['batch']} row {failure['index']}"
        print(f"  FAILED {label}: {codes}")
    if len(results["failures"]) > 25:
        print(f"  … {len(results['failures']) - 25} more in {out}")
    if (a.dry_run and len(batches) > 1 and not carry
            and any(e.get("code") == "ref_unresolved" for f in results["failures"] for e in f["errors"])):
        print("  CAVEAT: this keepr cannot carry a dry run across batches. A ref_unresolved to a row of an "
              "EARLIER batch is expected here and resolves at commit; one to a row nowhere in the file is real.")
    # Rows that landed without doing all they asked — e.g. an upsert's
    # source.createdAt, which is fixed when the item is created.
    for noted in results["notes"][:25]:
        label = noted["externalId"] or f"batch {noted['batch']} row {noted['index']}"
        print(f"  NOTE {label}: {'; '.join(noted['notes'])}")
    if len(results["notes"]) > 25:
        print(f"  … {len(results['notes']) - 25} more notes in {out}")
    for warned in results["warnings"][:25]:
        label = warned["externalId"] or f"batch {warned['batch']} row {warned['index']}"
        print(f"  WARNING {label}: {'; '.join(w.get('message') or w.get('code', '') for w in warned['warnings'])}")
    if len(results["warnings"]) > 25:
        print(f"  … {len(results['warnings']) - 25} more warnings in {out}")

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


def candidates_note(error):
    """An ambiguous tag name's candidates, so the next run can send the path."""
    candidates = error.get("candidates") or []
    if not candidates:
        return ""
    paths = []
    for c in candidates:
        path = c.get("path")
        paths.append(("/".join(path) if isinstance(path, list) else str(path)) + f" ({c.get('tagId')})")
    return " [could be: " + ", ".join(paths) + "]"


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
              f"{' DRY' if run.get('dryRun') else ''}"
              f"{'  import ' + run['importId'] if run.get('importId') else ''}"
              f"{'  UNDONE' if run.get('undone') else ''}  "
              + " · ".join(f"{k} {v}" for k, v in summary.items()))


# ------------------------------------------------------------------ upload requests

def cmd_request_upload(a):
    """Ask the PERSON for files they hold (KPR-183): POST /api/upload-requests
    with the items waiting and, per entry, the file's name or a name pattern;
    keepr returns a link they open to drop the files. The bytes never pass
    through this script — use it for files on their phone or computer that the
    agent cannot read, or that are too big to carry."""
    collection = resolve_collection(a.collection)
    try:
        with open(a.entries, encoding="utf-8") as fh:
            entries = json.load(fh)
    except (OSError, ValueError) as exc:
        die(f"--entries must be a JSON file holding a list of entries: {exc}")
    if isinstance(entries, dict):
        entries = entries.get("entries")
    if not isinstance(entries, list) or not entries:
        die('--entries must hold a non-empty list like [{"item_id": "...", "name": "R-1.pdf"}]')
    body = {"collection_id": collection, "entries": entries}
    if a.note:
        body["note"] = a.note
    if a.days is not None:
        body["expiresInDays"] = a.days
    status, res = request("POST", "/api/upload-requests", body)
    if status == 400 and isinstance(res, dict) and res.get("code") == "entries_refused":
        print(f"keepr refused {res.get('failureCount', len(res.get('failures', [])))} entries; nothing was created "
              "(it is all or nothing):", file=sys.stderr)
        for f in res.get("failures", [])[:50]:
            print(f"  #{f.get('index')} ({f.get('itemId') or 'no item'}): {f.get('message')}", file=sys.stderr)
        sys.exit(2)
    fail_on(status, res, "creating the upload request")
    if a.json:
        print(json.dumps(res, indent=2, default=str))
        return
    print(f"upload request {res.get('_id')} for {res.get('entries')} file(s), until {str(res.get('expiresAt', ''))[:10]}")
    print(f"give the person this link: {res.get('url')}")
    print(f"then: keepr.py upload-status --id {res.get('_id')}")


def cmd_upload_status(a):
    if not HEX24.match(a.id or ""):
        die("--id is the 24-hex id request-upload printed")
    status, res = request("GET", f"/api/upload-requests/{a.id}")
    if status == 404:
        die("no upload request with that id for this account: it expired, was withdrawn, or is someone else's")
    fail_on(status, res, "reading the upload request")
    if a.json:
        print(json.dumps(res, indent=2, default=str))
        return
    counts = res.get("counts", {})
    print(f"{counts.get('fulfilled', 0)} of {counts.get('entries', 0)} file(s) attached")
    waiting = [e for e in res.get("entries", []) if not e.get("fulfilled")]
    for e in waiting:
        want = e.get("name") or e.get("pattern") or "any file"
        print(f"  waiting  {e.get('title') or e.get('itemId')}{' (item gone)' if e.get('gone') else ''}  {want}")
    if waiting:
        print(f"the link still works until {str(res.get('expiresAt', ''))[:10]}: {res.get('url')}")


# ------------------------------------------------------------------ attach

# Several photos of one subject are usually named for it with a counter:
# molly-blake.jpg, molly-blake-2.jpg, molly-blake_3.JPG, "molly blake (4).jpg".
# Everything after the last separator, if it is only digits, is the counter.
# [0-9], not \d (Unicode digits in Python, ASCII in JavaScript); \s stays
# Unicode on both sides (a no-break space before the counter). keepr-mcp's
# keysFor is the same pattern.
COUNTER_SUFFIX = re.compile(r"[\s._-]*(?:\(\s*[0-9]+\s*\)|[0-9]+)$")


def external_id_for(file_path, base, mode):
    """Which record a file belongs to. `folder` uses the containing directory
    (photos/molly-blake/*.jpg), `exact` the whole filename stem, `stem` the stem
    with a trailing counter removed. Default tries folder first, then stem —
    the two layouts people actually have."""
    # NFC: macOS hands out decomposed names (Cafe + U+0301); an id typed or
    # imported is composed. Both sides fold the same way (KPR-182).
    rel = unicodedata.normalize("NFC", os.path.relpath(file_path, base))
    parent = os.path.dirname(rel)
    stem = os.path.splitext(os.path.basename(rel))[0]
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


def candidate_ids(file_path, base, mode):
    """The ids a file might name, most specific first; the first one an item has
    wins. In `auto`, a file inside a subfolder names that folder and nothing else
    (a folder that names no record leaves its files unmatched — never guessed
    from camera numbers like 1.jpg); a file at the top names its whole stem, then
    its stem without a trailing counter, so R-1042.pdf finds "R-1042" before the
    counter rule reads it as "R" plus 1042. keepr-mcp's keysFor
    (mcp/src/folderMatch.ts) is the same rule; both run tests/attach_vectors.json
    (KPR-182)."""
    if mode != "auto":
        found = external_id_for(file_path, base, mode)
        return [found] if found else []
    if os.path.dirname(os.path.relpath(file_path, base)):
        return [external_id_for(file_path, base, "folder")]
    out = []
    for m in ("exact", "stem"):
        found = external_id_for(file_path, base, m)
        if found and found not in out:
            out.append(found)
    return out


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
    # keepr serializes the name as `originalName`; reading only filename/name
    # meant the skip never fired against a real server (KPR-182 review).
    return {str(r.get("originalName") or r.get("filename") or r.get("name") or "") for r in rows if isinstance(r, dict)}


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
    # NFC, like the filenames (external_id_for): an id copied from a Mac
    # filename is decomposed (KPR-182 review).
    items = {unicodedata.normalize("NFC", k): v for k, v in (results.get("items") or {}).items()}
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
            external = unicodedata.normalize("NFC", external)
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
        candidates = candidate_ids(full, a.dir, a.match)
        external = next((c for c in candidates if c in items), None)
        if external:
            pairs.append((external, items[external], full))
        else:
            unmatched.append((full, "no item matches " + " or ".join(repr(c) for c in candidates)
                              if candidates else "could not derive an id"))
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


# ------------------------------------------------------------------ updates

def code_origin_ok(url):
    """Code is fetched over https only — or from this machine, for a self-hoster."""
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" or parsed.hostname in ("127.0.0.1", "localhost", "::1")


def fetch_public(path, timeout=UPDATE_TIMEOUT, code=False):
    """One GET of a public /api/docs resource, or None — no retries, no exit.
    The update check must never be why a command is slow or fails. `code`
    also refuses an answer that arrived over plain http after a redirect."""
    header = client_header()
    req = urllib.request.Request(base_url() + path, headers={
        "Accept": "application/json", **({"X-Keepr-Client": header} if header else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if code and not code_origin_ok(resp.geturl()):
                return None
            doc = json.loads(resp.read().decode("utf-8"))
            return doc if isinstance(doc, dict) else None
    except Exception:  # noqa: BLE001 — offline, 404 on an older deployment, bad JSON: all mean "say nothing"
        return None


def _strings(value):
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def channel_steps(clients):
    """This channel's update steps from the clients doc, shape-checked: a newer
    deployment may change the payload, and a check must never crash a command."""
    channels = clients.get("channels") if isinstance(clients, dict) else None
    raw = channels.get(client_channel()) if isinstance(channels, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    out = {
        "name": raw["name"] if isinstance(raw.get("name"), str) else "the keepr skill",
        "how": raw.get("how") if raw.get("how") in ("automatic", "assistant", "manual") else "manual",
        "commands": _strings(raw.get("commands")),
        "steps": _strings(raw.get("steps")),
    }
    for field in ("tip", "guide"):
        if isinstance(raw.get(field), str):
            out[field] = raw[field]
    return out


def update_status(clients):
    """(current, latest, channel steps) — or None when there is nothing to say."""
    current = skill_version()
    latest = clients.get("latest") if isinstance(clients, dict) else None
    latest = latest.get("skill") if isinstance(latest, dict) else None
    if not current or not isinstance(latest, str) or not re.match(r"^\d{1,4}\.\d{1,4}\.\d{1,4}$", latest):
        return None
    return current, latest, channel_steps(clients)


def self_update_blocker():
    """Why `keepr.py update` cannot rewrite this copy, or None when it can."""
    if client_channel() != "skill":
        return "this copy is not ours to rewrite"
    if not is_keepr_skill():
        return "this folder is not a keepr skill"
    if not code_origin_ok(base_url()):
        return "the skill is code, and code is only fetched over https"
    probe = SKILL_DIR
    while True:
        if os.path.exists(os.path.join(probe, ".git")):
            return f"it is inside a git checkout ({probe}); update it there"
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    if not os.access(SKILL_DIR, os.W_OK):
        return f"{SKILL_DIR} is not writable here"
    return None


def update_notice(clients):
    """The KEEPR UPDATE note, or None when this copy is current."""
    status = update_status(clients)
    if not status:
        return None
    current, latest, steps = status
    if version_tuple(current) >= version_tuple(latest):
        return None
    summary = clients.get("summary") if isinstance(clients.get("summary"), str) else None
    lines = [f"KEEPR UPDATE: {steps['name']} is out of date (keepr skill {current}; {latest} is out"
             + (f": {summary})." if summary else ")."),
             "Tell the person once, in one short sentence, after answering what they asked."]
    can_run = steps["how"] == "assistant" and steps["commands"] \
        and (client_channel() != "skill" or self_update_blocker() is None)
    if can_run:
        lines.append("You can update it yourself: run " + ", then ".join(f"`{c}`" for c in steps["commands"])
                     + ". Ask first if your environment needs permission to run commands.")
        if steps["steps"]:
            lines.append("Then tell them: " + " ".join(steps["steps"]))
    elif steps["steps"] and steps["how"] != "assistant":
        lines.append("Give them these steps: " + " ".join(f"{i}. {t}" for i, t in enumerate(steps["steps"], 1)))
    if steps.get("tip"):
        lines.append(steps["tip"])
    if steps.get("guide"):
        lines.append(("How to update: " if not can_run and steps["how"] == "assistant" else "More: ") + steps["guide"])
    return "\n".join(lines)


def daily_update_check():
    """Once a day, ask the deployment which release is current and say so on
    stderr when this copy is behind. Remembered in ~/.config/keepr so every
    other command in the day costs nothing. Never raises: whatever goes wrong
    here, the command the person asked for is what matters."""
    try:
        if (os.environ.get("KEEPR_UPDATE_CHECK") or "").strip().lower() in ("off", "0", "false", "no"):
            return
        if not is_keepr_skill():
            return
        now = time.time()
        try:
            with open(UPDATE_CHECK_FILE, encoding="utf-8") as fh:
                last = json.load(fh)
            if now - float(last.get("checkedAt") or 0) < UPDATE_CHECK_EVERY and last.get("url") == base_url():
                return
        except Exception:  # noqa: BLE001 — a missing or mangled file just means "check now"
            pass
        clients = fetch_public("/api/docs/clients")
        try:
            os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
            with open(UPDATE_CHECK_FILE, "w", encoding="utf-8") as fh:
                json.dump({"checkedAt": now, "url": base_url()}, fh)
        except OSError:
            pass
        notice = update_notice(clients)
        if notice:
            print("\n" + notice, file=sys.stderr)
    except Exception:  # noqa: BLE001
        return


def safe_bundle_path(rel):
    """A path from the deployment's bundle that may be written under the skill
    folder — relative, inside it, and of a type the deployment itself serves."""
    if not isinstance(rel, str) or not rel or len(rel) > 200:
        return False
    if rel.startswith(("/", "\\")) or "\\" in rel or ":" in rel:
        return False
    parts = rel.split("/")
    if any(p in ("", ".", "..") or p.startswith(".") for p in parts):
        return False
    stem = parts[-1].split(".")[0].upper()
    if stem in ("CON", "PRN", "AUX", "NUL") or re.match(r"^(COM|LPT)\d$", stem):
        return False
    return os.path.splitext(rel)[1] in UPDATE_EXTENSIONS


def _skill_files(root):
    """Every file under the skill folder, as bundle-style relative paths —
    skipping what the bundle never carries (tests/, caches)."""
    out = set()
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            dirnames[:] = [d for d in dirnames if d not in UPDATE_TOLERATED]
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(".pyc") or name == ".DS_Store":
                continue
            rel = name if rel_dir == "." else f"{rel_dir.replace(os.sep, '/')}/{name}"
            out.add(rel)
    return out


def _write_file(root, rel, text):
    """Write one file atomically (temp file + os.replace), scripts executable."""
    target = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), prefix=".keepr-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        if rel.endswith((".py", ".sh")):
            os.chmod(tmp, 0o755)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def cmd_update(a):
    clients = fetch_public("/api/docs/clients", timeout=30)
    if not clients:
        die(f"{base_url()} does not say which release is current (it may predate updates, or be unreachable).")
    status = update_status(clients)
    if not status:
        die("This is not a keepr skill folder with a readable VERSION, so it cannot tell whether it is current.")
    current, latest, steps = status
    title = steps["name"][0].upper() + steps["name"][1:]
    if version_tuple(current) >= version_tuple(latest):
        print(f"{title} {current} is up to date.")
        return

    blocker = self_update_blocker()
    if blocker:
        # A plugin, an upload to Claude, a git checkout, a read-only folder:
        # not ours to rewrite. Say how it IS updated instead.
        print(f"{title} is out of date (keepr skill {current}; {latest} is out). "
              + ("It is updated outside this script:" if client_channel() != "skill"
                 else f"It cannot update itself: {blocker}."))
        if client_channel() != "skill":
            for c in steps["commands"]:
                print(f"  run: {c}")
        for i, t in enumerate(steps["steps"] if client_channel() != "skill" else [], 1):
            print(f"  {i}. {t}")
        if steps.get("tip"):
            print(f"  {steps['tip']}")
        if steps.get("guide"):
            print(f"  How to update: {steps['guide']}")
        return

    with_tests = os.path.isdir(os.path.join(SKILL_DIR, "tests"))
    bundle = fetch_public("/api/docs/skill" + ("?include=tests" if with_tests else ""), timeout=60, code=True)
    files = (bundle or {}).get("files")
    version = (bundle or {}).get("version")
    if not isinstance(files, dict) or not isinstance(version, str):
        die("The deployment did not return the skill bundle. Nothing was changed.")
    if version_tuple(version) <= version_tuple(current):
        print(f"{title} {current} is up to date (the deployment serves {version}).")
        return
    total = 0
    folded = set()
    for rel, text in files.items():
        if not safe_bundle_path(rel) or not isinstance(text, str):
            die(f"The bundle carries a path this script will not write ({rel!r}). Nothing was changed.")
        if rel.lower() in folded:
            die(f"The bundle carries two paths that differ only in case ({rel!r}). Nothing was changed.")
        folded.add(rel.lower())
        try:
            size = len(text.encode("utf-8"))
        except UnicodeEncodeError:
            die("The bundle carries text that is not valid UTF-8. Nothing was changed.")
        total += size
        if size > UPDATE_MAX_FILE or total > UPDATE_MAX_TOTAL:
            die("The bundle is larger than a skill can be. Nothing was changed.")
    for required in ("SKILL.md", "VERSION", "scripts/keepr.py"):
        if required not in files:
            die(f"The bundle is missing {required}. Nothing was changed.")
    if files["VERSION"].strip() != version:
        die("The bundle's VERSION does not match what the deployment says it is serving. Nothing was changed.")

    # Only ever touch the files that belong to the skill. Anything in the
    # folder that neither this copy's nor the new bundle's top level names is
    # somebody else's, and the update stops rather than guess.
    old_files = _skill_files(SKILL_DIR)
    ours_top = {rel.split("/")[0] for rel in files} | {"SKILL.md", "GETTING-STARTED.md", "VERSION", "scripts",
                                                       "references", "examples"}
    strangers = sorted({rel.split("/")[0] for rel in old_files} - ours_top)
    if strangers:
        die(f"{SKILL_DIR} holds things that are not part of the keepr skill ({', '.join(strangers[:5])}). "
            "Nothing was changed; update it by hand: " + (steps.get("guide") or WEB_URL))

    # A copy of the current version first, kept afterwards: the way back if
    # the new one misbehaves, and what is restored if writing fails half way.
    os.makedirs(UPDATE_BACKUPS_DIR, mode=0o700, exist_ok=True)
    backup = tempfile.mkdtemp(dir=UPDATE_BACKUPS_DIR, prefix=f"keepr-{current}-")
    for rel in old_files:
        src = os.path.join(SKILL_DIR, *rel.split("/"))
        dst = os.path.join(backup, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst, follow_symlinks=False)

    # Files are replaced IN the folder, never the folder itself: a shell
    # sitting in it keeps its working directory, and a symlinked or mounted
    # skill folder stays what it is.
    stale = old_files - set(files)
    try:
        for rel, text in files.items():
            _write_file(SKILL_DIR, rel, text)
        for rel in stale:
            os.remove(os.path.join(SKILL_DIR, *rel.split("/")))
    except OSError as e:
        restored = True
        try:
            for rel in old_files:
                src = os.path.join(backup, *rel.split("/"))
                dst = os.path.join(SKILL_DIR, *rel.split("/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst, follow_symlinks=False)
            for rel in set(files) - old_files:
                try:
                    os.remove(os.path.join(SKILL_DIR, *rel.split("/")))
                except OSError:
                    pass
        except OSError:
            restored = False
        die(f"Could not write the update ({e}). "
            + ("The previous version was put back." if restored
               else f"The previous version could not be put back; a copy is at {backup}."))

    # Keep the newest two backups.
    try:
        kept = sorted((os.path.join(UPDATE_BACKUPS_DIR, d) for d in os.listdir(UPDATE_BACKUPS_DIR)),
                      key=os.path.getmtime, reverse=True)
        for old in kept[2:]:
            shutil.rmtree(old, ignore_errors=True)
    except OSError:
        pass
    try:
        os.remove(UPDATE_CHECK_FILE)
    except OSError:
        pass
    print(f"Updated the keepr skill from {current} to {version}. The new version is used from the next command on. "
          f"The previous version is kept at {backup}.")


# ------------------------------------------------------------------ create-card

# The option keys that belong under element.options, so a spec can write them
# flat and stay readable.
ELEMENT_OPTION_KEYS = {
    "isTitle", "required", "requiredWhen", "help", "choices", "allowMultiple",
    "lookupCardId", "measure", "defaultUnit", "units", "decimals", "leadingZeros",
    "nonNegative", "min", "max", "trueLabel", "falseLabel", "country", "accept",
    "percent", "thousands", "step", "control",
    "rangeEnd", "minuteStep", "weekdays", "precision", "identity", "drivenFrom",
    "currencies", "defaultCurrency", "display", "maxSizeMb",
}
KNOWN_TYPES = {
    "text-small", "text-large", "rich-text", "choice", "number", "decimal", "integer",
    "boolean", "date", "date-time", "time", "url", "phone", "email", "location",
    "rating", "card-lookup", "measurement", "user", "currency", "color", "file",
}


def normalize_element(el, card_ids, ref_for=None):
    """A spec element -> the card-definition wire shape. `label` may be a string;
    `lookupCard` may name another card in the same spec by key.

    With `ref_for` (a card blueprint), `lookupCard` and `sourceCard` become
    blueprint references — { "ref": … } for a card in the spec, { "key": … }
    otherwise, which keepr resolves — and nothing needs an id."""
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
    if el.get("lookupCard") and ref_for:
        options["lookupCardId"] = ref_for(el["lookupCard"])
    elif el.get("lookupCard"):
        target = card_ids.get(el["lookupCard"])
        if not target:
            die(f"element '{el.get('name')}' looks up card '{el['lookupCard']}', which is neither "
                "already in the collection nor earlier in this spec")
        options["lookupCardId"] = target
    if el.get("sourceCard") and ref_for:
        if not isinstance(options.get("drivenFrom"), dict):
            die(f"element '{el.get('name')}': sourceCard needs drivenFrom (sourceElementName, linkElementName, aggregate)")
        options["drivenFrom"] = dict(options["drivenFrom"], sourceCardId=ref_for(el["sourceCard"]))
    if data_type == "card-lookup" and not options.get("lookupCardId"):
        die(f"element '{el.get('name')}': a card-lookup needs lookupCard (a key) or lookupCardId")
    return {"name": el.get("name") or slug(label["singular"]), "label": label,
            "dataType": data_type, "options": options}


def global_card_id(key):
    """The id of the global card with this key, or None. A global card need not
    be in the collection yet to be extended."""
    q = f'scope = global and key = "{str(key).replace(chr(34), "")}"'
    found = get("/api/card-definitions?" + urllib.parse.urlencode({"q": q}), f"looking for a global card '{key}'") or []
    match = next((c for c in found if c.get("key") == key), None)
    return str(match.get("_id")) if match else None


def check_card_references(todo, card_ids):
    """Every parentCard and lookupCard, checked BEFORE the first card is created.

    A reference that names nothing used to be found mid-loop — after the cards
    before it were already created — or, for a parent, sent as a raw key the
    server refuses. Either way the user was left with half a spec. A parent may
    be a card already in the collection, one EARLIER in this spec, or a global
    card; a lookup target, one of the first two. Global parents are resolved
    here and remembered in card_ids.
    """
    problems = []
    earlier = set()
    for i, card in enumerate(todo):
        key = card.get("key") or slug(card.get("name", ""))
        parent = card.get("parentCard")
        if parent and parent not in card_ids and parent not in earlier:
            if any((c.get("key") or slug(c.get("name", ""))) == parent for c in todo[i + 1:]):
                problems.append(f"card '{key}': its parent '{parent}' comes later in the spec. Put the parent first.")
            else:
                gid = global_card_id(parent)
                if gid:
                    card_ids[parent] = gid
                else:
                    problems.append(f"card '{key}': parentCard '{parent}' is not in the collection, earlier in this spec, "
                                    "or a global card. Cards here: " + (", ".join(k for k in card_ids if k) or "(none)"))
        for el in card.get("elements", []):
            target = el.get("lookupCard")
            if target and target not in card_ids and target not in earlier:
                problems.append(f"card '{key}', element '{el.get('name')}': looks up card '{target}', which is neither "
                                "already in the collection nor earlier in this spec")
        earlier.add(key)
    if problems:
        die("nothing was created:\n  " + "\n  ".join(problems))


SYSTEM_COLUMNS = ("title", "primaryDate", "updatedAt", "createdAt", "sourceCreatedAt", "tags", "owner")


def build_blueprint(todo, card_ids, filters, layouts, tags=None):
    """A card blueprint for the cards of a spec (keepr 2.1, docs/SCHEMA.md
    "Card blueprints"): a card named by key that is IN the spec is { "ref" } —
    the card itself too, for a lookup to its own kind — and any other is
    { "key" }, which keepr resolves against the collection's cards, then the
    global ones. keepr creates the parents first and patches lookups and
    rollups in once every card exists, all or nothing."""
    local = {}
    for card in todo:
        key = card.get("key") or slug(card.get("name", ""))
        local[key] = key
        if card.get("name"):
            local.setdefault(slug(card["name"]), key)

    def ref_for(name):
        return {"ref": local[name]} if name in local else {"key": name}

    cards = []
    for card in todo:
        key = card.get("key") or slug(card.get("name", ""))
        entry = {
            "localId": key, "key": key,
            "name": card.get("name") or key,
            "elements": [normalize_element(el, card_ids, ref_for) for el in card.get("elements", [])],
        }
        for field in ("description", "icon", "color", "displayTemplate", "options"):
            if card.get(field):
                entry[field] = card[field]
        if card.get("parentCard"):
            entry["parentRef"] = ref_for(card["parentCard"])
        if card.get("elementSets"):
            entry["elementSetRefs"] = [{"key": k} for k in card["elementSets"]]
        cards.append(entry)
    collection = {}
    if filters:
        collection["savedFilters"] = filters
    if layouts:
        out = []
        for layout in layouts:
            card_key = layout.get("card")
            if card_key not in local:
                die(f"layout for '{card_key}': a table layout in a spec is for a card in the spec")
            spec_card = next((c for c in todo if (c.get("key") or slug(c.get("name", ""))) == local[card_key]), {})
            own = {el.get("name") for el in spec_card.get("elements", [])}
            columns = [({"system": c} if (c in SYSTEM_COLUMNS and c not in own) else {"element": c}) if isinstance(c, str) else c
                       for c in layout.get("columns", [])]
            out.append({"kind": "table", "scope": "card", "cardRef": {"ref": local[card_key]},
                        "body": {"columns": columns, **({"sort": layout["sort"]} if layout.get("sort") else {})}})
        collection["cardLayouts"] = out
    if tags:
        # keepr 2.2 (tags T10): NEW collection tags, each optionally applied by a
        # rule on a card. Every rule arrives PAUSED — it tags nothing until the
        # person resumes it in keepr. `parent` names another tag of the spec;
        # a rule's `card` (and each related clause's) is named like lookupCard.
        tag_local = {}
        for tag in tags:
            base = "tag-" + (slug(tag.get("name", "")) or "tag")[:52]
            local_id, n = base, 2
            while local_id in tag_local.values():
                local_id, n = f"{base}-{n}", n + 1
            tag_local[(tag.get("name") or "").strip().lower()] = local_id
        out = []
        for tag in tags:
            name = (tag.get("name") or "").strip()
            if not name:
                die("a tag in the spec has no name")
            entry = {"localId": tag_local[name.lower()], "name": name}
            for field in ("description", "color", "icon", "aliases"):
                if tag.get(field):
                    entry[field] = tag[field]
            if tag.get("parent"):
                parent = tag_local.get(str(tag["parent"]).strip().lower())
                if not parent:
                    die(f"tag '{name}': its parent '{tag['parent']}' is not a tag in the spec — a spec nests only the tags it makes")
                entry["parentRef"] = {"ref": parent}
            rule = tag.get("rule")
            if rule:
                if not rule.get("card"):
                    die(f"tag '{name}': its rule needs the card whose items it tags")
                built = {"cardRef": ref_for(rule["card"])}
                for field in ("where", "match", "strict"):
                    if field in rule:
                        built[field] = rule[field]
                if rule.get("related"):
                    built["related"] = [{**{k: v for k, v in c.items() if k != "card"}, "cardRef": ref_for(c.get("card"))} for c in rule["related"]]
                entry["rule"] = built
            out.append(entry)
        collection["tags"] = out
    return {"cards": cards, **({"collection": collection} if collection else {})}


def print_blueprint_problems(res):
    for p in (res.get("problems") or []):
        print(f"  {p.get('path', '')}: {p.get('message', '')} ({p.get('code', '')})", file=sys.stderr)


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
    filters = spec.get("filters", []) if isinstance(spec, dict) else []
    layouts = spec.get("layouts", []) if isinstance(spec, dict) else []
    tags = spec.get("tags", []) if isinstance(spec, dict) else []

    # keepr 2.1: one blueprint, checked by keepr, applied all or nothing.
    blueprint = build_blueprint(todo, card_ids, filters, layouts, tags)
    verb = "apply" if a.apply else "preview"
    status, res = request("POST", f"/api/collections/{collection}/blueprints/{verb}", {"blueprint": blueprint})
    res = res if isinstance(res, dict) else {}
    if status == 404 and str(res.get("message", "")).lower() == "not found" and not res.get("code"):
        # A deployment without blueprints: the 2.0 path, card by card.
        if filters or layouts or tags:
            die("this keepr deployment cannot create filters, layouts or tags with new cards — drop them from the spec")
        return create_cards_one_by_one(a, collection, todo, card_ids)
    if status >= 400:
        print(f"keepr refused the cards ({status}{' ' + res['code'] if res.get('code') else ''}): {res.get('message', '')}", file=sys.stderr)
        print_blueprint_problems(res)
        bp = res.get("blueprint") or {}
        if bp.get("compensated") is True:
            print("Nothing was kept: keepr removed everything this apply had created.", file=sys.stderr)
        elif bp.get("compensated") is False:
            left = ", ".join(f"{r.get('kind')} {r.get('name') or r.get('id')}" for r in bp.get("remaining", []))
            print(f"WARNING: keepr could not remove everything this apply created: {left}. Check the collection in the web app.", file=sys.stderr)
        sys.exit(1)
    if not a.apply:
        for line in res.get("summary") or []:
            print(line)
        if not res.get("wouldApply", False):
            print("\nkeepr would refuse these cards. Nothing was created. Fix each line and propose again:", file=sys.stderr)
            print_blueprint_problems(res)
            sys.exit(1)
        for step in res.get("steps") or []:
            if step.get("kind") == "card":
                parent = step.get("parent") or {}
                inherit = f", inheriting from {parent.get('ref') or parent.get('key') or parent.get('globalKey')}" if parent else ""
                print(f"\n--- would create card '{step.get('key')}' ({step.get('name')}){inherit}")
                spec_card = next((c for c in todo if (c.get("key") or slug(c.get("name", ""))) == step.get("localId")), {})
                for el in spec_card.get("elements", []):
                    link = f" -> looks up {el['lookupCard']}" if el.get("lookupCard") else ""
                    print(f"    {el.get('name') or slug(str(el.get('label', '')))}  [{el.get('dataType')}]{link}")
            elif step.get("kind") == "member":
                print(f"--- would add the global card '{step.get('key')}' ({step.get('name')}) to the collection")
            elif step.get("kind") == "filter":
                print(f"--- would save the filter '{step.get('name')}'")
            elif step.get("kind") == "layout":
                print(f"--- would set a {step.get('layoutKind')} layout")
            elif step.get("kind") == "tag":
                print(f"--- would add the tag '{step.get('name')}'")
            elif step.get("kind") == "tagRule":
                card = step.get("card") or {}
                print(f"--- would apply '{step.get('name')}' by a rule on {card.get('ref') or card.get('key') or card.get('globalKey')}"
                      f"{' (only the rule applies it)' if step.get('strict') else ''} — PAUSED: it tags nothing until the person resumes it in keepr")
        print("\nNothing was created. Show this to the user, and re-run with --apply once they agree —\n"
              "a card is schema, and creating one needs `manage` on the collection. The apply is all or nothing.")
        return
    for c in res.get("cards") or []:
        print(f"created card '{c.get('key')}' → {c.get('id')}")
    for f in res.get("filters") or []:
        print(f"saved the filter '{f.get('name')}'")
    for layout in res.get("layouts") or []:
        print(f"set a {layout.get('kind')} layout")
    for member in res.get("members") or []:
        print(f"added the global card '{member.get('key')}' to the collection")
    for tag in res.get("tags") or []:
        print(f"added the tag '{tag.get('name')}' → {tag.get('id')}")
    for rule in res.get("rules") or []:
        preview = rule.get("preview") or {}
        would = f", would tag {preview.get('matching')} of {preview.get('total')} items now" if isinstance(preview.get("matching"), int) else ""
        print(f"'{rule.get('name')}' is applied by a rule, PAUSED{would} — the person resumes it in keepr (Settings → Tags)")


def create_cards_one_by_one(a, collection, todo, card_ids):
    """keepr 2.0's path, for a deployment without card blueprints: every
    reference is checked first, then each card is POSTed in spec order."""
    check_card_references(todo, card_ids)

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


# ---------------------------------------------------------------- setup (KPR-195)
#
# A setup is keepr's own document (references/setup.md): layouts, filters,
# quick adds, tags, rules, notifications, charts, on new or existing cards.
# Previewed by keepr, applied all or nothing. The preview prints a fingerprint
# of the SETUP ITSELF and of keepr's plan — every step with what it was and
# what it becomes — and --apply needs it back (--expect): it previews again
# and applies only when both are what the person read. A spec edited since,
# or a colleague's edit to something the setup changes, is refused.

# Characters that show nothing: controls, bidi overrides, zero-width marks,
# tag characters (keepr-mcp chartTable.ts INVISIBLE_RANGES).
_INVISIBLE = re.compile("[" + "".join(
    re.escape(chr(a)) if a == b else f"{re.escape(chr(a))}-{re.escape(chr(b))}"
    for a, b in [(0x00, 0x08), (0x0b, 0x0c), (0x0e, 0x1f), (0x7f, 0x9f), (0xad, 0xad), (0x061c, 0x061c), (0x180e, 0x180e),
                 (0x200b, 0x200f), (0x202a, 0x202e), (0x2060, 0x2069), (0xfeff, 0xfeff), (0xe0000, 0xe007f)]) + "]")


def _one_line(value, limit=200):
    """Someone else's text, safe to print in a line: one line, nothing invisible, at most `limit` characters."""
    text = str("" if value is None else value)
    text = re.sub(r"[\t\n\r\v\f\x85  ]", " ", text)
    text = " ".join(_INVISIBLE.sub("", text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _setup_fingerprint(setup, steps):
    plan = [{k: v for k, v in (s or {}).items() if k != "preview"} for s in steps or []]
    blob = json.dumps({"setup": setup, "plan": plan}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


_MAX_CHANGES = 12


def _changes(before, after):
    """Each path that differs, was → now — `actions[0].title: Waiting on you →
    Work is waiting on you`, never only "actions" (KPR-197 live pass). A part
    added or taken away whole is named so. At most _MAX_CHANGES, then a count."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return []
    scalar = lambda v: v is None or isinstance(v, (str, int, float, bool))
    same = lambda x, y: json.dumps(x, sort_keys=True, default=str) == json.dumps(y, sort_keys=True, default=str)
    out = []

    def walk(b, a, path):
        if same(b, a):
            return
        if scalar(b) and scalar(a):
            out.append(f"{path}: {_one_line('(none)' if b is None else b, 4000)} → {_one_line('(none)' if a is None else a, 4000)}")
        elif b is None:
            out.append(f"{path}: added")
        elif a is None:
            out.append(f"{path}: removed")
        elif isinstance(b, list) and isinstance(a, list):
            for i in range(max(len(b), len(a))):
                walk(b[i] if i < len(b) else None, a[i] if i < len(a) else None, f"{path}[{i}]")
        elif isinstance(b, dict) and isinstance(a, dict):
            for k in sorted(set(b) | set(a)):
                walk(b.get(k), a.get(k), f"{path}.{k}" if path else k)
        else:
            out.append(f"{path}: replaced")

    walk(before, after, "")
    return out[:_MAX_CHANGES] + ([f"and {len(out) - _MAX_CHANGES} more"] if len(out) > _MAX_CHANGES else [])


def _draw_layout(kind, body):
    body = body if isinstance(body, dict) else {}
    if kind == "tile":
        rows = body.get("rows") or []
        return ["      | " + " | ".join(f"{_one_line(c.get('element') or c.get('system') or '?', 60)} ({c.get('span') or 1})"
                                       for c in (row if isinstance(row, list) else []) if isinstance(c, dict)) + " |" for row in rows] or ["      (no rows)"]
    if kind == "form":
        return [f"      [{_one_line(g.get('title') or 'Untitled', 80)}]{' (collapsed)' if g.get('collapsed') else ''}: "
                + (", ".join(_one_line(e, 60) for e in g.get("elements") or []) or "(empty)")
                for g in body.get("groups") or [] if isinstance(g, dict)] or ["      (no groups)"]
    if kind == "table":
        return ["      columns: " + (", ".join(_one_line(c.get("element") or c.get("system") or "?", 60)
                                            for c in body.get("columns") or [] if isinstance(c, dict)) or "(none)")]
    if kind == "page":
        blocks = len(body.get("blocks") or [])
        return [f"      {'a page of the records a query selects' if body.get('subject') == 'query' else 'one record per page'}, {blocks} block(s)"]
    return []


def _print_setup_steps(steps, setup):
    sent_layouts = ((setup.get("collection") or {}).get("cardLayouts") or []) if isinstance(setup, dict) else []
    layout_i = 0
    for s in steps or []:
        kind = s.get("kind")
        change = {"changed": "CHANGES", "unchanged": "unchanged"}.get(s.get("change"), "adds")
        name = _one_line(s.get("name") or s.get("key") or s.get("layoutKind") or "")
        if kind in ("automation", "notification"):
            where = "Settings › Notifications" if kind == "notification" else "Settings › Automations"
            if s.get("change") == "unchanged":
                state = "paused" if s.get("state") == "paused" else "on"
            elif s.get("state") == "paused":
                why = " ".join(_one_line(r.get("message") or r.get("code")) for r in (s.get("arrives") or {}).get("reasons") or [])
                state = (f"PAUSED — waits for the person to turn it on, in keepr › {where}"
                         + (" (this change pauses a rule that is running now)" if s.get("willPause") else "") + (f": {why}" if why else ""))
            else:
                state = "ON — runs as soon as it is applied"
            print(f"  {change} {kind} '{name}' — {state}")
            preview = s.get("preview") or {}
            if preview.get("summary"):
                print(f"      {_one_line(preview['summary'], 400)}")
            elif preview.get("note"):
                print(f"      {_one_line(preview['note'], 300)}")
            for act in preview.get("actions") or []:
                bits = []
                if isinstance(act.get("matches"), int):
                    bits.append(f"{act['matches']} record(s) match today")
                elif act.get("message"):
                    bits.append(_one_line(act["message"]))
                if isinstance(act.get("recipientCount"), int):
                    bits.append(f"reaches {act['recipientCount']} {'person' if act['recipientCount'] == 1 else 'people'}")
                if act.get("title"):
                    bits.append(f"says \"{_one_line(act['title'], 120)}\"")
                if bits:
                    print(f"      {_one_line(act.get('type'), 40)}: {'; '.join(bits)}")
            sources = (preview.get("generate") or {}).get("sources") or {}
            if isinstance(sources.get("matches"), int):
                print(f"      makes work for {sources['matches']} record(s) a run" + (f" (of {sources.get('total')})" if sources.get("truncated") else ""))
            runs = [_one_line(r.get("local"), 40) for r in preview.get("nextRuns") or [] if r.get("local")]
            if runs:
                print(f"      next runs: {', '.join(runs)}")
            for w in preview.get("warnings") or []:
                if w.get("message"):
                    print(f"      warning: {_one_line(w['message'], 300)}")
            if s.get("change") == "changed":
                ch = _changes(s.get("before"), s.get("after"))
                if ch:
                    print(f"      changes: {'; '.join(ch)}")
        elif kind == "layout":
            card = s.get("card") or {}
            ref = card.get("key") or card.get("ref") or card.get("globalKey") or "?"
            print(f"  {change} the {_one_line(s.get('layoutKind'), 20)}{(' ' + repr(name)) if s.get('name') else ''} of {_one_line(ref, 80)} ({_one_line(s.get('tier'), 20)} tier)")
            body = (s.get("after") or {}).get("body") if isinstance(s.get("after"), dict) else None
            if body is None and layout_i < len(sent_layouts):
                body = (sent_layouts[layout_i] or {}).get("body")
            layout_i += 1
            before = (s.get("before") or {}).get("body") if isinstance(s.get("before"), dict) else None
            if s.get("change") == "changed" and before is not None and s.get("layoutKind") in ("tile", "form", "table"):
                # Drawn as it is and as it will be: the person agrees to the difference.
                print("    now:")
                for line in _draw_layout(s.get("layoutKind"), before):
                    print(line)
                print("    becomes:")
                for line in _draw_layout(s.get("layoutKind"), body):
                    print(line)
            elif s.get("change") != "unchanged":
                for line in _draw_layout(s.get("layoutKind"), body):
                    print(line)
        elif kind == "tagRule":
            print(f"  adds the rule of tag '{name}' — PAUSED — it tags nothing until the person turns it on, in keepr › Settings › Tags")
        else:
            print(f"  {change} {_one_line(kind, 40)} '{name}'")
            if s.get("change") == "changed":
                ch = _changes(s.get("before"), s.get("after"))
                if ch:
                    print(f"      changes: {'; '.join(ch)}")


def _setup_refusal(status, res, what):
    hint = scope_hint(status, res)
    print(f"{what} ({status}{' ' + _one_line(res.get('code'), 60) if res.get('code') else ''}): {_one_line(res.get('message'), 400)}", file=sys.stderr)
    if hint:
        print(f"  ({hint})", file=sys.stderr)
    for p in (res.get("problems") or []):
        print(f"  {_one_line(p.get('path'), 120)}: {_one_line(p.get('message'), 400)} ({_one_line(p.get('code'), 60)})", file=sys.stderr)


def lift_element_options(setup):
    """New cards in a setup may be written the way references/cards.md teaches —
    `"isTitle": true`, `"choices": [...]`, `"lookupCard": "release"` beside the
    element's name. A blueprint takes those under `options` (and a lookup as a
    reference), so they are moved there before anything is sent; a key already
    under `options` wins. (KPR-197 live pass: the setup refused them.)"""
    local = {}
    for card in setup.get("cards") or []:
        if isinstance(card, dict) and isinstance(card.get("localId"), str):
            local[card["localId"]] = card["localId"]
            if isinstance(card.get("key"), str):
                local[card["key"]] = card["localId"]
    for group in ("cards", "elementSets"):
        for card in setup.get(group) or []:
            for el in (card.get("elements") or []) if isinstance(card, dict) else []:
                if not isinstance(el, dict):
                    continue
                options = el.get("options") if isinstance(el.get("options"), dict) else {}
                if isinstance(el.get("lookupCard"), str):
                    name = el.pop("lookupCard")
                    options.setdefault("lookupCardId", {"ref": local[name]} if name in local else {"key": name})
                for key in [k for k in el if k in ELEMENT_OPTION_KEYS]:
                    options.setdefault(key, el.pop(key))
                if options:
                    el["options"] = options


def cmd_setup(a):
    collection = resolve_collection(a.collection)
    try:
        with open(a.spec, encoding="utf-8") as fh:
            setup = json.load(fh)
    except (FileNotFoundError, ValueError) as e:
        die(f"cannot read {a.spec}: {e}")
    if not isinstance(setup, dict):
        die("a setup is one JSON object: {\"cards\"?: [...], \"collection\"?: {...}} — see references/setup.md")
    if a.apply and not a.expect:
        die("--apply needs --expect FINGERPRINT: run the preview first, show the person, then apply with the fingerprint it printed.")
    lift_element_options(setup)

    status, res = request("POST", f"/api/collections/{collection}/blueprints/preview", {"blueprint": setup})
    res = res if isinstance(res, dict) else {}
    if status >= 400:
        _setup_refusal(status, res, "keepr refused the setup")
        sys.exit(1)
    if not res.get("wouldApply", False):
        print("keepr would refuse this setup. Nothing was changed. Fix each line and propose again:", file=sys.stderr)
        _setup_refusal(status, res, "refused")
        sys.exit(1)
    steps = res.get("steps") or []
    fp = _setup_fingerprint(setup, steps)

    if not a.apply:
        print("PROPOSED — nothing has changed. Show this to the person and wait for a yes.\n")
        for line in res.get("summary") or []:
            print(_one_line(line, 600))
        print()
        _print_setup_steps(steps, setup)
        paused = [s for s in steps if s.get("kind") in ("automation", "notification") and s.get("change") != "unchanged" and s.get("state") == "paused"]
        rules_n = sum(1 for s in paused if s.get("kind") == "automation")
        notes_n = len(paused) - rules_n
        tags_n = sum(1 for s in steps if s.get("kind") == "tagRule")
        if rules_n:
            print(f"\n{rules_n} rule(s) will arrive PAUSED. Only the person can turn them on, in keepr › Settings › Automations.")
        if notes_n:
            print(f"{notes_n} notification(s) will arrive PAUSED. Only the person can turn them on, in keepr › Settings › Notifications.")
        if tags_n:
            print(f"{tags_n} tag rule(s) will arrive PAUSED. Only the person can turn them on, in keepr › Settings › Tags.")
        print(f"\nfingerprint: {fp}\nTo apply it once they agree: keepr.py setup --collection {a.collection!r} --spec {a.spec} --apply --expect {fp}")
        return

    if fp != a.expect:
        die("NOTHING WAS CHANGED: this is not the setup the person saw — the spec file, or something in the collection it "
            "changes, is different now. Run the preview again and show them the fresh one.")
    status, res = request("POST", f"/api/collections/{collection}/blueprints/apply", {"blueprint": setup})
    res = res if isinstance(res, dict) else {}
    if status >= 400:
        _setup_refusal(status, res, "keepr refused the setup")
        bp = res.get("blueprint") or {}
        if bp.get("compensated") is True:
            print("Nothing was kept: keepr undid everything this apply had made or changed.", file=sys.stderr)
        elif bp.get("compensated") is False:
            left = ", ".join(f"{_one_line(r.get('kind'), 40)} {_one_line(r.get('name') or r.get('id'), 120)}" for r in bp.get("remaining", []))
            print(f"WARNING: keepr could not undo everything this apply did: {left}. Check the collection in the web app.", file=sys.stderr)
        elif status >= 500:
            print("keepr failed part-way and did not say whether it undid what it had done. Check the collection in the web app before trying again.", file=sys.stderr)
        sys.exit(1)
    print("APPLIED.")
    for row in res.get("members") or []:
        print(f"  added to the collection: {_one_line(row.get('name'))} ({_one_line(row.get('key'), 80)}), a global card")
    for what in ("cards", "elementSets", "filters", "layouts", "quickAdds", "tags", "charts", "dashboards"):
        for row in res.get(what) or []:
            print(f"  {what[:-1]}: {_one_line(row.get('name') or row.get('kind') or row.get('id'))}{' (changed)' if row.get('changed') else ''}")
    waiting = []
    for what in ("automations", "notifications"):
        for row in res.get(what) or []:
            if row.get("enabled"):
                print(f"  {what[:-1]} running now: {_one_line(row.get('name'))}")
            else:
                waiting.append((what[:-1], row))
    for what, where in (("automation", "Settings › Automations"), ("notification", "Settings › Notifications")):
        mine = [row for w, row in waiting if w == what]
        if mine:
            print(f"\nPAUSED — waiting for the person to turn them on, in keepr › {where}:")
            for row in mine:
                print(f"  {what}: {_one_line(row.get('name'))}")
    for row in res.get("rules") or []:
        print(f"  tag rule PAUSED: {_one_line(row.get('name'))} — the person turns it on in keepr › Settings › Tags")
    if waiting or res.get("rules"):
        print("Only the person can turn these on; keepr refuses a key that tries.")


def _find_rule(collection, ref):
    status, rules = request("GET", f"/api/collections/{collection}/automations?describe=1")
    fail_on(status, rules, "reading the rules")
    rules = [r for r in (rules or []) if not r.get("inherited")]
    if ref is None:
        return rules, None
    hits = [r for r in rules if r.get("_id") == ref] if HEX24.match(ref) else [r for r in rules if (r.get("name") or "").lower() == ref.lower()]
    if not hits:
        die(f"no rule '{_one_line(ref, 80)}' in this collection — run keepr.py automations --collection … to list them.")
    if len(hits) > 1:
        die(f"'{_one_line(ref, 80)}' names {len(hits)} rules: " + ", ".join(f"{_one_line(r.get('name'))} ({r.get('_id')})" for r in hits) + ". Name one by id.")
    return rules, hits[0]


def cmd_automations(a):
    collection = resolve_collection(a.collection)
    if a.runs and a.pause:
        die("give --runs or --pause, not both.")
    if a.runs or a.pause:
        _, rule = _find_rule(collection, a.runs or a.pause)
        if a.runs:
            status, runs = request("GET", f"/api/collections/{collection}/automations/{rule['_id']}/runs?limit={a.limit}")
            fail_on(status, runs, "reading the runs")
            print(f"runs of '{_one_line(rule.get('name'))}', newest first:")
            for run in runs or []:
                actions = len(run.get("results") or [])
                print(f"  {_one_line(run.get('startedAt'), 40)}  {_one_line(run.get('status'), 40)}"
                      + (f"  {actions} action(s)" if actions else "")
                      + (f"  error: {_one_line(run['error'], 300)}" if run.get("error") else ""))
            if not runs:
                print("  (it has not run yet)")
            return
        status, res = request("POST", f"/api/collections/{collection}/automations/{rule['_id']}/disable", {})
        fail_on(status, res, "pausing it")
        print(f"PAUSED '{_one_line(rule.get('name'))}'. To turn it back on, the person does it in keepr › Settings › Automations.")
        return
    rules, _ = _find_rule(collection, None)
    status, defs = request("GET", f"/api/notification-defs?collection_id={collection}")
    # The collection's own, and the caller's personal ones for THIS collection.
    defs = [d for d in ((defs or {}).get("defs") or []) if d.get("scope") == "collection" or (d.get("scope") == "user" and d.get("collection_id"))] if status < 400 and isinstance(defs, dict) else []

    def state(r):
        return "WAITING FOR THE PERSON (paused until they turn it on)" if r.get("awaitingPerson") else ("PAUSED" if r.get("enabled") is False else "ON")

    def made(r):
        kind = (r.get("createdVia") or {}).get("kind")
        return {"api-key": ", made by an API key", "oauth": ", made by an assistant", "session": ", made by a person"}.get(kind, "")
    print(f"{len(rules)} rule(s), {len(defs)} notification(s):")
    for r in rules:
        managed = " — an automatic tag's rule" if r.get("kind") == "tag-rule" else (" — a calculated value" if r.get("managed") else "")
        print(f"  '{_one_line(r.get('name'))}' [{_one_line(r.get('kind') or 'rule', 40)}] — {state(r)}{made(r)}{managed}  {r.get('_id')}")
        if r.get("summary"):
            print(f"      {_one_line(r['summary'], 400)}")
    for d in defs:
        print(f"  notification '{_one_line(d.get('name'))}' (key {_one_line(d.get('key'), 80)}) — {state(d)}{made(d)}  {d.get('_id')}")
    if any(r.get("awaitingPerson") for r in rules):
        print("\nOnly the person can turn on a rule that is WAITING, in keepr › Settings › Automations.")
    if any(d.get("awaitingPerson") for d in defs):
        print("Only the person can turn on a notification that is WAITING, in keepr › Settings › Notifications.")


def cmd_history(a):
    if a.item and a.card:
        die("give --item or --card, not both.")
    if a.item:
        if not HEX24.match(a.item):
            die(f"'{_one_line(a.item, 40)}' is not an item id (24 hex characters).")
        path, what = f"/api/items/{a.item}/history", f"item {a.item}"
    elif a.card:
        if HEX24.match(a.card):
            card_id = a.card
        else:
            if not a.collection:
                die("a card named by key needs --collection.")
            collection = resolve_collection(a.collection)
            schema = load_schema(collection)
            hit = next((c for c in schema.get("cards", []) if (c.get("key") or "").lower() == a.card.lower() or (c.get("name") or "").lower() == a.card.lower()), None)
            if not hit:
                die(f"no card '{_one_line(a.card, 80)}' in this collection.")
            card_id = hit.get("id")
        path, what = f"/api/card-definitions/{card_id}/history", f"card {_one_line(a.card, 80)}"
    else:
        if not a.collection:
            die("give --item ID, --card KEY (with --collection), or --collection.")
        collection = resolve_collection(a.collection)
        path, what = f"/api/collections/{collection}/history", "the collection"
    status, rows, headers = request("GET", f"{path}?limit={a.limit}&skip={a.skip}", with_headers=True)
    fail_on(status, rows, "reading the history")
    total = (headers or {}).get("X-Total-Count") or (headers or {}).get("x-total-count")
    rows = rows if isinstance(rows, list) else []
    print(f"history of {what}, newest first ({len(rows)}{f' of {total}' if total else ''}{f', from {a.skip}' if a.skip else ''}):")
    for r in rows:
        print(f"  {_one_line(r.get('at'), 40)}  {_one_line(r.get('summary') or r.get('action'), 400)}")
    if not rows:
        print("  (nothing recorded)")


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


def tag_words(item):
    """An item's tags as words — (tags, my_tags): hand-applied first, then a
    rule's, each named through the item's `tagTitles` as far as this key may
    see; an id with no name is said as such, never dropped. `my_tags` are the
    key owner's own private tags."""
    titles = {str(k).lower(): v for k, v in (item.get("tagTitles") or {}).items()}
    hand = [str(t).lower() for t in item.get("tagIds") or []]
    rule = [str(t).lower() for t in item.get("tagAutoIds") or []]
    order = hand + [t for t in rule if t not in hand]

    def name(tag_id):
        entry = titles.get(tag_id)
        if not entry:
            return f"(a tag this key cannot name, {tag_id})"
        if entry.get("kind") == "tag":
            return entry.get("name") or tag_id
        if entry.get("unavailable"):
            return f"(no longer available, {tag_id})"
        return entry.get("title") or tag_id

    tags = []
    for tag_id in order:
        word = name(tag_id)
        if tag_id in rule and tag_id in hand:
            word += " (by hand and by a rule)"
        elif tag_id in rule:
            word += " (by a rule)"
        tags.append(word)
    mine = []
    for entry in item.get("myTags") or []:
        tag_id = str(entry.get("tagId")).lower()
        if entry.get("kind") == "item":
            word = name(tag_id) if tag_id in titles else f"(no longer available, {tag_id})"
        else:
            word = entry.get("name") or tag_id
        if entry.get("fromCollection"):
            word += " (on the collection)"
        mine.append(word)
    return tags, mine


def tags_suffix(item):
    tags, mine = tag_words(item)
    parts = ([f"tags: {', '.join(tags)}"] if tags else []) + ([f"my tags: {', '.join(mine)}"] if mine else [])
    return ("  · " + " · ".join(parts)) if parts else ""


CODE_RE = re.compile(r"^[0-9a-hjkmnp-tv-z]{7,16}$")


def item_link(item):
    # An item's short address, /i/<code> (keepr-api docs/SCHEMA.md § Record
    # codes); the long one only for an item keepr has not given a code yet.
    code = item.get("code")
    if isinstance(code, str) and CODE_RE.match(code):
        return f"{WEB_URL}/i/{code}"
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
        print(f"  {item_title(item, card):<40} {key:<16} {str(item.get('_id')):<26} {primary_date(item, card)}{tags_suffix(item)}")
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
        if item.get("notes"):
            print(f"  notes: {item['notes']}")
        tags, mine = tag_words(item)
        if tags:
            print(f"  tags: {', '.join(tags)}")
        if mine:
            print(f"  my tags: {', '.join(mine)}  (only the key's owner sees these)")
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
    asked = [t.strip() for t in a.types.split(",") if t.strip()] if a.types else None
    # Tags have their own search (items used as tags are found by title there),
    # asked beside the records by default — ruled b31 (2026-09-30); --types
    # can still narrow it.
    wants_tags = asked is None or "tags" in asked
    plain = [t for t in asked if t != "tags"] if asked else None
    body = {}
    if plain is None or plain:
        if plain:
            params["types"] = ",".join(plain)
        body = get("/api/search?" + urllib.parse.urlencode(params), "searching")
    tag_hits = []
    if wants_tags:
        found = get("/api/tags/search?" + urllib.parse.urlencode({"q": q, "limit": params["limit"]}), "searching tags") or {}
        tag_hits = found.get("results") or []
        body["tags"] = tag_hits
    if a.json:
        print(json.dumps(body, indent=2, default=str))
        return
    buckets = {k: body.get(k) or [] for k in ("collections", "cards", "items")}
    counts = {k: len(v) for k, v in buckets.items()} if (plain is None or plain) else {}
    if wants_tags:
        counts["tags"] = len(tag_hits)
    print(f'"{q}": ' + " · ".join(f"{k} {n}" for k, n in counts.items())
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
    for hit in tag_hits:
        tag = hit.get("tag") or {}
        where = f"  in collection {(hit.get('collection') or {}).get('name') or (hit.get('collection') or {}).get('_id')}" if hit.get("collection") else ""
        if hit.get("kind") == "item":
            print(f"  item tag    {str(tag.get('_id')):<26} {tag.get('title', '')}  (an item used as a tag — send this id in a row's \"tags\"){where}")
        elif hit.get("kind") == "private":
            print(f"  my tag      {str(tag.get('_id')):<26} {'/'.join(tag.get('path') or [tag.get('name', '')])}  (private — only you see it; never on a row)")
        else:
            print(f"  tag         {str(tag.get('_id')):<26} {'/'.join(tag.get('path') or [tag.get('name', '')])}{where}")
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
    p.add_argument("--import-id", help="name this import (default: kept from an unfinished run of these rows, else new)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("runs", help="recent ingest runs (audit)")
    p.add_argument("--collection", required=True)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_runs)

    p = sub.add_parser("request-upload", help="ask the person for files through a link")
    p.add_argument("--collection", required=True)
    p.add_argument("--entries", required=True, help='a JSON file: [{"item_id": ..., "name"|"pattern": ..., "element": ...}]')
    p.add_argument("--note", help="one line shown to the person (280 characters)")
    p.add_argument("--days", type=int, help="how long the link works, 1-30 (default 7)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_request_upload)

    p = sub.add_parser("upload-status", help="what has arrived for an upload request")
    p.add_argument("--id", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_upload_status)

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

    p = sub.add_parser("setup", help="propose a setup (layouts, filters, rules…) and apply it by fingerprint")
    p.add_argument("--collection", required=True)
    p.add_argument("--spec", required=True, help="setup.json — references/setup.md")
    p.add_argument("--apply", action="store_true", help="apply it (ask the person first)")
    p.add_argument("--expect", metavar="FINGERPRINT", help="the fingerprint the preview printed; required with --apply")
    p.set_defaults(fn=cmd_setup)

    p = sub.add_parser("automations", help="a collection's rules and notifications; a rule's runs; pause one")
    p.add_argument("--collection", required=True)
    p.add_argument("--runs", metavar="RULE", help="a rule's recent runs, by id or exact name")
    p.add_argument("--pause", metavar="RULE", help="pause a rule, by id or exact name")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(fn=cmd_automations)

    p = sub.add_parser("history", help="who changed what: an item, a card, or a collection (reads only)")
    p.add_argument("--item", help="an item id")
    p.add_argument("--card", help="a card key (with --collection) or id")
    p.add_argument("--collection", help="the collection")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--skip", type=int, default=0, help="older entries: skip this many of the newest")
    p.set_defaults(fn=cmd_history)

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
    p.add_argument("--types", help="comma-separated subset of collections,cards,items,tags (all four by default)")
    p.add_argument("--limit", type=int, default=20, help="per bucket, max 50")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("update", help="update this skill to the latest release, or say how")
    p.set_defaults(fn=cmd_update)

    args = ap.parse_args()
    # After the command — its output comes first, and the note follows on
    # stderr even when the command exits early (die() raises SystemExit).
    # Never for the commands that are about the key or about updating.
    try:
        args.fn(args)
    finally:
        if args.cmd not in ("login", "logout", "update"):
            daily_update_check()


if __name__ == "__main__":
    main()
