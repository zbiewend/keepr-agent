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
import shutil
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
             {"name": "genres", "label": "Genres", "dataType": "choice", "allowMultiple": True,
              "choices": [{"value": "fantasy", "label": "Fantasy"}, {"value": "mystery", "label": "Mystery"}]},
         ]},
        {"id": "75a1b2c3d4e5f6a7b8c9d0e2", "key": "shelf", "name": "Shelf", "parentCardId": None,
         "itemTags": "chosen", "applyWhereReferenced": True,
         "elements": [{"name": "name", "label": "Name", "dataType": "text-small", "isTitle": True}]},
    ],
    # The collection's tag vocabulary (keepr T8): the only tags a row may name.
    "tags": [
        {"id": "c0a1b2c3d4e5f6a7b8c9d0e1", "name": "Genre", "path": "Genre", "parentId": None,
         "restricted": False, "rule": None, "aliases": []},
        {"id": "c0a1b2c3d4e5f6a7b8c9d0e2", "name": "Sci-fi", "path": "Genre/Sci-fi", "parentId": "c0a1b2c3d4e5f6a7b8c9d0e1",
         "restricted": False, "rule": None, "aliases": ["SF"]},
        {"id": "c0a1b2c3d4e5f6a7b8c9d0e3", "name": "Signed", "path": "Signed", "parentId": None,
         "restricted": True, "rule": None, "aliases": []},
        {"id": "c0a1b2c3d4e5f6a7b8c9d0e4", "name": "Overdue", "path": "Overdue", "parentId": None,
         "restricted": False, "rule": {"strict": True}, "aliases": []},
    ],
    "writeContract": {"maxBatch": 200, "idempotency": "source.externalId",
                      "strictDefault": True, "ingestPath": f"/api/collections/{COLLECTION}/ingest",
                      "contractVersion": "abc123def456", "contract": "/api/docs/contract"},
}

CALLS = []      # every request the stub served, for assertions about what was sent
# Card blueprints (keepr 2.1). Off by default, so the create-card tests below
# exercise the card-by-card path a deployment without them still uses.
BLUEPRINTS = {"enabled": False, "preview": None, "apply": None}
# An older keepr whose strict envelope refuses importId.
INGEST = {"refuse_import_id": False, "refuse_would_create": False}
ATTACHED = {}   # itemId -> [{_id, filename}], so re-uploads can be detected

# Two keys: the ordinary read+write one, and one that may also change cards.
# The scope refusal on change-preview is what tells them apart.
KEYS = {"kpr_testkey": ["read", "write"], "kpr_cardskey": ["read", "write", "cards"]}

BOOK_ID = "75a1b2c3d4e5f6a7b8c9d0e1"
PERSON_DEF = {"_id": "95a1b2c3d4e5f6a7b8c9d0e1", "key": "person", "name": "Person", "scope": "global"}
SHELF_ID = "75a1b2c3d4e5f6a7b8c9d0e2"

