#!/usr/bin/env python3
"""Offline tests for scripts/keepr.py.

A stub keepr API on localhost answers the handful of endpoints the script calls,
so the whole loop — name resolution, templates, CSV mapping, batching, dry runs,
per-row failures, card proposals — is exercised without a key or a network.

Run: python3 tests/test_keepr.py   (or tests/run.sh)
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "keepr.py")

COLLECTION = "65a1b2c3d4e5f6a7b8c9d0e1"
OTHER = "65a1b2c3d4e5f6a7b8c9d0e2"
CARD_SCOPED = "65a1b2c3d4e5f6a7b8c9d0e3"

SCHEMA = {
    "collection": {"id": COLLECTION, "name": "My Books", "allowAttachments": True, "status": "active"},
    "cards": [
        {"id": "75a1b2c3d4e5f6a7b8c9d0e1", "key": "book", "name": "Book", "parentCardId": None,
         "elements": [
             {"name": "title", "label": "Title", "dataType": "text-small", "isTitle": True, "required": True},
             {"name": "author", "label": "Author", "dataType": "text-small"},
             {"name": "rating", "label": "Rating", "dataType": "rating", "max": 5},
             {"name": "read-on", "label": "Read on", "dataType": "date"},
             {"name": "status", "label": "Status", "dataType": "choice",
              "choices": [{"value": "reading", "label": "Reading"}, {"value": "done", "label": "Done"}]},
             {"name": "shelf", "label": "Shelf", "dataType": "card-lookup", "lookupCardKey": "shelf"},
             {"name": "added", "label": "Added", "dataType": "date", "driven": True},
         ]},
        {"id": "75a1b2c3d4e5f6a7b8c9d0e2", "key": "shelf", "name": "Shelf", "parentCardId": None,
         "elements": [{"name": "name", "label": "Name", "dataType": "text-small", "isTitle": True}]},
    ],
    "writeContract": {"maxBatch": 200, "idempotency": "source.externalId",
                      "strictDefault": True, "ingestPath": f"/api/collections/{COLLECTION}/ingest",
                      "contractVersion": "abc123def456", "contract": "/api/docs/contract"},
}

CALLS = []      # every request the stub served, for assertions about what was sent
ATTACHED = {}   # itemId -> [{_id, filename}], so re-uploads can be detected

# Two keys: the ordinary read+write one, and one that may also change cards.
# The scope refusal on change-preview is what tells them apart.
KEYS = {"kpr_testkey": ["read", "write"], "kpr_cardskey": ["read", "write", "cards"]}

BOOK_ID = "75a1b2c3d4e5f6a7b8c9d0e1"
SHELF_ID = "75a1b2c3d4e5f6a7b8c9d0e2"

ITEMS = [
    {"_id": "aaaaaaaaaaaaaaaaaaaaaaa1", "collection_id": COLLECTION, "card_id": BOOK_ID,
     "elements": {"title": "Dune", "author": "Frank Herbert", "rating": 5, "read-on": "2026-01-10"},
     "displayValue": "Dune", "tags": ["scifi"], "createdAt": "2026-01-11T00:00:00Z", "updatedAt": "2026-01-12T00:00:00Z"},
    {"_id": "aaaaaaaaaaaaaaaaaaaaaaa2", "collection_id": COLLECTION, "card_id": BOOK_ID,
     "elements": {"title": "Piranesi", "author": "Susanna Clarke", "rating": 4, "read-on": "2026-02-02"},
     "displayValue": "Piranesi", "tags": [], "createdAt": "2026-02-03T00:00:00Z", "updatedAt": "2026-02-03T00:00:00Z"},
    {"_id": "aaaaaaaaaaaaaaaaaaaaaaa3", "collection_id": COLLECTION, "card_id": BOOK_ID,
     "elements": {"title": "Hyperion", "author": "Dan Simmons", "rating": 3},
     "displayValue": "Hyperion", "tags": [], "createdAt": "2026-03-01T00:00:00Z", "updatedAt": "2026-03-01T00:00:00Z"},
]

# The card definition as PATCH wants it back: the card's OWN elements in
# their stored form. This is what change-card must send back whole.
BOOK_DEF = {
    "_id": BOOK_ID, "name": "Book", "key": "book", "description": "", "scope": "collection",
    "collection_id": COLLECTION, "parentCardId": None, "options": {"notes": True},
    "elements": [
        {"name": "title", "label": {"singular": "Title", "plural": "Titles"}, "dataType": "text-small",
         "options": {"isTitle": True, "required": True}},
        {"name": "author", "label": {"singular": "Author", "plural": "Authors"}, "dataType": "text-small", "options": {}},
        {"name": "rating", "label": {"singular": "Rating", "plural": "Ratings"}, "dataType": "rating", "options": {"max": 5}},
        {"name": "read-on", "label": {"singular": "Read on", "plural": "Read on"}, "dataType": "date", "options": {}},
        {"name": "status", "label": {"singular": "Status", "plural": "Statuses"}, "dataType": "choice",
         "options": {"choices": [{"value": "reading", "label": "Reading"}, {"value": "done", "label": "Done"}]}},
        {"name": "shelf", "label": {"singular": "Shelf", "plural": "Shelves"}, "dataType": "card-lookup",
         "options": {"lookupCardId": SHELF_ID}},
        {"name": "added", "label": {"singular": "Added", "plural": "Added"}, "dataType": "date",
         "options": {"drivenFrom": {"kind": "created"}}},
    ],
}


def change_preview(payload):
    """A stub of what the server's change-preview classifies, from the same
    comparison it would make: the stored own elements against the payload's."""
    before = {e["name"]: e for e in BOOK_DEF["elements"]}
    after = {e.get("name"): e for e in payload.get("elements") or []}
    changes = []
    for name, el in after.items():
        if name not in before:
            changes.append({"kind": "added", "element": name, "dataType": el.get("dataType")})
            continue
        old = before[name]
        if el.get("dataType") != old.get("dataType"):
            changes.append({"kind": "retyped", "element": name, "from": old.get("dataType"), "to": el.get("dataType"),
                            "conversion": "none", "itemsWithValues": 40, "destructive": True})
        elif (el.get("options") or {}) != (old.get("options") or {}):
            keys = sorted(k for k in set(el.get("options") or {}) | set(old.get("options") or {})
                          if (el.get("options") or {}).get(k) != (old.get("options") or {}).get(k))
            changes.append({"kind": "optionsChanged", "element": name, "keys": keys})
        if (el.get("label") or {}).get("singular") != (old.get("label") or {}).get("singular"):
            changes.append({"kind": "labelChanged", "element": name,
                            "from": (old.get("label") or {}).get("singular"), "to": (el.get("label") or {}).get("singular")})
    for name, old in before.items():
        if name not in after:
            changes.append({"kind": "removed", "element": name, "dataType": old.get("dataType"),
                            "itemsWithValues": 12, "destructive": True})
    card_fields = [{"field": f, "from": BOOK_DEF.get(f), "to": payload[f]}
                   for f in ("name", "description") if f in payload and payload[f] != BOOK_DEF.get(f)]
    destructive = any(c.get("destructive") for c in changes)
    summary = ", ".join(f"{c['kind']} {c.get('element', '')}".strip() for c in changes) or "no element changes"
    return {"card": {"id": BOOK_ID, "name": "Book", "key": "book", "collectionId": COLLECTION},
            "wouldApply": True, "refusal": None, "changes": changes, "cardFields": card_fields,
            "sideEffects": [], "destructive": destructive,
            "summary": ("DESTRUCTIVE — " if destructive else "") + summary}