ITEMS = [
    {"_id": "aaaaaaaaaaaaaaaaaaaaaaa1", "collection_id": COLLECTION, "card_id": BOOK_ID,
     "elements": {"title": "Dune", "author": "Frank Herbert", "rating": 5, "read-on": "2026-01-10"},
     "displayValue": "Dune", "tags": ["scifi"], "createdAt": "2026-01-11T00:00:00Z", "updatedAt": "2026-01-12T00:00:00Z",
     # The rebuilt tags as keepr serves them (a legacy "tags" list is never printed).
     "tagIds": ["c0a1b2c3d4e5f6a7b8c9d0e2", "d0a1b2c3d4e5f6a7b8c9d0e1", "d0a1b2c3d4e5f6a7b8c9d0e2"],
     "tagAutoIds": ["c0a1b2c3d4e5f6a7b8c9d0e4"],
     "tagTitles": {"c0a1b2c3d4e5f6a7b8c9d0e2": {"kind": "tag", "name": "Sci-fi", "restricted": False},
                   "c0a1b2c3d4e5f6a7b8c9d0e4": {"kind": "tag", "name": "Overdue", "restricted": False},
                   "d0a1b2c3d4e5f6a7b8c9d0e1": {"title": "Top shelf", "item_id": "e0a1b2c3d4e5f6a7b8c9d0e1"}},
     "myTags": [{"tagId": "f0a1b2c3d4e5f6a7b8c9d0e1", "kind": "tag", "name": "To reread"}]},
    {"_id": "aaaaaaaaaaaaaaaaaaaaaaa2", "collection_id": COLLECTION, "card_id": BOOK_ID,
     "elements": {"title": "Piranesi", "author": "Susanna Clarke", "rating": 4, "read-on": "2026-02-02"},
     "displayValue": "Piranesi", "createdAt": "2026-02-03T00:00:00Z", "updatedAt": "2026-02-03T00:00:00Z"},
    {"_id": "aaaaaaaaaaaaaaaaaaaaaaa3", "collection_id": COLLECTION, "card_id": BOOK_ID,
     "elements": {"title": "Hyperion", "author": "Dan Simmons", "rating": 3},
     "displayValue": "Hyperion", "createdAt": "2026-03-01T00:00:00Z", "updatedAt": "2026-03-01T00:00:00Z"},
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


# The two public /api/docs resources `update` reads. Tests set them; None is
# an older deployment that answers 404.
DOCS = {"clients": None, "skill": None}
CLIENT_HEADERS = []     # X-Keepr-Client on every request, in order


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
        CLIENT_HEADERS.append(self.headers.get("X-Keepr-Client"))
        docs_path = urllib.parse.urlparse(self.path).path
        if docs_path in ("/api/docs/clients", "/api/docs/skill"):
            doc = DOCS[docs_path.rsplit("/", 1)[1]]
            return self._send(200, doc) if doc is not None else self._send(404, {"message": "Not Found"})
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
                "items": [{k: ITEMS[0][k] for k in ("_id", "collection_id", "card_id", "elements")}],
            })
        if parsed.path == "/api/tags/search":
            return self._send(200, {"results": [
                {"kind": "collection", "tag": {"_id": "c0a1b2c3d4e5f6a7b8c9d0e2", "name": "Sci-fi", "path": ["Genre", "Sci-fi"]},
                 "collection": {"_id": COLLECTION, "name": "My Books"}},
                {"kind": "item", "tag": {"_id": "d0a1b2c3d4e5f6a7b8c9d0e1", "title": "Top shelf"},
                 "collection": {"_id": COLLECTION, "name": "My Books"}},
                {"kind": "private", "tag": {"_id": "f0a1b2c3d4e5f6a7b8c9d0e1", "name": "To reread", "path": ["To reread"]}},
            ], "more": False})
        if parsed.path == f"/api/card-definitions/{BOOK_ID}":
            return self._send(200, BOOK_DEF)
        if parsed.path == "/api/card-definitions":
            # The global-card lookup a parent falls back to.
            q = (query.get("q") or [""])[0] if isinstance(query.get("q"), list) else (query.get("q") or "")
            return self._send(200, [PERSON_DEF] if 'key = "person"' in q else [])
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
        if BLUEPRINTS["enabled"] and self.path == f"/api/collections/{COLLECTION}/blueprints/preview":
            return self._send(200, BLUEPRINTS["preview"](body["blueprint"]))
        if BLUEPRINTS["enabled"] and self.path == f"/api/collections/{COLLECTION}/blueprints/apply":
            status, doc = BLUEPRINTS["apply"](body["blueprint"])
            return self._send(status, doc)
        if self.path == "/api/card-definitions":
            # The real envelope: 201 { status, payload: <the stored card> }.
            return self._send(201, {"status": {"acknowledged": True},
                                    "payload": {"_id": "85a1b2c3d4e5f6a7b8c9d0e9", "key": body.get("key")}})
        if self.path == f"/api/card-definitions/{BOOK_ID}/change-preview":
            if "cards" not in KEYS.get(self._key() or "", []):
                return self._send(403, {"statusCode": 403, "error": "Forbidden", "message": "insufficient_scope",
                                        "code": "insufficient_scope", "requiredScope": "cards"})
            return self._send(200, change_preview(body))
        if self.path == f"/api/collections/{COLLECTION}/ingest":
            if INGEST["refuse_import_id"] and "importId" in body:
                return self._send(400, {"statusCode": 400, "error": "Bad Request", "message": '"importId" is not allowed'})
            if INGEST["refuse_would_create"] and "wouldCreate" in body:
                return self._send(400, {"statusCode": 400, "error": "Bad Request", "message": '"wouldCreate" is not allowed'})
            rows, summary = [], {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
            dry = bool(body.get("dryRun"))
            # What a $ref can find, as keepr settles it: this call's rows and
            # the would-create rows of earlier calls it was told about.
            known = {(item.get("source") or {}).get("externalId") for item in body.get("items", [])}
            known |= {entry["externalId"] for entry in body.get("wouldCreate", [])}
            for i, item in enumerate(body.get("items", [])):
                external = (item.get("source") or {}).get("externalId")
                ref = ((item.get("elements") or {}).get("shelf") or {})
                if isinstance(ref, dict) and ref.get("$ref") and ref["$ref"] not in known:
                    summary["failed"] += 1
                    rows.append({"index": i, "status": "failed", "externalId": external,
                                 "errors": [{"element": "shelf", "code": "ref_unresolved",
                                             "message": f'no item with externalId "{ref["$ref"]}"'}]})
                    continue
                # One deliberate failure mode, so the error path is covered: a
                # rating that is not a number is what the real validator refuses.
                if str((item.get("elements") or {}).get("rating", "")).strip() == "future":
                    summary["failed"] += 1
                    rows.append({"index": i, "status": "failed", "externalId": external,
                                 "errors": [{"element": "rating", "code": "from_the_future",
                                             "message": "a code this skill has never seen"}]})
                    continue
                # Tags, as keepr judges a row's names (T8): one that names no
                # tag, and one that names two.
                tags = item.get("tags") or []
                if "Nowhere" in tags:
                    summary["failed"] += 1
                    rows.append({"index": i, "status": "failed", "externalId": external,
                                 "errors": [{"element": None, "code": "unknown_tag",
                                             "message": 'tags: "Nowhere" is not a tag of this collection or the collection above it.'}]})
                    continue
                if "Classic" in tags:
                    summary["failed"] += 1
                    rows.append({"index": i, "status": "failed", "externalId": external,
                                 "errors": [{"element": None, "code": "ambiguous_tag",
                                             "message": 'tags: "Classic" could be more than one tag. Send its path or its id.',
                                             "candidates": [{"tagId": "c0a1b2c3d4e5f6a7b8c9d0f1", "path": ["Genre", "Classic"], "private": False},
                                                            {"tagId": "c0a1b2c3d4e5f6a7b8c9d0f2", "path": ["Era", "Classic"], "private": False}]}]})
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
                # keepr's one row note today: an upsert's source date is fixed at create.
                if body.get("mode") == "upsert" and (item.get("source") or {}).get("createdAt"):
                    rows[-1]["notes"] = ["source is fixed when the item is created; its created date was not changed"]
                # A tag deleted since the row was written: left off, with a warning.
                if "c0a1b2c3d4e5f6a7b8c9d0e9" in tags:
                    rows[-1]["warnings"] = [{"code": "tag_dropped", "field": "tags", "tagIds": ["c0a1b2c3d4e5f6a7b8c9d0e9"],
                                             "message": "A tag on the form is no longer available and was left off. Everything else was saved."}]
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


def run(*args, env=None, cwd=None, stdin=None, script=None):
    # The daily update check is off unless a test is about it: it is one more
    # request, and most tests count requests.
    environ = dict(os.environ, KEEPR_URL=BASE, KEEPR_API_KEY="kpr_testkey", HOME=HOME, KEEPR_UPDATE_CHECK="off")
    environ.pop("KEEPR_CLIENT_CHANNEL", None)
    environ.update(env or {})
    return subprocess.run([sys.executable, script or SCRIPT, *args], capture_output=True, text=True,
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
        CLIENT_HEADERS.clear()
        DOCS.update(clients=None, skill=None)
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

    def test_schema_lists_the_tag_vocabulary_and_where_items_are_tags(self):
        out = run("schema", "--collection", COLLECTION)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("tags — name them in a row's \"tags\" like this", out.stdout)
        self.assertIn("    Genre/Sci-fi  [id c0a1b2c3d4e5f6a7b8c9d0e2]  (also: SF)", out.stdout)
        self.assertIn("    Signed  [id c0a1b2c3d4e5f6a7b8c9d0e3]  (restricted — only a manager, signed in to keepr, puts it on or takes it off; never from here)", out.stdout)
        self.assertIn("    Overdue  [id c0a1b2c3d4e5f6a7b8c9d0e4]  (applied by a rule only — never send it)", out.stdout)
        self.assertIn("chosen items of this card can be used as tags — find one with `search --q <title> --types tags`", out.stdout)

    def test_schema_shows_types_choices_and_driven_warning(self):
        result = run("schema", "--collection", COLLECTION)
        self.assertIn("one of: reading, done", result.stdout)
        self.assertIn("links to card 'shelf'", result.stdout)
        self.assertIn("driven — do not send", result.stdout)
        self.assertIn("required", result.stdout)

    def test_schema_states_the_condition_of_a_conditional_requirement(self):
        keepr = load_module()
        line = keepr.describe_element({
            "name": "acceptance", "dataType": "text-large", "required": False,
            "requiredWhen": [{"element": "status", "op": "in", "value": ["ready", "in-progress"]},
                             {"element": "type", "op": "eq", "value": "story"}],
        })
        self.assertIn("required when status in (ready, in-progress) and type = story", line)
        self.assertNotIn("conditionally", line)

    def test_schema_marks_a_sequence_do_not_send_and_shows_its_spelling(self):
        keepr = load_module()
        line = keepr.describe_element({"name": "key", "dataType": "integer", "sequence": True,
                                       "serverAssigned": True, "prefix": "KPR-", "leadingZeros": 4})
        self.assertIn("numbered by keepr — do not send", line)
        self.assertIn("shown as KPR-0042", line)

    def test_schema_says_a_percent_takes_the_number_shown(self):
        keepr = load_module()
        line = keepr.describe_element({"name": "discount", "dataType": "number", "percent": True, "thousands": True})
        self.assertIn("a percent — send the number shown (12.5 for 12.5 %), never a fraction", line)
        self.assertIn("shown grouped (1,234,567) — send the plain number", line)
        plain = keepr.describe_element({"name": "count", "dataType": "number", "percent": False})
        self.assertNotIn("percent", plain)

    def test_schema_shows_a_choice_label_only_when_it_says_more(self):
        keepr = load_module()
        line = keepr.describe_element({"name": "status", "dataType": "choice", "choices": [
            {"value": "ready", "label": "Ready"}, {"value": "in-progress", "label": "In progress"}]})
        self.assertIn('one of: ready, in-progress ("In progress")', line)

    def test_schema_says_a_choice_that_allows_multiple_takes_any_of_its_values(self):
        keepr = load_module()
        line = keepr.describe_element({"name": "genres", "dataType": "choice", "allowMultiple": True, "choices": [
            {"value": "fantasy", "label": "Fantasy"}, {"value": "mystery", "label": "Mystery"}]})
        self.assertIn("list", line)
        self.assertIn("any of: fantasy, mystery", line)
        single = keepr.describe_element({"name": "status", "dataType": "choice", "allowMultiple": False,
                                         "choices": [{"value": "ready", "label": "Ready"}]})
        self.assertIn("one of: ready", single)
        legacy = keepr.describe_element({"name": "kind", "dataType": "text-small", "allowMultiple": True,
                                         "choices": [{"value": "a", "label": "A"}]})
        self.assertIn("one of: a", legacy)                       # only a choice holds a list of choices

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
        self.assertEqual(elements["genres"], ["<any of: fantasy|mystery>"])  # a list, and still caught unfilled

    def test_unfilled_template_is_caught_before_any_call(self):
        out = self.path("rows.json")
        run("template", "--collection", COLLECTION, "--card", "book", "--out", out)
        CALLS.clear()
        result = run("ingest", "--rows", out, "--dry-run")
        self.assertEqual(result.returncode, 1)
        self.assertIn("template placeholders", result.stderr)
        self.assertFalse([c for c in CALLS if c[0] == "POST"])

    def test_rows_tags_are_sent_as_written_for_keepr_to_resolve(self):
        out = self.path("rows.json")
        with open(out, "w") as fh:
            json.dump({"collection": COLLECTION, "items": [
                {"card": "book", "elements": {"title": "Dune"}, "tags": ["SF", "Genre/Sci-fi", "c0a1b2c3d4e5f6a7b8c9d0e3"]},
                {"card": "book", "elements": {"title": "Piranesi"}, "tags": []},
            ]}, fh)
        result = run("ingest", "--rows", out, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        sent = [c for c in CALLS if c[0] == "POST"][0][2]["items"]
        self.assertEqual(sent[0]["tags"], ["SF", "Genre/Sci-fi", "c0a1b2c3d4e5f6a7b8c9d0e3"])
        self.assertEqual(sent[1]["tags"], [], "an empty list is an instruction on an upsert: take the tags off")

    def test_tags_that_are_not_a_list_of_names_are_refused_before_any_call(self):
        out = self.path("rows.json")
        with open(out, "w") as fh:
            json.dump({"collection": COLLECTION, "items": [
                {"card": "book", "elements": {"title": "Dune"}, "tags": ["SF"]},
                {"card": "book", "elements": {"title": "Piranesi"}, "tags": "fantasy"},
                {"card": "book", "elements": {"title": "Hyperion"}, "tags": [""]},
            ]}, fh)
        CALLS.clear()
        result = run("ingest", "--rows", out, "--dry-run")
        self.assertEqual(result.returncode, 1)
        self.assertIn("2 row(s) have \"tags\" that are not a list of tag names, paths or ids (first: row 1)", result.stderr)
        self.assertFalse([c for c in CALLS if c[0] == "POST"])

    def test_tag_refusals_name_the_candidates_and_a_dropped_tag_is_a_warning(self):
        out = self.path("rows.json")
        with open(out, "w") as fh:
            json.dump({"collection": COLLECTION, "source": {"system": "books"}, "items": [
                {"card": "book", "elements": {"title": "Dune"}, "tags": ["Nowhere"], "source": {"externalId": "b1"}},
                {"card": "book", "elements": {"title": "Emma"}, "tags": ["Classic"], "source": {"externalId": "b2"}},
                {"card": "book", "elements": {"title": "Hyperion"}, "tags": ["c0a1b2c3d4e5f6a7b8c9d0e9"], "source": {"externalId": "b3"}},
            ]}, fh)
        result = run("ingest", "--rows", out, "--dry-run")
        self.assertEqual(result.returncode, 2, "a refused row is a failure")
        self.assertIn('FAILED b1: -: unknown_tag — tags: "Nowhere" is not a tag', result.stdout)
        self.assertIn("ambiguous_tag", result.stdout)
        self.assertIn("[could be: Genre/Classic (c0a1b2c3d4e5f6a7b8c9d0f1), Era/Classic (c0a1b2c3d4e5f6a7b8c9d0f2)]", result.stdout)
        self.assertIn("WARNING b3: A tag on the form is no longer available", result.stdout)
        self.assertNotIn("does not know", result.stderr, "every tag code is one this skill documents")
        with open(self.path("rows.results.json")) as fh:
            self.assertEqual(json.load(fh)["warnings"][0]["externalId"], "b3")

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

    def test_csv_sends_a_choice_that_allows_multiple_as_a_list(self):
        csv_path = self.path("books.csv")
        with open(csv_path, "w") as fh:
            fh.write('title,genres,status\nDune,"fantasy; mystery ;",reading\nPiranesi,fantasy,done\n')
        out = self.path("rows.json")
        result = run("csv", "--file", csv_path, "--card", "book", "--collection", COLLECTION, "--out", out)
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(out) as fh:
            doc = json.load(fh)
        self.assertEqual(doc["items"][0]["elements"]["genres"], ["fantasy", "mystery"])
        self.assertEqual(doc["items"][1]["elements"]["genres"], ["fantasy"])
        self.assertEqual(doc["items"][0]["elements"]["status"], "reading")   # a single choice stays a string
        # Without the schema the cell goes as written: keepr splits it on ";" itself.
        bare = self.path("bare.json")
        run("csv", "--file", csv_path, "--card", "book", "--out", bare)
        with open(bare) as fh:
            self.assertEqual(json.load(fh)["items"][0]["elements"]["genres"], "fantasy; mystery ;")

    def test_the_codes_of_the_data_types_second_pass_are_known(self):
        keepr = load_module()
        for code in ("duplicate_value", "invalid_url", "too_long", "pattern", "account_link_needs_access", "session_required"):
            self.assertIn(code, keepr.KNOWN_ERROR_CODES)

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

    def test_one_import_id_rides_on_every_batch_and_the_commit_after_a_dry_run(self):
        rows = self.write_rows([{"card": "book", "elements": {"title": f"Book {i}"},
                                 "source": {"externalId": f"b{i}"}} for i in range(250)])
        dry = run("ingest", "--rows", rows, "--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        ids = {c[2]["importId"] for c in CALLS if c[0] == "POST"}
        self.assertEqual(len(ids), 1, "both batches carry the same id")
        (import_id,) = ids
        self.assertRegex(import_id, r"^imp-\d{8}-[0-9a-f]{6}$")
        self.assertIn(f"import {import_id}", dry.stdout)
        CALLS.clear()
        commit = run("ingest", "--rows", rows)
        self.assertEqual(commit.returncode, 0, commit.stderr)
        self.assertEqual({c[2]["importId"] for c in CALLS if c[0] == "POST"}, {import_id}, "the commit reuses the dry run's id")
        self.assertIn("Settings → Imports", commit.stdout)
        CALLS.clear()
        again = run("ingest", "--rows", rows, "--mode", "upsert")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertNotIn(import_id, {c[2]["importId"] for c in CALLS if c[0] == "POST"}, "a finished import's rows re-sent are a new import")

    def test_import_id_can_be_named_and_an_older_keepr_gets_the_rows_without_it(self):
        rows = self.write_rows([{"card": "book", "elements": {"title": "Dune"}, "source": {"externalId": "d1"}}])
        named = run("ingest", "--rows", rows, "--import-id", "shelf-1")
        self.assertEqual(named.returncode, 0, named.stderr)
        self.assertEqual([c[2]["importId"] for c in CALLS if c[0] == "POST"], ["shelf-1"])
        self.assertEqual(run("ingest", "--rows", rows, "--import-id", "has spaces").returncode, 1)
        CALLS.clear()
        INGEST["refuse_import_id"] = True
        self.addCleanup(lambda: INGEST.update(refuse_import_id=False))
        old = run("ingest", "--rows", rows)
        self.assertEqual(old.returncode, 0, old.stderr)
        posts = [c[2] for c in CALLS if c[0] == "POST"]
        self.assertEqual(len(posts), 2)
        self.assertNotIn("importId", posts[1])

    def shelves_then_books(self):
        # 200 shelves fill batch 1; the books in batch 2 name two of them.
        return self.write_rows(
            [{"card": "shelf", "elements": {"name": f"Shelf {i}"},
              "source": {"externalId": f"s{i}", **({"createdAt": "2019-04-02"} if i == 7 else {})}} for i in range(200)]
            + [{"card": "book", "elements": {"title": "Dune", "shelf": {"$ref": "s5"}}, "source": {"externalId": "d1"}},
               {"card": "book", "elements": {"title": "Emma", "shelf": {"$ref": "s7"}}, "source": {"externalId": "e1"}},
               {"card": "book", "elements": {"title": "Lost", "shelf": {"$ref": "nowhere"}}, "source": {"externalId": "l1"}}])

    def test_a_dry_run_over_batches_carries_the_rows_a_later_batch_names(self):
        rows = self.shelves_then_books()
        result = run("ingest", "--rows", rows, "--dry-run")
        self.assertEqual(result.returncode, 2, "the $ref to nowhere is still refused")
        posts = [c[2] for c in CALLS if c[0] == "POST"]
        self.assertNotIn("wouldCreate", posts[0])
        self.assertEqual(posts[1]["wouldCreate"], [{"card": "shelf", "externalId": "s5"},
                                                  {"card": "shelf", "externalId": "s7", "createdAt": "2019-04-02"}],
                         "only the rows batch 2 names, never the whole import")
        self.assertNotIn("FAILED d1", result.stdout)
        self.assertIn("FAILED l1", result.stdout)
        self.assertNotIn("CAVEAT", result.stdout)
        CALLS.clear()
        commit = run("ingest", "--rows", rows)
        self.assertTrue(all("wouldCreate" not in c[2] for c in CALLS if c[0] == "POST"), "a commit's batches have written their rows")

    def test_an_older_keepr_gets_the_dry_run_without_it_and_is_explained(self):
        INGEST["refuse_would_create"] = True
        self.addCleanup(lambda: INGEST.update(refuse_would_create=False))
        result = run("ingest", "--rows", self.shelves_then_books(), "--dry-run")
        posts = [c[2] for c in CALLS if c[0] == "POST"]
        self.assertEqual(len(posts), 3, "batch 1, batch 2 refused, batch 2 again")
        self.assertNotIn("wouldCreate", posts[2])
        self.assertIn("FAILED d1", result.stdout)
        self.assertIn("CAVEAT: this keepr cannot carry a dry run across batches", result.stdout)

    def test_a_row_note_is_printed_and_saved(self):
        rows = self.write_rows([{"card": "book", "elements": {"title": "Dune"},
                                 "source": {"externalId": "d1", "createdAt": "1965-08-01"}}])
        result = run("ingest", "--rows", rows, "--mode", "upsert")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NOTE d1: source is fixed when the item is created", result.stdout)
        posted = [c for c in CALLS if c[0] == "POST"][0][2]
        self.assertEqual(posted["items"][0]["source"]["createdAt"], "1965-08-01", "sent as written")
        with open(rows.replace(".json", ".results.json")) as fh:
            self.assertEqual(json.load(fh)["notes"][0]["externalId"], "d1")

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
        self.assertFalse([c for c in CALLS if c[0] == "POST" and c[1] == "/api/card-definitions"])

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
        posts = [c[2] for c in CALLS if c[0] == "POST" and c[1] == "/api/card-definitions"]
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[1]["elements"][0]["options"]["lookupCardId"], "85a1b2c3d4e5f6a7b8c9d0e9")
        self.assertEqual(posts[0]["elements"][0]["label"], {"singular": "Name", "plural": "Names"})

    def write_spec(self, cards):
        spec = self.path("cards.json")
        with open(spec, "w") as fh:
            json.dump(cards, fh)
        return spec

    def test_a_parent_that_names_nothing_is_refused_before_anything_is_created(self):
        spec = self.write_spec([
            {"name": "Epic", "key": "epic", "elements": [{"name": "title", "label": "Title", "dataType": "text-small"}]},
            {"name": "Story", "key": "story", "parentCard": "work-itm",
             "elements": [{"name": "points", "label": "Points", "dataType": "integer"}]},
        ])
        result = run("create-card", "--collection", COLLECTION, "--spec", spec, "--apply")
        self.assertEqual(result.returncode, 1)
        self.assertIn("nothing was created", result.stderr)
        self.assertIn("parentCard 'work-itm' is not in the collection, earlier in this spec, or a global card", result.stderr)
        self.assertFalse([c for c in CALLS if c[0] == "POST" and c[1] == "/api/card-definitions"], "not even the first, valid card")

    def test_a_parent_later_in_the_spec_is_refused_with_the_fix(self):
        spec = self.write_spec([
            {"name": "Story", "key": "story", "parentCard": "work-item",
             "elements": [{"name": "points", "label": "Points", "dataType": "integer"}]},
            {"name": "Work item", "key": "work-item", "elements": [{"name": "title", "label": "Title", "dataType": "text-small"}]},
        ])
        result = run("create-card", "--collection", COLLECTION, "--spec", spec, "--apply")
        self.assertEqual(result.returncode, 1)
        self.assertIn("comes later in the spec. Put the parent first", result.stderr)
        self.assertFalse([c for c in CALLS if c[0] == "POST" and c[1] == "/api/card-definitions"])

    def test_a_global_parent_is_found_by_key_and_sent_by_id(self):
        spec = self.write_spec({"name": "Author", "key": "author", "parentCard": "person",
                                "elements": [{"name": "pen-name", "label": "Pen name", "dataType": "text-small"}]})
        result = run("create-card", "--collection", COLLECTION, "--spec", spec, "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        posts = [c[2] for c in CALLS if c[0] == "POST" and c[1] == "/api/card-definitions"]
        self.assertEqual(posts[0]["parentCardId"], PERSON_DEF["_id"])

    def test_a_bad_lookup_in_a_later_card_stops_the_whole_spec(self):
        spec = self.write_spec([
            {"name": "Author", "key": "author", "elements": [{"name": "name", "label": "Name", "dataType": "text-small"}]},
            {"name": "Note", "key": "note",
             "elements": [{"name": "about", "label": "About", "dataType": "card-lookup", "lookupCard": "nowhere"}]},
        ])
        result = run("create-card", "--collection", COLLECTION, "--spec", spec, "--apply")
        self.assertEqual(result.returncode, 1)
        self.assertIn("looks up card 'nowhere'", result.stderr)
        self.assertFalse([c for c in CALLS if c[0] == "POST" and c[1] == "/api/card-definitions"], "the first card is not created either")

    # -------------------------------------------------- card blueprints (2.1)

    def blueprint_stub(self, problems=(), apply=None):
        def preview(bp):
            return {"wouldApply": not problems, "problems": list(problems),
                    "steps": [{"kind": "card", "localId": c["localId"], "key": c["key"], "name": c["name"],
                               **({"parent": c["parentRef"]} if c.get("parentRef") else {})} for c in bp["cards"]],
                    "summary": [f"Creates {len(bp['cards'])} cards in \"My Books\"."]}
        BLUEPRINTS.update(enabled=True, preview=preview,
                          apply=apply or (lambda bp: (201, {"collectionId": COLLECTION, "cards": [
                              {"localId": c["localId"], "id": "8" * 24, "key": c["key"], "name": c["name"]} for c in bp["cards"]],
                              "filters": [{"id": "1" * 24, "name": f["name"]} for f in bp.get("collection", {}).get("savedFilters", [])],
                              "layouts": [], "quickAdds": [], "elementSets": []})))
        self.addCleanup(lambda: BLUEPRINTS.update(enabled=False))

    def test_a_spec_becomes_one_blueprint_with_references_not_ids(self):
        self.blueprint_stub()
        spec = self.write_spec({"cards": [
            {"name": "Task", "key": "task", "parentCard": "book", "displayTemplate": "{{title}}",
             "elements": [{"name": "title", "label": "Title", "dataType": "text-small"},
                          {"name": "depends-on", "label": "Depends on", "dataType": "card-lookup", "lookupCard": "task"},
                          {"name": "epic", "label": "Epic", "dataType": "card-lookup", "lookupCard": "epic"}]},
            {"name": "Epic", "key": "epic", "elements": [{"name": "name", "label": "Name", "dataType": "text-small"}]},
        ], "filters": [{"name": "Open", "query": "status = open"}], "layouts": [{"card": "task", "columns": ["title", "updatedAt", "sourceCreatedAt"]}]})
        result = run("create-card", "--collection", COLLECTION, "--spec", spec)
        self.assertEqual(result.returncode, 0, result.stderr)
        sent = [c[2] for c in CALLS if c[0] == "POST" and c[1].endswith("/blueprints/preview")][0]["blueprint"]
        task = sent["cards"][0]
        self.assertEqual(task["parentRef"], {"key": "book"})
        self.assertEqual(task["elements"][1]["options"]["lookupCardId"], {"ref": "task"}, "a self-lookup")
        self.assertEqual(task["elements"][2]["options"]["lookupCardId"], {"ref": "epic"}, "a card later in the spec")
        self.assertEqual(sent["collection"]["cardLayouts"][0]["body"]["columns"], [{"element": "title"}, {"system": "updatedAt"}, {"system": "sourceCreatedAt"}],
                         "an element the card has wins over the system column of the same name")
        self.assertIn("Creates 2 cards", result.stdout)
        self.assertIn("would create card 'task'", result.stdout)
        self.assertFalse([c for c in CALLS if c[1] == "/api/card-definitions"], "no card-by-card write")

    def test_tags_and_a_paused_rule_ride_the_blueprint(self):
        def preview(bp):
            steps = [{"kind": "card", "localId": c["localId"], "key": c["key"], "name": c["name"]} for c in bp["cards"]]
            steps += [{"kind": "tag", "localId": t["localId"], "name": t["name"]} for t in bp["collection"]["tags"]]
            steps += [{"kind": "tagRule", "tag": t["localId"], "name": t["name"], "card": t["rule"]["cardRef"], "strict": False, "paused": True}
                      for t in bp["collection"]["tags"] if t.get("rule")]
            return {"wouldApply": True, "problems": [], "steps": steps, "summary": ["Creates 1 card in \"My Books\", with 2 tags."]}
        BLUEPRINTS.update(enabled=True, preview=preview, apply=lambda bp: (201, {
            "collectionId": COLLECTION, "cards": [{"localId": "task", "id": "8" * 24, "key": "task", "name": "Task"}],
            "filters": [], "layouts": [], "quickAdds": [], "elementSets": [], "members": [],
            "tags": [{"localId": "tag-work", "id": "6" * 24, "name": "Work"}, {"localId": "tag-late", "id": "7" * 24, "name": "Late"}],
            "rules": [{"localId": "tag-late", "tagId": "7" * 24, "name": "Late", "enabled": False, "preview": {"total": 4, "matching": 3, "complete": True}}]}))
        self.addCleanup(lambda: BLUEPRINTS.update(enabled=False))
        spec = self.write_spec({"cards": [{"name": "Task", "key": "task", "elements": [{"name": "status", "label": "Status", "dataType": "text-small"}]}],
                                "tags": [{"name": "Work", "color": "emerald"},
                                         {"name": "Late", "parent": "Work", "rule": {"card": "task", "where": "status = open"}}]})
        shown = run("create-card", "--collection", COLLECTION, "--spec", spec)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        sent = [c[2] for c in CALLS if c[0] == "POST" and c[1].endswith("/blueprints/preview")][-1]["blueprint"]
        self.assertEqual(sent["collection"]["tags"], [
            {"localId": "tag-work", "name": "Work", "color": "emerald"},
            {"localId": "tag-late", "name": "Late", "parentRef": {"ref": "tag-work"}, "rule": {"cardRef": {"ref": "task"}, "where": "status = open"}},
        ])
        self.assertIn("would add the tag 'Late'", shown.stdout)
        self.assertIn("would apply 'Late' by a rule on task — PAUSED", shown.stdout)
        applied = run("create-card", "--collection", COLLECTION, "--spec", spec, "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("'Late' is applied by a rule, PAUSED, would tag 3 of 4 items now", applied.stdout)

    def test_a_tag_whose_parent_is_not_in_the_spec_is_refused_before_any_call(self):
        self.blueprint_stub()
        spec = self.write_spec({"cards": [{"name": "Task", "key": "task", "elements": [{"name": "t", "label": "T", "dataType": "text-small"}]}],
                                "tags": [{"name": "Late", "parent": "Elsewhere"}]})
        result = run("create-card", "--collection", COLLECTION, "--spec", spec)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not a tag in the spec", result.stderr)
        self.assertFalse([c for c in CALLS if c[1].endswith("/blueprints/preview")])

    def test_blueprint_problems_are_listed_and_nothing_is_created(self):
        self.blueprint_stub(problems=[{"path": "cards[0].key", "code": "key_taken", "message": "A card with the key \"book\" already exists."}])
        spec = self.write_spec({"name": "Book 2", "key": "book2", "elements": [{"name": "t", "label": "T", "dataType": "text-small"}]})
        result = run("create-card", "--collection", COLLECTION, "--spec", spec)
        self.assertEqual(result.returncode, 1)
        self.assertIn("cards[0].key: A card with the key \"book\" already exists. (key_taken)", result.stderr)

    def test_apply_is_one_call_and_reports_what_keepr_stored(self):
        self.blueprint_stub()
        spec = self.write_spec({"name": "Epic", "key": "epic", "elements": [{"name": "name", "label": "Name", "dataType": "text-small"}]})
        result = run("create-card", "--collection", COLLECTION, "--spec", spec, "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("created card 'epic' → " + "8" * 24, result.stdout)
        self.assertEqual(len([c for c in CALLS if c[1].endswith("/blueprints/apply")]), 1)

    def test_a_global_card_the_blueprint_joins_is_named_before_and_after(self):
        def preview(bp):
            return {"wouldApply": True, "problems": [],
                    "steps": [{"kind": "member", "key": "person", "name": "Person"},
                              {"kind": "card", "localId": "epic", "key": "epic", "name": "Epic"}],
                    "summary": ["Creates 1 card in \"My Books\".", "Adds the global card \"Person\" to the collection, because the blueprint refers to it."]}
        BLUEPRINTS.update(enabled=True, preview=preview, apply=lambda bp: (201, {
            "collectionId": COLLECTION, "cards": [{"localId": "epic", "id": "8" * 24, "key": "epic", "name": "Epic"}],
            "filters": [], "layouts": [], "quickAdds": [], "elementSets": [],
            "members": [{"id": "9" * 24, "key": "person", "name": "Person"}]}))
        self.addCleanup(lambda: BLUEPRINTS.update(enabled=False))
        spec = self.write_spec({"name": "Epic", "key": "epic", "elements": [{"name": "name", "label": "Name", "dataType": "text-small"}]})
        shown = run("create-card", "--collection", COLLECTION, "--spec", spec)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("would add the global card 'person' (Person) to the collection", shown.stdout)
        applied = run("create-card", "--collection", COLLECTION, "--spec", spec, "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("added the global card 'person' to the collection", applied.stdout)

    def test_a_refused_apply_says_whether_anything_was_left(self):
        self.blueprint_stub(apply=lambda bp: (400, {"statusCode": 400, "message": "bad filter", "code": "invalid_query",
                                                    "blueprint": {"compensated": True, "remaining": []}}))
        spec = self.write_spec({"name": "Epic", "key": "epic", "elements": [{"name": "name", "label": "Name", "dataType": "text-small"}]})
        result = run("create-card", "--collection", COLLECTION, "--spec", spec, "--apply")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Nothing was kept", result.stderr)

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
        # The batch read carries no tags (keepr projects elements only), and a
        # legacy tag string is never printed.
        self.assertNotIn("tags:", out.stdout)
        self.assertNotIn("scifi", out.stdout)
        self.assertIn(f"https://keepr.cloud/collections/{COLLECTION}/items/{ITEMS[0]['_id']}", out.stdout)
        ids_call = [c for c in CALLS if c[0] == "GET" and "ids=" in c[1]][0][1]
        self.assertIn("ids=" + ",".join([ITEMS[0]["_id"], ITEMS[1]["_id"], "bbbbbbbbbbbbbbbbbbbbbbb9"]), ids_call)

    def test_get_one_item_names_its_tags_who_applied_them_and_the_owners_own(self):
        out = run("get", "--id", ITEMS[0]["_id"])
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("  tags: Sci-fi, Top shelf, (a tag this key cannot name, d0a1b2c3d4e5f6a7b8c9d0e2), Overdue (by a rule)", out.stdout)
        self.assertIn("  my tags: To reread  (only the key's owner sees these)", out.stdout)
        self.assertNotIn("scifi", out.stdout, "the legacy string list is never printed")

    def test_items_lines_carry_the_tags(self):
        out = run("items", "--collection", COLLECTION)
        self.assertEqual(out.returncode, 0, out.stderr)
        dune = next(line for line in out.stdout.splitlines() if "Dune" in line)
        self.assertIn("· tags: Sci-fi, Top shelf", dune)
        self.assertIn("· my tags: To reread", dune)
        piranesi = next(line for line in out.stdout.splitlines() if "Piranesi" in line)
        self.assertNotIn("tags:", piranesi)

    def test_get_one_unreadable_item_is_a_count_not_a_crash(self):
        out = run("get", "--id", "bbbbbbbbbbbbbbbbbbbbbbb9")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("0 of 1 requested — 1 not readable by this key", out.stdout)

    def test_get_refuses_a_non_id_before_any_call(self):
        out = run("get", "--id", "dune")
        self.assertEqual(out.returncode, 1)
        self.assertIn("Not item ids", out.stderr)
        self.assertEqual(CALLS, [])

    def test_search_includes_tags_by_default_and_types_narrows(self):
        out = run("search", "--q", "shelf", "--types", "tags")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith('"shelf": tags 3'), out.stdout)
        self.assertEqual([c[1].split("?")[0] for c in CALLS if c[0] == "GET"], ["/api/tags/search"], "no record search")
        self.assertIn("tag         c0a1b2c3d4e5f6a7b8c9d0e2   Genre/Sci-fi  in collection My Books", out.stdout)
        self.assertIn("item tag    d0a1b2c3d4e5f6a7b8c9d0e1   Top shelf  (an item used as a tag — send this id", out.stdout)
        self.assertIn("my tag      f0a1b2c3d4e5f6a7b8c9d0e1   To reread  (private — only you see it; never on a row)", out.stdout)
        CALLS.clear()
        out = run("search", "--q", "dune")
        self.assertEqual(out.returncode, 0, out.stderr)
        asked = [c[1].split("?")[0] for c in CALLS if c[0] == "GET"]
        self.assertIn("/api/search", asked)
        self.assertIn("/api/tags/search", asked, "records and tags by default (b31)")
        self.assertIn(" · tags 3", out.stdout.splitlines()[0])
        CALLS.clear()
        run("search", "--q", "dune", "--types", "items")
        self.assertFalse([c for c in CALLS if "/api/tags/search" in c[1]], "--types narrows it: items alone ask no tag search")

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

    # -------------------------------------------------- staying current

    def current_version(self):
        with open(os.path.join(HERE, "..", "VERSION"), encoding="utf-8") as fh:
            return fh.read().strip()

    def clients_doc(self, latest):
        return {"latest": {"skill": latest, "server": "0.2.4"}, "summary": "Something new.",
                "channels": {
                    "skill": {"name": "the keepr skill", "how": "assistant",
                              "commands": ["python3 scripts/keepr.py update"],
                              "steps": ["The new version is used from the next command on."],
                              "guide": "https://keepr.cloud/docs/guides/assistants/update-your-assistant#another-coding-agent"},
                    "plugin": {"name": "the keepr plugin for Claude Code", "how": "assistant",
                               "commands": ["claude plugin marketplace update keepr-agent", "claude plugin update keepr@keepr-agent"],
                               "steps": ["Restart Claude Code to use the new version."],
                               "guide": "https://keepr.cloud/docs/guides/assistants/update-your-assistant#claude-code-plugin"},
                    "claude-ai": {"name": "the keepr skill in Claude", "how": "manual",
                                  "steps": ["Download the new skill.", "In Claude, open Settings, then Skills."],
                                  "guide": "https://keepr.cloud/docs/guides/assistants/update-your-assistant#the-skill-in-claude"}}}

    def copy_of_skill(self):
        """A throwaway install of this skill, so `update` rewrites a copy and never the source."""
        target = os.path.join(self.tmp, "skills", "keepr")
        shutil.copytree(os.path.join(HERE, ".."), target, ignore=shutil.ignore_patterns("__pycache__", "tests"))
        return target

    def test_every_request_names_this_copy(self):
        run("collections")
        want = f"keepr-skill/{self.current_version()} (skill)"
        self.assertTrue(CLIENT_HEADERS and all(h == want for h in CLIENT_HEADERS), CLIENT_HEADERS)
        CLIENT_HEADERS.clear()
        run("collections", env={"KEEPR_CLIENT_CHANNEL": "plugin"})
        self.assertEqual(CLIENT_HEADERS[0], f"keepr-skill/{self.current_version()} (plugin)")

    def test_a_copy_behind_says_so_once_a_day_with_the_steps_for_its_channel(self):
        DOCS["clients"] = self.clients_doc("99.0.0")
        # A throwaway install: the repo's own copy sits in a git checkout, where
        # the note sends people to the guide instead of offering to rewrite it.
        script = os.path.join(self.copy_of_skill(), "scripts", "keepr.py")
        first = run("collections", env={"KEEPR_UPDATE_CHECK": "on"}, script=script)
        self.assertEqual(first.returncode, 0)
        self.assertIn(f"KEEPR UPDATE: the keepr skill is out of date (keepr skill {self.current_version()}; 99.0.0 is out: Something new.).", first.stderr)
        self.assertLess(first.stderr.find("KEEPR UPDATE"), len(first.stderr), "on stderr")
        self.assertNotIn("KEEPR UPDATE", first.stdout, "never mixed into the command's own output")
        self.assertIn("You can update it yourself: run `python3 scripts/keepr.py update`", first.stderr)
        self.assertIn("after answering what they asked", first.stderr)
        second = run("collections", env={"KEEPR_UPDATE_CHECK": "on"}, script=script)
        self.assertNotIn("KEEPR UPDATE", second.stderr, "asked once a day, not on every command")

    def test_a_copy_in_a_git_checkout_is_sent_to_the_guide_not_told_to_rewrite_itself(self):
        DOCS["clients"] = self.clients_doc("99.0.0")
        copy = self.copy_of_skill()
        os.makedirs(os.path.join(self.tmp, ".git"))
        note = run("collections", env={"KEEPR_UPDATE_CHECK": "on"}, script=os.path.join(copy, "scripts", "keepr.py")).stderr
        self.assertIn("KEEPR UPDATE", note)
        self.assertNotIn("keepr.py update", note)
        self.assertIn("How to update: https://keepr.cloud/docs/guides/assistants/update-your-assistant#another-coding-agent", note)

    def test_a_current_copy_and_an_older_deployment_say_nothing(self):
        DOCS["clients"] = self.clients_doc(self.current_version())
        self.assertNotIn("KEEPR UPDATE", run("collections", env={"KEEPR_UPDATE_CHECK": "on"}).stderr)
        os.remove(self.config_path("update-check.json"))
        DOCS["clients"] = None
        result = run("collections", env={"KEEPR_UPDATE_CHECK": "on"})
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("KEEPR UPDATE", result.stderr)

    def test_update_rewrites_a_copy_installed_from_the_skill_link(self):
        copy = self.copy_of_skill()
        with open(os.path.join(copy, "references", "retired.md"), "w") as fh:
            fh.write("a file the new release no longer has")
        DOCS["clients"] = self.clients_doc("99.0.0")
        DOCS["skill"] = {"version": "99.0.0", "files": {
            "SKILL.md": "---\nname: keepr\n---\nnew", "VERSION": "99.0.0\n", "scripts/keepr.py": "print('new')\n"}}
        # Run from INSIDE the skill folder, the way the note says to: the shell's
        # working directory must survive the update.
        result = run("update", script="scripts/keepr.py", cwd=copy)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"Updated the keepr skill from {self.current_version()} to 99.0.0.", result.stdout)
        with open(os.path.join(copy, "VERSION")) as fh:
            self.assertEqual(fh.read().strip(), "99.0.0")
        self.assertFalse(os.path.exists(os.path.join(copy, "references", "retired.md")), "what the release dropped is removed")
        self.assertTrue(os.access(os.path.join(copy, "scripts", "keepr.py"), os.X_OK), "the script stays executable")
        self.assertEqual(os.listdir(os.path.dirname(copy)), ["keepr"], "nothing is left beside the skill")
        backups = os.listdir(self.config_path("skill-backups"))
        self.assertEqual(len(backups), 1, "the previous version is kept")
        after = subprocess.run([sys.executable, "scripts/keepr.py", "--help"], cwd=copy, capture_output=True, text=True)
        self.assertEqual(after.returncode, 0, "the same shell can run the next command")

    def test_update_never_touches_a_folder_that_is_not_a_keepr_skill(self):
        # keepr.py copied into somebody's project, beside that project's VERSION.
        project = os.path.join(self.tmp, "myproject")
        os.makedirs(os.path.join(project, "scripts"))
        os.makedirs(os.path.join(project, "src"))
        shutil.copy(SCRIPT, os.path.join(project, "scripts", "keepr.py"))
        with open(os.path.join(project, "VERSION"), "w") as fh:
            fh.write("1.2.3\n")
        with open(os.path.join(project, "src", "precious.c"), "w") as fh:
            fh.write("int main(void) { return 0; }\n")
        DOCS["clients"] = self.clients_doc("99.0.0")
        DOCS["skill"] = {"version": "99.0.0", "files": {"SKILL.md": "x", "VERSION": "99.0.0", "scripts/keepr.py": "x"}}
        result = run("update", script=os.path.join(project, "scripts", "keepr.py"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a keepr skill", result.stderr)
        self.assertTrue(os.path.exists(os.path.join(project, "src", "precious.c")))
        CLIENT_HEADERS.clear()
        run("collections", script=os.path.join(project, "scripts", "keepr.py"))
        self.assertTrue(CLIENT_HEADERS and all(h is None for h in CLIENT_HEADERS), "and it never claims to be one")

    def test_update_refuses_a_skill_holding_things_that_are_not_the_skills(self):
        copy = self.copy_of_skill()
        with open(os.path.join(copy, "my-notes.md"), "w") as fh:
            fh.write("mine")
        DOCS["clients"] = self.clients_doc("99.0.0")
        DOCS["skill"] = {"version": "99.0.0", "files": {"SKILL.md": "x", "VERSION": "99.0.0", "scripts/keepr.py": "x"}}
        result = run("update", script=os.path.join(copy, "scripts", "keepr.py"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("my-notes.md", result.stderr)
        self.assertTrue(os.path.exists(os.path.join(copy, "my-notes.md")))

    def test_update_leaves_a_git_checkout_alone(self):
        copy = self.copy_of_skill()
        os.makedirs(os.path.join(self.tmp, ".git"))
        DOCS["clients"] = self.clients_doc("99.0.0")
        result = run("update", script=os.path.join(copy, "scripts", "keepr.py"))
        self.assertEqual(result.returncode, 0)
        self.assertIn("git checkout", result.stdout)
        with open(os.path.join(copy, "VERSION")) as fh:
            self.assertEqual(fh.read().strip(), self.current_version())

    def test_a_plugin_is_recognised_by_its_manifest_wherever_it_lives(self):
        plugin = os.path.join(self.tmp, "anywhere", "keepr")
        os.makedirs(os.path.join(plugin, ".claude-plugin"))
        with open(os.path.join(plugin, ".claude-plugin", "plugin.json"), "w") as fh:
            fh.write("{}")
        target = os.path.join(plugin, "skills", "keepr")
        shutil.copytree(os.path.join(HERE, ".."), target, ignore=shutil.ignore_patterns("__pycache__", "tests"))
        run("collections", script=os.path.join(target, "scripts", "keepr.py"))
        self.assertEqual(CLIENT_HEADERS[0], f"keepr-skill/{self.current_version()} (plugin)")

    def test_a_malformed_clients_answer_never_breaks_a_command(self):
        for doc in ([1, 2], {"latest": "2.0.4"}, {"latest": {"skill": "99.0.0"}, "channels": {"skill": "x"}},
                    {"latest": {"skill": "99.0.0"}, "channels": {"skill": {"steps": "not a list"}}}):
            with self.subTest(doc=doc):
                try:
                    os.remove(self.config_path("update-check.json"))
                except OSError:
                    pass
                DOCS["clients"] = doc
                result = run("collections", env={"KEEPR_UPDATE_CHECK": "on"})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
        os.makedirs(self.config_path(), exist_ok=True)
        with open(self.config_path("update-check.json"), "w") as fh:
            fh.write('{"checkedAt": [1]}')
        result = run("collections", env={"KEEPR_UPDATE_CHECK": "on"})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_update_refuses_a_bundle_that_would_write_outside_the_skill(self):
        copy = self.copy_of_skill()
        DOCS["clients"] = self.clients_doc("99.0.0")
        DOCS["skill"] = {"version": "99.0.0", "files": {
            "SKILL.md": "x", "VERSION": "99.0.0", "scripts/keepr.py": "x", "../escaped.py": "x"}}
        result = run("update", script=os.path.join(copy, "scripts", "keepr.py"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("Nothing was changed", result.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "skills", "escaped.py")))
        with open(os.path.join(copy, "VERSION")) as fh:
            self.assertEqual(fh.read().strip(), self.current_version())

    def test_update_in_a_plugin_says_how_and_writes_nothing(self):
        copy = self.copy_of_skill()
        DOCS["clients"] = self.clients_doc("99.0.0")
        result = run("update", script=os.path.join(copy, "scripts", "keepr.py"), env={"KEEPR_CLIENT_CHANNEL": "plugin"})
        self.assertEqual(result.returncode, 0)
        self.assertIn("run: claude plugin marketplace update keepr-agent", result.stdout)
        self.assertIn("Restart Claude Code", result.stdout)
        self.assertFalse(any("/api/docs/skill" in c[1] for c in CALLS), "a plugin's folder is never rewritten")

    def test_update_when_current_says_so(self):
        DOCS["clients"] = self.clients_doc(self.current_version())
        result = run("update")
        self.assertEqual(result.returncode, 0)
        self.assertIn(f"The keepr skill {self.current_version()} is up to date.", result.stdout)


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 0), Stub)
    BASE = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        unittest.main(verbosity=2)
    finally:
        server.shutdown()