# What a newer deployment publishes: one element type and one error code this
# copy of the skill has never heard of.
CONTRACT = {
    "version": "abc123def456",
    "elementTypes": [{"name": t, "send": "...", "note": ""} for t in
                     ["text-small", "number", "date", "colour"]],
    "errorCodes": {"shape": [{"code": "type", "means": "..."}],
                   "row": [{"code": "duplicate", "means": "..."},
                           {"code": "quota_exceeded", "means": "the collection is over its row budget"}]},
    "writeContract": {"maxBatch": 200},
}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, body, headers=None):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def _key(self):
        token = (self.headers.get("Authorization") or "").replace("Bearer ", "", 1)
        return token if token in KEYS else None

    def do_GET(self):
        CALLS.append(("GET", self.path, None))
        key = self._key()
        if not key:
            return self._send(401, {"message": "Invalid API key."})
        if self.path == "/api/user-info":
            return self._send(200, {"fullName": "Ada Lovelace", "email": "ada@example.com",
                                    "auth": {"kind": "api-key", "scopes": KEYS[key],
                                             "collectionIds": [COLLECTION, OTHER]}})
        parsed = urllib.parse.urlparse(self.path)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        if parsed.path == "/api/items":
            if "ids" in query:
                wanted = query["ids"].split(",")
                found = [{k: i[k] for k in ("_id", "collection_id", "card_id", "elements")}
                         for i in ITEMS if i["_id"] in wanted]
                return self._send(200, found, {"X-Total-Count": str(len(found))})
            rows = list(ITEMS)
            if "rating > 4" in query.get("q", ""):
                rows = [i for i in rows if i["elements"].get("rating", 0) > 4]
            skip, limit = int(query.get("skip") or 0), int(query.get("limit") or 50)
            return self._send(200, rows[skip:skip + limit], {"X-Total-Count": str(len(rows))})
        m = re.match(r"^/api/items/([0-9a-f]{24})$", parsed.path)
        if m:
            item = next((i for i in ITEMS if i["_id"] == m.group(1)), None)
            return self._send(200, item) if item else self._send(404, {"message": "Not Found"})
        if parsed.path == "/api/search":
            return self._send(200, {
                "query": query.get("q"),
                "collections": [{"_id": COLLECTION, "name": "My Books", "status": "active", "myAccess": {"role": "owner"}}],
                "cards": [{"_id": BOOK_ID, "name": "Book", "key": "book", "description": "", "scope": "collection",
                           "collection_id": COLLECTION}],
                "items": [{k: ITEMS[0][k] for k in ("_id", "collection_id", "card_id", "elements", "tags")}],
            })
        if parsed.path == f"/api/card-definitions/{BOOK_ID}":
            return self._send(200, BOOK_DEF)
        if self.path == "/api/collections":
            return self._send(200, [
                {"_id": COLLECTION, "name": "My Books", "status": "active", "myAccess": {"role": "owner"}},
                {"_id": OTHER, "name": "My Bookmarks", "status": "active", "myAccess": {"role": "write"}},
                {"_id": CARD_SCOPED, "name": "Shared Notes", "status": "archived",
                 "myAccess": {"role": None, "isOwner": False,
                              "cardRoles": {"75a1b2c3d4e5f6a7b8c9d0e3": "write"}, "queryGrants": []}},
            ])
        if self.path == f"/api/collections/{COLLECTION}/schema":
            return self._send(200, SCHEMA)
        if self.path == "/api/docs/contract":
            return self._send(200, CONTRACT)
        m = re.match(r"^/api/items/([A-Za-z0-9_-]+)/attachments$", self.path)
        if m:
            return self._send(200, ATTACHED.get(m.group(1), []))
        if self.path.startswith(f"/api/collections/{COLLECTION}/ingest-runs"):
            return self._send(200, [{"_id": "run1", "createdAt": "2026-09-18T00:00:00Z",
                                     "mode": "create", "dryRun": False,
                                     "summary": {"created": 2, "updated": 0, "skipped": 0, "failed": 0}}])
        return self._send(404, {"message": "not found"})

    def do_POST(self):
        m = re.match(r"^/api/items/([A-Za-z0-9_-]+)/attachments$", self.path)
        if m:
            item = m.group(1)
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            name = re.search(rb'filename="([^"]*)"', body)
            filename = name.group(1).decode() if name else "?"
            CALLS.append(("UPLOAD", item, filename))
            if filename.endswith(".exe"):
                return self._send(415, {"message": "Files of type .exe cannot be attached."})
            ATTACHED.setdefault(item, []).append({"_id": "att" + str(len(CALLS)), "filename": filename})
            return self._send(201, {"_id": "att" + str(len(CALLS)), "filename": filename})
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        CALLS.append(("POST", self.path, body))
        if self.path == "/api/card-definitions":
            return self._send(201, {"_id": "85a1b2c3d4e5f6a7b8c9d0e9", "key": body.get("key")})
        if self.path == f"/api/card-definitions/{BOOK_ID}/change-preview":
            if "cards" not in KEYS.get(self._key() or "", []):
                return self._send(403, {"statusCode": 403, "error": "Forbidden", "message": "insufficient_scope",
                                        "code": "insufficient_scope", "requiredScope": "cards"})
            return self._send(200, change_preview(body))
        if self.path == f"/api/collections/{COLLECTION}/ingest":
            rows, summary = [], {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
            dry = bool(body.get("dryRun"))
            for i, item in enumerate(body.get("items", [])):
                external = (item.get("source") or {}).get("externalId")
                # One deliberate failure mode, so the error path is covered: a
                # rating that is not a number is what the real validator refuses.
                if str((item.get("elements") or {}).get("rating", "")).strip() == "future":
                    summary["failed"] += 1
                    rows.append({"index": i, "status": "failed", "externalId": external,
                                 "errors": [{"element": "rating", "code": "from_the_future",
                                             "message": "a code this skill has never seen"}]})
                    continue
                if str((item.get("elements") or {}).get("rating", "")).strip() == "n/a":
                    summary["failed"] += 1
                    rows.append({"index": i, "status": "failed", "externalId": external,
                                 "errors": [{"element": "rating", "code": "type",
                                             "message": 'expected number, got "n/a"'}]})
                    continue
                summary["created"] += 1
                rows.append({"index": i, "status": "would-create" if dry else "created",
                             "id": f"aaaaaaaaaaaaaaaaaaaa{i:04d}", "externalId": external,
                             "displayValue": (item.get("elements") or {}).get("title", "")})
            return self._send(200, {"runId": "run-1", "summary": summary, "rows": rows})
        return self._send(404, {"message": "not found"})

    def do_PATCH(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        CALLS.append(("PATCH", self.path, body))
        if not self._key():
            return self._send(401, {"message": "Invalid API key."})
        if self.path == f"/api/card-definitions/{BOOK_ID}":
            if "cards" not in KEYS[self._key()]:
                return self._send(403, {"statusCode": 403, "error": "Forbidden", "message": "insufficient_scope",
                                        "code": "insufficient_scope", "requiredScope": "cards"})
            return self._send(200, {"status": {}, "payload": dict(BOOK_DEF, **body)})
        return self._send(404, {"message": "not found"})


HOME = None     # a fresh HOME per test, so ~/.config/keepr is the test's own


def run(*args, env=None, cwd=None, stdin=None):
    environ = dict(os.environ, KEEPR_URL=BASE, KEEPR_API_KEY="kpr_testkey", HOME=HOME)
    environ.update(env or {})
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                          env=environ, cwd=cwd, stdin=stdin)


def load_module():
    """keepr.py as an importable module, for the two functions worth calling
    directly (the credentials writer and the patch builder). HOME is read at
    import, so the module sees the test's HOME."""
    import importlib.util
    previous = os.environ.get("HOME")
    os.environ["HOME"] = HOME
    try:
        spec = importlib.util.spec_from_file_location("keepr", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        os.environ["HOME"] = previous
    return module


class KeeprScriptTest(unittest.TestCase):
    def setUp(self):
        global HOME
        CALLS.clear()
        ATTACHED.clear()
        self.tmp = tempfile.mkdtemp()
        HOME = tempfile.mkdtemp()

    def path(self, name):
        return os.path.join(self.tmp, name)

    def config_path(self, *parts):
        return os.path.join(HOME, ".config", "keepr", *parts)

    # -------------------------------------------------- credentials

    def test_missing_key_explains_how_to_get_one(self):
        result = run("check", env={"KEEPR_API_KEY": "", "KEEPR_KEY": ""})
        self.assertEqual(result.returncode, 1)
        self.assertIn("My Profile -> API keys", result.stderr)
        self.assertIn("keepr.py login", result.stderr)
        self.assertIn("KEEPR_API_KEY", result.stderr)
        self.assertIn("never by an assistant", result.stderr)

    def test_login_refuses_to_run_without_a_terminal(self):
        # Piped stdin means something other than the person is supplying the
        # key. Refused before any prompt, and no request is made.
        result = run("login", stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Run this yourself in a terminal; an assistant must never handle your key.", result.stderr)
        self.assertEqual(CALLS, [])

    def test_credentials_file_is_used_when_the_environment_is_empty(self):
        keepr = load_module()
        keepr.write_credentials(BASE, "kpr_testkey")
        result = run("check", env={"KEEPR_API_KEY": "", "KEEPR_KEY": "", "KEEPR_URL": ""})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ada@example.com", result.stdout)

    def test_the_environment_beats_the_credentials_file(self):
        keepr = load_module()
        keepr.write_credentials(BASE, "kpr_wrong")        # would 401 if it were read
        result = run("check", env={"KEEPR_API_KEY": "kpr_testkey"})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_credentials_are_written_0600_in_a_0700_directory(self):
        keepr = load_module()
        keepr.write_credentials(BASE, "kpr_testkey")
        path = self.config_path("credentials")
        self.assertEqual(oct(os.stat(path).st_mode & 0o777), oct(0o600))
        self.assertEqual(oct(os.stat(os.path.dirname(path)).st_mode & 0o777), oct(0o700))
        with open(path) as fh:
            self.assertEqual(json.load(fh), {"url": BASE, "key": "kpr_testkey"})

    def test_logout_removes_the_file(self):
        keepr = load_module()
        keepr.write_credentials(BASE, "kpr_testkey")
        result = run("logout")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(os.path.exists(self.config_path("credentials")))
        self.assertIn("still valid", result.stdout)

    def test_check_reports_the_scopes_the_server_declares(self):
        result = run("check")
        self.assertIn("scopes: read, write", result.stdout)
        self.assertIn("cannot change cards", result.stdout)
        cards = run("check", env={"KEEPR_API_KEY": "kpr_cardskey"})
        self.assertIn("scopes: read, write, cards", cards.stdout)
        self.assertNotIn("cannot change cards", cards.stdout)

    def test_the_delete_scope_is_reported_and_refused_in_the_key_forms_words(self):
        keepr = load_module()
        self.assertIn("cannot delete records",
                      keepr.describe_scopes({"auth": {"scopes": ["read", "write"], "collectionIds": None}}))
        self.assertIn("; delete records",
                      keepr.describe_scopes({"auth": {"scopes": ["read", "write", "delete"], "collectionIds": None}}))
        hint = keepr.scope_hint(403, {"message": "insufficient_scope", "code": "insufficient_scope",
                                      "requiredScope": "delete"})
        self.assertIn("Can delete records", hint)
        self.assertIn("2026-09-24", hint)

    def test_a_spent_delete_budget_is_an_answer_never_retried(self):
        keepr = load_module()
        body = {"statusCode": 429, "message": "This key has used its 500 deletes for today.",
                "code": "delete_budget_exhausted", "limit": 500, "used": 500, "remaining": 0,
                "requested": 3, "resetsAt": "2026-09-25T00:00:00.000Z"}
        self.assertTrue(keepr.is_final_refusal(429, body))
        self.assertFalse(keepr.is_final_refusal(429, {"message": "Too Many Requests"}))
        self.assertIn("500 of 500", keepr.budget_hint(429, body))
        self.assertIn("2026-09-25T00:00:00.000Z", keepr.budget_hint(429, body))

        import io
        import urllib.error
        calls = []

        def refuse(req, timeout=None):
            calls.append(req.full_url)
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {},
                                         io.BytesIO(json.dumps(body).encode()))
        keepr.urllib.request.urlopen = refuse
        keepr.time.sleep = lambda s: self.fail("a spent budget must not be retried")
        status, parsed = keepr.request("DELETE", "/api/items/x", key="kpr_testkey", url=BASE)
        self.assertEqual(status, 429)
        self.assertEqual(parsed["code"], "delete_budget_exhausted")
        self.assertEqual(len(calls), 1)

    def test_key_that_is_not_a_keepr_key_is_refused_before_the_call(self):
        result = run("check", env={"KEEPR_API_KEY": "sk-not-a-keepr-key"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("kpr_", result.stderr)
        self.assertEqual(CALLS, [])

    def test_rejected_key_reports_the_refusal_not_a_traceback(self):
        result = run("check", env={"KEEPR_API_KEY": "kpr_wrong"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("HTTP 401", result.stderr)
        self.assertIn("revoked", result.stderr)

    def test_check_names_the_account_and_its_collections(self):
        result = run("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ada@example.com", result.stdout)
        self.assertIn("My Books", result.stdout)

    def test_a_card_scoped_grant_reads_as_access_not_as_none(self):
        # myAccess.role is null for a key whose only grant is card-scoped; it can
        # still write there, so printing "None" would be actively misleading.
        result = run("check")
        self.assertIn("[card-write]", result.stdout)
        self.assertNotIn("[None]", result.stdout)
        self.assertIn("ARCHIVED", result.stdout)

    def test_collections_listing_labels_every_access_kind(self):
        result = run("collections")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("owner", result.stdout)
        self.assertIn("card-write", result.stdout)

    # -------------------------------------------------- resolving a collection

    def test_collection_resolves_by_exact_name(self):
        result = run("schema", "--collection", "My Books")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("card 'book'", result.stdout)

    def test_ambiguous_name_lists_candidates_instead_of_guessing(self):
        result = run("schema", "--collection", "My Book")
        self.assertEqual(result.returncode, 1)
        self.assertIn("matches several collections", result.stderr)
        self.assertIn("My Bookmarks", result.stderr)

    def test_unknown_name_lists_what_is_reachable(self):
        result = run("schema", "--collection", "Recipes")
        self.assertEqual(result.returncode, 1)
        self.assertIn("No collection named 'Recipes'", result.stderr)

    def test_schema_shows_types_choices_and_driven_warning(self):
        result = run("schema", "--collection", COLLECTION)
        self.assertIn("one of: reading, done", result.stdout)
        self.assertIn("links to card 'shelf'", result.stdout)
        self.assertIn("driven — do not send", result.stdout)
        self.assertIn("required", result.stdout)

    # -------------------------------------------------- template

    def test_template_omits_driven_elements_and_marks_every_value(self):
        out = self.path("rows.json")
        result = run("template", "--collection", "My Books", "--card", "book", "--out", out)
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(out) as fh:
            doc = json.load(fh)
        elements = doc["items"][0]["elements"]
        self.assertNotIn("added", elements)                       # driven
        self.assertEqual(elements["read-on"], "<YYYY-MM-DD>")
        self.assertIn("reading|done", elements["status"])

    def test_unfilled_template_is_caught_before_any_call(self):
        out = self.path("rows.json")
        run("template", "--collection", COLLECTION, "--card", "book", "--out", out)
        CALLS.clear()
        result = run("ingest", "--rows", out, "--dry-run")
        self.assertEqual(result.returncode, 1)
        self.assertIn("template placeholders", result.stderr)
        self.assertFalse([c for c in CALLS if c[0] == "POST"])

    # -------------------------------------------------- csv

    def test_csv_maps_headers_drops_unmatched_and_keys_on_id_column(self):
        csv_path = self.path("books.csv")
        with open(csv_path, "w") as fh:
            fh.write("ISBN,Title,Author,Rating,Sales rank\n"
                     "978-1,Dune,Frank Herbert,5,12\n"
                     "978-2,Piranesi,Susanna Clarke,,7\n")
        out = self.path("rows.json")
        result = run("csv", "--file", csv_path, "--card", "book", "--collection", COLLECTION,
                     "--map", "ISBN=isbn", "--id-column", "ISBN", "--system", "books-csv", "--out", out)
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(out) as fh:
            doc = json.load(fh)
        self.assertEqual(len(doc["items"]), 2)
        first = doc["items"][0]
        self.assertEqual(first["elements"]["title"], "Dune")      # "Title" -> slug "title"
        self.assertEqual(first["source"]["externalId"], "978-1")
        self.assertEqual(doc["source"]["system"], "books-csv")
        self.assertNotIn("sales-rank", first["elements"])          # no such element: dropped
        self.assertNotIn("isbn", first["elements"])                # mapped to a name the card lacks
        self.assertNotIn("rating", doc["items"][1]["elements"])     # blank cell omitted, not ""
        self.assertIn("Sales rank", result.stderr)

    def test_csv_without_id_column_warns_about_duplicates(self):
        csv_path = self.path("books.csv")
        with open(csv_path, "w") as fh:
            fh.write("title,author\nDune,Frank Herbert\n")
        result = run("csv", "--file", csv_path, "--card", "book", "--out", self.path("r.json"))
        self.assertIn("create duplicates", result.stderr)

    # -------------------------------------------------- ingest

    def write_rows(self, items, **doc):
        path = self.path("rows.json")
        with open(path, "w") as fh:
            json.dump(dict({"collection": COLLECTION, "source": {"system": "test"}, "items": items}, **doc), fh)
        return path

    def test_dry_run_writes_nothing_and_says_so(self):
        rows = self.write_rows([{"card": "book", "elements": {"title": "Dune"},
                                 "source": {"externalId": "d1"}}])
        result = run("ingest", "--rows", rows, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DRY RUN", result.stdout)
        posted = [c for c in CALLS if c[0] == "POST"][0][2]
        self.assertIs(posted["dryRun"], True)
        self.assertIs(posted["strict"], True)

    def test_commit_reports_totals_and_saves_results(self):
        rows = self.write_rows([{"card": "book", "elements": {"title": "Dune"},
                                 "source": {"externalId": "d1"}}])
        result = run("ingest", "--rows", rows)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("created 1", result.stdout)
        with open(rows.replace(".json", ".results.json")) as fh:
            results = json.load(fh)
        self.assertEqual(results["items"]["d1"], "aaaaaaaaaaaaaaaaaaaa0000")

    def test_a_failed_row_is_named_with_its_code_and_exits_2(self):
        rows = self.write_rows([
            {"card": "book", "elements": {"title": "Dune", "rating": "n/a"}, "source": {"externalId": "d1"}},
        ])
        result = run("ingest", "--rows", rows, "--dry-run")
        self.assertEqual(result.returncode, 2)
        self.assertIn("FAILED d1", result.stdout)
        self.assertIn("expected number", result.stdout)

    def test_rows_are_chunked_at_the_batch_cap(self):
        rows = self.write_rows([{"card": "book", "elements": {"title": f"Book {i}"},
                                 "source": {"externalId": f"b{i}"}} for i in range(250)])
        result = run("ingest", "--rows", rows, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        posts = [c for c in CALLS if c[0] == "POST"]
        self.assertEqual([len(p[2]["items"]) for p in posts], [200, 50])
        self.assertIn("created 250", result.stdout)

    def test_upsert_demands_an_external_id_on_every_row(self):
        rows = self.write_rows([{"card": "book", "elements": {"title": "Dune"}}])
        result = run("ingest", "--rows", rows, "--mode", "upsert")
        self.assertEqual(result.returncode, 1)
        self.assertIn("needs source.externalId", result.stderr)

    def test_external_ids_without_a_system_are_refused_locally(self):
        rows = self.write_rows([{"card": "book", "elements": {"title": "Dune"},
                                 "source": {"externalId": "d1"}}], source={})
        result = run("ingest", "--rows", rows, "--dry-run")
        self.assertEqual(result.returncode, 1)
        self.assertIn("--system", result.stderr)

    def test_a_bare_list_of_rows_is_accepted(self):
        path = self.path("rows.json")
        with open(path, "w") as fh:
            json.dump([{"card": "book", "elements": {"title": "Dune"}}], fh)
        result = run("ingest", "--rows", path, "--collection", "My Books", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("created 1", result.stdout)

    def test_lenient_turns_strict_off_on_the_wire(self):
        rows = self.write_rows([{"card": "book", "elements": {"title": "Dune"}}])
        run("ingest", "--rows", rows, "--dry-run", "--lenient")
        posted = [c for c in CALLS if c[0] == "POST"][0][2]
        self.assertIs(posted["strict"], False)

    # -------------------------------------------------- cards

    def test_create_card_proposes_without_writing(self):
        spec = self.path("card.json")
        with open(spec, "w") as fh:
            json.dump({"name": "Note", "key": "note",
                       "elements": [{"name": "body", "label": "Body", "dataType": "text-large"}]}, fh)
        result = run("create-card", "--collection", COLLECTION, "--spec", spec)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("would create card 'note'", result.stdout)
        self.assertFalse([c for c in CALLS if c[0] == "POST"])

    def test_create_card_applies_and_resolves_lookups_within_the_spec(self):
        spec = self.path("cards.json")
        with open(spec, "w") as fh:
            json.dump([
                {"name": "Author", "key": "author",
                 "elements": [{"name": "name", "label": "Name", "dataType": "text-small", "isTitle": True}]},
                {"name": "Note", "key": "note",
                 "elements": [{"name": "by", "label": "By", "dataType": "card-lookup", "lookupCard": "author"}]},
            ], fh)
        result = run("create-card", "--collection", COLLECTION, "--spec", spec, "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        posts = [c[2] for c in CALLS if c[0] == "POST"]
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[1]["elements"][0]["options"]["lookupCardId"], "85a1b2c3d4e5f6a7b8c9d0e9")
        self.assertEqual(posts[0]["elements"][0]["label"], {"singular": "Name", "plural": "Names"})

    def test_existing_cards_are_left_alone(self):
        spec = self.path("card.json")
        with open(spec, "w") as fh:
            json.dump({"name": "Book", "key": "book", "elements": []}, fh)
        result = run("create-card", "--collection", COLLECTION, "--spec", spec, "--apply")
        self.assertIn("already in this collection", result.stdout)
        self.assertFalse([c for c in CALLS if c[0] == "POST"])

    def test_an_unknown_data_type_is_refused_with_the_valid_list(self):
        spec = self.path("card.json")
        with open(spec, "w") as fh:
            json.dump({"name": "Note", "key": "note2",
                       "elements": [{"name": "when", "label": "When", "dataType": "datetime"}]}, fh)
        result = run("create-card", "--collection", COLLECTION, "--spec", spec)
        self.assertEqual(result.returncode, 1)
        self.assertIn("date-time", result.stderr)

    # -------------------------------------------------- audit

    def test_runs_lists_the_ledger(self):
        result = run("runs", "--collection", COLLECTION)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("created 2", result.stdout)

    # -------------------------------------------------- attachments

    def results_file(self, items):
        path = self.path("rows.results.json")
        with open(path, "w") as fh:
            json.dump({"collection": COLLECTION, "items": items}, fh)
        return path

    def photo(self, *parts):
        full = os.path.join(self.tmp, *parts)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(b"\x89PNG fake bytes")
        return full

    def test_files_are_matched_to_records_by_a_counter_suffix(self):
        # molly-blake.jpg, molly-blake-2.jpg, "molly blake (3).jpg" are all Molly.
        self.photo("photos", "molly-blake.jpg")
        self.photo("photos", "molly-blake-2.jpg")
        self.photo("photos", "molly-blake (3).jpg")
        self.photo("photos", "leah-park_1.jpg")
        results = self.results_file({"molly-blake": "item-molly", "leah-park": "item-leah"})
        out = run("attach", "--results", results, "--dir", self.path("photos"), "--dry-run")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("4 file(s) → 2 item(s)", out.stdout)
        self.assertNotIn("UNMATCHED", out.stderr)

    def test_a_folder_per_record_also_works(self):
        self.photo("photos", "molly-blake", "front.jpg")
        self.photo("photos", "molly-blake", "back.jpg")
        results = self.results_file({"molly-blake": "item-molly"})
        out = run("attach", "--results", results, "--dir", self.path("photos"), "--dry-run")
        self.assertIn("2 file(s) → 1 item(s)", out.stdout)

    def test_a_file_matching_no_record_is_reported_not_guessed(self):
        self.photo("photos", "molly-blake.jpg")
        self.photo("photos", "someone-else.jpg")
        results = self.results_file({"molly-blake": "item-molly"})
        out = run("attach", "--results", results, "--dir", self.path("photos"))
        self.assertEqual(out.returncode, 2, "unmatched files are a non-zero exit")
        self.assertIn("UNMATCHED someone-else.jpg", out.stderr)
        self.assertIn("attached molly-blake.jpg", out.stdout)

    def test_dry_run_uploads_nothing(self):
        self.photo("photos", "molly-blake.jpg")
        results = self.results_file({"molly-blake": "item-molly"})
        out = run("attach", "--results", results, "--dir", self.path("photos"), "--dry-run")
        self.assertIn("DRY RUN", out.stdout)
        self.assertFalse([c for c in CALLS if c[0] == "UPLOAD"])

    def test_re_running_a_folder_skips_what_is_already_attached(self):
        self.photo("photos", "molly-blake.jpg")
        results = self.results_file({"molly-blake": "item-molly"})
        first = run("attach", "--results", results, "--dir", self.path("photos"))
        self.assertIn("attached molly-blake.jpg", first.stdout)
        second = run("attach", "--results", results, "--dir", self.path("photos"))
        self.assertIn("already attached", second.stdout)
        self.assertEqual(len([c for c in CALLS if c[0] == "UPLOAD"]), 1, "uploaded once, not twice")

    def test_an_explicit_map_beats_filename_guessing(self):
        self.photo("scans", "IMG_4471.jpg")
        results = self.results_file({"molly-blake": "item-molly"})
        mapping = self.path("map.json")
        with open(mapping, "w") as fh:
            json.dump({"molly-blake": ["IMG_4471.jpg"]}, fh)
        out = run("attach", "--results", results, "--map", mapping, "--dir", self.path("scans"))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertRegex(out.stdout, r"attached IMG_4471\.jpg .*→ molly-blake")

    def test_a_refused_file_type_is_named_with_the_reason(self):
        self.photo("photos", "molly-blake.exe")
        results = self.results_file({"molly-blake": "item-molly"})
        out = run("attach", "--results", results, "--dir", self.path("photos"))
        self.assertEqual(out.returncode, 2)
        self.assertIn("cannot be attached", out.stderr)

    def test_several_files_can_go_to_one_item_directly(self):
        a, b = self.photo("a.jpg"), self.photo("b.jpg")
        out = run("attach", "--item", "item-molly", "--file", a, "--file", b)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(len([c for c in CALLS if c[0] == "UPLOAD"]), 2)

    def test_attaching_before_committing_the_ingest_is_refused(self):
        results = self.results_file({})
        out = run("attach", "--results", results, "--dir", self.tmp)
        self.assertEqual(out.returncode, 1)
        self.assertIn("Commit the ingest first", out.stderr)

    # -------------------------------------------------- contract

    def test_contract_check_names_what_the_skill_does_not_know(self):
        out = run("contract", "--check")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("colour", out.stdout)
        self.assertIn("quota_exceeded", out.stdout)
        self.assertIn("over its row budget", out.stdout)
        self.assertIn("contract version abc123def456", out.stdout)

    def test_an_unrecognised_error_code_tells_the_agent_to_fetch_the_contract(self):
        rows = self.write_rows([{"card": "book", "elements": {"title": "Dune", "rating": "future"},
                                 "source": {"externalId": "d1"}}])
        out = run("ingest", "--rows", rows, "--dry-run")
        self.assertEqual(out.returncode, 2)
        self.assertIn("keepr.py contract", out.stderr)
        self.assertIn("from_the_future", out.stderr)

    def test_schema_reports_the_deployment_contract_version(self):
        out = run("schema", "--collection", COLLECTION)
        self.assertIn("contract version", out.stdout)

    # -------------------------------------------------- reading

    def test_items_leads_with_shown_of_total_and_says_how_to_see_more(self):
        out = run("items", "--collection", "My Books", "--limit", "2")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith('2 of 3 items in "My Books"'), out.stdout)
        self.assertIn("Dune", out.stdout)
        self.assertIn("book", out.stdout)
        self.assertIn("2026-01-11", out.stdout)                     # the primary date (created)
        self.assertIn("1 more not shown", out.stdout)
        self.assertIn("--skip 2", out.stdout)
        self.assertIn("narrow with --q", out.stdout)

    def test_items_states_the_filter_and_sends_it_as_kql(self):
        out = run("items", "--collection", COLLECTION, "--q", "rating > 4", "--card", "book")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith('1 of 1 items in "My Books" matching rating > 4 card book'), out.stdout)
        self.assertNotIn("more not shown", out.stdout)
        listing = [c for c in CALLS if c[0] == "GET" and c[1].startswith("/api/items?")][0][1]
        q = urllib.parse.parse_qs(urllib.parse.urlparse(listing).query)
        self.assertEqual(q["q"], ["(rating > 4) and card = book"])
        self.assertEqual(q["collection_id"], [COLLECTION])
        self.assertEqual(q["limit"], ["25"])

    def test_items_sort_flags_reach_the_wire_only_when_given(self):
        run("items", "--collection", COLLECTION)
        plain = urllib.parse.parse_qs(urllib.parse.urlparse(CALLS[-1][1]).query)
        self.assertNotIn("sort_field", plain)
        self.assertNotIn("sort_direction", plain)
        run("items", "--collection", COLLECTION, "--sort", "rating", "--desc")
        sorted_ = urllib.parse.parse_qs(urllib.parse.urlparse(CALLS[-1][1]).query)
        self.assertEqual(sorted_["sort_field"], ["rating"])
        self.assertEqual(sorted_["sort_direction"], ["desc"])

    def test_items_json_carries_the_total_from_the_header(self):
        out = run("items", "--collection", COLLECTION, "--limit", "1", "--json")
        doc = json.loads(out.stdout)
        self.assertEqual((doc["total"], doc["shown"]), (3, 1))

    def test_get_batch_says_not_readable_and_never_deleted(self):
        out = run("get", "--id", ITEMS[0]["_id"], "--id", ITEMS[1]["_id"], "--id", "bbbbbbbbbbbbbbbbbbbbbbb9")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith("2 of 3 requested — 1 not readable by this key: bbbbbbbbbbbbbbbbbbbbbbb9"),
                        out.stdout)
        self.assertNotIn("deleted", out.stdout.lower())
        self.assertIn("author: Frank Herbert", out.stdout)
        self.assertIn(f"https://keepr.cloud/collections/{COLLECTION}/items/{ITEMS[0]['_id']}", out.stdout)
        ids_call = [c for c in CALLS if c[0] == "GET" and "ids=" in c[1]][0][1]
        self.assertIn("ids=" + ",".join([ITEMS[0]["_id"], ITEMS[1]["_id"], "bbbbbbbbbbbbbbbbbbbbbbb9"]), ids_call)

    def test_get_one_unreadable_item_is_a_count_not_a_crash(self):
        out = run("get", "--id", "bbbbbbbbbbbbbbbbbbbbbbb9")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("0 of 1 requested — 1 not readable by this key", out.stdout)

    def test_get_refuses_a_non_id_before_any_call(self):
        out = run("get", "--id", "dune")
        self.assertEqual(out.returncode, 1)
        self.assertIn("Not item ids", out.stderr)
        self.assertEqual(CALLS, [])

    def test_search_reports_per_bucket_counts_first(self):
        out = run("search", "--q", "dune", "--types", "collections,cards,items")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith('"dune": collections 1 · cards 1 · items 1'), out.stdout)
        self.assertIn("Dune", out.stdout)
        self.assertIn("types=collections%2Ccards%2Citems", CALLS[0][1])

    # -------------------------------------------------- change-card

    def spec(self, doc):
        path = self.path("change.json")
        with open(path, "w") as fh:
            json.dump(doc, fh)
        return path

    def previews(self):
        return [c[2] for c in CALLS if c[0] == "POST" and c[1].endswith("/change-preview")]

    def patches(self):
        return [c[2] for c in CALLS if c[0] == "PATCH"]

    def token_in(self, stdout):
        m = re.search(r"--apply ([0-9a-f]{16})", stdout)
        self.assertIsNotNone(m, stdout)
        return m.group(1)

    CARDS = {"KEEPR_API_KEY": "kpr_cardskey"}

    def test_a_change_naming_one_element_sends_every_element(self):
        # THE test. PATCH replaces `elements` whole, so a spec that mentions
        # only `rating` must still carry all seven, with only rating changed.
        out = run("change-card", "--collection", "My Books", "--card", "book",
                  "--spec", self.spec({"elements": [{"name": "rating", "max": 10}]}), env=self.CARDS)
        self.assertEqual(out.returncode, 0, out.stderr)
        sent = self.previews()[0]["elements"]
        self.assertEqual([e["name"] for e in sent], [e["name"] for e in BOOK_DEF["elements"]])
        rating = next(e for e in sent if e["name"] == "rating")
        self.assertEqual(rating["options"], {"max": 10})
        self.assertEqual(rating["dataType"], "rating")
        untouched = [e for e in sent if e["name"] != "rating"]
        self.assertEqual(untouched, [e for e in BOOK_DEF["elements"] if e["name"] != "rating"])
        self.assertEqual(self.patches(), [], "a proposal writes nothing")
        self.assertIn("~ options    rating: max", out.stdout)
        self.assertIn("unchanged 6", out.stdout)
        self.assertNotIn("DESTRUCTIVE", out.stdout)
        self.assertIn("Nothing was changed", out.stdout)
        self.token_in(out.stdout)

    def test_a_new_element_is_appended_and_nothing_is_removed(self):
        out = run("change-card", "--collection", COLLECTION, "--card", "book",
                  "--spec", self.spec({"elements": [{"name": "isbn", "label": "ISBN", "dataType": "text-small"}]}),
                  env=self.CARDS)
        self.assertEqual(out.returncode, 0, out.stderr)
        sent = self.previews()[0]["elements"]
        self.assertEqual(len(sent), 8)
        self.assertEqual(sent[-1]["name"], "isbn")
        self.assertEqual(sent[-1]["label"], {"singular": "ISBN", "plural": "ISBNs"})
        self.assertIn("+ added      isbn (text-small)", out.stdout)
        self.assertNotIn("--confirm", out.stdout)

    def test_removal_happens_only_through_the_remove_list(self):
        # Leaving an element out of the spec is not a removal.
        out = run("change-card", "--collection", COLLECTION, "--card", "book",
                  "--spec", self.spec({"elements": [{"name": "author", "label": "Writer"}]}), env=self.CARDS)
        self.assertEqual(len(self.previews()[0]["elements"]), 7)
        self.assertNotIn("REMOVED", out.stdout)
        CALLS.clear()
        out = run("change-card", "--collection", COLLECTION, "--card", "book",
                  "--spec", self.spec({"remove": ["shelf"]}), env=self.CARDS)
        self.assertEqual(out.returncode, 0, out.stderr)
        sent = self.previews()[0]["elements"]
        self.assertEqual(len(sent), 6)
        self.assertNotIn("shelf", [e["name"] for e in sent])
        self.assertIn("DESTRUCTIVE", out.stdout)
        self.assertIn("REMOVED    shelf (card-lookup) — 12 item(s) hold a value", out.stdout)
        self.assertIn('--confirm "Book"', out.stdout)

    def test_removing_an_element_the_card_does_not_own_is_refused_locally(self):
        out = run("change-card", "--collection", COLLECTION, "--card", "book",
                  "--spec", self.spec({"remove": ["publisher"]}), env=self.CARDS)
        self.assertEqual(out.returncode, 1)
        self.assertIn("not one of this card's own elements", out.stderr)
        self.assertEqual(self.previews(), [])

    def test_a_spec_that_renames_the_key_is_refused(self):
        out = run("change-card", "--collection", COLLECTION, "--card", "book",
                  "--spec", self.spec({"key": "books", "elements": []}), env=self.CARDS)
        self.assertEqual(out.returncode, 1)
        self.assertIn("stable handle", out.stderr)
        self.assertEqual(self.previews(), [])

    def test_a_destructive_proposal_needs_the_card_name_typed_back(self):
        proposed = run("change-card", "--collection", COLLECTION, "--card", "book",
                       "--spec", self.spec({"remove": ["shelf"]}), env=self.CARDS)
        token = self.token_in(proposed.stdout)
        self.assertTrue(os.path.exists(self.config_path("proposals", token + ".json")))

        bare = run("change-card", "--apply", token, env=self.CARDS)
        self.assertEqual(bare.returncode, 1)
        self.assertIn("destructive", bare.stderr)
        self.assertIn('--confirm "Book"', bare.stderr)
        wrong = run("change-card", "--apply", token, "--confirm", "Books", env=self.CARDS)
        self.assertEqual(wrong.returncode, 1)
        self.assertIn("does not match", wrong.stderr)
        self.assertEqual(self.patches(), [], "no PATCH until the name matches")
        self.assertTrue(os.path.exists(self.config_path("proposals", token + ".json")), "a refused confirm keeps the proposal")

        applied = run("change-card", "--apply", token, "--confirm", "Book", env=self.CARDS)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(len(self.patches()), 1)
        self.assertEqual(len(self.patches()[0]["elements"]), 6)
        self.assertIn("changed card 'book'", applied.stdout)
        self.assertFalse(os.path.exists(self.config_path("proposals", token + ".json")), "used once")

    def test_a_safe_proposal_applies_without_confirm_and_sends_the_stored_payload(self):
        proposed = run("change-card", "--collection", COLLECTION, "--card", "book",
                       "--spec", self.spec({"name": "Books", "elements": [{"name": "rating", "max": 10}]}), env=self.CARDS)
        self.assertIn('~ card       name: "Book" -> "Books"', proposed.stdout)
        token = self.token_in(proposed.stdout)
        applied = run("change-card", "--apply", token, env=self.CARDS)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        patch = self.patches()[0]
        self.assertEqual(patch["name"], "Books")
        self.assertEqual(len(patch["elements"]), 7)
        self.assertEqual(patch, self.previews()[0], "what was applied is exactly what was previewed")

    def test_an_expired_proposal_is_refused_and_discarded(self):
        os.makedirs(self.config_path("proposals"))
        token = "0123456789abcdef"
        with open(self.config_path("proposals", token + ".json"), "w") as fh:
            json.dump({"token": token, "expiresAt": time.time() - 1, "destructive": False,
                       "cardId": BOOK_ID, "cardName": "Book", "cardKey": "book",
                       "payload": {"elements": []}}, fh)
        out = run("change-card", "--apply", token, env=self.CARDS)
        self.assertEqual(out.returncode, 1)
        self.assertIn("expired", out.stderr)
        self.assertEqual(self.patches(), [])
        self.assertFalse(os.path.exists(self.config_path("proposals", token + ".json")))

    def test_an_unknown_token_is_refused(self):
        out = run("change-card", "--apply", "ffffffffffffffff", env=self.CARDS)
        self.assertEqual(out.returncode, 1)
        self.assertIn("No proposal", out.stderr)

    def test_a_key_without_cards_scope_is_told_what_to_change(self):
        out = run("change-card", "--collection", COLLECTION, "--card", "book",
                  "--spec", self.spec({"elements": [{"name": "rating", "max": 10}]}))
        self.assertEqual(out.returncode, 1)
        self.assertIn("HTTP 403", out.stderr)
        self.assertIn("This key cannot change cards. Create or edit a key with Can change cards turned on.", out.stderr)
        self.assertFalse(os.path.isdir(self.config_path("proposals")), "no proposal without a preview")


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 0), Stub)
    BASE = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        unittest.main(verbosity=2)
    finally:
        server.shutdown()
