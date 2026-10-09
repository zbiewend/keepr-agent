#!/usr/bin/env node

// dist/src/config.js
import { readFileSync } from "node:fs";
import { join } from "node:path";

// dist/src/cleanText.js
var MAX_LABEL = 120;
var NAME_MAX = 200;
var INVISIBLE = /[\p{Cc}\p{Default_Ignorable_Code_Point}\u2800]/gu;
function cleanText(raw, max = MAX_LABEL) {
  const one = raw.replace(/[\t\n\r\v\f\u0085]/g, " ").replace(INVISIBLE, "").replace(/\s+/g, " ").trim();
  const chars = Array.from(one);
  return chars.length > max ? `${chars.slice(0, max - 1).join("")}\u2026` : one;
}
var HIDDEN = new RegExp("[\\p{Cc}\\p{Zl}\\p{Zp}\\p{Default_Ignorable_Code_Point}\\u2800]|(?! )\\p{Zs}", "u");
var HIDDEN_ALL = new RegExp(HIDDEN.source, "gu");
function hasHidden(raw) {
  return HIDDEN.test(raw);
}
function needsEscape(raw) {
  return hasHidden(raw) || /["\\]/.test(raw) || raw !== raw.trim();
}
function identifierText(raw) {
  if (!needsEscape(raw))
    return raw;
  return JSON.stringify(raw).replace(HIDDEN_ALL, (ch) => {
    const cp = ch.codePointAt(0);
    return cp > 65535 ? `\\u{${cp.toString(16)}}` : `\\u${cp.toString(16).padStart(4, "0")}`;
  });
}
function identifierQuoted(raw) {
  return needsEscape(raw) ? identifierText(raw) : `"${raw}"`;
}
function quoted(raw, max = NAME_MAX) {
  return `"${sayName(raw, max)}"`;
}
function sayName(raw, max = NAME_MAX) {
  return cleanText(raw === null || raw === void 0 ? "" : String(raw), max).replace(/"/g, "'");
}

// dist/src/updates.js
var CHANNELS = ["connector", "plugin", "skill", "claude-ai", "extension", "local"];
function channelFromEnv(value) {
  const v = String(value ?? "").trim();
  return CHANNELS.includes(v) && v !== "connector" ? v : "local";
}
function clientHeader(version2, channel) {
  return `keepr-mcp/${version2} (${channel})`;
}
function compareVersions(a, b) {
  const pa = a.split(".").map(Number);
  const pb = b.split(".").map(Number);
  for (let i = 0; i < 3; i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d)
      return d < 0 ? -1 : 1;
  }
  return 0;
}
var TTL_MS = 10 * 6e4;
var cache = /* @__PURE__ */ new Map();
async function fetchClients(http, baseUrl, now = Date.now()) {
  const hit = cache.get(baseUrl);
  if (hit && now - hit.at < TTL_MS)
    return hit.doc;
  let doc = null;
  try {
    const res = await http.request({ path: "/api/docs/clients", anonymous: true, timeoutMs: 3e3, attempts: 1 });
    if (res.ok && res.body && typeof res.body === "object")
      doc = res.body;
  } catch {
  }
  cache.set(baseUrl, { at: now, doc });
  return doc;
}
var strings = (v) => Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
var version = (v) => typeof v === "string" && /^\d{1,4}\.\d{1,4}\.\d{1,4}$/.test(v) ? v : null;
function channelUpdate(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw))
    return null;
  const r = raw;
  if (typeof r.name !== "string" || typeof r.guide !== "string")
    return null;
  const how = r.how === "automatic" || r.how === "assistant" ? r.how : "manual";
  return {
    name: cleanText(r.name),
    how,
    commands: strings(r.commands),
    steps: strings(r.steps).map((st) => cleanText(st, 600)),
    ...typeof r.tip === "string" ? { tip: cleanText(r.tip, 600) } : {},
    guide: cleanText(r.guide, 600)
  };
}
function statusFrom(doc, current, channel) {
  if (!doc || typeof doc !== "object")
    return null;
  const latestDoc = doc.latest && typeof doc.latest === "object" ? doc.latest : {};
  const latest = version(latestDoc.server);
  const latestSkill = version(latestDoc.skill);
  const upToDate = channel === "connector" || !latest || compareVersions(current, latest) >= 0;
  const channels = doc.channels && typeof doc.channels === "object" ? doc.channels : {};
  const update = channelUpdate(channels[channel]);
  return { channel, current, latest, latestSkill, upToDate, summary: typeof doc.summary === "string" ? cleanText(doc.summary, 1e3) : null, update };
}
function updateNotice(status) {
  try {
    if (!status || status.upToDate || !status.update || !status.latest)
      return null;
    const u = status.update;
    const lines = [
      `KEEPR UPDATE: ${u.name} is out of date (keepr-mcp ${status.current}; ${status.latest} is out${status.summary ? `: ${status.summary}` : ""}). This note comes once per session.`
    ];
    const commands = u.commands ?? [];
    if (u.how === "assistant" && commands.length) {
      lines.push(`It updates with ${commands.map((c) => `\`${identifierText(c)}\``).join(", then ")}.`);
      if (u.steps.length)
        lines.push(`After that: ${u.steps.join(" ")}`);
    } else if (u.steps.length) {
      lines.push(`The person's steps: ${u.steps.map((st, i) => `${i + 1}. ${st}`).join(" ")}`);
    }
    if (u.tip)
      lines.push(u.tip);
    lines.push(`More: ${u.guide}`);
    return lines.join("\n");
  } catch {
    return null;
  }
}

// dist/src/keys.files.js
function keyConfig(_env, _readStored, withoutKey) {
  return withoutKey();
}
var keyWords = {
  alsoAKey: "",
  notSignedIn: "Not signed in to keepr: this server has no connection, so every tool refuses. Signing in is done in the browser: the person signs in on keepr's page and presses Allow.",
  keyFrom: (_source) => "a key",
  keyRefused: "",
  nothingToDisconnect: "This server is not connected to keepr. Nothing to disconnect."
};

// dist/src/config.js
var CREDENTIALS_RELATIVE = [".config", "keepr", "credentials"];
function toolsetFromEnv(value) {
  const v = (value ?? "").trim().toLowerCase();
  if (v === "files")
    return { toolset: "files", unknown: null };
  if (v === "" || v === "full")
    return { toolset: "full", unknown: null };
  return { toolset: "full", unknown: value ?? null };
}
function readStoredCredentials(env) {
  const home = (env.HOME || env.USERPROFILE || "").trim();
  if (!home)
    return {};
  const file = join(home, ...CREDENTIALS_RELATIVE);
  let text;
  try {
    text = readFileSync(file, "utf8");
  } catch {
    return {};
  }
  try {
    const doc = JSON.parse(text);
    if (!doc || typeof doc !== "object" || Array.isArray(doc))
      throw new Error("not an object");
    const { url, key, oauth } = doc;
    return {
      url: typeof url === "string" ? url : void 0,
      key: typeof key === "string" ? key : void 0,
      oauth: oauth && typeof oauth === "object" && !Array.isArray(oauth) ? oauth : void 0
    };
  } catch {
    return { unreadable: file };
  }
}
function loadConfig(env = process.env) {
  const toolset = toolsetFromEnv(env.KEEPR_TOOLS).toolset;
  return { ...loadKeyConfig(env, toolset), channel: channelFromEnv(env.KEEPR_CLIENT_CHANNEL), toolset };
}
function loadKeyConfig(env, toolset) {
  const withoutKey = () => {
    const stored = readStoredCredentials(env);
    const baseUrl = (env.KEEPR_URL || stored.url || "https://api.keepr.cloud").trim().replace(/\/+$/, "");
    if (stored.unreadable) {
      return { baseUrl, apiKey: null, keySource: null, keyProblem: `~/${CREDENTIALS_RELATIVE.join("/")} is not a file keepr can read, so this server cannot sign in. The person can delete it, then connect again with keepr_connect.` };
    }
    const connected = typeof stored.oauth?.refreshToken === "string" && stored.oauth.apiUrl === baseUrl;
    return { baseUrl, apiKey: null, keyProblem: null, keySource: connected ? "oauth" : null };
  };
  if (toolset === "files")
    return withoutKey();
  return keyConfig(env, () => readStoredCredentials(env), withoutKey);
}
function keyDisplayPrefix(key) {
  return key.slice(0, 10);
}

// dist/src/http.js
import { setTimeout as sleep } from "node:timers/promises";
import { randomBytes } from "node:crypto";
import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
var RETRY_STATUSES = /* @__PURE__ */ new Set([429, 502, 503, 504]);
var RETRIES = 3;
var TIMEOUT_MS = 12e4;
var PACE_BELOW_REMAINING = 5;
var PACE_MAX_WAIT_MS = 65e3;
var FileChangedError = class extends Error {
  expected;
  sent;
  kind;
  constructor(message, expected, sent, kind = "changed") {
    super(message);
    this.expected = expected;
    this.sent = sent;
    this.kind = kind;
    this.name = "FileChangedError";
  }
};
var KeeprTransportError = class extends Error {
  url;
  cause;
  constructor(message, url, cause) {
    super(message);
    this.url = url;
    this.cause = cause;
    this.name = "KeeprTransportError";
  }
};
var STATUS_HINTS = {
  400: "The request was malformed. The message names the failing rule.",
  // Credential-neutral (the KPR-246 follow-up): the files-only server and
  // every connection hold no key, so this names none. guard.ts adds what
  // fixes it for the credential this server holds — the reconnect sentence
  // on a keepr_connect connection, a new key for a key (src/keys.ts).
  401: "keepr refused the credential this server signs in with: it was revoked, disconnected or has expired, or the account is inactive. Repeating the call does not help.",
  403: "Authenticated, but not allowed to do this. Read the message: it may be scope, role, an unverified email address, or an archived collection.",
  404: "Not found, or not reachable with this credential. Hidden collections answer 404 rather than 403, so this may mean it is not allowed into it. Do not go looking through other collections for somewhere the data fits.",
  409: "A state conflict \u2014 a duplicate, a locked record, or an account already linked.",
  413: "Over a size cap. Send fewer rows, or a smaller file.",
  415: "That file type is refused by the platform. Executables and scripts are never accepted.",
  426: "This copy of keepr-mcp is too old for keepr (client_too_old). Nothing else will work until it is updated: give the person the guide link from the message, in one sentence.",
  428: "This record must be signed by a person. An API key or an assistant's connection cannot do that, because the attestation endpoint needs a real session. This one has to be written in the web app.",
  429: "Rate limited. Stop and wait for the reset rather than retrying."
};
function parseIntOrNull(v) {
  if (v === null)
    return null;
  const n = Number.parseInt(v, 10);
  return Number.isFinite(n) ? n : null;
}
function readRateLimit(h) {
  const limit = parseIntOrNull(h.get("ratelimit-limit"));
  const remaining = parseIntOrNull(h.get("ratelimit-remaining"));
  const reset = parseIntOrNull(h.get("ratelimit-reset"));
  if (limit === null && remaining === null && reset === null)
    return null;
  return { limit, remaining, resetSeconds: reset };
}
var KeeprHttp = class {
  baseUrl;
  apiKey;
  fetchImpl;
  sleepImpl;
  client;
  bearer;
  lastRateLimit = null;
  constructor(baseUrl, apiKey, fetchImpl = fetch, sleepImpl = sleep, client = null, bearer = null) {
    this.baseUrl = baseUrl;
    this.apiKey = apiKey;
    this.fetchImpl = fetchImpl;
    this.sleepImpl = sleepImpl;
    this.client = client;
    this.bearer = bearer;
  }
  rateLimit() {
    return this.lastRateLimit;
  }
  async request(opts) {
    if (!this.bearer || opts.anonymous)
      return this.send(opts, opts.anonymous ? null : this.apiKey);
    const auth = await this.bearer.token();
    const res = await this.send(opts, auth);
    if (res.status !== 401 || !auth)
      return res;
    const next = await this.bearer.afterUnauthorized(auth);
    return next && next !== auth ? this.send(opts, next) : res;
  }
  async send(opts, auth) {
    const method = (opts.method || "GET").toUpperCase();
    const url = this.buildUrl(opts.path, opts.query);
    if ((opts.attempts ?? RETRIES) > 1)
      await this.paceIfNearLimit(opts.maxWaitMs);
    let lastError = null;
    const attempts = Math.max(1, opts.attempts ?? RETRIES);
    for (let attempt = 0; attempt < attempts; attempt++) {
      let res;
      try {
        res = opts.stream ? await this.sendStream(url, method, opts, opts.stream, auth) : await this.fetchImpl(url, this.init(method, opts, auth));
      } catch (err) {
        const changed = fileChanged(err);
        if (changed)
          throw changed;
        lastError = err;
        if (attempt < attempts - 1) {
          await this.sleepImpl(2 ** attempt * 1e3);
          continue;
        }
        throw new KeeprTransportError(`Cannot reach ${this.baseUrl}. ${err?.message ?? String(err)}`, url, err);
      }
      const rate = readRateLimit(res.headers);
      if (rate)
        this.lastRateLimit = rate;
      if (RETRY_STATUSES.has(res.status) && attempt < attempts - 1) {
        const wait = this.backoffFor(res, attempt);
        if (opts.maxWaitMs === void 0 || wait <= opts.maxWaitMs) {
          await this.sleepImpl(wait);
          continue;
        }
      }
      const text = await res.text();
      let parsed = null;
      let nonJson = false;
      if (text.length) {
        try {
          parsed = JSON.parse(text);
        } catch {
          parsed = text;
          nonJson = true;
        }
      }
      return {
        ok: res.ok,
        status: res.status,
        body: parsed,
        totalCount: parseIntOrNull(res.headers.get("x-total-count")),
        rateLimit: rate,
        requestId: res.headers.get("x-request-id"),
        nonJson
      };
    }
    throw new KeeprTransportError(`Cannot reach ${this.baseUrl}.`, url, lastError);
  }
  baseHeaders(opts, auth) {
    const headers = { Accept: "application/json" };
    if (auth && !opts.anonymous)
      headers.Authorization = `Bearer ${auth}`;
    if (this.client)
      headers["X-Keepr-Client"] = this.client;
    return headers;
  }
  /**
   * A streamed upload, over node:http rather than fetch. MEASURED (KPR-182,
   * Node 24, a 300 MB file to a reader slowed to 100 MB/s): fetch's request
   * body ignores backpressure and the process grew by the whole file (333
   * MB), with a ReadableStream body and with openAsBlob alike; node:http
   * piping grew by 58 MB, flat. So the file goes through pipeline(), which
   * reads the next chunk only when the socket has taken the last one.
   * Answers a Response, so the retry and parsing above do not care which.
   */
  sendStream(url, method, opts, file, auth) {
    const { parts, contentType, length } = multipartParts(file);
    const target = new URL(url);
    const send = target.protocol === "https:" ? httpsRequest : httpRequest;
    const timeoutMs = (opts.timeoutMs ?? TIMEOUT_MS) + Math.ceil(file.length / (20 * 1024 * 1024)) * 6e4;
    return new Promise((resolve2, reject) => {
      const req = send(target, {
        method,
        headers: { ...this.baseHeaders(opts, auth), "Content-Type": contentType, "Content-Length": String(length) }
      }, (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("error", reject);
        res.on("end", () => {
          const status = res.statusCode ?? 0;
          try {
            const body = status === 204 || status === 205 || status === 304 ? null : Buffer.concat(chunks);
            resolve2(new Response(body, { status, headers: flatHeaders(res.headers) }));
          } catch (err) {
            reject(new Error(`keepr answered an unreadable response (HTTP ${status}): ${err.message}`));
          }
        });
      });
      req.setTimeout(timeoutMs, () => req.destroy(new Error(`no answer within ${Math.round(timeoutMs / 1e3)} s`)));
      req.on("error", reject);
      pipeline(Readable.from(parts()), req).catch((err) => {
        req.destroy(err);
        reject(err);
      });
    });
  }
  init(method, opts, auth) {
    const headers = this.baseHeaders(opts, auth);
    let body;
    if (opts.formData) {
      body = opts.formData;
    } else if (opts.body !== void 0) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(opts.body);
    }
    return {
      method,
      headers,
      body,
      signal: AbortSignal.timeout(opts.timeoutMs ?? TIMEOUT_MS)
    };
  }
  buildUrl(path, query) {
    const url = new URL(path.startsWith("/") ? path : `/${path}`, this.baseUrl);
    for (const [k, v] of Object.entries(query ?? {})) {
      if (v === void 0 || v === null || v === "")
        continue;
      url.searchParams.set(k, String(v));
    }
    return url.toString();
  }
  backoffFor(res, attempt) {
    const retryAfter = parseIntOrNull(res.headers.get("retry-after"));
    if (retryAfter !== null)
      return Math.min(retryAfter * 1e3, PACE_MAX_WAIT_MS);
    return 2 ** attempt * 1e3;
  }
  /** Wait out a nearly-exhausted window instead of spending it on 429s — unless that is longer than the caller allows. */
  async paceIfNearLimit(maxWaitMs) {
    const rl = this.lastRateLimit;
    if (!rl || rl.remaining === null || rl.remaining > PACE_BELOW_REMAINING)
      return;
    const waitMs = Math.min(((rl.resetSeconds ?? 1) + 1) * 1e3, PACE_MAX_WAIT_MS);
    if (maxWaitMs !== void 0 && waitMs > maxWaitMs)
      return;
    await this.sleepImpl(waitMs);
    this.lastRateLimit = null;
  }
};
function fileChanged(err) {
  let e = err;
  for (let depth = 0; e && depth < 4; depth++) {
    if (e instanceof FileChangedError)
      return e;
    e = e.cause;
  }
  return null;
}
function headerFilename(name) {
  return name.replace(/"/g, "%22").replace(/\r/g, "%0D").replace(/\n/g, "%0A");
}
function flatHeaders(h) {
  const out = {};
  for (const [k, v] of Object.entries(h))
    if (v !== void 0)
      out[k] = Array.isArray(v) ? v.join(", ") : String(v);
  return out;
}
function multipartParts(file) {
  const boundary = `----keepr${randomBytes(12).toString("hex")}`;
  const head = Buffer.from(`--${boundary}\r
Content-Disposition: form-data; name="${file.field ?? "file"}"; filename="${headerFilename(file.filename)}"\r
Content-Type: ${file.contentType || "application/octet-stream"}\r
\r
`, "utf8");
  const tail = Buffer.from(`\r
--${boundary}--\r
`, "utf8");
  async function* parts() {
    yield head;
    let sent = 0;
    try {
      for await (const chunk of file.open()) {
        sent += chunk.length;
        if (sent > file.length)
          throw new FileChangedError(`${file.filename} grew while it was being sent`, file.length, sent);
        yield chunk;
      }
    } catch (err) {
      if (err instanceof FileChangedError)
        throw err;
      const code = err?.code ?? err?.message;
      throw new FileChangedError(`${file.filename} could not be read (${code})`, file.length, sent, "unreadable");
    }
    if (sent !== file.length)
      throw new FileChangedError(`${file.filename} shrank while it was being sent`, file.length, sent);
    yield tail;
  }
  return { parts, contentType: `multipart/form-data; boundary=${boundary}`, length: head.length + file.length + tail.length };
}
function errorCode(body) {
  if (body && typeof body === "object" && "code" in body) {
    const c = body.code;
    if (typeof c === "string")
      return c;
  }
  return null;
}
var MESSAGE_MAX = 600;
function errorMessage(body, fallback, max = MESSAGE_MAX) {
  if (body && typeof body === "object" && "message" in body) {
    const m = body.message;
    if (typeof m === "string" && m.trim())
      return cleanText(m, max);
  }
  if (typeof body === "string" && body.trim())
    return cleanText(body, Math.min(max, 400));
  return fallback;
}

// dist/src/oauthLocal.js
import { spawn } from "node:child_process";
import { createHash, randomBytes as randomBytes2 } from "node:crypto";
import { mkdirSync, readFileSync as readFileSync2, renameSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { hostname } from "node:os";
import { dirname, join as join2 } from "node:path";
import { setTimeout as sleep2 } from "node:timers/promises";
var CONNECT_SCOPES = ["read", "write", "cards"];
var CALLBACK_PATH = "/callback";
var REGISTERED_REDIRECT = `http://127.0.0.1${CALLBACK_PATH}`;
var REFRESH_EARLY_MS = 6e4;
var FLOW_TTL_MS = 5 * 6e4;
var CLIENT_UNUSED_MAX_AGE_MS = 20 * 36e5;
var HTTP_TIMEOUT_MS = 15e3;
var LOCK_STALE_MS = 4 * 2 * HTTP_TIMEOUT_MS;
var LOCK_WAIT_MS = 2 * HTTP_TIMEOUT_MS + 5e3;
var LOOPBACK_HOSTS = /* @__PURE__ */ new Set(["localhost", "127.0.0.1", "[::1]"]);
var BUSY_SAVING = "Another keepr window on this computer is saving its sign-in right now, so nothing was saved. Call keepr_connect again in a moment.";
function credentialsFileFor(env) {
  const home = (env.HOME || env.USERPROFILE || "").trim();
  return home ? join2(home, ...CREDENTIALS_RELATIVE) : null;
}
function storedConnectionFor(file, baseUrl) {
  const doc = readDoc(file);
  return doc.ok ? pickStored(doc.value, baseUrl) : null;
}
function pickStored(doc, baseUrl) {
  const o = doc.oauth;
  if (!o || typeof o !== "object" || Array.isArray(o))
    return null;
  const s = o;
  if (s.apiUrl !== baseUrl || typeof s.clientId !== "string" || typeof s.issuer !== "string")
    return null;
  return {
    apiUrl: s.apiUrl,
    issuer: s.issuer,
    clientId: s.clientId,
    clientRegisteredAt: typeof s.clientRegisteredAt === "number" ? s.clientRegisteredAt : 0,
    clientUsed: s.clientUsed === true,
    accessToken: typeof s.accessToken === "string" ? s.accessToken : void 0,
    accessExpiresAt: typeof s.accessExpiresAt === "number" ? s.accessExpiresAt : void 0,
    refreshToken: typeof s.refreshToken === "string" ? s.refreshToken : void 0,
    scopes: Array.isArray(s.scopes) ? s.scopes.map(String) : void 0,
    connectedAt: typeof s.connectedAt === "string" ? s.connectedAt : void 0
  };
}
function readDoc(file) {
  if (!file)
    return { ok: true, value: {} };
  let text;
  try {
    text = readFileSync2(file, "utf8");
  } catch (err) {
    if (err.code === "ENOENT")
      return { ok: true, value: {} };
    return { ok: false, reason: `${file} cannot be read (${err.code ?? "error"}).` };
  }
  try {
    const doc = JSON.parse(text);
    if (!doc || typeof doc !== "object" || Array.isArray(doc))
      throw new Error("not an object");
    return { ok: true, value: doc };
  } catch {
    return { ok: false, reason: `${file} is not the JSON keepr writes, so it was left alone. Fix or delete it, then connect again.` };
  }
}
function writeDoc(file, doc) {
  if (!Object.keys(doc).length) {
    try {
      unlinkSync(file);
    } catch {
    }
    return;
  }
  mkdirSync(dirname(file), { recursive: true, mode: 448 });
  const tmp = `${file}.${process.pid}.${randomBytes2(4).toString("hex")}.tmp`;
  writeFileSync(tmp, `${JSON.stringify(doc, null, 2)}
`, { mode: 384, flag: "wx" });
  renameSync(tmp, file);
}
function base64url(buf) {
  return buf.toString("base64url");
}
function pkcePair() {
  const verifier = base64url(randomBytes2(32));
  return { verifier, challenge: base64url(createHash("sha256").update(verifier).digest()) };
}
function openInBrowser(url) {
  const [cmd, args] = process.platform === "darwin" ? ["open", [url]] : process.platform === "win32" ? ["rundll32", ["url.dll,FileProtocolHandler", url]] : ["xdg-open", [url]];
  try {
    const child = spawn(cmd, args, { detached: true, stdio: "ignore" });
    child.on("error", () => {
    });
    child.unref();
    return true;
  } catch {
    return false;
  }
}
function defaultClientName() {
  const host = hostname().replace(/\.(local|lan|home)$/i, "").slice(0, 60) || "this computer";
  return `keepr plugin on ${host}`;
}
function landingPage(ok2, text) {
  const title = ok2 ? "Connected to keepr" : "keepr was not connected";
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title}</title><style>body{font:16px/1.5 system-ui,sans-serif;max-width:32rem;margin:15vh auto;padding:0 16px;color:#1f2328;background:#fff}@media(prefers-color-scheme:dark){body{color:#e6edf3;background:#0d1117}}h1{font-size:1.25rem;margin:0 0 .5rem}</style></head><body><h1>${title}</h1><p>${text}</p></body></html>`;
}
function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
function originOf(url) {
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}
var LocalConnection = class {
  opts;
  stored;
  flow = null;
  starting = null;
  refreshing = null;
  meta = null;
  /** Set when the server refused the refresh token: the person must connect again. */
  revoked = false;
  /** When this process last gave up waiting for another's refresh. */
  lockBusyAt = 0;
  fetchImpl;
  openBrowser;
  now;
  flowTtlMs;
  lockWaitMs;
  clientName;
  constructor(opts) {
    this.opts = opts;
    this.fetchImpl = opts.fetchImpl ?? fetch;
    this.openBrowser = opts.openBrowser ?? openInBrowser;
    this.now = opts.now ?? Date.now;
    this.flowTtlMs = opts.flowTtlMs ?? FLOW_TTL_MS;
    this.lockWaitMs = opts.lockWaitMs ?? LOCK_WAIT_MS;
    this.clientName = opts.clientName ?? defaultClientName();
    this.stored = storedConnectionFor(opts.credentialsFile, opts.baseUrl);
  }
  /** Holds a refresh token for this API — what "connected" means before the first request proves it. */
  get connected() {
    return Boolean(this.stored?.refreshToken);
  }
  get scopes() {
    return this.stored?.scopes ?? [];
  }
  /** True while a flow is open and waiting for the person. */
  get waiting() {
    return Boolean(this.flow && !this.flow.outcome);
  }
  /**
   * Another process held the refresh lock past our wait just now. A 401 in
   * this state means "renewal in progress elsewhere", not "disconnected".
   */
  get busyElsewhere() {
    return this.lockBusyAt > 0 && Date.now() - this.lockBusyAt < this.lockWaitMs * 2;
  }
  // lock waits are wall-clock, like the lock's mtime
  // ------------------------------------------------------------ BearerSource
  async token() {
    const s = this.stored;
    if (!s?.refreshToken)
      return null;
    if (s.accessToken && (s.accessExpiresAt ?? 0) - this.now() > REFRESH_EARLY_MS)
      return s.accessToken;
    return this.refresh(null);
  }
  async afterUnauthorized(rejected) {
    if (!this.stored?.refreshToken)
      return null;
    if (this.busyElsewhere)
      return null;
    return this.refresh(rejected);
  }
  /** One refresh at a time in this process; the lock does the same across processes. */
  refresh(rejected) {
    if (!this.refreshing) {
      this.refreshing = this.withLock(
        () => this.refreshLocked(rejected),
        // No lock, no refresh: spending the refresh token without it is
        // exactly how a replay happens. The token in hand goes out; if it
        // is dead, the 401 says so and the next call tries again.
        () => this.stored?.accessToken ?? null
      ).finally(() => {
        this.refreshing = null;
      });
    }
    return this.refreshing;
  }
  async refreshLocked(rejected) {
    const doc = readDoc(this.opts.credentialsFile);
    if (this.opts.credentialsFile && doc.ok) {
      const onDisk = pickStored(doc.value, this.opts.baseUrl);
      if (!onDisk?.refreshToken) {
        this.stored = onDisk;
        return null;
      }
      if (onDisk.refreshToken !== this.stored?.refreshToken) {
        this.stored = onDisk;
        const fresh = onDisk.accessToken && onDisk.accessToken !== rejected && (onDisk.accessExpiresAt ?? 0) - this.now() > REFRESH_EARLY_MS;
        if (fresh)
          return onDisk.accessToken;
      }
    }
    const s = this.stored;
    if (!s?.refreshToken)
      return null;
    let meta;
    try {
      meta = await this.metadata();
    } catch {
      return s.accessToken ?? null;
    }
    if (meta.issuer !== s.issuer)
      return s.accessToken ?? null;
    const res = await this.post(meta.token_endpoint, {
      grant_type: "refresh_token",
      refresh_token: s.refreshToken,
      client_id: s.clientId
    }).catch(() => null);
    if (!res)
      return s.accessToken ?? null;
    if (res.status === 400 && res.json?.error === "invalid_grant") {
      this.revoked = true;
      this.stored = null;
      this.write(doc);
      return null;
    }
    const body = res.json;
    if (!res.ok || typeof body?.access_token !== "string" || typeof body?.refresh_token !== "string") {
      return s.accessToken ?? null;
    }
    this.stored = {
      ...s,
      accessToken: body.access_token,
      accessExpiresAt: this.now() + Number(body.expires_in ?? 3600) * 1e3,
      refreshToken: body.refresh_token,
      scopes: typeof body.scope === "string" ? body.scope.split(/\s+/).filter(Boolean) : s.scopes
    };
    this.write(readDoc(this.opts.credentialsFile));
    return body.access_token;
  }
  /**
   * Run `fn` holding `credentials.lock`, or `onTimeout` when another holder
   * keeps it past lockWaitMs. The lock holds its holder's id, so a holder
   * removes only its own; a lock is broken only past LOCK_STALE_MS.
   */
  async withLock(fn, onTimeout) {
    const file = this.opts.credentialsFile;
    if (!file)
      return fn();
    const lock = `${file}.lock`;
    const owner = `${hostname()}:${process.pid}:${randomBytes2(12).toString("hex")}`;
    const deadline = Date.now() + this.lockWaitMs;
    for (; ; ) {
      try {
        writeFileSync(lock, owner, { flag: "wx", mode: 384 });
        break;
      } catch (err) {
        const code = err.code;
        if (code === "ENOENT") {
          mkdirSync(dirname(lock), { recursive: true, mode: 448 });
          continue;
        }
        if (code !== "EEXIST")
          throw err;
        try {
          const holder = readFileSync2(lock, "utf8");
          if (holderIsDead(holder)) {
            if (readFileSync2(lock, "utf8") === holder)
              unlinkSync(lock);
            continue;
          }
          if (Date.now() - statSync(lock).mtimeMs > LOCK_STALE_MS) {
            const holder2 = readFileSync2(lock, "utf8");
            if (Date.now() - statSync(lock).mtimeMs > LOCK_STALE_MS && readFileSync2(lock, "utf8") === holder2)
              unlinkSync(lock);
            continue;
          }
        } catch {
          continue;
        }
        if (Date.now() > deadline) {
          this.lockBusyAt = Date.now();
          return onTimeout();
        }
        await sleep2(50);
      }
    }
    this.lockBusyAt = 0;
    try {
      return await fn();
    } finally {
      try {
        if (readFileSync2(lock, "utf8") === owner)
          unlinkSync(lock);
      } catch {
      }
    }
  }
  // ------------------------------------------------------------ connecting
  /**
   * Start the flow, or wait on the one already open. Resolves within
   * `waitMs` with connected, failed, or waiting (the flow keeps listening).
   */
  async connect(waitMs) {
    const doc = readDoc(this.opts.credentialsFile);
    if (!doc.ok)
      return { state: "failed", message: doc.reason };
    const onDisk = pickStored(doc.value, this.opts.baseUrl);
    if (onDisk?.refreshToken) {
      this.stored = onDisk;
      this.revoked = false;
      if (this.flow && !this.flow.outcome)
        this.flow.finish({ state: "connected", scopes: onDisk.scopes ?? [] });
      if (this.flow)
        this.flow.reported = true;
      return { state: "connected", scopes: onDisk.scopes ?? [] };
    }
    if (!this.opts.credentialsFile && this.stored?.refreshToken)
      return { state: "connected", scopes: this.stored.scopes ?? [] };
    if (this.flow?.outcome && !this.flow.reported) {
      this.flow.reported = true;
      return this.flow.outcome;
    }
    let flow = this.flow && !this.flow.outcome ? this.flow : null;
    let reused = Boolean(flow);
    if (!flow) {
      if (!this.starting)
        this.starting = this.startFlow().finally(() => {
          this.starting = null;
        });
      else
        reused = true;
      const started = await this.starting;
      if (!("done" in started))
        return started;
      flow = started;
    }
    const settled = await within(flow.done, waitMs);
    if (settled) {
      flow.reported = true;
      return settled;
    }
    return { state: "waiting", url: flow.url, browserOpened: flow.browserOpened, reused };
  }
  async startFlow() {
    let meta;
    try {
      meta = await this.metadata();
    } catch (err) {
      return { state: "failed", message: `keepr's sign-in service could not be used at ${this.opts.baseUrl}: ${err.message}` };
    }
    let clientId;
    try {
      clientId = await this.ensureClient(meta);
    } catch (err) {
      return { state: "failed", message: err.message };
    }
    const flow = await this.openFlow(meta, clientId);
    this.flow = flow;
    flow.browserOpened = this.openBrowser(flow.url);
    return flow;
  }
  /**
   * Revoke the grant on the server and forget it here. Under the lock, with
   * the refresh token re-read from the file: a process holding a rotated-away
   * token would otherwise revoke nothing (the API answers 200 to an unknown
   * token) and still forget the live one.
   */
  async disconnect() {
    if (this.flow && !this.flow.outcome) {
      this.flow.finish({ state: "failed", message: "Disconnected before the connection was approved." });
      this.flow.reported = true;
    }
    return this.withLock(async () => {
      const doc = readDoc(this.opts.credentialsFile);
      const s = (doc.ok ? pickStored(doc.value, this.opts.baseUrl) : null) ?? this.stored;
      let revokedOnServer = false;
      if (s?.refreshToken) {
        try {
          const meta = await this.metadata();
          if (meta.issuer === s.issuer && meta.revocation_endpoint) {
            const res = await this.post(meta.revocation_endpoint, {
              token: s.refreshToken,
              token_type_hint: "refresh_token",
              client_id: s.clientId
            });
            revokedOnServer = res.ok;
          }
        } catch {
        }
      }
      this.stored = null;
      this.revoked = false;
      this.write(doc);
      return { revokedOnServer, busy: false };
    }, () => ({ revokedOnServer: false, busy: true }));
  }
  /** Adopt the file's connection when this process holds none — another process may have made it. */
  refreshFromDisk() {
    if (this.stored?.refreshToken)
      return;
    const onDisk = storedConnectionFor(this.opts.credentialsFile, this.opts.baseUrl);
    if (onDisk?.refreshToken) {
      this.stored = onDisk;
      this.revoked = false;
    }
  }
  /** Close a waiting flow's listener — process exit, and tests. */
  close() {
    if (this.flow && !this.flow.outcome)
      this.flow.finish({ state: "failed", message: "The keepr plugin stopped." });
  }
  /** The authorization server's metadata, checked once and kept for the process. */
  async metadata() {
    if (this.meta)
      return this.meta;
    const res = await this.fetchImpl(`${this.opts.baseUrl}/.well-known/oauth-authorization-server`, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(HTTP_TIMEOUT_MS)
    });
    if (!res.ok)
      throw new Error(`HTTP ${res.status} from the authorization server metadata`);
    const meta = await res.json();
    this.meta = checkedMetadata(meta, this.opts.baseUrl);
    return this.meta;
  }
  /**
   * A client_id the server will still recognise: one registered recently and never used, else a fresh one.
   * Its refusals offer keepr_connect again, never an API key (ruling d05: no person handles a key to
   * connect; files-only mode reads none — KPR-246 review).
   */
  async ensureClient(meta) {
    const s = this.stored;
    const usable = s && s.issuer === meta.issuer && !s.clientUsed && this.now() - s.clientRegisteredAt < CLIENT_UNUSED_MAX_AGE_MS;
    if (usable)
      return s.clientId;
    if (!meta.registration_endpoint)
      throw new Error("keepr at this address does not offer client registration, so this plugin cannot connect itself to it.");
    const res = await this.fetchImpl(meta.registration_endpoint, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({
        client_name: this.clientName,
        redirect_uris: [REGISTERED_REDIRECT],
        token_endpoint_auth_method: "none",
        grant_types: ["authorization_code", "refresh_token"],
        response_types: ["code"]
      }),
      signal: AbortSignal.timeout(HTTP_TIMEOUT_MS)
    });
    const body = await res.json().catch(() => null);
    if (!res.ok || typeof body?.client_id !== "string") {
      throw new Error(`keepr refused to register this plugin (HTTP ${res.status}${body?.error_description ? `: ${cleanText(String(body.error_description), 600)}` : ""}). Call keepr_connect again in a few minutes.`);
    }
    const before = this.stored;
    this.stored = {
      apiUrl: this.opts.baseUrl,
      issuer: meta.issuer,
      clientId: body.client_id,
      clientRegisteredAt: this.now(),
      clientUsed: false
    };
    if (!await this.writeLocked()) {
      this.stored = before;
      throw new Error(BUSY_SAVING);
    }
    return body.client_id;
  }
  async openFlow(meta, clientId) {
    const { verifier, challenge } = pkcePair();
    const state = base64url(randomBytes2(24));
    let finish;
    const done = new Promise((resolve2) => {
      finish = resolve2;
    });
    let flow = null;
    const server = createServer((req, res) => {
      if (!flow) {
        res.writeHead(503).end();
        return;
      }
      void this.onCallback(flow, req, res);
    });
    await new Promise((resolve2, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", () => resolve2());
    });
    const addr = server.address();
    const port = addr && typeof addr === "object" ? addr.port : 0;
    const redirectUri = `http://127.0.0.1:${port}${CALLBACK_PATH}`;
    const url = new URL(meta.authorization_endpoint);
    url.searchParams.set("response_type", "code");
    url.searchParams.set("client_id", clientId);
    url.searchParams.set("redirect_uri", redirectUri);
    url.searchParams.set("code_challenge", challenge);
    url.searchParams.set("code_challenge_method", "S256");
    url.searchParams.set("state", state);
    url.searchParams.set("scope", CONNECT_SCOPES.join(" "));
    const f = {
      url: url.toString(),
      state,
      verifier,
      redirectUri,
      hostHeader: `127.0.0.1:${port}`,
      meta,
      clientId,
      timer: setTimeout(() => f.finish({
        state: "failed",
        message: `Nobody approved the connection within ${Math.round(this.flowTtlMs / 6e4) || 1} minute(s), so the link has stopped working; keepr_connect again makes a new one.`
      }), this.flowTtlMs),
      browserOpened: false,
      done,
      outcome: null,
      reported: false,
      exchanging: false,
      finish: (o) => {
        if (f.outcome)
          return;
        f.outcome = o;
        clearTimeout(f.timer);
        server.close();
        server.closeAllConnections();
        finish(o);
      }
    };
    f.timer.unref();
    flow = f;
    return f;
  }
  async onCallback(flow, req, res) {
    const send = (status, ok2, text) => {
      res.writeHead(status, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", Connection: "close" });
      res.end(landingPage(ok2, text));
    };
    if (req.headers.host !== flow.hostHeader) {
      send(400, false, "This address only answers keepr's own redirect.");
      return;
    }
    const url = new URL(req.url ?? "/", "http://127.0.0.1");
    if (flow.outcome || url.pathname !== CALLBACK_PATH) {
      send(404, false, "There is nothing here.");
      return;
    }
    const p = url.searchParams;
    if (p.get("state") !== flow.state) {
      send(400, false, "This link does not match the connection keepr is waiting for.");
      return;
    }
    if (flow.exchanging) {
      send(409, false, "This connection is already being finished. Go back to Claude.");
      return;
    }
    const iss = p.get("iss");
    const issRequired = flow.meta.authorization_response_iss_parameter_supported === true;
    if ((iss || issRequired) && iss !== flow.meta.issuer) {
      send(400, false, "The answer came from a different server than the one asked. Go back to Claude and try again.");
      flow.finish({ state: "failed", message: `The answer named issuer ${iss ?? "(none)"}, not ${flow.meta.issuer} (RFC 9207), so it was refused.` });
      return;
    }
    const error = p.get("error");
    if (error) {
      const declined = error === "access_denied";
      send(200, false, declined ? "You chose not to connect. You can close this tab." : `keepr answered: ${escapeHtml(error)}. You can close this tab and try again from Claude.`);
      flow.finish({ state: "failed", message: declined ? "The person chose not to connect (they clicked Deny on keepr's page)." : `keepr answered ${error} instead of connecting.` });
      return;
    }
    const code = p.get("code");
    if (!code) {
      send(400, false, "The answer had no code in it. Go back to Claude and try again.");
      flow.finish({ state: "failed", message: "The browser came back without an authorization code." });
      return;
    }
    flow.exchanging = true;
    const exchanged = await this.post(flow.meta.token_endpoint, {
      grant_type: "authorization_code",
      code,
      redirect_uri: flow.redirectUri,
      client_id: flow.clientId,
      code_verifier: flow.verifier
    }).catch((err) => ({ ok: false, status: 0, json: { error_description: err.message } }));
    const body = exchanged.json;
    if (!exchanged.ok || typeof body?.access_token !== "string" || typeof body?.refresh_token !== "string") {
      const why = typeof body?.error_description === "string" ? cleanText(body.error_description, 600) : `HTTP ${exchanged.status}`;
      send(502, false, "keepr approved the connection, but this plugin could not finish it. Go back to Claude and try again.");
      flow.finish({ state: "failed", message: `The approval could not be exchanged for a connection: ${why}` });
      return;
    }
    const scopes = typeof body.scope === "string" ? body.scope.split(/\s+/).filter(Boolean) : [];
    const before = this.stored;
    this.stored = {
      apiUrl: this.opts.baseUrl,
      issuer: flow.meta.issuer,
      clientId: flow.clientId,
      clientRegisteredAt: this.stored?.clientRegisteredAt ?? this.now(),
      clientUsed: true,
      accessToken: body.access_token,
      accessExpiresAt: this.now() + Number(body.expires_in ?? 3600) * 1e3,
      refreshToken: body.refresh_token,
      scopes,
      connectedAt: new Date(this.now()).toISOString()
    };
    this.revoked = false;
    if (!await this.writeLocked()) {
      const minted = this.stored;
      this.stored = before;
      let withdrawn = false;
      if (flow.meta.revocation_endpoint) {
        const r = await this.post(flow.meta.revocation_endpoint, {
          token: minted.refreshToken,
          token_type_hint: "refresh_token",
          client_id: minted.clientId
        }).catch(() => null);
        withdrawn = Boolean(r?.ok);
      }
      try {
        send(503, false, "keepr approved the connection, but another keepr window on this computer was busy saving its own, so this one was not kept. Go back to Claude and connect again.");
      } catch {
      }
      flow.finish({
        state: "failed",
        message: "keepr approved the connection, but another keepr window on this computer held its sign-in file the whole time, so it could not be saved" + (withdrawn ? " and was withdrawn in keepr." : "; keepr could not be reached to withdraw it, so the person can remove it under Connected assistants on their profile.") + " Call keepr_connect again in a moment."
      });
      return;
    }
    send(200, true, "You can close this tab and go back to Claude.");
    flow.finish({ state: "connected", scopes });
  }
  /** Form-encoded, which is what the token and revocation endpoints are written for. */
  async post(endpoint, fields) {
    const res = await this.fetchImpl(endpoint, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(fields).toString(),
      signal: AbortSignal.timeout(HTTP_TIMEOUT_MS)
    });
    const text = await res.text();
    let json = null;
    try {
      json = text ? JSON.parse(text) : null;
    } catch {
      json = null;
    }
    return { ok: res.ok, status: res.status, json };
  }
  /**
   * Merge the `oauth` block into a document read under the lock, keeping
   * everything else in it. A file that cannot be read is never written; a
   * write that fails leaves the connection working in memory, and says so on
   * stderr (never a token).
   */
  write(doc) {
    const file = this.opts.credentialsFile;
    if (!file || !doc.ok)
      return;
    if (this.stored)
      doc.value.oauth = this.stored;
    else
      delete doc.value.oauth;
    try {
      writeDoc(file, doc.value);
    } catch (err) {
      process.stderr.write(`keepr-mcp: could not save the keepr connection to ${file}: ${err.code ?? err.message}
`);
    }
  }
  /**
   * write(), outside a refresh: under credentials.lock, with the file re-read
   * there, so it cannot land between another process's read and write —
   * keepr.py's (its `keeprPy` block, KPR-249) or another window's. Never
   * without the lock (KPR-270: it used to write anyway, from a document read
   * outside it, when the wait ran out). withLock keeps trying for the lock
   * for lockWaitMs — every 50 ms, breaking a dead holder's lock at once and a
   * stale one past LOCK_STALE_MS — and when a live holder keeps it longer,
   * nothing is written and this answers false: busy, try again.
   */
  async writeLocked() {
    return this.withLock(async () => {
      this.write(readDoc(this.opts.credentialsFile));
      return true;
    }, () => false);
  }
};
function checkedMetadata(meta, baseUrl) {
  if (!meta || typeof meta.issuer !== "string" || typeof meta.authorization_endpoint !== "string" || typeof meta.token_endpoint !== "string") {
    throw new Error("the authorization server metadata is incomplete");
  }
  const base = new URL(baseUrl);
  const issuerOrigin = originOf(meta.issuer);
  if (issuerOrigin !== base.origin)
    throw new Error(`the authorization server names issuer ${meta.issuer}, not ${base.origin}`);
  for (const field of ["token_endpoint", "registration_endpoint", "revocation_endpoint"]) {
    const v = meta[field];
    if (v !== void 0 && originOf(v) !== issuerOrigin)
      throw new Error(`the authorization server's ${field} is not on ${issuerOrigin}`);
  }
  let consent;
  try {
    consent = new URL(meta.authorization_endpoint);
  } catch {
    throw new Error("the authorization endpoint is not a URL");
  }
  const localApi = base.protocol === "http:" && LOOPBACK_HOSTS.has(base.hostname);
  if (!(consent.protocol === "https:" || consent.protocol === "http:" && localApi)) {
    throw new Error(`the consent page must be https, not ${consent.protocol}`);
  }
  return meta;
}
function holderIsDead(holder) {
  const [host, pidText] = holder.split(":");
  const pid = Number(pidText);
  if (host !== hostname() || !Number.isInteger(pid) || pid <= 0 || pid === process.pid)
    return false;
  try {
    process.kill(pid, 0);
    return false;
  } catch (err) {
    return err.code === "ESRCH";
  }
}
async function within(promise, ms) {
  let timer;
  const timeout = new Promise((resolve2) => {
    timer = setTimeout(() => resolve2(null), Math.max(0, ms));
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    clearTimeout(timer);
  }
}

// dist/src/contract.snapshot.json
var contract_snapshot_default = {
  version: "e34b7c13c2cc",
  title: "keepr write contract",
  summary: "What keepr accepts from a machine client: the element types, the batch envelope, and every error code a row can come back with. Generated from the running server, so it describes THIS deployment.",
  loop: [
    "GET /api/collections/{id}/schema \u2014 the cards and elements this collection accepts",
    "POST /api/collections/{id}/ingest with dryRun: true \u2014 validate every row, write nothing",
    "fix the rows the dry run named",
    "POST /api/collections/{id}/ingest \u2014 commit"
  ],
  auth: {
    scheme: "Authorization: Bearer kpr_<43 chars>",
    scopes: {
      read: "GET, HEAD, OPTIONS",
      write: "creating and changing items, attachments and ingest \u2014 every other method except the card surface",
      cards: "creating and changing cards, element sets and card layouts (never delete of a collection)",
      delete: "deleting, beside write or cards: every DELETE that removes something, bulk op delete and reject, intake-review reject, a replace-mode write carrying elements (PUT /api/items/{id}, bulk update rows, ingest upsert \u2014 whenever the effective merge is false), and a collection PUT that drops a card from cards[] \u2014 off by default, and never implied"
    },
    notes: [
      "A key acts as its owner, never as a new principal, and is never an administrator.",
      'write and cards each imply read; neither implies the other. A 403 insufficient_scope carries requiredScope ("write", "cards" or "delete") naming the scope the key lacks.',
      'A key minted before the cards scope existed cannot change cards until it is re-minted or edited with "Can change cards".',
      'delete is added to write or cards, never alone: a destructive route needs its base scope AND delete. Keys and grants made before 2026-09-24 do not have it; deleting needs a new key (or a reconnect) with "Can delete records".',
      "A key or grant with delete may hard-delete at most deletesPerKeyPerDay items per UTC day; past that, 429 delete_budget_exhausted with limit, used, remaining, requested and resetsAt, and nothing is deleted. A bulk that would overrun the budget is refused whole.",
      "A key confined to a collection allowlist gets 404 \u2014 not 403 \u2014 for everything outside it.",
      "A keepr client names itself on every request with X-Keepr-Client: keepr-skill/<version> (<channel>) or keepr-mcp/<version> (<channel>). One below the oldest supported release gets 426 code client_too_old, with latest and guide; GET /api/docs/clients has the versions and how to update each channel. A request without the header is never refused for it.",
      "Session-only surfaces refuse keys: sharing and grants, collection delete and transfer, share links, password and email changes, API key management, all /api/admin/*. The refusal is 403 code session_required whatever the key holds \u2014 no scope fixes it."
    ]
  },
  endpoints: {
    whoami: "GET /api/user-info",
    collections: "GET /api/collections",
    schema: "GET /api/collections/{id}/schema",
    ingest: "POST /api/collections/{id}/ingest",
    ingestRuns: "GET /api/collections/{id}/ingest-runs",
    createItem: "POST /api/items",
    createCard: "POST /api/card-definitions",
    blueprintPreview: "POST /api/collections/{id}/blueprints/preview",
    blueprintApply: "POST /api/collections/{id}/blueprints/apply",
    attach: "POST /api/items/{itemId}/attachments",
    listAttachments: "GET /api/items/{itemId}/attachments",
    charts: "GET /api/collections/{id}/charts",
    chartPreview: "POST /api/collections/{id}/charts/preview",
    chartRun: "POST /api/charts/run",
    automationPreview: "POST /api/collections/{id}/automations/preview",
    automationList: "GET /api/collections/{id}/automations",
    automationRuns: "GET /api/collections/{id}/automations/{automationId}/runs",
    automationEnable: "POST /api/collections/{id}/automations/{automationId}/enable",
    automationDisable: "POST /api/collections/{id}/automations/{automationId}/disable",
    notificationDefs: "GET /api/notification-defs",
    itemHistory: "GET /api/items/{id}/history",
    cardHistory: "GET /api/card-definitions/{id}/history",
    collectionHistory: "GET /api/collections/{id}/history",
    itemsBulk: "POST /api/items/bulk",
    resolveCode: "GET /api/codes/{kind}/{code}",
    uploadRequestCreate: "POST /api/upload-requests",
    uploadRequestRead: "GET /api/upload-requests/{id}",
    uploadRequestCancel: "DELETE /api/upload-requests/{id}",
    itemConfirm: "POST /api/items/{id}/confirmations/{element}",
    itemUnconfirm: "DELETE /api/items/{id}/confirmations/{element}",
    itemConfirmations: "GET /api/items/{id}/confirmations",
    itemConfirmers: "GET /api/items/{id}/confirmations/{element}/people"
  },
  recordCodes: {
    url: "A record's short web address is ${APP_BASE_URL}/<letter>/<code>. A code is 7 or more characters of lowercase Crockford base32 and reads in any case (i and l as 1, o as 0). Every id stays valid; a code is a second name for the record, never a permission.",
    letters: {
      collection: "c",
      item: "i",
      card: "d",
      tag: "t",
      "element-set": "e",
      "multi-add-form": "f"
    }
  },
  currencies: {
    minorUnits: 'An amount is an integer count of minor units: { amount: 1250, currency: "USD" } is 12.50 USD. Divide by 10 to the exponent to get the major amount.',
    exponents: {
      AED: 2,
      AFN: 2,
      ALL: 2,
      AMD: 2,
      AOA: 2,
      ARS: 2,
      AUD: 2,
      AWG: 2,
      AZN: 2,
      BAM: 2,
      BBD: 2,
      BDT: 2,
      BHD: 3,
      BIF: 0,
      BMD: 2,
      BND: 2,
      BOB: 2,
      BRL: 2,
      BSD: 2,
      BTN: 2,
      BWP: 2,
      BYN: 2,
      BZD: 2,
      CAD: 2,
      CDF: 2,
      CHF: 2,
      CLP: 0,
      CNY: 2,
      COP: 2,
      CRC: 2,
      CUP: 2,
      CVE: 2,
      CZK: 2,
      DJF: 0,
      DKK: 2,
      DOP: 2,
      DZD: 2,
      EGP: 2,
      ERN: 2,
      ETB: 2,
      EUR: 2,
      FJD: 2,
      FKP: 2,
      GBP: 2,
      GEL: 2,
      GHS: 2,
      GIP: 2,
      GMD: 2,
      GNF: 0,
      GTQ: 2,
      GYD: 2,
      HKD: 2,
      HNL: 2,
      HTG: 2,
      HUF: 2,
      IDR: 2,
      ILS: 2,
      INR: 2,
      IQD: 3,
      IRR: 2,
      ISK: 0,
      JMD: 2,
      JOD: 3,
      JPY: 0,
      KES: 2,
      KGS: 2,
      KHR: 2,
      KMF: 0,
      KPW: 2,
      KRW: 0,
      KWD: 3,
      KYD: 2,
      KZT: 2,
      LAK: 2,
      LBP: 2,
      LKR: 2,
      LRD: 2,
      LSL: 2,
      LYD: 3,
      MAD: 2,
      MDL: 2,
      MGA: 2,
      MKD: 2,
      MMK: 2,
      MNT: 2,
      MOP: 2,
      MRU: 2,
      MUR: 2,
      MVR: 2,
      MWK: 2,
      MXN: 2,
      MYR: 2,
      MZN: 2,
      NAD: 2,
      NGN: 2,
      NIO: 2,
      NOK: 2,
      NPR: 2,
      NZD: 2,
      OMR: 3,
      PAB: 2,
      PEN: 2,
      PGK: 2,
      PHP: 2,
      PKR: 2,
      PLN: 2,
      PYG: 0,
      QAR: 2,
      RON: 2,
      RSD: 2,
      RUB: 2,
      RWF: 0,
      SAR: 2,
      SBD: 2,
      SCR: 2,
      SDG: 2,
      SEK: 2,
      SGD: 2,
      SHP: 2,
      SLE: 2,
      SOS: 2,
      SRD: 2,
      SSP: 2,
      STN: 2,
      SVC: 2,
      SYP: 2,
      SZL: 2,
      THB: 2,
      TJS: 2,
      TMT: 2,
      TND: 3,
      TOP: 2,
      TRY: 2,
      TTD: 2,
      TWD: 2,
      TZS: 2,
      UAH: 2,
      UGX: 0,
      USD: 2,
      UYU: 2,
      UZS: 2,
      VED: 2,
      VES: 2,
      VND: 0,
      VUV: 0,
      WST: 2,
      XAF: 0,
      XCD: 2,
      XCG: 2,
      XOF: 0,
      XPF: 0,
      YER: 2,
      ZAR: 2,
      ZMW: 2,
      ZWG: 2,
      BOV: 2,
      CHE: 2,
      CHW: 2,
      CLF: 4,
      COU: 2,
      MXV: 2,
      USN: 2,
      UYI: 0,
      UYW: 4
    }
  },
  units: {
    composite: "A number in a two-part unit is a decimal of its first part: 5.5 in ft-in is 5.5 ft, spelled 5 ft 6 in (the whole first part, then the rest times minorPerMajor in the second, rounded to a whole one).",
    twoPart: {
      "lb-oz": {
        parts: [
          "lb",
          "oz"
        ],
        minorPerMajor: 16
      },
      "st-lb": {
        parts: [
          "st",
          "lb"
        ],
        minorPerMajor: 14
      },
      "ft-in": {
        parts: [
          "ft",
          "in"
        ],
        minorPerMajor: 12
      },
      "h-min": {
        parts: [
          "h",
          "min"
        ],
        minorPerMajor: 60
      },
      "min-s": {
        parts: [
          "min",
          "s"
        ],
        minorPerMajor: 60
      }
    },
    symbols: {
      longton: "long ton",
      C: "\xB0C",
      F: "\xB0F",
      floz: "fl oz",
      mm3: "mm\xB3",
      cm3: "cm\xB3",
      dm3: "dm\xB3",
      m3: "m\xB3",
      in3: "in\xB3",
      ft3: "ft\xB3",
      yd3: "yd\xB3",
      drypt: "dry pt",
      dryqt: "dry qt",
      peck: "pk",
      impfloz: "imp fl oz",
      imppt: "imp pt",
      impqt: "imp qt",
      impgal: "imp gal",
      cm2: "cm\xB2",
      m2: "m\xB2",
      km2: "km\xB2",
      ft2: "ft\xB2",
      yd2: "yd\xB2",
      mi2: "mi\xB2",
      mm2: "mm\xB2",
      in2: "in\xB2",
      "floz/s": "fl oz/s",
      "mm3/s": "mm\xB3/s",
      "cm3/s": "cm\xB3/s",
      "dm3/s": "dm\xB3/s",
      "m3/s": "m\xB3/s",
      "in3/s": "in\xB3/s",
      "ft3/s": "ft\xB3/s",
      "yd3/s": "yd\xB3/s",
      "drypt/s": "dry pt/s",
      "dryqt/s": "dry qt/s",
      "peck/s": "pk/s",
      "impfloz/s": "imp fl oz/s",
      "imppt/s": "imp pt/s",
      "impqt/s": "imp qt/s",
      "impgal/s": "imp gal/s",
      "floz/min": "fl oz/min",
      "mm3/min": "mm\xB3/min",
      "cm3/min": "cm\xB3/min",
      "dm3/min": "dm\xB3/min",
      "m3/min": "m\xB3/min",
      "in3/min": "in\xB3/min",
      "ft3/min": "ft\xB3/min",
      "yd3/min": "yd\xB3/min",
      "drypt/min": "dry pt/min",
      "dryqt/min": "dry qt/min",
      "peck/min": "pk/min",
      "impfloz/min": "imp fl oz/min",
      "imppt/min": "imp pt/min",
      "impqt/min": "imp qt/min",
      "impgal/min": "imp gal/min",
      "floz/h": "fl oz/h",
      "mm3/h": "mm\xB3/h",
      "cm3/h": "cm\xB3/h",
      "dm3/h": "dm\xB3/h",
      "m3/h": "m\xB3/h",
      "in3/h": "in\xB3/h",
      "ft3/h": "ft\xB3/h",
      "yd3/h": "yd\xB3/h",
      "drypt/h": "dry pt/h",
      "dryqt/h": "dry qt/h",
      "peck/h": "pk/h",
      "impfloz/h": "imp fl oz/h",
      "imppt/h": "imp pt/h",
      "impqt/h": "imp qt/h",
      "impgal/h": "imp gal/h",
      "floz/d": "fl oz/d",
      "mm3/d": "mm\xB3/d",
      "cm3/d": "cm\xB3/d",
      "dm3/d": "dm\xB3/d",
      "m3/d": "m\xB3/d",
      "in3/d": "in\xB3/d",
      "ft3/d": "ft\xB3/d",
      "yd3/d": "yd\xB3/d",
      "drypt/d": "dry pt/d",
      "dryqt/d": "dry qt/d",
      "peck/d": "pk/d",
      "impfloz/d": "imp fl oz/d",
      "imppt/d": "imp pt/d",
      "impqt/d": "imp qt/d",
      "impgal/d": "imp gal/d",
      "floz/wk": "fl oz/wk",
      "mm3/wk": "mm\xB3/wk",
      "cm3/wk": "cm\xB3/wk",
      "dm3/wk": "dm\xB3/wk",
      "m3/wk": "m\xB3/wk",
      "in3/wk": "in\xB3/wk",
      "ft3/wk": "ft\xB3/wk",
      "yd3/wk": "yd\xB3/wk",
      "drypt/wk": "dry pt/wk",
      "dryqt/wk": "dry qt/wk",
      "peck/wk": "pk/wk",
      "impfloz/wk": "imp fl oz/wk",
      "imppt/wk": "imp pt/wk",
      "impqt/wk": "imp qt/wk",
      "impgal/wk": "imp gal/wk",
      "longton/s": "long ton/s",
      "longton/min": "long ton/min",
      "longton/h": "long ton/h",
      "longton/d": "long ton/d",
      "longton/wk": "long ton/wk",
      "beat/min": "bpm",
      deg: "\xB0",
      "mpg-uk": "imp mpg"
    }
  },
  imports: {
    importId: "OPTIONAL on the ingest envelope: 1-64 of [A-Za-z0-9._-]. Mint one per import and send the same one on every batch of it (dry runs included); keepr lists the batches as one import.",
    undo: "A person who manages the collection can undo an import from its Settings \u2192 Imports (web, session-only): the items it created are deleted and the ones it updated are restored, except any changed since. There is no API-key route for it."
  },
  source: {
    createdAt: "OPTIONAL on a row's source, beside its externalId and system: when the record was created in that system. YYYY-MM-DD, or an ISO date-time with an offset; never in the future. Set when the item is created only: an upsert row that sends a different one still succeeds, and carries notes[] saying the date was not changed. It is shown as provenance; keepr's own createdAt is never set by a client."
  },
  dryRun: {
    wouldCreate: "OPTIONAL on a dry-run envelope only: up to 10000 of { card, externalId, system?, createdAt? }, the rows earlier calls of the same dry run answered would-create (system defaults to the request's source.system). A $ref to one resolves as it will at commit, and a row repeating one is a duplicate (create) or would-update (upsert; checked on its own elements, not merged over the earlier row's, so it cannot say skipped). Send only the entries this call refers to or repeats. On a commit it is 400 would_create_not_dry_run \u2014 the earlier calls have written their rows \u2014 and an entry with no system, or naming a card the collection does not have, is 400 would_create_invalid."
  },
  tags: {
    tags: "OPTIONAL on a row: the item's hand-applied tags, the whole list, as tag names, aliases, paths (Parent/Child) or 24-hex ids. Names resolve among the tags of this collection and the collection above it \u2014 GET /api/collections/{id}/schema lists them under tags. An item tag (a card's items used as tags) goes by its id only: GET /api/tags/search finds it by its item's title. keepr never creates a tag on a write: a name that is no tag here is unknown_tag, one that could be two is ambiguous_tag (with candidates), a private tag is private_tag_not_allowed. On an upsert the list replaces the stored one, except that a restricted tag is kept when the list leaves it out; [] takes off every tag you may take off. A RESTRICTED tag (restricted: true in the schema) decides who can see what: only a person signed in to keepr puts one on or takes one off, so a row that adds or removes one is session_required \u2014 ask the person to do it in keepr. A new item may also come back carrying a restricted tag the collection puts on new items of its card. Absent or null changes nothing. At most 50. Send tags or tagIds, not both.",
    tagIds: "OPTIONAL on a row, instead of tags: the same whole list as 24-hex tag ids only.",
    tagAutoIds: "NEVER sent: tags a rule applies are written by the rule; a row carrying the key is refused.",
    warnings: 'A row that succeeded may carry warnings[]: { code: "tag_dropped", tagIds } names tags it sent that were deleted since \u2014 left off, the rest written.',
    blueprints: "A card blueprint (blueprintPreview / blueprintApply) may bring NEW collection tags in collection.tags ({ localId, name, color?, icon?, description?, aliases?, parentRef?: { ref }, rule? }), each optionally applied by a rule ({ cardRef, where?, match?, strict?, related? }; its filters name tags by name). A key needs write beside cards for it. Every rule arrives PAUSED: it tags nothing until it is resumed (leave that to the person, in keepr), and the apply answers what each would tag (rules[].preview). A blueprint tag is never restricted."
  },
  setups: {
    cards: "Optional: a setup may create no cards and only arrange existing ones. A setup with nothing in it is setup_empty.",
    layouts: 'collection.cardLayouts may name an existing card by { key }. tile and table: scope "collection" (the default) or "card" (only on a card this collection owns); form: the card tier only, on an owned card; page: either tier. A card tier the collection may not set is layout_tier.',
    changes: "An entry that matches what is there CHANGES it rather than adding one: tile, table and form by their tier, a page layout, saved filter or quick add (pinned for everyone) by id or exact name. The preview marks each step change: added | changed | unchanged, with before and after; unchanged entries are skipped; a failed apply puts every change back.",
    judged: "The preview runs layout bodies through the apply's validators when the card and everything its elements come from exist, and filter queries when the setup creates no cards, element sets or tags.",
    rules: "collection.automations: rules of kind rule | threshold | expected-item | generate-items, as POST \u2026/automations takes them (no enabled), naming cards by { ref } (one the setup makes), { key }, { globalKey } or id. collection.notifications: collection-tier notification definitions, matched by key. An entry matches an existing rule by id or exact name (a notification by id or key) and changes it; managed rules (driven fields, automatic tags) are rule_managed. The preview carries each rule's rule preview and state on | paused. A rule that notifies, changes other records, creates records or runs on a clock, and every notification, arrives PAUSED with awaitingPerson: true, whoever applies; a change to what a running one does pauses it (willPause). Only a person turns one on (403 person_must_enable to a key). A key needs write.",
    charts: "collection.charts and collection.dashboards entries take an optional id; one that matches a chart or dashboard for everyone (by id, else exact name) CHANGES it in place (its pin stays) rather than being chart_name_taken / dashboard_name_taken. A dashboard tile names a chart by chartRef (the setup's) or chartId (one for everyone in the collection). Steps carry change, id, before and after; a failed apply puts each back."
  },
  writeContract: {
    maxBatch: 200,
    idempotency: "source.externalId",
    ref: '{"$ref": "<externalId>"} accepted for card-lookup elements',
    strictDefault: true,
    ingestPath: "/api/collections/{id}/ingest",
    serverAssigned: "an element marked driven or sequence is written by the server; a supplied value is refused in strict mode and dropped otherwise"
  },
  limits: {
    maxRowsPerCall: 200,
    maxIngestBytes: "5 MB per ingest call",
    activeApiKeysPerUser: 25,
    deletesPerKeyPerDay: 500
  },
  elementTypes: [
    {
      name: "text-small",
      send: "a string",
      note: "one line; at most 255 characters, or the element's own maxLength (too_long past it); an element's pattern refuses a value that does not fit it (pattern), and its case / trim settings change what is stored (capitals, small letters, spaces trimmed)"
    },
    {
      name: "text-large",
      send: "a string",
      note: "multi-line; newlines are preserved; at most 20,000 characters, or 50,000 when the element's extendedLength is set, or the element's own maxLength"
    },
    {
      name: "rich-text",
      send: "a markdown string",
      note: "as the web editor stores it; at most 100,000 characters, or 250,000 with extendedLength"
    },
    {
      name: "choice",
      send: "the choice's value",
      note: "the value, never the label; anything else is invalid_choice. allowMultiple takes an array of values (stored once each, in the order of the choices list) or one string with values separated by ';'"
    },
    {
      name: "number",
      send: 'a number, or a numeric string (en-US grouping read: "1,234,567.5")',
      note: 'a decimals setting ROUNDS the value; min/max and nonNegative are enforced; a percent element takes the number shown (12.5 for 12.5 %, never 0.125), or "12.5%" \u2014 a "%" on any other element is refused (type); thousands grouping is display only, and commas that do not group in threes ("1,23", a decimal comma "1,5") are refused (type)'
    },
    {
      name: "decimal",
      send: "a number, or a numeric string",
      note: "as number, with the element's declared precision"
    },
    {
      name: "integer",
      send: "a whole number",
      note: "a fractional value is rounded half away from zero; text is read as for number"
    },
    {
      name: "boolean",
      send: "true or false",
      note: "a real boolean; trueLabel/falseLabel are display only"
    },
    {
      name: "date",
      send: '"YYYY-MM-DD"',
      note: 'locale dates (12/05/2024) and epoch numbers are REFUSED as ambiguous; a precision element also takes "YYYY-MM" or "YYYY" and floors to it; allowMultiple takes an array of at most 1,000 dates'
    },
    {
      name: "date-time",
      send: "an ISO-8601 timestamp",
      note: "a bare YYYY-MM-DD becomes midnight UTC; allowMultiple takes an array of at most 1,000"
    },
    {
      name: "time",
      send: '"HH:mm" or "HH:mm:ss"',
      note: "H:mm is zero-padded"
    },
    {
      name: "url",
      send: "a link: https://\u2026, http://\u2026, mailto:\u2026, tel:\u2026, sms:\u2026, geo:\u2026, facetime:\u2026, spotify:\u2026, zoommtg:\u2026, msteams:\u2026 or slack:\u2026",
      note: "a bare host (example.com/x) is stored as https://example.com/x; any other scheme, or a space, is invalid_url; at most 2,048 characters"
    },
    {
      name: "phone",
      send: "a phone number",
      note: "the national spelling of the element's country, or E.164; stored as E.164"
    },
    {
      name: "email",
      send: '"local@domain.tld"',
      note: "at most 254 characters; the domain is lower-cased"
    },
    {
      name: "location",
      send: "an address string, or { lat, lng }",
      note: "the element's accept setting may allow only one of the two"
    },
    {
      name: "rating",
      send: "a number from 0 to the element's max",
      note: "outside that range is a range error; whole stars, or halves when allowHalf is set \u2014 anything between is a type error"
    },
    {
      name: "card-lookup",
      send: 'a 24-hex item id, or { "$ref": "<externalId>" }',
      note: "an array when allowMultiple; the target must be the element's lookupCardId or a descendant of it"
    },
    {
      name: "measurement",
      send: '{ value, unit }, a number in the default unit, or a parseable string like "8 lb 7 oz"',
      note: "the stored base is computed \u2014 never send it"
    },
    {
      name: "user",
      send: "a 24-hex account id",
      note: "the account must exist and be active"
    },
    {
      name: "currency",
      send: '{ amount, currency } with amount in MINOR units (1250 = 12.50), { value, currency } in major units, a number in the default currency, or a string like "$12.50" / "12.5 CAD"',
      note: "the currency must be one of the element's currencies; more decimals than the currency has (1.234 USD) is refused, never rounded"
    },
    {
      name: "color",
      send: 'a color: "#rrggbb", "#rgb", "rgb(31, 111, 235)" or one of the 22 choice color names ("DodgerBlue")',
      note: 'stored as a lower-case "#rrggbb"; a hex needs its #, and a translucent color, a percentage or any other name is invalid_color'
    },
    {
      name: "file",
      send: "nothing: an attachment of this item, set with keepr_attach_file (element) or the item form",
      note: "stored as a 24-hex attachment id, or an array of up to 20 with allowMultiple; an import row, a bulk edit or an automation may only re-send the stored value unchanged (anything else, a blank included, is file_not_settable)"
    },
    {
      name: "confirmations",
      send: 'nothing: how many people said "me too" \u2014 a person confirms or takes it back with POST or DELETE /api/items/{id}/confirmations/{element} (endpoints itemConfirm, itemUnconfirm), once each',
      note: "stored as a whole number, absent until the first confirmation and read as 0 when absent (filters, sorting, charts); a row may re-send the stored count unchanged and nothing else (confirmations_not_settable); who confirmed is never in an item \u2014 only a collection's managers can list them (itemConfirmers)"
    }
  ],
  emptyValue: 'null or "" means empty. Omitting the key means empty too, except on a CREATE, where an element the row omits starts at its default (defaultValue, defaultToToday or defaultToNow in the schema; a default that no longer fits the element is left out and the element starts empty). On upsert, an omitted key KEEPS its stored value while "" overwrites it; a default never applies to an update.',
  errorCodes: {
    shape: [
      {
        code: "attachment_in_use",
        means: "409 on DELETE /api/items/{id}/attachments/{aid}: the attachment is the value of a file element (element names it) \u2014 clear or replace the value with an item write instead; never met by a row"
      },
      {
        code: "attachments_disabled",
        means: "a new or changed file value while the collection's attachments are switched off (the stored value, unchanged, still saves)"
      },
      {
        code: "confirmations_not_settable",
        means: "a value for a confirmations element: keepr keeps that count from the people who confirmed \u2014 leave it out (the stored count re-sent unchanged is fine), and confirm with POST /api/items/{id}/confirmations/{element}"
      },
      {
        code: "driven_element",
        means: "the element is system-owned; its value is computed, never sent"
      },
      {
        code: "file_already_used",
        means: "the same file named twice under one element, or a file another element of the item already holds"
      },
      {
        code: "file_not_found",
        means: "an id under a file element that is not a file this write may use: unknown, deleted, someone else's, or on another item (one answer for every reason)"
      },
      {
        code: "file_not_settable",
        means: "a file element's value is set by a person (the item form) or keepr_attach_file, never by an import row, a bulk edit or an automation: only the stored value, unchanged, may ride along \u2014 a new value, another one, or a blank on a stored file is refused"
      },
      {
        code: "file_too_large",
        means: "the file is larger than the element's maxSizeMb (limitMb carries it)"
      },
      {
        code: "file_wrong_kind",
        means: 'the element takes photos only (accept: "image") and the file is not one keepr could read as a photo \u2014 a PDF never is'
      },
      {
        code: "invalid_choice",
        means: "not one of the element's choice values"
      },
      {
        code: "invalid_color",
        means: 'not a color keepr reads: a hex with its # ("#1f6feb", "#abc"), rgb(r, g, b) with whole numbers 0\u2013255, or one of the 22 choice color names; a translucent color is refused too'
      },
      {
        code: "invalid_currency",
        means: `not an ISO 4217 code keepr knows, a symbol that names several currencies ("kr"), or outside the element's currencies`
      },
      {
        code: "invalid_email",
        means: "not local@domain.tld, or over 254 characters"
      },
      {
        code: "invalid_location",
        means: "neither an address nor a coordinate pair, or the half the element's accept setting forbids"
      },
      {
        code: "invalid_lookup",
        means: "not a 24-hex id or a $ref, or an array on a single-valued element"
      },
      {
        code: "invalid_phone",
        means: "unparseable, or impossible in the numbering plan of the element's country"
      },
      {
        code: "invalid_unit",
        means: "not a unit of that measurement's measure, or outside the element's allowlist"
      },
      {
        code: "invalid_url",
        means: "not a link keepr stores: a scheme off its list (http, https, mailto, tel, sms, geo, facetime, spotify, zoommtg, msteams, slack), a space inside, or neither a link nor a host"
      },
      {
        code: "pattern",
        means: "a short text that does not fit the element's pattern (the collection schema gives it); the message is the element author's own sentence"
      },
      {
        code: "range",
        means: "outside a declared bound \u2014 a rating past max, a number past min/max, a date outside its bounds or on a disallowed weekday"
      },
      {
        code: "required",
        means: "a required element was empty or missing"
      },
      {
        code: "sequence_element",
        means: "the element is numbered by the server (options.sequence); its value cannot be written \u2014 refused in strict mode, dropped otherwise"
      },
      {
        code: "too_long",
        means: "longer than the element allows (limit carries it): the element's own maxLength, else 255 characters for a short text, 20,000 long (50,000 extended), 100,000 rich (250,000 extended), 2,048 for a url"
      },
      {
        code: "too_many_dates",
        means: "more than 1,000 distinct entries in a date or date-time list (limit carries it); a longer list stored before the cap, re-sent unchanged, still saves"
      },
      {
        code: "too_many_files",
        means: "more files than a file element holds (limit carries it: 20)"
      },
      {
        code: "type",
        means: "the value does not coerce to the element's data type"
      },
      {
        code: "unknown_element",
        means: "no element of that name on the card (strict mode only; non-strict drops the key)"
      },
      {
        code: "user_not_found",
        means: "no existing, active account with that id"
      }
    ],
    row: [
      {
        code: "account_already_linked",
        means: "another item of this collection already links that account"
      },
      {
        code: "account_link_needs_access",
        means: "the row sets or changes the account link on a card a group built from records reads, changes a field such a group's rule reads on a linked record so that its person could join, or changes a field such a rule reads through this record (a looked-up record's name, a record a total counts), and the caller lacks, across the collection, the access that group gives \u2014 a manager makes the change"
      },
      {
        code: "ambiguous_tag",
        means: "a tags name could be more than one tag; candidates lists each one's tagId and path \u2014 send the path or the id"
      },
      {
        code: "attestation_required",
        means: "the record's card requires a signature on every change (record.attest in the schema) and the upsert row would change it without one: no X-Attestation header, an expired one, another person's, or one minted for another card or collection \u2014 nothing is written (as PUT answers 428). A person signed in to keepr signs (POST /api/auth/attest); an API key or an assistant cannot, so ask the person to make the change in keepr. A row that changes nothing is skipped, never refused"
      },
      {
        code: "card_in_sub_collection",
        means: "hint.code on a card_not_allowed row: the card belongs to a sub-collection (hint.collection_id, hint.name) \u2014 ingest the row there"
      },
      {
        code: "card_mismatch",
        means: "an upsert matched an item of a different card; card cannot change on upsert"
      },
      {
        code: "card_not_allowed",
        means: "the card exists but is not writable in this collection"
      },
      {
        code: "card_unknown",
        means: "no card definition with that key or id"
      },
      {
        code: "duplicate",
        means: "create mode, and that (system, externalId) pair already exists \u2014 switch to upsert"
      },
      {
        code: "duplicate_value",
        means: 'another item of the card already holds this value of a unique element (text and email compared ignoring case); itemId and title name it when you can read it \u2014 use mode "upsert" keyed on the element to re-run an import'
      },
      {
        code: "externalId_required",
        means: "upsert mode with no source.externalId on the row"
      },
      {
        code: "forbidden_card",
        means: "the caller's grants do not cover that card"
      },
      {
        code: "forbidden_item",
        means: "an upsert matched an item the caller may not modify"
      },
      {
        code: "internal",
        means: "an unexpected server error on this row; the row was not written"
      },
      {
        code: "invalid_tag_ids",
        means: "tags is not a list of tag names, paths or ids, tagIds is not a list of tag ids, or the row sends both"
      },
      {
        code: "item_locked",
        means: "the record's card has locked it (record.lock in the schema): an upsert row that would change it \u2014 an element value, its visibility, its tags \u2014 or an attachment added to or removed from it, is refused and nothing is written (as PUT refuses); a row that changes nothing is skipped, never refused. A manager's unlock reopens it, and the write that lands closes it again. A dry run refuses what its commit will: a row repeating a record an earlier row of the request creates, or one whose unlock an earlier row spends, is judged against that record as the commit will meet it"
      },
      {
        code: "lookup_filtered_out",
        means: "the element is a strict lookup and the record is outside its filter (the collection schema gives filter and strict); itemIds names the refused ids \u2014 choose a record the filter offers (list them with the filter in ?q=). A record the item already holds always saves"
      },
      {
        code: "lookup_not_found",
        means: "a plain 24-hex id is not a readable item of this collection"
      },
      {
        code: "private_not_allowed",
        means: "private items are not allowed on that card, or the caller may not flip visibility"
      },
      {
        code: "private_tag_not_allowed",
        means: "a tags entry is a private tag: only its owner sees it and it is never on an item, so a row carries collection tags only"
      },
      {
        code: "ref_unresolved",
        means: "a $ref matched no readable item, or its target row failed earlier in the request"
      },
      {
        code: "ref_wrong_card",
        means: "the reference resolves to an item whose card the element does not accept"
      },
      {
        code: "restricted_tag",
        means: "the row adds, or takes off, a restricted tag, and only managers of the collection it belongs to may; a restricted tag the list leaves out is kept, not refused"
      },
      {
        code: "rule_owned_tag",
        means: "a tag a strict rule applies, and only the rule \u2014 a row cannot add it by hand"
      },
      {
        code: "session_required",
        means: "only a person signed in to keepr may make this change, never an API key or an assistant: the row adds or takes off a restricted tag (those decide who can see what; a restricted tag the list leaves out is kept), or sets or changes the account link on a card a group built from records reads, changes a field such a group's rule reads on a linked record so that its person could join, or changes a field such a rule reads through this record (a looked-up record's name, a record a total counts); only a signed-in person may \u2014 an API key or assistant cannot (re-sending the stored values is fine)"
      },
      {
        code: "source_invalid",
        means: "the effective source is malformed \u2014 most often an externalId with no system in effect"
      },
      {
        code: "stale",
        means: "somebody changed the item's tags while the row was being written, twice; nothing was written for it \u2014 send the row again"
      },
      {
        code: "too_many_tags",
        means: "the row would give the item more than 50 tags"
      },
      {
        code: "unknown_tag",
        means: "a tags or tagIds entry is not a tag this item can carry: a name or path that names no tag of this collection or the collection above it that the caller can read, or an id that is not one (one answer for every reason \u2014 missing, deleted, private, another collection's). keepr never creates a tag on a write"
      }
    ]
  },
  rowStatuses: {
    created: "a new item was written",
    updated: "an existing item changed",
    skipped: "the stored item already matched exactly \u2014 nothing was written",
    failed: "the row was refused; errors[] says why",
    "would-create": "dry run: this row would create an item",
    "would-update": "dry run: this row would change an existing item"
  }
};

// dist/src/contract.js
var SNAPSHOT = contract_snapshot_default;
var REFETCH_COOLDOWN_MS = 6e4;
var FETCH_TIMEOUT_MS = 3e3;
var ContractCache = class {
  http;
  body = SNAPSHOT;
  source = "snapshot";
  codeMeaning = /* @__PURE__ */ new Map();
  elementTypes = /* @__PURE__ */ new Map();
  lastFetchAttempt = 0;
  /** The version we last went chasing. A NEW unknown version always earns a
   *  fetch; seeing the SAME unknown version again does not. */
  chasing = null;
  /** Set when a refetch still disagreed — our reading is wrong, not the server's. */
  mismatchLatched = false;
  constructor(http) {
    this.http = http;
    this.reindex();
  }
  get version() {
    return this.body.version;
  }
  get isLive() {
    return this.source === "live";
  }
  get maxBatch() {
    return this.body.writeContract?.maxBatch ?? 200;
  }
  /**
   * One unauthenticated GET at boot. Never throws — a mute server is worse.
   * A cache that is already live and was fetched inside the cooldown is left
   * alone: the remote transport shares ONE cache across every credential
   * (src/remote.ts), and a fetch per new session would be a fetch per
   * connector for the same document.
   */
  async load() {
    if (this.isLive && Date.now() - this.lastFetchAttempt < REFETCH_COOLDOWN_MS)
      return;
    await this.refetch();
  }
  /**
   * Called with the contractVersion that rode in on a schema response. A
   * mismatch is re-fetched ONCE and awaited: the schema in hand may name
   * element types the stale copy cannot explain, and returning it
   * un-annotated is worse than three seconds.
   */
  async noteVersionSeen(seen) {
    if (!seen || seen === this.body.version || this.mismatchLatched)
      return;
    if (seen === this.chasing && Date.now() - this.lastFetchAttempt < REFETCH_COOLDOWN_MS)
      return;
    this.chasing = seen;
    const before = this.body.version;
    await this.refetch();
    if (this.body.version !== seen && this.body.version === before) {
      this.mismatchLatched = true;
    }
  }
  async refetch() {
    this.lastFetchAttempt = Date.now();
    try {
      const res = await this.http.request({
        path: "/api/docs/contract",
        anonymous: true,
        timeoutMs: FETCH_TIMEOUT_MS
      });
      if (res.ok && res.body && typeof res.body === "object" && typeof res.body.version === "string") {
        this.body = res.body;
        this.source = "live";
        this.reindex();
      }
    } catch {
    }
  }
  reindex() {
    this.codeMeaning.clear();
    this.elementTypes.clear();
    const codes = this.body.errorCodes ?? { shape: [], row: [] };
    for (const entry of [...codes.shape ?? [], ...codes.row ?? []]) {
      if (entry?.code)
        this.codeMeaning.set(entry.code, entry.means);
    }
    for (const t2 of this.body.elementTypes ?? []) {
      if (t2?.name)
        this.elementTypes.set(t2.name, t2);
    }
  }
  /** The deployment's own sentence for an error code. */
  meaningOf(code) {
    if (!code)
      return null;
    return this.codeMeaning.get(code) ?? null;
  }
  /** What to send for a data type, in the deployment's words. */
  formOf(dataType) {
    return this.elementTypes.get(dataType) ?? null;
  }
  knowsCode(code) {
    return this.codeMeaning.has(code);
  }
  knownTypeNames() {
    return [...this.elementTypes.keys()].sort();
  }
  /**
   * Does this deployment mint a scope of that name? A deployment older than
   * the `cards` scope documents only read and write, and against it a write
   * key still changes cards — the client must not refuse what the server
   * would allow.
   */
  /**
   * Whether the deployment documents an endpoint by its contract name — e.g.
   * `blueprintPreview`. The build-time snapshot says yes for everything this
   * build knows, so an unreachable contract never downgrades a request.
   */
  hasEndpoint(name) {
    const endpoints = this.body.endpoints;
    return Boolean(endpoints && typeof endpoints === "object" && name in endpoints);
  }
  /** Whether the deployment takes a SETUP of existing cards (the contract's `setups`, KPR-190). */
  get takesSetup() {
    return Boolean(this.body.setups);
  }
  /** Whether a setup may change the charts and dashboards a collection has (`setups.charts`, KPR-215). */
  get takesSetupChartChanges() {
    return Boolean(this.body.setups?.charts);
  }
  /** Whether a setup may carry automations and notifications (`setups.rules`, KPR-191). */
  get takesSetupRules() {
    return Boolean(this.body.setups?.rules);
  }
  /**
   * Whether the ingest envelope takes `importId` (undo import). An older
   * deployment's strict envelope REFUSES an unknown key, so the ingest tool
   * sends one only when this says so — and drops it on the one refusal that
   * names it, for a snapshot that is newer than the server.
   */
  get takesImportId() {
    return Boolean(this.body.imports);
  }
  /**
   * Whether a dry-run envelope takes `wouldCreate` (a dry run split across
   * batches). Gated like importId, for the same reason: an older strict
   * envelope refuses the key.
   */
  get takesWouldCreate() {
    return Boolean(this.body.dryRun?.wouldCreate);
  }
  /**
   * Whether an ingest row takes `tags` by name, path or id (tags T8). An
   * older deployment answered a row carrying tags `tags_retired` (T1) or
   * knew nothing of them, so rows carry `tags` only when this says so.
   */
  get takesTagNames() {
    return Boolean(this.body.tags?.tags);
  }
  /**
   * A currency's ISO 4217 minor-unit exponent (USD 2, JPY 0, BHD 3), from
   * the deployment's own registry (`currencies.exponents`), or null when it
   * names none. Never from Intl: Node's ICU disagrees with ISO for 16 codes
   * keepr knows, and a wrong exponent misreads every amount by a power of ten.
   */
  currencyExponent(code) {
    if (!code)
      return null;
    const table = this.body.currencies?.exponents;
    const value = table && Object.prototype.hasOwnProperty.call(table, code) ? table[code] : void 0;
    return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 6 ? value : null;
  }
  /**
   * A two-part unit's parts and how many of the second make one of the
   * first (`ft-in` → { parts: ['ft', 'in'], minorPerMajor: 12 },
   * `units.twoPart`), or null for any other unit — or a deployment that
   * does not say.
   */
  twoPartOf(unit) {
    if (!unit)
      return null;
    const table = this.body.units?.twoPart;
    const entry = table && Object.prototype.hasOwnProperty.call(table, unit) ? table[unit] : void 0;
    const parts = entry?.parts;
    const per = entry?.minorPerMajor;
    if (!Array.isArray(parts) || parts.length !== 2 || !parts.every((p) => typeof p === "string" && p))
      return null;
    if (typeof per !== "number" || !Number.isInteger(per) || per < 2)
      return null;
    return { parts: [parts[0], parts[1]], minorPerMajor: per };
  }
  /** The unit a number in `unit` is a number of: a two-part unit's first part (a value in `ft-in` is a decimal of ft), else the unit itself. */
  unitShownAs(unit) {
    return this.twoPartOf(unit)?.parts[0] ?? unit;
  }
  /** How a unit is written for a reader: its symbol where it is not its id (`C` → °C, `m3` → m³, `units.symbols`), else the id. */
  unitSymbol(unit) {
    const table = this.body.units?.symbols;
    const symbol = table && Object.prototype.hasOwnProperty.call(table, unit) ? table[unit] : void 0;
    return typeof symbol === "string" && symbol ? symbol : unit;
  }
  knowsScope(name) {
    const scopes = this.body.auth?.scopes;
    return Boolean(scopes && typeof scopes === "object" && name in scopes);
  }
  /**
   * A build-quality signal, not an instruction to the model. keepr.py had to
   * say "go run contract --check" because it could not fix itself; by the time
   * this fires the live contract has ALREADY explained the code correctly.
   * So it means "keepr-mcp is behind the deployment", which is our problem.
   */
  stalenessNote(codesSeen) {
    const unknown = codesSeen.filter((c) => c && !this.codeMeaning.has(c));
    if (!unknown.length)
      return null;
    const list = [...new Set(unknown)].join(", ");
    return this.source === "live" ? `This deployment uses error codes this build does not document: ${list}. The live contract was used to explain them, so the result above is correct \u2014 but keepr-mcp is behind the deployment.` : `Unrecognised error codes (${list}) and the live contract could not be fetched, so these are explained from a build-time snapshot that may be out of date.`;
  }
};

// dist/src/breaker.js
var WINDOW_MS = 5 * 6e4;
var LIMIT = 3;
var RefusalBreaker = class {
  now;
  seen = /* @__PURE__ */ new Map();
  constructor(now = Date.now) {
    this.now = now;
  }
  /** Record a refusal. Returns how many identical ones have been seen. */
  record(signature, status) {
    const t2 = this.now();
    const prev = this.seen.get(signature);
    if (!prev || t2 - prev.firstAt > WINDOW_MS || prev.status !== status) {
      this.seen.set(signature, { count: 1, firstAt: t2, status });
      return 1;
    }
    prev.count += 1;
    return prev.count;
  }
  /** True when this exact call has already been refused identically LIMIT times. */
  isTripped(signature) {
    const prev = this.seen.get(signature);
    if (!prev)
      return false;
    if (this.now() - prev.firstAt > WINDOW_MS) {
      this.seen.delete(signature);
      return false;
    }
    return prev.count >= LIMIT;
  }
  /** A success means the condition changed; forget the history for this call. */
  clear(signature) {
    this.seen.delete(signature);
  }
  trippedMessage(signature) {
    const prev = this.seen.get(signature);
    const status = prev ? prev.status : 0;
    return `This exact call has already been refused ${LIMIT} times with HTTP ${status}. Retrying cannot change it \u2014 something outside this conversation has to change first. Tell the user what is blocking, and stop calling this tool.`;
  }
};

// dist/src/ledger.js
var MAX_RUNS = 50;
var RunLedger = class {
  runs = [];
  record(rec) {
    this.runs.unshift(rec);
    if (this.runs.length > MAX_RUNS)
      this.runs.length = MAX_RUNS;
  }
  byRunId(runId) {
    return this.runs.find((r) => r.runId === runId) ?? null;
  }
  /** Most recent first, so a bare externalId resolves to the newest import. */
  resolveExternalId(externalId, runId) {
    const pool = runId ? this.runs.filter((r) => r.runId === runId) : this.runs;
    for (const run2 of pool) {
      const itemId = run2.itemsByExternalId[externalId];
      if (itemId)
        return { itemId, run: run2 };
    }
    return null;
  }
  /** Every remembered run, most recent first. */
  all() {
    return [...this.runs];
  }
  get size() {
    return this.runs.length;
  }
  knownRunIds() {
    return this.runs.map((r) => r.runId);
  }
};

// dist/src/proposals.js
import { randomBytes as randomBytes3 } from "node:crypto";
var TTL_MS2 = 30 * 6e4;
var MAX_OPEN = 20;
var MAX_TOMBSTONES = 100;
var ProposalStore = class {
  open = /* @__PURE__ */ new Map();
  /** Tokens that expired, so a late apply hears "expired", not "unknown" (the review's F15). */
  gone = /* @__PURE__ */ new Map();
  create(collectionId, collectionName, cards, blueprint = null) {
    return this.add({ kind: "create", collectionId, collectionName, cards, blueprint });
  }
  change(spec) {
    return this.add({ kind: "change", ...spec });
  }
  setup(spec) {
    return this.add({ kind: "setup", ...spec });
  }
  bulk(spec) {
    return this.add({ kind: "bulk", ...spec });
  }
  add(spec) {
    this.sweep();
    if (this.open.size >= MAX_OPEN) {
      const oldest = [...this.open.values()].sort((a, b) => a.createdAt - b.createdAt)[0];
      if (oldest) {
        this.open.delete(oldest.token);
        this.gone.set(oldest.token, oldest.kind);
      }
    }
    const proposal = {
      ...spec,
      token: `prop_${randomBytes3(9).toString("hex")}`,
      createdAt: Date.now()
    };
    this.open.set(proposal.token, proposal);
    return proposal;
  }
  /**
   * Spend a token. `kinds` names the proposals the caller applies: a token of
   * another kind is answered `wrong_kind` and NOT spent, so the model can
   * take it to the right tool (a setup token sent to keepr_apply_card).
   */
  take(token, kinds) {
    this.sweep();
    const found = this.open.get(token);
    if (!found) {
      const kind = this.gone.get(token);
      return kind ? { ok: false, reason: "expired", kind } : { ok: false, reason: "unknown" };
    }
    if (kinds && !kinds.includes(found.kind))
      return { ok: false, reason: "wrong_kind", kind: found.kind };
    this.open.delete(token);
    return { ok: true, proposal: found };
  }
  sweep() {
    const now = Date.now();
    for (const [token, p] of this.open) {
      if (now - p.createdAt <= TTL_MS2)
        continue;
      this.open.delete(token);
      this.gone.set(token, p.kind);
      if (this.gone.size > MAX_TOMBSTONES)
        this.gone.delete(this.gone.keys().next().value);
    }
  }
  get size() {
    return this.open.size;
  }
};

// dist/src/elementIds.js
var ELEMENT_ID = /^[a-z0-9]{8}$/;

// dist/src/elementRefusals.js
var ELEMENT_REFUSAL_CODES = ["ambiguous_element", "unknown_element", "invalid_element_choices", "query_too_long"];
var MAX_NAME = 80;
var MAX_CANDIDATES = 20;
var MAX_CARDS = 6;
var t = (v, max = MAX_NAME) => cleanText(v === null || v === void 0 ? "" : String(v), max);
var str = (v) => typeof v === "string" && v.trim() ? v : null;
var num = (v) => typeof v === "number" && Number.isFinite(v) ? v : void 0;
var isCode = (v) => typeof v === "string" && ELEMENT_REFUSAL_CODES.includes(v);
function candidateOf(raw) {
  if (!raw || typeof raw !== "object")
    return null;
  const c = raw;
  const id = typeof c.elementId === "string" ? c.elementId.replace(/^#/, "") : "";
  if (!ELEMENT_ID.test(id))
    return null;
  const cards = (Array.isArray(c.cards) ? c.cards : []).filter((k) => !!k && typeof k === "object").map((k) => ({
    cardId: typeof k.cardId === "string" && /^[0-9a-fA-F]{24}$/.test(k.cardId) ? k.cardId : null,
    name: t(k.name),
    ...str(k.element) ? { element: t(k.element) } : {},
    ...str(k.qualifier) ? { qualifier: t(k.qualifier) } : {}
  }));
  return {
    elementId: id,
    label: t(str(c.label) ?? c.name),
    name: t(c.name),
    cards,
    ...c.hiddenCopies === true ? { hiddenCopies: true } : {}
  };
}
function elementRefusalOf(body) {
  if (!body || typeof body !== "object")
    return null;
  const b = body;
  const code = isCode(b.code) ? b.code : b.code === "invalid_filter" && isCode(b.cause) ? b.cause : null;
  if (!code)
    return null;
  return {
    code,
    field: str(b.field) ? t(b.field, 120) : str(b.path) && b.code === "invalid_filter" ? t(b.path, 120) : null,
    element: str(b.element) ? t(b.element) : null,
    // A chart's or a dashboard's `path` is the spec's ("filter"); the comparison's own path rides as `conditionPath`.
    path: b.code === "invalid_filter" ? str(b.conditionPath) ? t(b.conditionPath, 200) : null : str(b.path) ? t(b.path, 200) : null,
    choiceKey: str(b.choiceKey) ? t(b.choiceKey, 200) : null,
    reference: b.reference === true,
    requiresAll: b.requiresAll === true,
    unpickable: b.unpickable === true,
    candidates: (Array.isArray(b.candidates) ? b.candidates : []).map(candidateOf).filter((c) => c !== null).slice(0, MAX_CANDIDATES),
    ...num(b.conditions) !== void 0 ? { conditions: num(b.conditions) } : {},
    ...num(b.max) !== void 0 ? { max: num(b.max) } : {},
    ...num(b.length) !== void 0 ? { length: num(b.length) } : {},
    ...num(b.limit) !== void 0 ? { limit: num(b.limit) } : {}
  };
}
var isReference = (r) => r.reference || /^\{\{.*\}\}$/.test(r.choiceKey ?? "");
function replacementFor(r, id) {
  const seg = `#${id}`;
  const key = r.choiceKey ?? r.element ?? "";
  if (isReference(r))
    return `{{${seg}}}`;
  const element = r.element ?? "";
  if (element && key.length > element.length && key.endsWith(`.${element}`))
    return `${key.slice(0, key.length - element.length)}${seg}`;
  return seg;
}
var q = (v) => `"${v.replace(/"/g, "'")}"`;
var LOOKALIKE = {
  "\u0430": "a",
  "\u0432": "b",
  "\u0435": "e",
  "\u0451": "e",
  "\u043A": "k",
  "\u043C": "m",
  "\u043D": "h",
  "\u043E": "o",
  "\u0440": "p",
  "\u0441": "c",
  "\u0442": "t",
  "\u0443": "y",
  "\u0445": "x",
  "\u0456": "i",
  "\u0457": "i",
  "\u0458": "j",
  "\u0455": "s",
  "\u0501": "d",
  "\u051B": "q",
  "\u051D": "w",
  "\u0261": "g",
  "\u0131": "i",
  "\u03B1": "a",
  "\u03B2": "b",
  "\u03B5": "e",
  "\u03B7": "n",
  "\u03B9": "i",
  "\u03BA": "k",
  "\u03BD": "v",
  "\u03BF": "o",
  "\u03C1": "p",
  "\u03C4": "t",
  "\u03C5": "u",
  "\u03C7": "x",
  "\u03B6": "z"
};
function lookalikeKey(name) {
  return Array.from(name.normalize("NFKD").replace(new RegExp("\\p{M}", "gu"), "").toLowerCase()).map((ch) => LOOKALIKE[ch] ?? ch).join("");
}
var KEEPR_QUALIFIERS = /* @__PURE__ */ new Set(["global", "another collection"]);
function cardText(card, shared, copies) {
  const qualifier = card.qualifier ? ` (${KEEPR_QUALIFIERS.has(card.qualifier) ? card.qualifier : q(card.qualifier)})` : "";
  const tell = qualifier || (shared.has(lookalikeKey(card.name)) && card.cardId ? ` (card ${card.cardId})` : "");
  const as = copies && card.element ? ` as ${q(card.element)}` : "";
  return `${card.name ? q(card.name) : "a card"}${tell}${as}`;
}
function candidateLines(r) {
  const ids = /* @__PURE__ */ new Map();
  for (const c of r.candidates)
    for (const k of c.cards) {
      const key = lookalikeKey(k.name);
      if (!ids.has(key))
        ids.set(key, /* @__PURE__ */ new Set());
      ids.get(key).add(k.cardId ?? `${c.elementId}:${k.qualifier ?? ""}`);
    }
  const shared = new Set([...ids].filter(([, set]) => set.size > 1).map(([key]) => key));
  return r.candidates.map((c) => {
    const copies = c.cards.some((k) => k.element && k.element !== c.name);
    const cards = c.cards.slice(0, MAX_CARDS).map((k) => cardText(k, shared, copies));
    const more = c.cards.length > MAX_CARDS ? ` and ${c.cards.length - MAX_CARDS} more` : "";
    const on = cards.length ? ` on ${cards.join(", ")}${more}` : " on a card this connection cannot open";
    const hidden = c.hiddenCopies ? " \u2014 also held under another name on a card this connection cannot open, which naming it reads too" : "";
    return `  #${c.elementId}  ${q(c.label || c.name)}${on}${hidden}`;
  });
}
function groupText(r, ids, negative) {
  const join5 = negative ? " and " : " or ";
  if (isReference(r))
    return r.path ? `(${ids.map((id) => `${r.path} \u2026 ${replacementFor(r, id)}`).join(join5)})` : null;
  return `(${ids.map((id) => `${replacementFor(r, id)} ${negative ? "!=" : "="} \u2026`).join(join5)})`;
}
function groupOrWords(r, ids, negative) {
  return groupText(r, ids, negative) ?? `the whole comparison once per id, each with its id in place of ${q(r.choiceKey ?? r.element ?? "the name")}, joined by ${negative ? "and" : "or"}`;
}
function elementRefusalLines(r, fix = {}) {
  const where = fix.where ?? (r.field ? `${r.field}${fix.within ? ` in ${fix.within}` : ""}` : fix.within ? `a filter in ${fix.within}` : "the filter");
  const named = r.element ? q(r.element) : "a name";
  const ids = r.candidates.map((c) => c.elementId);
  const lines = [""];
  if (r.code === "unknown_element") {
    lines.push(`NO SUCH ELEMENT: ${named} in ${where} names no element keepr finds there.`);
    lines.push("", fix.notYours ? `NEXT: ${fix.notYours}` : "NEXT: keepr_schema lists this collection's elements, each with its #id beside its name. Write the condition with the #id of the one the person means; if it is not plain which one that is, ask them \u2014 never guess a name.");
    return lines;
  }
  if (r.code === "query_too_long") {
    if (r.conditions !== void 0) {
      lines.push(`TOO MANY CONDITIONS: naming each element by itself made ${where} ${r.conditions} conditions; keepr takes ${r.max !== void 0 ? `at most ${r.max}` : "fewer"}.`);
      lines.push("", `NEXT: name fewer elements \u2014 write only the ids of the cards the person means, and if it is not plain which those are, ask them \u2014${fix.pinned ? "" : ` or narrow it to one card with card = <key> beside the condition${fix.pin ? `; ${fix.pin}` : ""},`} or split the question into several calls.`);
    } else {
      lines.push(`TOO LONG: ${where} is ${r.length !== void 0 ? `${r.length} characters` : "too long"} once keepr stores it (its names written as ids)${r.limit !== void 0 ? `; keepr takes at most ${r.limit}` : ""}.`);
      lines.push("", "NEXT: shorten it, or split it into several filters; if it is not plain which part the person can do without, ask them.");
    }
    return lines;
  }
  if (r.code === "invalid_element_choices") {
    lines.push("", "NEXT: name the element by its #id in the text itself instead; keepr_schema lists each element's #id.");
    return lines;
  }
  if (!r.candidates.length) {
    lines.push(`WHICH ELEMENT: ${named} in ${where} could mean more than one element, and none of them is on a card this connection can open, so keepr lists none.`);
    lines.push("", "NEXT: tell the person; the filter has to be written in keepr by someone who can open those cards.");
    return lines;
  }
  if (r.requiresAll && r.candidates.length === 1 && !r.unpickable) {
    const [c] = r.candidates;
    lines.push(`WHICH ELEMENT: ${named} in ${where} is #${c.elementId} (${q(c.label || c.name)}), and keepr reads it under another name on another card too:`);
    lines.push(...candidateLines(r));
    lines.push("", "NEXT: this filter decides who sees what, and the rule would read every copy, so keepr asks the person to confirm it. Tell them what it reads; they confirm it in keepr.");
    return lines;
  }
  const several = r.candidates.length > 1;
  lines.push(several ? `WHICH ELEMENT: ${named} in ${where} could mean any of these ${r.candidates.length} elements:` : `WHICH ELEMENT: ${named} in ${where} could mean more than one element; this is the one on a card this connection can open:`);
  lines.push(...candidateLines(r));
  if (r.unpickable) {
    lines.push("", `NEXT: nothing written here can be accepted. This filter decides who sees what and its condition matches a missing value, so it must name every element ${named} could mean \u2014 and another card that defines it is one this connection cannot open. Tell the person: someone who can open every card changes it in keepr, or the condition goes on one card's own filter.`);
    return lines;
  }
  if (fix.notYours) {
    lines.push("", `NEXT: ${fix.notYours}`);
    return lines;
  }
  if (r.requiresAll) {
    lines.push("", `NEXT: keepr takes only the whole group here. This filter decides who sees what and its condition matches a missing value, so one card's element would let every other card's items through. Write the condition once per id: a != (or is not), not in, !~ or is empty joined by and \u2014 ${groupOrWords(r, ids, true)}; a positive comparison under a not joined by or, inside that not \u2014 not ${groupOrWords(r, ids, false)}. Or leave it to the person in keepr.`);
    return lines;
  }
  const first = ids[0];
  const steps = [
    `  - one of them: ${replacementFor(r, first)} in place of ${r.choiceKey && r.choiceKey !== r.element ? q(r.choiceKey) : named}${several ? " (or another id above)" : ""};`
  ];
  if (several) {
    steps.push(`  - any of these cards: the condition once per id, joined by or \u2014 ${groupOrWords(r, ids, false)}; with != (or is not), not in, !~ or is empty, joined by and \u2014 ${groupOrWords(r, ids, true)}. A not before the condition goes before the whole group;`);
  }
  if (fix.pinned) {
    steps.push(`  - a card pin does not help here: this filter is already read on one card, and ${several ? "these are" : "this is"} on the cards beneath it${fix.pinnedHint ? ` \u2014 ${fix.pinnedHint}` : ""}.`);
  } else {
    steps.push(`  - one card only: card = <key> beside it, in the same and, reads ${named} on that card \u2014 and on the cards beneath it, so where one of those restates ${named} keepr asks again${fix.pin ? `; or ${fix.pin}` : ""}.`);
  }
  lines.push("", `NEXT: if the person has not said which one they mean, ask them, with these labels and cards \u2014 never pick one yourself. Then ${fix.again ?? `send ${where} again`} with the element named by its id:`, ...steps);
  return lines;
}
function elementRefusalData(r) {
  return {
    code: r.code,
    ...r.field ? { field: r.field } : {},
    ...r.element ? { element: r.element } : {},
    ...r.path ? { path: r.path } : {},
    ...r.choiceKey ? { choiceKey: r.choiceKey } : {},
    ...r.reference ? { reference: true } : {},
    ...r.requiresAll ? { requiresAll: true } : {},
    ...r.unpickable ? { unpickable: true } : {},
    ...r.code === "ambiguous_element" ? {
      candidates: r.candidates.map((c) => ({
        elementId: c.elementId,
        // What to write: the id as KQL spells it at this place.
        write: replacementFor(r, c.elementId),
        label: c.label,
        name: c.name,
        cards: c.cards,
        ...c.hiddenCopies ? { hiddenCopies: true } : {}
      }))
    } : {},
    ...r.conditions !== void 0 ? { conditions: r.conditions } : {},
    ...r.max !== void 0 ? { max: r.max } : {},
    ...r.length !== void 0 ? { length: r.length } : {},
    ...r.limit !== void 0 ? { limit: r.limit } : {}
  };
}

// dist/src/format.js
function ok(text, structured) {
  return { content: [{ type: "text", text }], ...structured ? { structuredContent: structured } : {} };
}
function fail(text, structured) {
  return { content: [{ type: "text", text }], ...structured ? { structuredContent: structured } : {}, isError: true };
}
function failFromResponse(res, what, kql, notes = []) {
  const code = errorCode(res.body);
  const message = errorMessage(res.body, `HTTP ${res.status}`);
  const element = res.ok ? null : elementRefusalOf(res.body);
  const hint = element ? void 0 : STATUS_HINTS[res.status];
  const proxyNote = res.nonJson ? "\n\nThe response body was not JSON, so this may not be keepr answering at all \u2014 an intercepting proxy is the usual cause." : "";
  const lines = [
    `FAILED \u2014 ${what}.`,
    "",
    `keepr answered HTTP ${res.status}${code ? ` (${code})` : ""}: ${message}`
  ];
  if (hint)
    lines.push("", hint);
  if (notes.length)
    lines.push(...notes);
  if (element)
    lines.push(...elementRefusalLines(element, kql));
  return fail(lines.join("\n") + proxyNote, {
    ok: false,
    status: res.status,
    code,
    message,
    requestId: res.requestId,
    ...element ? { elementRefusal: elementRefusalData(element) } : {}
  });
}

// dist/src/guard.js
function neededScope(def) {
  return def.scope ?? (def.writes ? "write" : null);
}
function guard(def, ctx, args, run2) {
  const signature = `${def.name}:${stableStringify(args)}`;
  if (ctx.breaker.isTripped(signature)) {
    return Promise.resolve(fail(ctx.breaker.trippedMessage(signature)));
  }
  if (!ctx.startup.reachable) {
    return Promise.resolve(fail(`keepr is unreachable from here (${ctx.config.baseUrl}), so this cannot run.

This is a transport problem between this server and the keepr API, not a keepr outage.`));
  }
  if (ctx.startup.problem)
    return Promise.resolve(fail(ctx.startup.problem));
  const needed = neededScope(def);
  if (needed && ctx.hasScope(needed) === false)
    return Promise.resolve(fail(ctx.refusalFor(needed)));
  return run2().then((result) => {
    if (result.isError) {
      const status = Number(result.structuredContent?.status ?? 0);
      if (status === 401 && ctx.usesConnection) {
        result.content.push({ type: "text", text: ctx.noteConnectionLost() });
        return result;
      }
      if (status === 401) {
        ctx.credentialRefused = true;
        if (ctx.credential === "key" && keyWords.keyRefused)
          result.content.push({ type: "text", text: keyWords.keyRefused });
      }
      if (status >= 400 && status < 500 && status !== 429)
        ctx.breaker.record(signature, status);
    } else {
      ctx.breaker.clear(signature);
    }
    const notice = ctx.takeUpdateNotice();
    if (notice)
      result.content.push({ type: "text", text: notice });
    return result;
  }).catch((err) => {
    if (err instanceof KeeprTransportError) {
      return fail(`Could not reach keepr: ${err.message}

This is the network between this server and ${ctx.config.baseUrl}, not a refusal.`);
    }
    return fail(`keepr-mcp failed internally: ${err.message}

This is a bug in keepr-mcp, not something the user did.`);
  });
}
function stableStringify(value) {
  if (value === null || typeof value !== "object")
    return JSON.stringify(value) ?? "null";
  if (Array.isArray(value))
    return `[${value.map(stableStringify).join(",")}]`;
  const entries = Object.entries(value).filter(([, v]) => v !== void 0).sort(([a], [b]) => a.localeCompare(b));
  return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${stableStringify(v)}`).join(",")}}`;
}
function describeFor(def, ctx) {
  const needed = neededScope(def);
  return needed && ctx.hasScope(needed) === false ? `UNAVAILABLE (${needed === "cards" ? `this ${ctx.credential} cannot change cards \u2014 it needs Can change cards` : `this ${ctx.credential} is read-only`}). ${def.description}` : def.description;
}
function runTool(def, ctx, args) {
  return def.unguarded ? def.handler(args, ctx).catch((err) => fail(`keepr-mcp failed internally: ${err.message}

This is a bug in keepr-mcp, not something the user did.`)) : guard(def, ctx, args, () => def.handler(args, ctx));
}

// dist/src/server.js
var SERVER_NAME = "keepr";
var SERVER_VERSION = "0.14.0";
var WEBSITE_URL = "https://keepr.cloud";
var KQL_REFERENCE_URL = `${WEBSITE_URL}/docs/guides/finding-and-lists/kql-reference`;
function brandIcons(publicUrl = process.env.KEEPR_PUBLIC_URL || "https://api.keepr.cloud") {
  const base = publicUrl.replace(/\/+$/, "");
  return [
    { src: `${base}/logo512.png`, mimeType: "image/png", sizes: ["512x512"] },
    { src: `${base}/logo192.png`, mimeType: "image/png", sizes: ["192x192"] },
    { src: `${base}/favicon.svg`, mimeType: "image/svg+xml", sizes: ["any"] }
  ];
}
var READ_ONLY = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false };

// dist/src/context.js
var COLLECTION_NAME_MAX = 200;
var SCOPE_NAMES = ["read", "write", "cards", "delete"];
function collectionKind(c) {
  if (typeof c.kind === "string" && c.kind)
    return c.kind;
  const publication = c.publication;
  if (publication && (publication.state === "published" || publication.state === "retiring"))
    return "global";
  return "standard";
}
function accessLabel(my) {
  if (!my)
    return { label: "none", writable: false };
  if (my.role)
    return { label: my.role, writable: ["owner", "manage", "write"].includes(my.role) };
  const cardRoles = Object.values(my.cardRoles ?? {});
  if (cardRoles.includes("write"))
    return { label: "card-write", writable: true };
  if (cardRoles.includes("read"))
    return { label: "card-read", writable: false };
  if ((my.queryGrants ?? []).length)
    return { label: "filtered", writable: false };
  return { label: "none", writable: false };
}
var KeeprContext = class {
  config;
  http;
  contract;
  /** Replaced by restart(): a refusal learned as one account must not trip calls made as the next. */
  breaker = new RefusalBreaker();
  /** Replaced by restart(): an ingest run's external ids belong to the account that wrote them. */
  ledger = new RunLedger();
  /** Replaced by restart(): a card proposal belongs to the account that previewed it. */
  proposals = new ProposalStore();
  collections = [];
  collectionsLoaded = false;
  /**
   * What is known about each scope: true (held), false (refused), or absent
   * (not yet known). Filled whole from /api/user-info at startup when the
   * deployment reports `auth.scopes`; otherwise one fact at a time from the
   * refusals, which is the latch the first build had and is kept as the
   * fallback for an older server.
   */
  scopeFacts = /* @__PURE__ */ new Map();
  /** The list exactly as /api/user-info reported it, or null when it did not. */
  scopesReported = null;
  /** The server itself mentioned a `cards` scope — proof the deployment mints one even when the contract in hand is an old snapshot. */
  cardsScopeSeen = false;
  /** The same, for `delete`. */
  deleteScopeSeen = false;
  /** True when /api/user-info told us outright, rather than a write teaching us. */
  keyScopeKnownAtStartup = false;
  keyCollectionIds = null;
  startup = { reachable: false, keyValid: false, keyRefused: false, accountEmail: null, accountName: null, problem: null };
  /**
   * A tool's call came back 401 for a relayed credential (a key or an access
   * token revoked or expired mid-context). The remote transport drops a
   * context marked so, and the credential's next request starts afresh —
   * one user-info call, then its 401 challenge — instead of answering tool
   * errors under a dead credential for half an hour (KPE-003 review R2-2).
   */
  credentialRefused = false;
  /** Whether this copy is current, from GET /api/docs/clients; null when the deployment does not say. */
  updates = null;
  /** The update notice rides on ONE tool result per context, then stays quiet. */
  updateNoticeGiven = false;
  /**
   * keepr_connect's connection (src/oauthLocal.ts). Stdio only: a context
   * built from an environment has one, so it can connect when no key is set;
   * a remote context (built from a Config) never does — its bearer arrived
   * on the request and is the client's to manage.
   */
  connection;
  /**
   * Built from an environment (stdio: one process, one key, read at start)
   * or from a ready Config (remote: one context per bearer, src/remote.ts).
   * The contract cache may be shared: it is the deployment's vocabulary, the
   * same for every credential, and one anonymous fetch per version is enough
   * for a whole process.
   */
  constructor(envOrConfig = process.env, http, contract, connection) {
    this.config = isConfig(envOrConfig) ? envOrConfig : loadConfig(envOrConfig);
    this.connection = connection !== void 0 ? connection : isConfig(envOrConfig) ? null : new LocalConnection({ baseUrl: this.config.baseUrl, credentialsFile: credentialsFileFor(envOrConfig) });
    const bearer = this.config.apiKey ? null : this.connection;
    this.http = http ?? new KeeprHttp(this.config.baseUrl, this.config.apiKey, void 0, void 0, clientHeader(SERVER_VERSION, this.config.channel), bearer);
    this.contract = contract ?? new ContractCache(this.http);
  }
  /**
   * What this server holds, in the words a person knows (KPR-256): `key`
   * for a keepr API key (kpr_…), `connection` for everything else — an
   * assistant connected through keepr's consent page (the connector's
   * OAuth grant, keepr_connect's) holds no key, and telling it to "create
   * a key" sends the person to the wrong page.
   */
  get credential() {
    return this.config.apiKey?.startsWith("kpr_") ? "key" : "connection";
  }
  /** Requests go out on keepr_connect's connection rather than a key. */
  get usesConnection() {
    return !this.config.apiKey && Boolean(this.connection);
  }
  /**
   * Forget what startup learned and learn it again — after keepr_connect or
   * keepr_disconnect changed who this server acts as.
   */
  async restart() {
    this.startup = { reachable: false, keyValid: false, keyRefused: false, accountEmail: null, accountName: null, problem: null };
    this.scopeFacts.clear();
    this.scopesReported = null;
    this.keyScopeKnownAtStartup = false;
    this.keyCollectionIds = null;
    this.collections = [];
    this.collectionsLoaded = false;
    this.cardsScopeSeen = false;
    this.deleteScopeSeen = false;
    this.breaker = new RefusalBreaker();
    this.proposals = new ProposalStore();
    this.ledger = new RunLedger();
    await this.start();
  }
  /**
   * A 401 mid-session on a connection: http.ts already tried one refresh,
   * so the grant is gone. Every later call refuses with the reconnect
   * sentence instead of each tool's own 401 ("create a new key").
   */
  noteConnectionLost() {
    if (this.connection?.busyElsewhere) {
      return "keepr is renewing this connection in another window right now. Try the same call again in a moment.";
    }
    const sentence = "The keepr connection was disconnected or has expired. keepr_connect connects again: the person presses Allow on keepr's page in their browser. Every other tool refuses until then.";
    this.startup.keyValid = false;
    this.startup.problem = sentence;
    return sentence;
  }
  /**
   * Three independent steps, each degrading on its own. The server NEVER
   * fails to start: a server that refuses `initialize` gives the model
   * nothing to read, and "keepr is unreachable" is the single most important
   * thing it could have said.
   */
  async start() {
    await this.contract.load();
    this.startup.reachable = this.contract.isLive;
    if (this.startup.reachable && !this.filesOnly) {
      this.updates = statusFrom(await fetchClients(this.http, this.config.baseUrl), SERVER_VERSION, this.config.channel);
    }
    if (this.config.keyProblem) {
      this.startup.problem = this.config.keyProblem;
      return;
    }
    if (!this.config.apiKey && !this.connection?.connected) {
      this.startup.problem = this.connection ? `${this.connection.revoked ? "The keepr connection was disconnected or has expired." : "Not connected to keepr yet."} keepr_connect signs this server in: it opens keepr in the person's browser, where they sign in if needed and press Allow \u2014 nothing to copy or paste. Every other tool refuses until then.` + (this.filesOnly ? "" : keyWords.alsoAKey) : keyWords.notSignedIn;
      return;
    }
    try {
      const who = await this.http.request({ path: "/api/user-info" });
      if (who.ok && who.body) {
        this.startup.keyValid = true;
        this.startup.reachable = true;
        this.startup.accountEmail = typeof who.body.email === "string" ? cleanText(who.body.email, 254) : null;
        this.startup.accountName = typeof who.body.fullName === "string" ? cleanText(who.body.fullName, 200) : null;
        const scopes = who.body.auth?.scopes;
        if (Array.isArray(scopes) && scopes.length) {
          this.scopesReported = scopes.map(String);
          if (this.scopesReported.includes("cards"))
            this.cardsScopeSeen = true;
          if (this.scopesReported.includes("delete"))
            this.deleteScopeSeen = true;
          for (const name of SCOPE_NAMES)
            this.scopeFacts.set(name, this.scopesReported.includes(name));
          this.keyScopeKnownAtStartup = true;
        }
        this.keyCollectionIds = who.body.auth?.collectionIds ?? null;
      } else if (who.status === 401) {
        this.startup.reachable = true;
        this.startup.keyRefused = true;
        this.startup.problem = this.usesConnection && this.connection?.busyElsewhere ? "keepr is renewing this connection in another window right now; keepr_connect picks it up in a moment." : this.usesConnection ? "The keepr connection was disconnected or has expired (401 after a refresh). keepr_connect connects again: the person presses Allow on keepr's page in their browser. Every other tool refuses until then." : "The API key was refused (401): unknown, revoked, expired, or its owner is inactive. The user must create a new one. Do not retry.";
      } else {
        this.startup.reachable = true;
        this.startup.problem = `Unexpected ${who.status} from /api/user-info: ${errorMessage(who.body, "no message")}`;
      }
    } catch (err) {
      this.startup.problem = `keepr is unreachable from here: ${err.message}`;
      return;
    }
    if (this.startup.keyValid)
      await this.loadCollections();
  }
  async loadCollections() {
    const res = await this.http.request({ path: "/api/collections" });
    if (!res.ok || !Array.isArray(res.body))
      return;
    this.collections = res.body.map((c) => {
      const my = c.myAccess;
      const { label, writable } = accessLabel(my);
      const archived = c.status === "archived";
      const cardRole = ["owner", "manage"].includes(label);
      const row = {
        id: String(c._id ?? c.id ?? ""),
        // A collection's name is its owner's text, and every tool says it:
        // cleaned to one line here, where keepr's JSON becomes a row, so no
        // tool can forge a line from it (KPR-238 P5 re-check, R1). Nothing
        // is sent to keepr by name — a row goes by its id.
        name: cleanText(String(c.name ?? ""), COLLECTION_NAME_MAX),
        access: label,
        writable: writable && !archived,
        cardRole,
        // Two gates, and the second is the key's, not the role's: an
        // owner's key minted without Can change cards still cannot.
        canCreateCards: cardRole && !archived && this.hasScope("cards") !== false,
        archived,
        allowAttachments: typeof c.allowAttachments === "boolean" ? c.allowAttachments : null,
        kind: collectionKind(c),
        // A sub-collection names its parent: cards defined there are
        // usable here, and a record of one of this collection's own
        // cards is written HERE, not to the parent.
        parent: c.parent && typeof c.parent === "object" ? { id: String(c.parent._id ?? ""), name: cleanText(String(c.parent.name ?? ""), COLLECTION_NAME_MAX) } : null
      };
      const noun = this.credential;
      if (archived)
        row.blockedReason = "archived \u2014 read-only for everyone, including the owner";
      else if (!writable)
        row.blockedReason = `this ${noun}'s access here is "${label}"; writing needs write, manage or owner`;
      if (archived)
        row.cardsBlockedReason = "archived";
      else if (!cardRole)
        row.cardsBlockedReason = `this ${noun}'s access here is "${label}"; changing cards needs manage or owner`;
      else if (this.hasScope("cards") === false)
        row.cardsBlockedReason = `this ${noun} cannot change cards \u2014 it needs Can change cards`;
      return row;
    });
    this.collectionsLoaded = true;
  }
  knownCollections() {
    return this.collections;
  }
  get hasCollections() {
    return this.collectionsLoaded;
  }
  /**
   * Resolve a collection by id, then exact name, then unique
   * case-insensitive substring. Ambiguity is an ERROR listing the candidates
   * — never a guess, because guessing writes the user's data into the wrong
   * workspace and nothing downstream can detect that.
   */
  resolveCollection(ref) {
    const needle = cleanText(ref, 1e3);
    if (!needle)
      return { ok: false, message: "No collection given." };
    const byId = this.collections.find((c) => c.id === needle);
    if (byId)
      return { ok: true, row: byId };
    const exact = this.collections.filter((c) => c.name.toLowerCase() === needle.toLowerCase());
    if (exact.length === 1)
      return { ok: true, row: exact[0] };
    if (exact.length > 1)
      return { ok: false, message: this.ambiguous(needle, exact) };
    const partial = this.collections.filter((c) => c.name.toLowerCase().includes(needle.toLowerCase()));
    if (partial.length === 1)
      return { ok: true, row: partial[0] };
    if (partial.length > 1)
      return { ok: false, message: this.ambiguous(needle, partial) };
    if (/^[0-9a-fA-F]{24}$/.test(needle)) {
      return { ok: false, message: `No collection with id ${needle} is reachable by this key. A hidden collection answers 404, so this may be outside the key's allowlist. Do not look for somewhere else to put the data \u2014 ask the user.` };
    }
    const names = this.collections.map((c) => quoted(c.name, COLLECTION_NAME_MAX)).join(", ") || "(none)";
    return { ok: false, message: `No collection matches ${quoted(needle)}. This key can reach: ${names}.` };
  }
  ambiguous(needle, rows) {
    const list = rows.map((c) => `${quoted(c.name, COLLECTION_NAME_MAX)} (${c.id})`).join(", ");
    return `${quoted(needle)} matches ${rows.length} collections: ${list}. Ask the user which one \u2014 do not pick.`;
  }
  /** The write latch, as the first build named it: read from the scope facts. */
  get keyScope() {
    const w = this.scopeFacts.get("write");
    return w === true ? "write" : w === false ? "read" : "unknown";
  }
  /**
   * Does this key hold a scope? true / false / null for "not known yet".
   *
   * `cards` on a deployment whose contract does not document a cards scope
   * is the old rule — write authorised card changes — so it follows write
   * there. A build that refused card changes to every key against an older
   * server would be wrong in the direction that helps nobody.
   */
  hasScope(scope) {
    if (scope === "cards" && !this.cardsScopeExists())
      return this.hasScope("write");
    if (scope === "delete" && !this.deleteScopeExists())
      return this.hasScope("write");
    const fact = this.scopeFacts.get(scope);
    if (fact !== void 0)
      return fact;
    if (scope === "read" && (this.scopeFacts.get("write") || this.scopeFacts.get("cards")))
      return true;
    return null;
  }
  /** The scopes this key is known to hold, for reporting. */
  knownScopes() {
    return SCOPE_NAMES.filter((s) => (s !== "delete" || this.deleteScopeExists()) && this.hasScope(s) === true);
  }
  /**
   * Learn from a response to a call that needed `needed`. A success proves
   * the scope; a 403 insufficient_scope disproves one — the one the server
   * names in `requiredScope` when it does, else the one that was needed.
   */
  noteWriteAttempt(res, needed = "write") {
    if (res.ok) {
      this.scopeFacts.set(needed, true);
      return;
    }
    if (res.status !== 403 || !this.looksLikeScopeRefusal(res))
      return;
    const named = requiredScopeOf(res.body);
    if (named === "cards")
      this.cardsScopeSeen = true;
    if (named === "delete")
      this.deleteScopeSeen = true;
    const refused = named ?? needed;
    this.scopeFacts.set(refused, false);
    if (named === null && refused === "cards" && !this.cardsScopeExists())
      this.scopeFacts.set("write", false);
  }
  /** Does the deployment mint a `cards` scope at all? The contract says, or the server has said. */
  cardsScopeExists() {
    return this.cardsScopeSeen || this.contract.knowsScope("cards");
  }
  /** Does the deployment mint a `delete` scope? The contract says, or the server has said. */
  deleteScopeExists() {
    return this.deleteScopeSeen || this.contract.knowsScope("delete");
  }
  /**
   * `code` first, which is what every other refusal here is read by. The
   * message match stays as a fallback and is NOT dead code: a key can be
   * pointed at a deployment older than the change that added the code, and
   * an older server is exactly when a client should be most careful.
   */
  looksLikeScopeRefusal(res) {
    if (errorCode(res.body) === "insufficient_scope")
      return true;
    return errorMessage(res.body, "").includes("insufficient_scope");
  }
  readOnlyRefusal() {
    if (this.credential === "connection") {
      return "This connection is read-only, so it cannot write \u2014 a dry run is a write too, so it cannot even validate rows. " + WIDEN_CONNECTION("Read and write");
    }
    return 'This key has read scope, so it cannot write. Note a dry run is also a POST \u2014 a read key cannot even validate rows. Ask the user for a key with "Read and write" scope (web app -> My Profile -> API keys).';
  }
  /** The sentence for a card change this key is not allowed. Never "read-only": a read-and-write key gets it too. */
  cardsRefusal() {
    if (this.credential === "connection") {
      return 'This connection cannot change cards \u2014 it needs Can change cards, which "Read and write" does not include. ' + WIDEN_CONNECTION("Can change cards turned on");
    }
    return 'This key cannot change cards \u2014 it needs Can change cards. Creating or changing a card (or an element set or layout) is its own scope, and a "Read and write" key does not have it. Create or edit a key with Can change cards turned on (web app -> My Profile -> API keys).';
  }
  /** The sentence for a delete this key is not allowed. No tool here deletes; this is for relaying a refusal honestly. */
  deleteRefusal() {
    if (this.credential === "connection") {
      return "This connection cannot delete records \u2014 it needs Can delete records, which is off unless the person turned it on when they connected. Deleting is best done by the person in the web app.";
    }
    return 'This key cannot delete records \u2014 it needs Can delete records, a scope of its own that is off by default; "Read and write" does not include it, and keys made before 2026-09-24 do not have it. Deleting is best done by the user in the web app.';
  }
  refusalFor(scope) {
    if (scope === "delete")
      return this.deleteRefusal();
    return scope === "cards" ? this.cardsRefusal() : this.readOnlyRefusal();
  }
  /** The update notice, the first time it is asked for; null after, and null when current. */
  takeUpdateNotice() {
    if (this.updateNoticeGiven)
      return null;
    const notice = updateNotice(this.updates);
    if (notice)
      this.updateNoticeGiven = true;
    return notice;
  }
  /** Files-only mode (KEEPR_TOOLS=files, KPR-246): this server carries only the disk tools. */
  get filesOnly() {
    return this.config.toolset === "files";
  }
  /**
   * The tool that attaches ONE file from this computer's disk by its path:
   * keepr_attach_file on the full server, keepr_attach_local_file in
   * files-only mode — where keepr_attach_file is the connector's, which
   * runs on keepr's host and cannot read this disk.
   */
  get diskFileTool() {
    return this.filesOnly ? "keepr_attach_local_file" : "keepr_attach_file";
  }
  /** One line the client shows on connect. Computed, never canned. */
  instructions() {
    const lines = this.filesOnly ? [FILES_ONLY_PURPOSE] : ["keepr \u2014 structured records over the keepr API."];
    if (!this.startup.reachable) {
      lines.push(`keepr is UNREACHABLE from here (${this.config.baseUrl}). Every tool will refuse.`);
      return lines.join(" ");
    }
    if (this.startup.problem) {
      lines.push(this.startup.problem);
      return lines.join(" ");
    }
    const who = this.startup.accountEmail ?? this.startup.accountName ?? "an account";
    const how = this.config.keySource === "bearer" && this.credential === "connection" ? " through this connection" : `${this.config.keySource === "bearer" ? "" : ` at ${this.config.baseUrl}`}${this.config.apiKey && this.credential === "key" ? ` with key ${keyDisplayPrefix(this.config.apiKey)}\u2026` : this.usesConnection ? " through a connection made with keepr_connect" : ""}`;
    lines.push(`Acting as ${who}${how}.`, `${this.collections.length} collection${this.collections.length === 1 ? "" : "s"} reachable.`, `Contract ${this.contract.version}${this.contract.isLive ? "" : " (from a build-time snapshot; the live contract could not be fetched)"}.`, this.keyScopeKnownAtStartup ? this.scopeSentence() : "Write scope is unknown until the first write is attempted \u2014 this deployment does not report it.");
    const notice = updateNotice(this.updates);
    if (notice)
      lines.push(`

${notice}`);
    return lines.join(" ");
  }
  /** "This key has read, write and cards scope." — and what it cannot do, when that is worth a clause. */
  scopeSentence() {
    const held = this.knownScopes();
    const list = held.length <= 1 ? held.join("") : `${held.slice(0, -1).join(", ")} and ${held.at(-1)}`;
    const cannot = [];
    if (this.hasScope("write") === false)
      cannot.push("cannot write items");
    if (this.hasScope("cards") === false)
      cannot.push(`cannot change cards (that needs a ${this.credential} with Can change cards turned on)`);
    return `This ${this.credential} has ${list || "no known"} scope${cannot.length ? `: it ${cannot.join(" and ")}` : ""}.`;
  }
};
var FILES_ONLY_PURPOSE = "keepr file tools \u2014 the part of keepr that reads files on this computer's disk. keepr_attach_local_file attaches files to an item by their path, and keepr_attach_folder a whole folder onto the items its files belong to (keepr_attach_status follows that upload); keepr_connect and keepr_disconnect sign this server in to keepr and out. Every other keepr tool \u2014 collections, schema, items, search, charts, imports, cards, upload links \u2014 is on the keepr connector: The connector finds items and their ids; this server only sends files from this computer to them. An import made through the connector is not seen here, so name items by item_id, or match a folder by `collection` + `match_element` or a `map` of item ids.";
var WIDEN_CONNECTION = (what) => `The person can widen it in keepr: disconnect this assistant under Connected assistants on their account page, then connect again with ${what}.`;
function isConfig(v) {
  return typeof v.baseUrl === "string" && "keySource" in v;
}
function requiredScopeOf(body) {
  if (!body || typeof body !== "object")
    return null;
  const v = body.requiredScope;
  return v === "write" || v === "cards" || v === "read" || v === "delete" ? v : null;
}

// dist/src/tools/attach.js
import { createReadStream } from "node:fs";
import { stat as stat2, realpath } from "node:fs/promises";
import { basename as basename2 } from "node:path";

// dist/src/zodLite.js
var LiteSchema = class _LiteSchema {
  kind;
  spec;
  isOptional;
  description;
  bounds;
  constructor(kind, spec = {}, isOptional = false, description = void 0, bounds = {}) {
    this.kind = kind;
    this.spec = spec;
    this.isOptional = isOptional;
    this.description = description;
    this.bounds = bounds;
  }
  with(changes) {
    return new _LiteSchema(this.kind, this.spec, changes.isOptional ?? this.isOptional, changes.description ?? this.description, changes.bounds ?? this.bounds);
  }
  optional() {
    return this.with({ isOptional: true });
  }
  describe(description) {
    return this.with({ description });
  }
  min(n) {
    this.bounded("min");
    return this.with({ bounds: { ...this.bounds, min: n } });
  }
  max(n) {
    this.bounded("max");
    return this.with({ bounds: { ...this.bounds, max: n } });
  }
  strict() {
    return unsupported(".strict() \u2014 the files-only server drops unknown keys, as the SDK does for every tool not marked strict");
  }
  bounded(which) {
    if (this.kind !== "string" && this.kind !== "array")
      unsupported(`.${which}() on a ${this.kind}`);
  }
  /** The JSON Schema zod-to-json-schema writes for the same builder. */
  json() {
    const out = {};
    switch (this.kind) {
      case "string":
        out.type = "string";
        if (this.bounds.min !== void 0)
          out.minLength = this.bounds.min;
        if (this.bounds.max !== void 0)
          out.maxLength = this.bounds.max;
        break;
      case "boolean":
        out.type = "boolean";
        break;
      case "number":
        out.type = "number";
        break;
      case "array":
        out.type = "array";
        if (this.spec.item && this.spec.item.kind !== "custom")
          out.items = this.spec.item.json();
        if (this.bounds.min !== void 0)
          out.minItems = this.bounds.min;
        if (this.bounds.max !== void 0)
          out.maxItems = this.bounds.max;
        break;
      case "record":
        out.type = "object";
        out.additionalProperties = this.spec.value.json();
        break;
      case "union":
        out.anyOf = this.spec.options.map((o) => o.json());
        break;
      case "enum":
        out.type = "string";
        out.enum = [...this.spec.values];
        break;
      case "custom":
        break;
    }
    if (this.description !== void 0)
      out.description = this.description;
    return out;
  }
  /** Why `v` does not fit, or null. `at` is the path for the message. */
  problem(v, at) {
    if (v === void 0)
      return this.isOptional ? null : `Required at ${at}`;
    switch (this.kind) {
      case "string":
        if (typeof v !== "string")
          return `Expected string, received ${typeName(v)} at ${at}`;
        if (this.bounds.min !== void 0 && v.length < this.bounds.min)
          return `String must contain at least ${this.bounds.min} character(s) at ${at}`;
        if (this.bounds.max !== void 0 && v.length > this.bounds.max)
          return `String must contain at most ${this.bounds.max} character(s) at ${at}`;
        return null;
      case "boolean":
        return typeof v === "boolean" ? null : `Expected boolean, received ${typeName(v)} at ${at}`;
      case "number":
        return typeof v === "number" && Number.isFinite(v) ? null : `Expected number, received ${typeName(v)} at ${at}`;
      case "array": {
        if (!Array.isArray(v))
          return `Expected array, received ${typeName(v)} at ${at}`;
        if (this.bounds.min !== void 0 && v.length < this.bounds.min)
          return `Array must contain at least ${this.bounds.min} element(s) at ${at}`;
        if (this.bounds.max !== void 0 && v.length > this.bounds.max)
          return `Array must contain at most ${this.bounds.max} element(s) at ${at}`;
        for (let i = 0; i < v.length; i++) {
          const p = this.spec.item.problem(v[i], `${at}.${i}`);
          if (p)
            return p;
        }
        return null;
      }
      case "record": {
        if (!v || typeof v !== "object" || Array.isArray(v))
          return `Expected object, received ${typeName(v)} at ${at}`;
        for (const [k, x] of Object.entries(v)) {
          const p = this.spec.value.problem(x, `${at}.${k}`);
          if (p)
            return p;
        }
        return null;
      }
      case "union":
        return this.spec.options.some((o) => o.problem(v, at) === null) ? null : `Invalid input at ${at}`;
      case "enum":
        return typeof v === "string" && this.spec.values.includes(v) ? null : `Invalid enum value. Expected ${this.spec.values.map((x) => `'${x}'`).join(" | ")}, received ${typeof v === "string" ? `'${v}'` : typeName(v)} at ${at}`;
      case "custom":
        return null;
    }
  }
  /**
   * The value as zod's parse returns it, for a value `problem` passed: arrays
   * and records rebuilt, and a record's own `__proto__` key dropped, as zod
   * drops it (JSON.parse makes `"__proto__"` an ordinary own key).
   */
  clean(v) {
    if (v === void 0 || v === null)
      return v;
    switch (this.kind) {
      case "array":
        return v.map((x) => this.spec.item.clean(x));
      case "record": {
        const out = {};
        for (const k of Object.keys(v))
          if (k !== "__proto__")
            out[k] = this.spec.value.clean(v[k]);
        return out;
      }
      case "union": {
        const option = this.spec.options.find((o) => o.problem(v, "") === null);
        return option ? option.clean(v) : v;
      }
      default:
        return v;
    }
  }
};
function unsupported(what) {
  throw new Error(`zodLite (the files-only bundle's stand-in for zod) does not support ${what}. Add it to src/zodLite.ts with a test against zod, or keep the tool out of the files-only server.`);
}
function typeName(v) {
  if (v === null)
    return "null";
  if (Array.isArray(v))
    return "array";
  return typeof v;
}
function objectJson(shape) {
  const properties = {};
  const required = [];
  for (const [key, s] of Object.entries(shape)) {
    properties[key] = s.json();
    if (!s.isOptional)
      required.push(key);
  }
  const out = { type: "object", properties };
  if (required.length)
    out.required = required;
  if (Object.keys(shape).length)
    out.additionalProperties = false;
  out.$schema = "http://json-schema.org/draft-07/schema#";
  return out;
}
function parseArgs(shape, args) {
  if (typeof args !== "object" || args === null || Array.isArray(args))
    return { ok: false, message: `Expected object, received ${typeName(args)}` };
  const given = args;
  const value = {};
  for (const [key, s] of Object.entries(shape)) {
    const v = Object.prototype.hasOwnProperty.call(given, key) ? given[key] : void 0;
    const p = s.problem(v, key);
    if (p)
      return { ok: false, message: p };
    if (v !== void 0)
      value[key] = s.clean(v);
  }
  return { ok: true, value };
}
var builders = {
  string: () => new LiteSchema("string"),
  boolean: () => new LiteSchema("boolean"),
  number: () => new LiteSchema("number"),
  array: (item) => new LiteSchema("array", { item }),
  custom: (...check) => check.length ? unsupported("z.custom with a check \u2014 zodLite cannot run it") : new LiteSchema("custom"),
  record: (key, value) => key?.kind === "string" && value ? new LiteSchema("record", { value }) : unsupported("z.record keyed by anything but z.string(), or with no value schema"),
  union: (options) => new LiteSchema("union", { options }),
  enum: (values) => new LiteSchema("enum", { values }),
  object: () => unsupported("z.object \u2014 a tool's top level is its shape, and a nested object is not checked here")
};
var z = new Proxy(builders, {
  get(target, name) {
    if (typeof name === "string" && Object.prototype.hasOwnProperty.call(target, name))
      return target[name];
    if (typeof name === "symbol" || name === "then")
      return void 0;
    return unsupported(`z.${name}`);
  }
});

// dist/src/fileRules.js
var REFUSED_EXT = /* @__PURE__ */ new Set([
  "exe",
  "dll",
  "msi",
  "bat",
  "cmd",
  "com",
  "scr",
  "ps1",
  "sh",
  "jar",
  "apk",
  "vbs",
  "js",
  "mjs",
  "hta",
  "cpl",
  "pif",
  "lnk",
  "reg"
]);
var MAX_FILES = 20;
var MAX_FILE_BYTES = 100 * 1024 * 1024;
var PHOTO_EXT = /* @__PURE__ */ new Set(["jpg", "jpeg", "jpe", "png", "gif", "webp", "tif", "tiff", "avif", "heic", "heif"]);
function extOf(name) {
  return name.includes(".") ? name.split(".").pop().toLowerCase() : "";
}
var TYPES = {
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  jpe: "image/jpeg",
  png: "image/png",
  gif: "image/gif",
  webp: "image/webp",
  tif: "image/tiff",
  tiff: "image/tiff",
  avif: "image/avif",
  heic: "image/heic",
  heif: "image/heif",
  pdf: "application/pdf",
  txt: "text/plain",
  csv: "text/csv",
  json: "application/json",
  mov: "video/quicktime",
  mp4: "video/mp4",
  m4v: "video/x-m4v",
  mp3: "audio/mpeg",
  m4a: "audio/mp4",
  wav: "audio/wav",
  doc: "application/msword",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  xls: "application/vnd.ms-excel",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  zip: "application/zip"
};
function contentTypeFor(name) {
  return TYPES[extOf(name)] ?? "application/octet-stream";
}
function refusalFor(name, size, element, contentType) {
  const ext = extOf(name);
  if (REFUSED_EXT.has(ext))
    return `keepr refuses .${ext} files \u2014 executables and scripts are never accepted.`;
  if (size === 0)
    return "the file is empty.";
  if (size > MAX_FILE_BYTES)
    return `${mb(size)} \u2014 every attachment is limited to 100 MB.`;
  if (element) {
    if (element.accept === "image" && !PHOTO_EXT.has(ext) && !String(contentType ?? "").startsWith("image/")) {
      return `"${element.name}" takes photos only (JPEG, PNG, WebP, GIF, AVIF, TIFF, HEIC).`;
    }
    if (typeof element.maxSizeMb === "number" && size > element.maxSizeMb * 1024 * 1024) {
      return `${mb(size)} \u2014 larger than ${element.maxSizeMb} MB, the limit of "${element.name}".`;
    }
  }
  return null;
}
function mb(bytes) {
  if (bytes <= 0)
    return "0 KB";
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
function storedName(name) {
  let n = name.replace(/"/g, "%22").replace(/\r/g, "%0D").replace(/\n/g, "%0A");
  n = n.replace(/[\u0000-\u001f\u007f]/g, "").replace(/["\\]/g, "");
  n = n.split("/").pop() ?? "";
  n = n.replace(/^\.+/, "").trim();
  if (!n)
    return "file";
  if (n.length > 255) {
    const m = /\.([A-Za-z0-9]{1,12})$/.exec(n);
    const suffix = m ? `.${m[1].toLowerCase()}` : "";
    n = n.slice(0, 255 - suffix.length) + suffix;
  }
  return n;
}

// dist/src/agentPaths.js
import { statSync as statSync2 } from "node:fs";
import { readdir, readFile, stat } from "node:fs/promises";
import { homedir, userInfo } from "node:os";
import { join as join3, basename, dirname as dirname2, resolve } from "node:path";
function sessionsRoot(env = process.env) {
  return env.KEEPR_COWORK_SESSIONS || join3(homedir(), "Library", "Application Support", "Claude", "local-agent-mode-sessions");
}
async function findSession(name, root) {
  const cwd = `/sessions/${name}`;
  let level1;
  try {
    level1 = await readdir(root);
  } catch {
    return null;
  }
  for (const a of level1) {
    if (a === "skills-plugin")
      continue;
    let level2;
    try {
      level2 = await readdir(join3(root, a));
    } catch {
      continue;
    }
    for (const b of level2) {
      const dir = join3(root, a, b);
      let names;
      try {
        names = await readdir(dir);
      } catch {
        continue;
      }
      for (const n of names) {
        if (!/^local_.*\.json$/.test(n))
          continue;
        try {
          const rec = JSON.parse(await readFile(join3(dir, n), "utf8"));
          if (rec.cwd !== cwd)
            continue;
          return {
            record: join3(dir, n),
            sessionDir: join3(dir, n.replace(/\.json$/, "")),
            userSelectedFolders: Array.isArray(rec.userSelectedFolders) ? rec.userSelectedFolders.map(String) : []
          };
        } catch {
        }
      }
    }
  }
  return null;
}
async function exists(p) {
  try {
    await stat(p);
    return true;
  } catch {
    return false;
  }
}
async function resolveAgentPath(given, env = process.env) {
  if (await exists(given))
    return { path: given, mappedFrom: null };
  const m = /^\/sessions\/([^/]+)(\/.*)?$/.exec(given);
  if (!m)
    return { path: given, mappedFrom: null };
  const [, name, rest = ""] = m;
  const session = await findSession(name, sessionsRoot(env));
  if (!session)
    return { path: given, mappedFrom: null };
  const candidates = [];
  const mnt = /^\/mnt\/([^/]+)(\/.*)?$/.exec(rest);
  if (mnt) {
    const [, top, tail = ""] = mnt;
    if (top === "uploads" || top === "outputs")
      candidates.push(join3(session.sessionDir, top) + tail);
    for (const folder of session.userSelectedFolders)
      if (basename(folder) === top)
        candidates.push(folder + tail);
  }
  for (const c of candidates)
    if (await exists(c))
      return { path: c, mappedFrom: given };
  return { path: given, mappedFrom: null };
}
var PROTECTED = ["Documents", "Desktop", "Downloads"];
function pathProblem(given, code, filesOnly = false) {
  const link = filesOnly ? "Or the person can upload the files in keepr through an upload link, which the keepr connector makes." : "Or ask the person for the files with keepr_request_upload: it gives them a link to drop the files in keepr themselves.";
  if (code === "EPERM" || code === "EACCES") {
    const inProtected = PROTECTED.some((d) => given.startsWith(join3(homedir(), d)));
    return `macOS refused this server access to ${given}.` + (inProtected ? " Documents, Desktop and Downloads are protected: the person allows it in System Settings \u2192 Privacy & Security \u2192 Files and Folders (or Full Disk Access) for Claude, then tries again \u2014 or moves the files to Pictures or another folder." : " The person can allow it in System Settings \u2192 Privacy & Security.") + ` ${link}`;
  }
  if (code === "ENOENT" || code === "ENOTDIR") {
    if (given.startsWith("/sessions/")) {
      return `${given} is a path inside your Cowork sandbox, and no folder selected for this Cowork session holds it on this computer. This server can read a folder the person selected for the session (it appears under /sessions/<name>/mnt/<folder>), or a path on the computer itself. Files made inside the sandbox, or dragged into the chat, are not on this computer's disk. ${link}`;
    }
    return `Nothing at ${given} on the computer this server runs on. This server reads that computer's own disk \u2014 from Claude Code that is the person's computer; from a sandbox (Cowork, claude.ai, a container) it is not the sandbox's files. Give the path as it is on this computer. ${link}`;
  }
  return `Could not read ${given}: ${code ?? "unknown error"}. ${link}`;
}
var HIDDEN2 = { kind: "hidden" };
var TOO_LONG = { kind: "too-long" };
function identity(p) {
  try {
    const st = statSync2(p, { bigint: true });
    return { dev: st.dev, ino: st.ino };
  } catch {
    return null;
  }
}
var same = (a, b) => !!a && !!b && a.dev === b.dev && a.ino === b.ino;
function homes() {
  const out = [homedir()];
  try {
    const passwd = userInfo().homedir;
    if (passwd && passwd !== out[0])
      out.push(passwd);
  } catch {
  }
  return out;
}
function credentialStores(platform = process.platform, env = process.env) {
  const stores = [];
  if (platform === "win32") {
    if (env.APPDATA?.trim())
      stores.push({ label: "%APPDATA%", path: env.APPDATA.trim() });
    if (env.LOCALAPPDATA?.trim())
      stores.push({ label: "%LOCALAPPDATA%", path: env.LOCALAPPDATA.trim() });
  }
  for (const home of homes()) {
    if (platform === "darwin")
      stores.push({ label: "~/Library", path: join3(home, "Library") });
    if (platform === "linux")
      stores.push({ label: "~/snap", path: join3(home, "snap") });
    if (platform === "win32") {
      stores.push({ label: "%APPDATA%", path: join3(home, "AppData", "Roaming") });
      stores.push({ label: "%LOCALAPPDATA%", path: join3(home, "AppData", "Local") });
    }
  }
  return stores;
}
function cloudDrives(platform = process.platform) {
  if (platform !== "darwin")
    return [];
  return homes().map((home) => join3(home, "Library", "CloudStorage"));
}
function iCloudFolders(platform = process.platform) {
  if (platform !== "darwin")
    return [];
  return homes().map((home) => join3(home, "Library", "Mobile Documents"));
}
var ICLOUD_DRIVE = "com~apple~CloudDocs";
function inICloudDocuments(chain) {
  const mobile = chain[chain.length - 1];
  const container = chain[chain.length - 2];
  const inside2 = chain[chain.length - 3];
  if (!container)
    return false;
  if (same(identity(container), identity(join3(mobile, ICLOUD_DRIVE))))
    return true;
  return !!inside2 && same(identity(inside2), identity(join3(container, "Documents")));
}
function storeMatcher(platform = process.platform, env = process.env) {
  const stores = credentialStores(platform, env).map((s) => ({ label: s.label, id: identity(s.path) })).filter((s) => s.id);
  return (p) => {
    if (!stores.length)
      return null;
    const id = identity(p);
    return stores.find((s) => same(s.id, id))?.label ?? null;
  };
}
var MAX_PATH_CHARS = 4096;
function pathLengthProblem(p) {
  if (p.length <= MAX_PATH_CHARS)
    return null;
  return `That path is ${p.length.toLocaleString("en-US")} characters long \u2014 no file or folder on this computer has a path that long (${MAX_PATH_CHARS.toLocaleString("en-US")} at most). Give the path as it is on this computer's disk.`;
}
function secretPlace(p, platform = process.platform, env = process.env) {
  if (p.length > MAX_PATH_CHARS)
    return TOO_LONG;
  const name = p.split(/[\\/]/).filter(Boolean).pop() ?? "";
  if (name.startsWith("."))
    return HIDDEN2;
  const homeIds = homes().map(identity).filter((h) => !!h);
  const stores = credentialStores(platform, env).map((s) => ({ label: s.label, id: identity(s.path) })).filter((s) => s.id);
  const clouds = cloudDrives(platform).map(identity).filter((c) => !!c);
  const mobile = iCloudFolders(platform).map(identity).filter((m) => !!m);
  let cur = resolve(p);
  let child = "";
  let inCloud = false;
  const chain = [];
  for (; ; ) {
    chain.push(cur);
    const id = identity(cur);
    if (id) {
      if (clouds.some((c) => same(c, id)))
        inCloud = true;
      if (mobile.some((m) => same(m, id)) && inICloudDocuments(chain))
        inCloud = true;
      const store = stores.find((s) => same(s.id, id));
      if (store && !inCloud)
        return { kind: "store", label: store.label };
      if (homeIds.some((h) => same(h, id)) && child.startsWith("."))
        return HIDDEN2;
    }
    const up = dirname2(cur);
    if (up === cur)
      return null;
    child = basename(cur);
    cur = up;
  }
}
function secretRefusal(given, kind, secret, real) {
  const them = kind === "file" ? "it" : "its files";
  if (secret.kind === "too-long")
    return pathLengthProblem(real ?? given) ?? `${given} is too long a path.`;
  if (secret.kind === "store") {
    const where = `${secret.label}, where this computer keeps keys, passwords and app settings`;
    return real ? `${given} leads to ${real}, inside ${where} \u2014 nothing there is attached from here.` : `${given} is inside ${where} \u2014 nothing there is attached from here. If the person wants ${them} attached, they can do it in keepr.`;
  }
  if (real)
    return `${given} leads to a hidden ${kind} (${real}) \u2014 those are never attached from here.`;
  return `${given} is a hidden ${kind} or inside a hidden folder \u2014 those are never attached from here. If the person wants ${them} attached, they can do it in keepr.`;
}
function remotePathProblem(p, platform = process.platform) {
  if (platform !== "win32")
    return null;
  if (!/^[\\/]{2}/.test(p) && !/^\\\?\?\\/.test(p))
    return null;
  return `${p} is a network or device path, which this server never opens \u2014 opening one can send the person's Windows sign-in to another computer. Give the path of a file or folder on this computer's own disk.`;
}

// dist/src/tools/attach.js
var HEX24 = /^[0-9a-fA-F]{24}$/;
var MAX_INLINE_BYTES = 1e6;
var LOCAL_FILE_TOOL = "keepr_attach_local_file";
var LOCAL_TOOLS_PRESENT = "only if keepr's local file tools are among your tools and the file is on that computer";
var attachFileTool = {
  name: "keepr_attach_file",
  title: "Attach files",
  // The stdio server's full mode (a path works there). The connector lists
  // attachFileOnConnectorTool below, in its own words.
  description: "Attaches files to a keepr item. A file held in the conversation goes as content_base64 with a filename, about a megabyte at most; a file on this computer goes by its `path`, streamed from disk, up to 100 MB. keepr_attach_folder fits many files, and keepr_request_upload gives the person a link for files this server cannot read. The item is named by item_id, or by external_id from a keepr_ingest run. With `element`, the files go into one of the item's file elements: a single file element is replaced (the old file is deleted, which needs Can delete records), a list is appended to.",
  writes: true,
  // It can replace the file in a single file element. Not idempotent:
  // skip_if_present: false uploads the same file again.
  annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
  inputSchema: {
    item_id: z.string().optional().describe("The item to attach to, 24 hex characters."),
    run_id: z.string().optional().describe("A runId from a committed keepr_ingest, used with external_id instead of item_id."),
    external_id: z.string().optional().describe("The external_id of a row written by keepr_ingest in this session."),
    files: z.array(z.custom()).min(1).max(20).describe("Files: {filename, content_base64, content_type?} for a small file held in the conversation (about a megabyte at most; the file as the person gave it, not resized or converted) \u2014 or {path} for a file on the computer this server runs on."),
    skip_if_present: z.boolean().optional().describe("Default true. Skips a file whose name is already attached, so re-running after adding two photos uploads two photos. With `element`, an attachment already there is reused only when no element holds it and its name and size both match; anything else is uploaded fresh."),
    element: z.string().optional().describe(`A file element of the item's card to put the files into (its name, as keepr_schema lists it, dataType "file", with accept, maxSizeMb and allowMultiple). A single file element takes one file and is replaced; a list is appended to, 20 files at most. Without it, the files are the item's other attachments.`)
  },
  handler: async (args, ctx) => {
    let itemId = typeof args.item_id === "string" ? args.item_id : "";
    if (!itemId && typeof args.external_id === "string" && args.external_id) {
      const found = ctx.ledger.resolveExternalId(args.external_id, typeof args.run_id === "string" ? args.run_id : null);
      if (!found) {
        const known = ctx.ledger.size;
        return fail(`No item in this session was written with external_id "${args.external_id}".` + (known ? ` ${known} ingest run${known === 1 ? "" : "s"} are remembered, but none contains it.` : " No committed ingest runs are remembered \u2014 a dry run does not create anything to attach to.") + "\n\nUse keepr_get_items to find the item and pass its item_id instead.");
      }
      itemId = found.itemId;
    }
    if (!HEX24.test(itemId)) {
      return fail("No item given. Pass item_id (24 hex characters), or external_id from a committed keepr_ingest run in this session.");
    }
    const files = args.files ?? [];
    if (!Array.isArray(files) || !files.length)
      return fail("No files given.");
    const item = await ctx.http.request({ path: `/api/items/${itemId}` });
    if (!item.ok)
      return failFromResponse(item, `reading item ${itemId}`);
    const collectionId = String(item.body?.collection_id ?? "");
    const collection = ctx.knownCollections().find((c) => c.id === collectionId);
    if (collection?.allowAttachments === false) {
      return fail(`Attachments are turned off for ${quoted(collection.name)}. Every upload here is refused until someone enables them in the collection's settings in the web app.`);
    }
    if (collection?.archived) {
      return fail(`${quoted(collection.name)} is archived and is read-only for everyone, so nothing can be attached.`);
    }
    const elementName = typeof args.element === "string" ? args.element.trim() : "";
    let target = null;
    let current = [];
    if (elementName) {
      const schema = await ctx.http.request({ path: `/api/collections/${collectionId}/schema` });
      if (!schema.ok)
        return failFromResponse(schema, "reading the elements of this item's collection");
      const card = (schema.body?.cards ?? []).find((c) => c.id === String(item.body?.card_id ?? ""));
      const fileElements = (card?.elements ?? []).filter((e) => e.dataType === "file");
      target = fileElements.find((e) => e.name === elementName) ?? null;
      if (!target) {
        return fail(`"${elementName}" is not a file element of this item's card.` + (fileElements.length ? ` Its file elements: ${fileElements.map((e) => identifierText(String(e.name))).join(", ")}.` : " The card has no file element \u2014 leave out `element` to attach the files as other attachments."));
      }
      const stored = item.body?.elements?.[elementName];
      current = (Array.isArray(stored) ? stored : stored ? [stored] : []).map(String).filter(Boolean);
      if (!target.allowMultiple && files.length > 1) {
        return fail(`"${elementName}" holds one file, and ${files.length} were given. Pass one file for it, or leave out \`element\` to attach the rest as other attachments.`);
      }
      if (target.allowMultiple && current.length + files.length > MAX_FILES) {
        return fail(`"${elementName}" holds at most ${MAX_FILES} files; it has ${current.length}, and ${files.length} more would pass that.`);
      }
      if (!target.allowMultiple && current.length && ctx.hasScope("delete") === false) {
        return fail(`"${elementName}" already holds a file, and putting another there REPLACES it: the old file is deleted (restorable for 30 days), which needs Can delete records. ${ctx.deleteRefusal()}`);
      }
    }
    const present = /* @__PURE__ */ new Map();
    if (args.skip_if_present !== false) {
      const existing = await ctx.http.request({ path: `/api/items/${itemId}/attachments` });
      if (existing.ok && Array.isArray(existing.body)) {
        for (const a of existing.body)
          present.set(String(a.originalName ?? ""), { id: String(a._id ?? ""), element: a.element ?? null, size: typeof a.size === "number" ? a.size : null });
      }
    }
    const bindReplaces = !!target && !target.allowMultiple && current.length > 0;
    const toBind = [];
    const allowPath = ctx.config.keySource !== "bearer";
    const tooLarge = [];
    const uploaded = [];
    const skipped = [];
    const failed = [];
    for (const spec of files) {
      const loaded = await loadBytes(spec, allowPath, ctx.filesOnly);
      if (!loaded.ok) {
        failed.push({ filename: loaded.filename, message: loaded.message });
        if (loaded.tooLarge)
          tooLarge.push(loaded.filename);
        continue;
      }
      const { filename, size } = loaded;
      const there = present.get(filename);
      if (there && !target) {
        skipped.push({ filename, reason: "already attached to this item" });
        continue;
      }
      if (there && target && there.id && there.size === size) {
        if (there.element === elementName && current.includes(there.id)) {
          skipped.push({ filename, reason: `already in "${elementName}"` });
          continue;
        }
        if (there.element === null && !bindReplaces && !toBind.includes(there.id)) {
          toBind.push(there.id);
          skipped.push({ filename, reason: "already attached to this item (same name and size) \u2014 put into the element" });
          continue;
        }
      }
      const ext = filename.includes(".") ? filename.split(".").pop().toLowerCase() : "";
      if (REFUSED_EXT.has(ext)) {
        failed.push({ filename, message: `keepr refuses .${ext} files \u2014 executables and scripts are never accepted. Images, PDFs and documents are fine.` });
        continue;
      }
      if (target && target.accept === "image" && !PHOTO_EXT.has(ext) && !String(spec.content_type ?? "").startsWith("image/")) {
        failed.push({ filename, message: `"${elementName}" takes photos only (JPEG, PNG, WebP, GIF, AVIF, TIFF, HEIC) \u2014 a PDF or a document never fits it. Leave out \`element\` to attach it as another attachment.` });
        continue;
      }
      if (target && typeof target.maxSizeMb === "number" && size > target.maxSizeMb * 1024 * 1024) {
        failed.push({ filename, message: `larger than ${target.maxSizeMb} MB, the limit of "${elementName}".` });
        continue;
      }
      let form;
      if (loaded.inline) {
        form = new FormData();
        form.append("file", new Blob([new Uint8Array(loaded.inline)], { type: spec.content_type || "application/octet-stream" }), filename);
      }
      let res;
      try {
        res = await ctx.http.request({
          method: "POST",
          path: `/api/items/${itemId}/attachments`,
          ...form ? { formData: form } : { stream: loaded.stream }
        });
      } catch (err) {
        if (err instanceof FileChangedError) {
          failed.push({ filename, message: err.kind === "unreadable" ? `it could not be read from the disk: ${err.message}.` : "it changed while it was being sent. Try again once it is finished being written." });
          continue;
        }
        throw err;
      }
      ctx.noteWriteAttempt(res);
      if (!res.ok) {
        if (res.status === 403 && ctx.keyScope === "read")
          return fail(ctx.readOnlyRefusal());
        const code = errorCode(res.body);
        const meaning = code ? ctx.contract.meaningOf(code) : null;
        const said = `${code ? `${code}: ` : ""}${errorMessage(res.body, "")}${meaning ? ` (${meaning})` : ""}`.trim();
        const why = res.status === 413 ? "over the per-user attachment cap (100 MB). The user has to free space before this will work." : res.status === 403 ? `refused \u2014 attachments may be off for this collection, or the owner's email is unverified.${said ? ` keepr said: ${said}` : ""}` : said || `HTTP ${res.status}`;
        failed.push({ filename, message: why });
        continue;
      }
      uploaded.push({ attachmentId: String(res.body?._id ?? ""), filename, bytes: size });
      present.set(filename, { id: String(res.body?._id ?? ""), element: null, size });
      if (target && res.body?._id)
        toBind.push(String(res.body._id));
    }
    let bound = [];
    let bindError = null;
    if (target && toBind.length) {
      const replacing = !target.allowMultiple && current.length > 0;
      const value = target.allowMultiple ? [...current, ...toBind] : toBind[0];
      const put = await ctx.http.request({
        method: "PUT",
        path: `/api/items/${itemId}`,
        body: { elements: { [elementName]: value }, merge: true }
      });
      ctx.noteWriteAttempt(put, replacing ? "delete" : "write");
      if (put.ok)
        bound = target.allowMultiple ? toBind : [toBind[0]];
      else {
        const code = errorCode(put.body);
        const meaning = code ? ctx.contract.meaningOf(code) : null;
        bindError = `${code ? `${code}: ` : ""}${errorMessage(put.body, `HTTP ${put.status}`)}${meaning ? ` (${meaning})` : ""}` + (put.status === 403 && replacing ? ` ${ctx.deleteRefusal()}` : "");
      }
    }
    const title = item.body?.displayValue ? sayName(item.body.displayValue) : itemId;
    const lines = [
      failed.length ? `PARTIAL \u2014 ${uploaded.length} attached to "${title}", ${failed.length} failed.` : `Attached ${uploaded.length} file${uploaded.length === 1 ? "" : "s"} to "${title}".`
    ];
    if (target && bound.length) {
      lines.push("", !target.allowMultiple && current.length ? `Put into "${elementName}", replacing the file that was there (deleted softly \u2014 History can bring it back for 30 days).` : `Put into "${elementName}" (${bound.length} file${bound.length === 1 ? "" : "s"}).`);
    }
    if (bindError)
      lines.push("", `NOT PUT INTO "${elementName}" \u2014 keepr refused the bind: ${bindError}`, "The uploaded files stay on the item as other attachments.");
    if (uploaded.length) {
      lines.push("", "ATTACHED:");
      for (const u of uploaded)
        lines.push(`  ${u.filename}  (${u.bytes} bytes)`);
    }
    if (skipped.length) {
      lines.push("", "SKIPPED:");
      for (const s of skipped)
        lines.push(`  ${s.filename} \u2014 ${s.reason}`);
    }
    if (failed.length) {
      lines.push("", "FAILED:");
      for (const f of failed)
        lines.push(`  ${f.filename} \u2014 ${f.message}`);
    }
    const next = tooLarge.length ? routesFor(tooLarge, itemId, collectionId, elementName || null, allowPath) : null;
    if (next)
      lines.push("", ...next.lines);
    const result = {
      itemId,
      itemDisplayValue: item.body?.displayValue ?? null,
      uploaded,
      skipped,
      failed,
      ...target ? { element: elementName, bound, ...bindError ? { bindError } : {} } : {},
      ...next ? { next: next.calls } : {}
    };
    return failed.length || bindError ? fail(lines.join("\n"), result) : ok(lines.join("\n"), result);
  }
};
function routesFor(names, itemId, collectionId, element, allowPath) {
  const request = { tool: "keepr_request_upload", args: { collection: collectionId, entries: names.map((name) => ({ item_id: itemId, name, ...element ? { element } : {} })) } };
  const lines = [`NEXT \u2014 ${names.length === 1 ? "this file is" : "these files are"} too big to send inline (about a megabyte at most). Do NOT resize or convert ${names.length === 1 ? "it" : "them"}.`];
  const calls = [];
  if (allowPath) {
    const byPath = { tool: "keepr_attach_file", args: { item_id: itemId, files: names.map(() => ({ path: "<where the file is on this computer>" })), ...element ? { element } : {} } };
    lines.push("  If the file is on the computer this server runs on (Claude Code, the extension, the plugin), give its path \u2014 streamed from disk, up to 100 MB:", `    keepr_attach_file ${JSON.stringify(byPath.args)}`, "  Many files in one folder: keepr_attach_folder.", "  If you cannot reach the file (it is on the person's phone, or only in the chat), ask the person for it with a link:");
    calls.push(byPath);
  } else {
    const local = { tool: LOCAL_FILE_TOOL, args: { item_id: itemId, files: names.map(() => ({ path: "<where the file is on that computer>" })), ...element ? { element } : {} }, when: LOCAL_TOOLS_PRESENT };
    lines.push("  This connector cannot read files from the person's computer. If keepr's local file tools are among your tools (the keepr plugin adds them in Claude Code, and in Cowork on the person's computer) and the file is on that computer, attach it from there by its path \u2014 streamed from disk, up to 100 MB:", `    ${LOCAL_FILE_TOOL} ${JSON.stringify(local.args)}`, "  Many files in one folder: keepr_attach_folder, from the same local tools.", "  Otherwise (no local file tools, or the file is only in the chat or on a phone), ask the person for it with a link \u2014 they drop it in keepr, and you can check it arrived:");
    calls.push(local);
  }
  lines.push(`    keepr_request_upload ${JSON.stringify(request.args)}`);
  calls.push(request);
  return { lines, calls };
}
async function loadBytes(spec, allowPath, filesOnly = false) {
  if (spec.content_base64) {
    const name = spec.filename || "attachment";
    let bytes;
    try {
      bytes = Buffer.from(spec.content_base64, "base64");
    } catch {
      return { ok: false, filename: name, message: "content_base64 is not valid base64." };
    }
    if (!bytes.length)
      return { ok: false, filename: name, message: "content_base64 decoded to zero bytes." };
    if (bytes.length > MAX_INLINE_BYTES) {
      return { ok: false, filename: name, tooLarge: true, message: `${mb(bytes.length)} is too big to send inline (about a megabyte at most) \u2014 see NEXT for the way that works.` };
    }
    if (!spec.filename)
      return { ok: false, filename: name, message: "content_base64 was given without a filename. keepr stores the name, so it cannot be guessed." };
    return { ok: true, filename: spec.filename, size: bytes.length, inline: bytes };
  }
  if (spec.path) {
    const name = spec.filename || basename2(spec.path);
    if (!allowPath) {
      return {
        ok: false,
        filename: name,
        message: `this connector cannot read files by path \u2014 it runs on keepr's servers, not on the person's computer. If keepr's local file tools are among your tools, ${LOCAL_FILE_TOOL} attaches it by path from there. A small file you hold: content_base64 with a filename (about a megabyte at most). Anything else: keepr_request_upload gives the person a link to upload it.`
      };
    }
    const remote = remotePathProblem(spec.path) ?? pathLengthProblem(spec.path);
    if (remote)
      return { ok: false, filename: name, message: remote };
    const secret = secretPlace(spec.path);
    if (secret)
      return { ok: false, filename: name, message: secretRefusal(spec.path, "file", secret) };
    const { path } = await resolveAgentPath(spec.path);
    let size;
    try {
      const real = await realpath(path);
      const leadsTo = secretPlace(real);
      if (leadsTo)
        return { ok: false, filename: name, message: secretRefusal(spec.path, "file", leadsTo, real) };
      const st = await stat2(path);
      if (!st.isFile())
        return { ok: false, filename: name, message: `${spec.path} is not a file.` };
      size = st.size;
    } catch (err) {
      return { ok: false, filename: name, message: pathProblem(spec.path, err.code, filesOnly) };
    }
    if (size > MAX_FILE_BYTES)
      return { ok: false, filename: name, message: "over 100 MB \u2014 every attachment is limited to 100 MB." };
    if (!size)
      return { ok: false, filename: name, message: "the file is empty." };
    return {
      ok: true,
      filename: name,
      size,
      stream: { open: () => createReadStream(path), length: size, filename: name, contentType: spec.content_type || contentTypeFor(name) }
    };
  }
  return { ok: false, filename: spec.filename || "attachment", message: "neither content_base64 nor path was given." };
}
var attachFileOnConnectorTool = {
  ...attachFileTool,
  title: "Attach a small file",
  // What the connector can do, in its own words (KPR-256): no `path`, no
  // "plugin" or "extension", and the local tools only on their condition.
  description: `Attaches a small file held in the conversation to a keepr item: content_base64 with a filename, about a megabyte at most, every character passing through the chat. This connector runs on keepr's servers and cannot read the person's disk. A larger file, or one on the person's computer, goes through keepr's local file tools when they are among the tools (${LOCAL_FILE_TOOL}, keepr_attach_folder), otherwise through keepr_request_upload's link. With \`element\`, they go into a file element: a single one is replaced (its old file deleted, which needs Can delete records), a list appended to.`,
  inputSchema: {
    ...attachFileTool.inputSchema,
    files: z.array(z.custom()).min(1).max(20).describe("Files: {filename, content_base64, content_type?} \u2014 a small file held in the conversation (about a megabyte at most; the file as the person gave it, not resized or converted). This connector reads no file from a disk.")
  }
};
var attachLocalFileTool = {
  name: LOCAL_FILE_TOOL,
  title: "Attach files from this computer",
  // The Claude directory's review (KPR-251): say what the tool does and when
  // it fits; no lines aimed at the model's behaviour, no outside software, no
  // tool this server does not list.
  description: "Attaches files from this computer's disk to one keepr item, by their path. Each file is streamed from disk, up to 100 MB, so nothing passes through the conversation; keepr_attach_folder fits a whole folder. The item is named by its id, 24 hex characters. With `element`, the files go into one of the item's file elements: a single file element takes one file and replaces the file there (the old file is deleted, which needs Can delete records), and a list takes up to 20. Without `element`, they are the item's other attachments.",
  writes: true,
  // Not idempotent by contract: a re-run skips a same-named file, but a
  // single file element is replaced. It writes to keepr, a closed world.
  annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
  inputSchema: {
    item_id: z.string().describe("The item to attach to, 24 hex characters."),
    files: z.array(z.custom()).min(1).max(20).describe("Files: {path, filename?, content_type?} \u2014 path is where the file is on this computer (in Cowork, inside a folder the person selected for the session, under /sessions/<name>/mnt/); filename renames it in keepr. Hidden files, and anything in a hidden folder of the home folder, are not attached."),
    skip_if_present: z.boolean().optional().describe("Default true. Skips a file whose name is already attached, so re-running after adding two photos uploads two photos. With `element`, an attachment already there is reused only when no element holds it and its name and size both match; anything else is uploaded fresh."),
    element: z.string().optional().describe("A file element of the item's card to put the files into, by its name. A single file element is replaced; a list is appended to.")
  },
  handler: async (args, ctx) => {
    const itemId = typeof args.item_id === "string" ? args.item_id.trim() : "";
    if (!HEX24.test(itemId)) {
      return fail("No item given. Pass item_id: the item's id in keepr, 24 hex characters.");
    }
    const files = Array.isArray(args.files) ? args.files : [];
    if (!files.length)
      return fail("No files given.");
    const inline = files.filter((f) => f && typeof f === "object" && f.content_base64);
    const pathless = files.filter((f) => !f || typeof f !== "object" || typeof f.path !== "string" || !f.path.trim());
    if (inline.length || pathless.length) {
      return fail(`${LOCAL_FILE_TOOL} reads files from this computer by \`path\`, and ${inline.length ? "takes no content_base64" : `${pathless.length} of the files had no path`}. A small file held in the conversation goes up through the keepr connector instead.`);
    }
    return attachFileTool.handler({
      item_id: itemId,
      files: files.map((f) => ({ path: f.path, ...f.filename ? { filename: f.filename } : {}, ...f.content_type ? { content_type: f.content_type } : {} })),
      ...args.skip_if_present !== void 0 ? { skip_if_present: args.skip_if_present } : {},
      ...args.element !== void 0 ? { element: args.element } : {}
    }, ctx);
  }
};

// dist/src/tools/attachFolder.js
import { stat as stat5, realpath as realpath4 } from "node:fs/promises";
import { createHash as createHash2, randomBytes as randomBytes5 } from "node:crypto";

// dist/src/folderMatch.js
import { readdir as readdir2, stat as stat3, realpath as realpath2 } from "node:fs/promises";
import { join as join4, relative, sep, basename as basename3, extname } from "node:path";
var MATCH_MODES = ["auto", "folder", "stem", "exact"];
var COUNTER_SUFFIX = /[\s._-]*(?:\(\s*[0-9]+\s*\)|[0-9]+)$/;
function stemOf(name) {
  const ext = extname(name);
  return ext && ext !== name ? name.slice(0, -ext.length) : name;
}
function keyFor(rel, mode) {
  const parts = rel.normalize("NFC").split("/").filter(Boolean);
  const name = parts[parts.length - 1] ?? "";
  const parent = parts.slice(0, -1);
  const stem = stemOf(name);
  if (mode === "folder")
    return parent.length ? parent[0] : null;
  if (mode === "exact")
    return stem;
  const stripped = stem.replace(COUNTER_SUFFIX, "") || stem;
  if (mode === "stem")
    return stripped;
  return parent.length ? parent[0] : stripped;
}
function keysFor(rel, mode) {
  if (mode !== "auto") {
    const k = keyFor(rel, mode);
    return k ? [k] : [];
  }
  const folder = keyFor(rel, "folder");
  if (folder)
    return [folder];
  const out = [];
  for (const k of [keyFor(rel, "exact"), keyFor(rel, "stem")])
    if (k && !out.includes(k))
      out.push(k);
  return out;
}
function inside(root, p) {
  return p === root || p.startsWith(root.endsWith(sep) ? root : root + sep);
}
function fenceProblem(rootReal, real) {
  if (!inside(rootReal, real))
    return `it is a link to ${real}, outside this folder`;
  if (relative(rootReal, real).split(sep).some((seg) => seg.startsWith(".")))
    return `it is a link to a hidden file (${real})`;
  return null;
}
async function listFiles(root, limit = 2e4, checkedReal) {
  const files = [];
  const skipped = [];
  let truncated = false;
  const rootReal = checkedReal ?? await realpath2(root);
  const relOf = (p) => relative(root, p).split(sep).join("/");
  const storeAt = storeMatcher();
  async function walk(dir, top) {
    if (truncated)
      return;
    let entries;
    try {
      entries = await readdir2(dir, { withFileTypes: true });
    } catch (err) {
      if (top)
        throw err;
      skipped.push({ rel: `${relOf(dir)}/`, reason: `this folder could not be read (${err.code ?? "error"}) \u2014 its files were left out` });
      return;
    }
    const dirs = entries.filter((e) => e.isDirectory() && !e.name.startsWith(".")).map((e) => e.name).sort().filter((d) => {
      const store = storeAt(join4(dir, d));
      if (store)
        skipped.push({ rel: `${relOf(join4(dir, d))}/`, reason: `${store}, where this computer keeps keys, passwords and app settings \u2014 left out` });
      return !store;
    });
    const names = entries.filter((e) => (e.isFile() || e.isSymbolicLink()) && !e.name.startsWith(".")).map((e) => e.name).sort();
    for (const name of names) {
      const path = join4(dir, name);
      let st;
      let real;
      try {
        st = await stat3(path);
        real = await realpath2(path);
      } catch {
        continue;
      }
      if (!st.isFile())
        continue;
      const fenced = fenceProblem(rootReal, real);
      if (fenced) {
        skipped.push({ rel: relOf(path), reason: `${fenced} \u2014 left out` });
        continue;
      }
      const secret = real !== path ? secretPlace(real) : null;
      if (secret) {
        skipped.push({ rel: relOf(path), reason: `it is a link to ${real}, ${secret.kind === "store" ? `inside ${secret.label}` : "a hidden place"} \u2014 left out` });
        continue;
      }
      if (files.length >= limit) {
        truncated = true;
        return;
      }
      files.push({ path, rel: relOf(path), name, size: st.size, mtimeMs: st.mtimeMs, ctimeMs: st.ctimeMs, ino: st.ino });
    }
    for (const d of dirs)
      await walk(join4(dir, d), false);
  }
  await walk(root, true);
  return { files, truncated, skipped };
}
function foldKey(v) {
  return v.trim().normalize("NFC").toLowerCase();
}
function matchByKeys(files, mode, source) {
  const pairs = [];
  const unmatched = [];
  const lookup = (k) => source.keys.get(source.caseless ? foldKey(k) : k);
  for (const file of files) {
    const candidates = keysFor(file.rel, mode);
    if (!candidates.length) {
      unmatched.push({ file, reason: "could not derive a key from its place in the folder (it is not in a subfolder)" });
      continue;
    }
    const key = candidates.find((k) => (lookup(k) ?? []).length) ?? null;
    const ids = key ? lookup(key) : null;
    if (!key || !ids) {
      unmatched.push({ file, reason: `no item has ${source.label} ${candidates.map((k) => `"${k}"`).join(" or ")}` });
      continue;
    }
    const distinct = [...new Set(ids)];
    if (distinct.length > 1) {
      unmatched.push({ file, reason: `${distinct.length} items have ${source.label} "${key}" \u2014 name the item in a map instead` });
      continue;
    }
    pairs.push({ file, itemId: distinct[0], key });
  }
  const used = new Set(pairs.map((p) => p.itemId));
  const without = [...source.keys.entries()].filter(([, ids]) => !ids.some((id) => used.has(id))).map(([k]) => k);
  return { pairs, unmatched, itemsWithoutFile: without };
}
async function matchByMap(root, map, resolve2, checkedReal) {
  const pairs = [];
  const unmatched = [];
  const rootReal = checkedReal ?? await realpath2(root);
  for (const [key, value] of Object.entries(map)) {
    const names = Array.isArray(value) ? value : [value];
    const itemId = resolve2(key);
    for (const name of names) {
      const remote = remotePathProblem(String(name)) ?? pathLengthProblem(String(name));
      if (remote) {
        unmatched.push({ file: { path: String(name), rel: String(name), name: basename3(String(name)) }, reason: remote });
        continue;
      }
      const path = String(name).startsWith("/") ? String(name) : join4(root, String(name));
      const rel = relative(root, path).split(sep).join("/");
      const shown = { path, rel, name: basename3(path) };
      if (!itemId) {
        unmatched.push({ file: shown, reason: `no item for "${key}" \u2014 give an item id, or an external_id from a keepr_ingest run in this session` });
        continue;
      }
      if (rel.split("/").some((seg) => seg.startsWith("."))) {
        unmatched.push({ file: shown, reason: "a hidden file, or a path outside the folder \u2014 the map names files in the folder" });
        continue;
      }
      let st;
      let real;
      try {
        st = await stat3(path);
        real = await realpath2(path);
      } catch {
        unmatched.push({ file: shown, reason: "no such file" });
        continue;
      }
      if (!st.isFile()) {
        unmatched.push({ file: shown, reason: "not a file" });
        continue;
      }
      const fenced = fenceProblem(rootReal, real);
      if (fenced) {
        unmatched.push({ file: shown, reason: `${fenced} \u2014 the map names files in the folder` });
        continue;
      }
      const secret = secretPlace(real);
      if (secret) {
        unmatched.push({ file: shown, reason: secret.kind === "store" ? `inside ${secret.label}, where this computer keeps keys, passwords and app settings \u2014 nothing there is attached from here` : "a hidden file \u2014 never attached from here" });
        continue;
      }
      pairs.push({ file: { ...shown, size: st.size, mtimeMs: st.mtimeMs, ctimeMs: st.ctimeMs, ino: st.ino }, itemId, key });
    }
  }
  return { pairs, unmatched, itemsWithoutFile: [] };
}

// dist/src/attachJobs.js
import { createReadStream as createReadStream2 } from "node:fs";
import { stat as stat4, realpath as realpath3 } from "node:fs/promises";
import { randomBytes as randomBytes4 } from "node:crypto";
import { setTimeout as sleep3 } from "node:timers/promises";
var IDS_PER_CALL = 100;
var CONCURRENCY = 3;
var MAX_RATE_WAITS = 20;
var KEEP_JOBS = 20;
var PLAN_WAIT_MS = 5e3;
function idsIn(value) {
  return (Array.isArray(value) ? value : value ? [value] : []).map(String).filter(Boolean);
}
async function planUploads(ctx, pairs, element) {
  const ids = [...new Set(pairs.map((p) => p.itemId))];
  const items = /* @__PURE__ */ new Map();
  for (let i = 0; i < ids.length; i += IDS_PER_CALL) {
    const chunk = ids.slice(i, i + IDS_PER_CALL);
    const res = await ctx.http.request({
      path: "/api/items",
      query: { ids: chunk.join(",") },
      maxWaitMs: PLAN_WAIT_MS
    });
    if (res.status === 429)
      return { error: BUSY };
    if (!res.ok)
      return { error: `keepr would not read the matched items: ${errorMessage(res.body, `HTTP ${res.status}`)}` };
    for (const it of Array.isArray(res.body) ? res.body : []) {
      items.set(String(it._id), {
        // An item's title is someone's text, said in every line below: one line, here (R1).
        id: String(it._id),
        title: it.displayValue ? cleanText(it.displayValue, 200) : String(it._id),
        cardId: String(it.card_id ?? ""),
        collectionId: String(it.collection_id ?? ""),
        elements: it.elements ?? {}
      });
    }
  }
  const unreadable = ids.filter((id) => !items.has(id));
  const collectionRefusal = /* @__PURE__ */ new Map();
  for (const it of items.values()) {
    if (collectionRefusal.has(it.collectionId))
      continue;
    const row = ctx.knownCollections().find((c) => c.id === it.collectionId);
    collectionRefusal.set(it.collectionId, !row ? null : row.allowAttachments === false ? `attachments are turned off in "${row.name}" \u2014 someone who manages it can turn them on in its settings.` : row.archived ? `"${row.name}" is archived and read-only.` : null);
  }
  const targets = /* @__PURE__ */ new Map();
  const schemas = /* @__PURE__ */ new Map();
  for (const it of items.values()) {
    if (!schemas.has(it.collectionId)) {
      const res = await ctx.http.request({ path: `/api/collections/${it.collectionId}/schema`, maxWaitMs: PLAN_WAIT_MS });
      if (res.status === 429)
        return { error: BUSY };
      if (!res.ok)
        return { error: `keepr would not read the elements of the items' collection: ${errorMessage(res.body, `HTTP ${res.status}`)}` };
      schemas.set(it.collectionId, res.body?.cards ?? []);
    }
    const card = schemas.get(it.collectionId).find((c) => c.id === it.cardId);
    const titleEl = (card?.elements ?? []).find((e) => e.isTitle);
    const titleValue = titleEl ? it.elements[titleEl.name] : void 0;
    if (it.title === it.id && (typeof titleValue === "string" || typeof titleValue === "number") && String(titleValue).trim())
      it.title = cleanText(String(titleValue), 200);
    if (element) {
      const def = (card?.elements ?? []).find((e) => e.dataType === "file" && e.name === element);
      if (def)
        targets.set(it.id, def);
    }
  }
  const files = pairs.map((p) => ({ file: p.file, itemId: p.itemId, key: p.key, refused: null, note: null }));
  const byItem = /* @__PURE__ */ new Map();
  for (const f of files) {
    if (!byItem.has(f.itemId))
      byItem.set(f.itemId, []);
    byItem.get(f.itemId).push(f);
  }
  for (const [itemId, group] of byItem) {
    const it = items.get(itemId);
    const def = targets.get(itemId) ?? null;
    const seen = /* @__PURE__ */ new Map();
    for (const f of group) {
      if (!it) {
        f.refused = "this key cannot read the item (a wrong id, a deleted item, or outside the key's allowlist).";
        continue;
      }
      const off = collectionRefusal.get(it.collectionId);
      if (off) {
        f.refused = off;
        continue;
      }
      if (element && !def) {
        f.refused = `the card of ${quoted(it.title)} has no file element "${element}".`;
        continue;
      }
      const why = refusalFor(f.file.name, f.file.size, def, contentTypeFor(f.file.name));
      if (why) {
        f.refused = why;
        continue;
      }
      const lower = storedName(f.file.name).toLowerCase();
      if (seen.has(lower)) {
        f.refused = `${seen.get(lower)} has the same name and is already going to ${quoted(it.title)}.`;
        continue;
      }
      seen.set(lower, f.file.rel);
    }
    if (!def || !it)
      continue;
    const going = group.filter((f) => !f.refused);
    const held = idsIn(it.elements[def.name]).length;
    if (!def.allowMultiple) {
      going.forEach((f, i) => {
        if (i > 0)
          f.refused = `${identifierQuoted(String(def.name))} holds one file, and ${going[0].file.rel} is already going there.`;
        else if (held)
          f.note = `${identifierQuoted(String(def.name))} of ${quoted(it.title)} already holds a file: skipped if it is this file, otherwise left alone (replace it with ${ctx.diskFileTool} on that item).`;
      });
    } else if (held + going.length > MAX_FILES) {
      going.forEach((f) => {
        f.note = `${identifierQuoted(String(def.name))} of ${quoted(it.title)} holds ${held} of its ${MAX_FILES} files: files already there are skipped, and any past the 20th are not sent.`;
      });
    }
  }
  return { files, items, element, targets, unreadable };
}
var BUSY = "keepr is busy for this key right now (its rate limit \u2014 an upload running in the background shares it). Nothing was sent; try the dry run again in a minute.";
var jobs = /* @__PURE__ */ new Map();
function getJob(id) {
  return jobs.get(id) ?? null;
}
function startJob(ctx, plan, folder, opts = {}) {
  const now = opts.now ?? Date.now;
  const files = plan.files.map((f) => ({
    rel: f.file.rel,
    name: f.file.name,
    path: f.file.path,
    size: f.file.size,
    mtimeMs: f.file.mtimeMs,
    ctimeMs: f.file.ctimeMs,
    ino: f.file.ino,
    itemId: f.itemId,
    state: f.refused ? "refused" : "queued",
    reason: f.refused,
    attachmentId: null,
    rateWaits: 0
  }));
  const items = /* @__PURE__ */ new Map();
  for (const f of files) {
    const info = plan.items.get(f.itemId);
    if (!info)
      continue;
    if (!items.has(f.itemId))
      items.set(f.itemId, { info, target: plan.targets.get(f.itemId) ?? null, pending: 0, toBind: [], reserved: 0, present: null, bound: 0, bindError: null });
    if (f.state === "queued")
      items.get(f.itemId).pending++;
  }
  const job = {
    id: `att-${randomBytes4(4).toString("hex")}`,
    startedAt: now(),
    finishedAt: null,
    element: plan.element,
    folder,
    files,
    items,
    rootReal: opts.rootReal ? Promise.resolve(opts.rootReal) : null,
    pausedUntil: 0,
    rateWaitsTotal: 0,
    done: Promise.resolve(),
    error: null
  };
  jobs.set(job.id, job);
  for (const [jid, j] of jobs) {
    if (jobs.size <= KEEP_JOBS)
      break;
    if (j.finishedAt !== null)
      jobs.delete(jid);
  }
  job.done = run(ctx, job, opts).catch((err) => {
    job.error = `the upload stopped unexpectedly: ${err?.message ?? String(err)}`;
    for (const f of job.files)
      if (f.state === "queued" || f.state === "uploading")
        settle(f, "failed", job.error);
  }).finally(() => {
    job.finishedAt = now();
  });
  return job;
}
async function run(ctx, job, opts) {
  const wait = opts.sleep ?? ((ms) => sleep3(ms));
  const now = opts.now ?? Date.now;
  const queue = job.files.filter((f) => f.state === "queued");
  const worker = async () => {
    for (; ; ) {
      const f = queue.shift();
      if (!f)
        return;
      const pause = job.pausedUntil - now();
      if (pause > 0)
        await wait(pause);
      let requeued = false;
      try {
        requeued = await sendOne(ctx, job, f, now);
      } catch (err) {
        settle(f, "failed", `it could not be sent: ${err?.message ?? String(err)}`);
      }
      if (requeued) {
        queue.push(f);
        continue;
      }
      const item = job.items.get(f.itemId);
      if (item && --item.pending === 0)
        await bind(ctx, item);
    }
  };
  await Promise.all(Array.from({ length: Math.max(1, opts.concurrency ?? CONCURRENCY) }, worker));
}
async function presentOn(ctx, item) {
  if (!item.present) {
    item.present = (async () => {
      const out = /* @__PURE__ */ new Map();
      let res;
      try {
        res = await ctx.http.request({ path: `/api/items/${item.info.id}/attachments` });
      } catch {
        return null;
      }
      if (res.status === 429) {
        item.present = null;
        return "busy";
      }
      if (!res.ok || !Array.isArray(res.body))
        return null;
      {
        for (const a of res.body) {
          const name = String(a.originalName ?? "");
          if (!out.has(name))
            out.set(name, []);
          out.get(name).push({ id: String(a._id ?? ""), element: a.element ?? null, size: typeof a.size === "number" ? a.size : null });
        }
      }
      return out;
    })();
  }
  return item.present;
}
async function sendOne(ctx, job, f, now) {
  const item = job.items.get(f.itemId);
  f.state = "uploading";
  const present = await presentOn(ctx, item);
  if (present === "busy")
    return requeueForRate(job, f, now, null);
  if (!present) {
    return settle(f, "failed", `keepr could not say what is already on "${item.info.title}", so it was not sent (it might have gone twice). Run the folder again.`);
  }
  const same2 = (present.get(storedName(f.name)) ?? []).filter((p) => p.size === f.size);
  const target = item.target;
  if (same2.length && !target)
    return settle(f, "skipped", "already on the item (same name and size)");
  if (same2.length && target) {
    const current = idsIn(item.info.elements[target.name]);
    if (same2.some((p) => p.element === target.name && current.includes(p.id)))
      return settle(f, "skipped", `already in ${identifierQuoted(String(target.name))}`);
    const free = same2.find((p) => p.element === null && !item.toBind.includes(p.id));
    const replaces = !target.allowMultiple && current.length > 0;
    if (free && !replaces && (!target.allowMultiple || reserve(item))) {
      item.toBind.push(free.id);
      return settle(f, "skipped", `already on the item (same name and size) \u2014 put into ${identifierQuoted(String(target.name))}`);
    }
  }
  let reserved = false;
  if (target) {
    const current = idsIn(item.info.elements[target.name]);
    if (!target.allowMultiple && current.length) {
      return settle(f, "failed", `${identifierQuoted(String(target.name))} already holds another file \u2014 replace it with ${ctx.diskFileTool} on that item, or attach this one without element.`);
    }
    if (target.allowMultiple) {
      if (!reserve(item))
        return settle(f, "failed", `${identifierQuoted(String(target.name))} is full (${MAX_FILES} files).`);
      reserved = true;
    }
  }
  try {
    return await sendReserved(ctx, job, f, item, now);
  } finally {
    if (reserved && f.state !== "uploaded")
      item.reserved--;
  }
}
function reserve(item) {
  const current = idsIn(item.info.elements[item.target.name]);
  if (current.length + item.reserved >= MAX_FILES)
    return false;
  item.reserved++;
  return true;
}
async function sendReserved(ctx, job, f, item, now) {
  const target = item.target;
  if (!job.rootReal)
    job.rootReal = realpath3(job.folder).catch(() => null);
  const rootReal = await job.rootReal;
  let real = null;
  try {
    real = await realpath3(f.path);
  } catch {
  }
  const fenced = rootReal && real ? fenceProblem(rootReal, real) : null;
  if (fenced)
    return settle(f, "failed", `${fenced} now \u2014 it was not sent.`);
  let st;
  try {
    st = await stat4(f.path);
  } catch (err) {
    return settle(f, "failed", err.code === "ENOENT" ? "it was moved or deleted after the folder was matched." : `it could not be read: ${err.code ?? err.message}.`);
  }
  if (st.size !== f.size || st.mtimeMs !== f.mtimeMs || st.ctimeMs !== f.ctimeMs || st.ino !== f.ino) {
    return settle(f, "failed", `it changed after the folder was matched (${f.size} bytes then, ${st.size} now). Run the folder again to send the new version.`);
  }
  let res;
  try {
    res = await ctx.http.request({
      method: "POST",
      path: `/api/items/${f.itemId}/attachments`,
      stream: { open: () => createReadStream2(f.path), length: f.size, filename: f.name, contentType: contentTypeFor(f.name) }
    });
  } catch (err) {
    if (err instanceof FileChangedError) {
      return settle(f, "failed", err.kind === "unreadable" ? `it could not be read from the disk while it was being sent (${err.message.replace(/^.* could not be read /, "")}).` : "it changed while it was being sent. Run the folder again to send the new version.");
    }
    if (err instanceof KeeprTransportError)
      return settle(f, "failed", `keepr could not be reached: ${err.message}`);
    return settle(f, "failed", `it could not be sent: ${err.message}`);
  }
  ctx.noteWriteAttempt(res);
  if (res.status === 429)
    return requeueForRate(job, f, now, res.rateLimit?.resetSeconds ?? null);
  if (!res.ok) {
    const code = errorCode(res.body);
    const meaning = code ? ctx.contract.meaningOf(code) : null;
    const said = `${code ? `${code}: ` : ""}${errorMessage(res.body, "")}${meaning ? ` (${meaning})` : ""}`.trim();
    const why = res.status === 413 ? "over the attachment storage cap \u2014 the person has to free space first." : res.status === 415 ? "keepr refuses that type of file." : res.status === 403 && ctx.keyScope === "read" ? ctx.readOnlyRefusal() : said || `HTTP ${res.status}`;
    return settle(f, "failed", why);
  }
  f.attachmentId = String(res.body?._id ?? "");
  if (target && f.attachmentId)
    item.toBind.push(f.attachmentId);
  return settle(f, "uploaded", null);
}
function requeueForRate(job, f, now, resetSeconds) {
  f.rateWaits++;
  job.rateWaitsTotal++;
  if (f.rateWaits > MAX_RATE_WAITS)
    return settle(f, "failed", "keepr kept refusing it for the rate limit. Run the folder again later to send what is left.");
  const seconds = Math.max(5, (resetSeconds ?? 30) + 1);
  job.pausedUntil = Math.max(job.pausedUntil, now() + seconds * 1e3);
  f.state = "queued";
  return true;
}
function settle(f, state, reason) {
  f.state = state;
  f.reason = reason;
  return false;
}
async function bind(ctx, item) {
  try {
    await bindOnce(ctx, item);
  } catch (err) {
    item.bindError = `keepr could not be reached to put the files in (${err?.message ?? String(err)}) \u2014 they stayed on the item as other attachments; run the folder again to put them in.`;
  }
}
async function bindOnce(ctx, item) {
  const target = item.target;
  if (!target || !item.toBind.length)
    return;
  const fresh = await ctx.http.request({ path: `/api/items/${item.info.id}` });
  if (!fresh.ok) {
    item.bindError = `keepr would not read the item again before putting the files in: ${errorMessage(fresh.body, `HTTP ${fresh.status}`)}`;
    return;
  }
  const current = idsIn(fresh.body?.elements?.[target.name]);
  if (!target.allowMultiple && current.length) {
    item.bindError = `${identifierQuoted(String(target.name))} was given a file by someone else while this ran; the new file stayed as another attachment.`;
    return;
  }
  const fresh_ = item.toBind.filter((id) => !current.includes(id));
  const room = Math.max(0, MAX_FILES - current.length);
  const going = target.allowMultiple ? fresh_.slice(0, room) : fresh_.slice(0, 1);
  const left = fresh_.length - going.length;
  if (!going.length) {
    item.bindError = `${identifierQuoted(String(target.name))} is full (${MAX_FILES} files) \u2014 someone added files while this ran; the new files stayed as other attachments.`;
    return;
  }
  const value = target.allowMultiple ? [...current, ...going] : going[0];
  const body = { elements: { [target.name]: value }, merge: true };
  if (fresh.body?.updatedAt)
    body.ifUpdatedAt = fresh.body.updatedAt;
  const put = await ctx.http.request({ method: "PUT", path: `/api/items/${item.info.id}`, body });
  ctx.noteWriteAttempt(put);
  if (put.ok) {
    item.bound = going.length;
    if (left)
      item.bindError = `${left} more file${left === 1 ? "" : "s"} did not fit in ${identifierQuoted(String(target.name))} (${MAX_FILES} at most) and stayed as other attachments.`;
    return;
  }
  const code = errorCode(put.body);
  item.bindError = `${code ? `${code}: ` : ""}${errorMessage(put.body, `HTTP ${put.status}`)} \u2014 the files stayed on the item as other attachments.`;
}
function summarise(job) {
  const t2 = { queued: 0, uploading: 0, uploaded: 0, skipped: 0, failed: 0, refused: 0, bound: 0, bindErrors: 0 };
  for (const f of job.files)
    t2[f.state]++;
  for (const it of job.items.values()) {
    t2.bound += it.bound;
    if (it.bindError)
      t2.bindErrors++;
  }
  return t2;
}

// dist/src/tools/attachFolder.js
var HEX242 = /^[0-9a-fA-F]{24}$/;
var LIST_PAGE = 200;
var ELEMENT_ITEMS_MAX = 5e3;
var SHOWN = 60;
var CONFIRM_TTL_MS = 30 * 6e4;
var confirms = /* @__PURE__ */ new Map();
function matchFingerprint(files) {
  const rows = files.map((f) => [f.file.rel, f.file.size, f.file.mtimeMs, f.file.ctimeMs, f.file.ino, f.itemId].join("\0")).sort();
  return createHash2("sha256").update(rows.join("\n")).digest("hex");
}
function signatureOf(args) {
  const pick = { folder: args.folder ?? null, run_id: args.run_id ?? null, map: args.map ?? null, collection: args.collection ?? null, match_element: args.match_element ?? null, match: args.match ?? null, element: args.element ?? null };
  return createHash2("sha256").update(JSON.stringify(pick)).digest("hex");
}
var attachFolderTool = {
  name: "keepr_attach_folder",
  title: "Attach a folder from this computer",
  description: "Attaches a whole folder of files (photos, receipts, scans, videos, up to 100 MB each) from this computer's disk to the keepr items they belong to; nothing passes through the conversation. Files match items by subfolder or filename, against this session's keepr_ingest runs (the default), a `map`, or `collection` + `match_element`. It takes two calls: dry_run: true shows the match and returns a `confirm` token; the same arguments with dry_run: false and that token start the upload, followed with keepr_attach_status. A re-run skips files already there.",
  writes: true,
  // Destructive ⚑ (the coordinator's call, KPR-256): by the narrow MCP sense
  // it only adds — a single file element that holds a file is left alone —
  // but it copies files off the person's computer, the riskiest thing any
  // keepr tool does, and the dry-run confirm is a step the model takes, not
  // a click by the person (the security review's F-246-1; the folder-root
  // fence is KPR-268). Claude always asks before a destructive tool runs, so
  // every bulk upload gets the person's click. Re-running skips what arrived.
  annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: false },
  inputSchema: {
    folder: z.string().min(1).describe("The folder, as a path this server can read: on Claude Code, the person's own disk; in Cowork, a folder the person selected for the session, under /sessions/<name>/mnt/. Files this server cannot read go up through keepr_request_upload's link instead."),
    dry_run: z.boolean().describe("REQUIRED. true shows the match, uploads nothing and returns a `confirm` token. false (with that token) starts the upload and returns a job id."),
    confirm: z.string().optional().describe("With dry_run: false \u2014 the token the dry run of these same arguments returned. Single use, 30 minutes."),
    run_id: z.string().optional().describe("Match against the external_ids of this keepr_ingest run. Default: every committed run in this session."),
    map: z.record(z.string(), z.union([z.string(), z.array(z.string())])).optional().describe('Explicit: {"<external_id or item_id>": ["file.jpg", "sub/other.jpg"]}, names relative to the folder. Beats filename matching.'),
    collection: z.string().optional().describe("With match_element: the collection whose items the files belong to (name or id)."),
    match_element: z.string().optional().describe(`Match the filename (or subfolder) to this element's value, e.g. "receiptNo", compared without case. For items not written in this session.`),
    match: z.enum(["auto", "folder", "stem", "exact"]).optional().describe("How a file names its item. auto (default): its subfolder (photos/molly-blake/front.jpg), else its filename, else its filename without a trailing counter (leah-park-2.jpg, R-1042.pdf). folder | stem | exact force one."),
    element: z.string().optional().describe("Put the files INTO this file element of each item (keepr_schema lists them) instead of the item's other attachments. A single file element is never replaced from here.")
  },
  handler: async (args, ctx) => {
    if (typeof args.dry_run !== "boolean")
      return fail("dry_run is required: true to see the match first, then false to upload.");
    const given = String(args.folder ?? "").trim();
    const remote = remotePathProblem(given) ?? pathLengthProblem(given);
    if (remote)
      return fail(remote, { ok: false, code: "folder_refused" });
    const secret = secretPlace(given);
    if (secret)
      return fail(secretRefusal(given, "folder", secret), { ok: false, code: "folder_refused" });
    const { path: resolved, mappedFrom } = await resolveAgentPath(given);
    let root;
    try {
      const st = await stat5(resolved);
      if (!st.isDirectory())
        return fail(`${given} is a file, not a folder. Give its folder \u2014 or use ${ctx.diskFileTool} for a single file.`);
      root = await realpath4(resolved);
      const leadsTo = secretPlace(root);
      if (leadsTo)
        return fail(secretRefusal(given, "folder", leadsTo, root), { ok: false, code: "folder_refused" });
    } catch (err) {
      return fail(pathProblem(given, err.code, ctx.filesOnly), { ok: false, code: "folder_unreadable" });
    }
    const mode = MATCH_MODES.includes(args.match) ? args.match : "auto";
    const element = typeof args.element === "string" && args.element.trim() ? args.element.trim() : null;
    const sig = signatureOf({ ...args, folder: given });
    const token = typeof args.confirm === "string" ? args.confirm : "";
    if (args.dry_run === false) {
      const held = confirms.get(token);
      if (!held || held.sig !== sig || held.expires < Date.now()) {
        return fail(token ? "That confirm token is not for these arguments, was used already, or has expired (30 minutes). Run the dry run again and show the person the match." : "Run keepr_attach_folder with dry_run: true first, show the person the match, then call again with the same arguments, dry_run: false and the `confirm` it returned.", { ok: false, code: "confirm_required" });
      }
    }
    let matched;
    let truncated = false;
    let skipped = [];
    let sourceNote = null;
    let sourceLabel;
    if (args.map && typeof args.map === "object") {
      const runId = typeof args.run_id === "string" ? args.run_id : null;
      const byExt = (k) => [k, k.normalize("NFC"), k.normalize("NFD")].map((v) => ctx.ledger.resolveExternalId(v, runId)?.itemId ?? null).find(Boolean) ?? null;
      matched = await matchByMap(root, args.map, (k) => HEX242.test(k) ? k : byExt(k), root);
      sourceLabel = "the map";
    } else {
      let walk;
      try {
        walk = await listFiles(root, void 0, root);
      } catch (err) {
        return fail(pathProblem(given, err.code, ctx.filesOnly), { ok: false, code: "folder_unreadable" });
      }
      truncated = walk.truncated;
      skipped = walk.skipped;
      if (!walk.files.length)
        return fail(`${given} holds no files (hidden files are left out).${skipped.length ? `
${listSkipped(skipped)}` : ""}`);
      const source = await keySource(ctx, args);
      if ("error" in source)
        return fail(source.error);
      matched = matchByKeys(walk.files, mode, source);
      sourceLabel = source.label;
      sourceNote = source.note ?? null;
    }
    if (!matched.pairs.length) {
      return fail(`No file in ${given} matched an item (${sourceLabel}).
${listUnmatched(matched.unmatched)}

Try another match mode, a \`map\` naming the files per item, or match_element with the element the filenames carry.`);
    }
    const plan = await planUploads(ctx, matched.pairs, element);
    if ("error" in plan)
      return fail(plan.error);
    const going = plan.files.filter((f) => !f.refused);
    const refused = plan.files.filter((f) => f.refused);
    const bytes = going.reduce((n, f) => n + f.file.size, 0);
    const title = (id) => plan.items.get(id)?.title ?? id;
    const header = [
      `${going.length} file${going.length === 1 ? "" : "s"} (${mb(bytes)}) \u2192 ${new Set(going.map((f) => f.itemId)).size} item${new Set(going.map((f) => f.itemId)).size === 1 ? "" : "s"}` + (element ? ` \xB7 into "${element}"` : "") + (refused.length ? ` \xB7 ${refused.length} refused` : "") + (matched.unmatched.length ? ` \xB7 ${matched.unmatched.length} unmatched` : "") + (matched.itemsWithoutFile.length ? ` \xB7 ${matched.itemsWithoutFile.length} item${matched.itemsWithoutFile.length === 1 ? "" : "s"} without a file` : "")
    ];
    if (mappedFrom)
      header.push(`(Read from ${resolved} \u2014 the computer's copy of ${mappedFrom}.)`);
    if (truncated)
      header.push("Only the first 20,000 files were read; pick a smaller folder for the rest.");
    if (sourceNote)
      header.push(sourceNote);
    if (args.dry_run) {
      const lines = [...header, ""];
      lines.push(`MATCHED (${going.length}):`);
      for (const f of going.slice(0, SHOWN))
        lines.push(`  ${f.file.rel} \u2192 ${title(f.itemId)}`);
      if (going.length > SHOWN)
        lines.push(`  \u2026 and ${going.length - SHOWN} more`);
      if (refused.length) {
        lines.push("", `REFUSED BEFORE UPLOAD (${refused.length}):`);
        for (const f of refused.slice(0, SHOWN))
          lines.push(`  ${f.file.rel} \u2192 ${title(f.itemId)}: ${f.refused}`);
        if (refused.length > SHOWN)
          lines.push(`  \u2026 and ${refused.length - SHOWN} more`);
      }
      const noted = going.filter((f) => f.note);
      if (noted.length) {
        lines.push("", `NOTE (${noted.length}):`);
        for (const f of noted.slice(0, SHOWN))
          lines.push(`  ${f.file.rel} \u2192 ${title(f.itemId)}: ${f.note}`);
      }
      if (matched.unmatched.length)
        lines.push("", `UNMATCHED (${matched.unmatched.length}):`, listUnmatched(matched.unmatched));
      if (skipped.length)
        lines.push("", `LEFT OUT (${skipped.length}):`, listSkipped(skipped));
      if (matched.itemsWithoutFile.length) {
        lines.push("", `ITEMS WITHOUT A FILE (${matched.itemsWithoutFile.length}), by ${sourceLabel}: ${matched.itemsWithoutFile.slice(0, 25).map((k) => identifierText(String(k))).join(", ")}${matched.itemsWithoutFile.length > 25 ? ", \u2026" : ""}`);
      }
      if (plan.unreadable.length)
        lines.push("", `${plan.unreadable.length} matched item id${plan.unreadable.length === 1 ? " is" : "s are"} not readable by this key: ${plan.unreadable.slice(0, 10).join(", ")}.`);
      const issued = randomBytes5(12).toString("hex");
      confirms.set(issued, { sig, match: matchFingerprint(going), expires: Date.now() + CONFIRM_TTL_MS });
      for (const [t2, c] of confirms)
        if (c.expires < Date.now())
          confirms.delete(t2);
      lines.push("", "DRY RUN \u2014 nothing was uploaded. Files already on their items (same name and size) are skipped when it runs.", `Show the person this match. To upload, call keepr_attach_folder again with the same arguments, dry_run: false and confirm: "${issued}".`);
      return ok(lines.join("\n"), {
        ok: true,
        dryRun: true,
        confirm: issued,
        leftOut: skipped.slice(0, 500),
        matched: going.slice(0, 500).map((f) => ({ file: f.file.rel, itemId: f.itemId, item: title(f.itemId), bytes: f.file.size })),
        refused: refused.slice(0, 500).map((f) => ({ file: f.file.rel, itemId: f.itemId, reason: f.refused })),
        unmatched: matched.unmatched.slice(0, 500).map((u) => ({ file: u.file.rel, reason: u.reason })),
        itemsWithoutFile: matched.itemsWithoutFile.slice(0, 500),
        counts: { matched: going.length, refused: refused.length, unmatched: matched.unmatched.length, itemsWithoutFile: matched.itemsWithoutFile.length, bytes }
      });
    }
    if (!going.length)
      return fail(`${header[0]}

Nothing to upload: every matched file is refused.
${refused.slice(0, 20).map((f) => `  ${f.file.rel}: ${f.refused}`).join("\n")}`);
    if (confirms.get(token)?.match !== matchFingerprint(going)) {
      confirms.delete(token);
      return fail(`The folder or the match changed since the dry run (${going.length} file${going.length === 1 ? "" : "s"} would go now), so nothing was sent. Run the dry run again and show the person the new match.`, { ok: false, code: "match_changed" });
    }
    confirms.delete(token);
    const job = startJob(ctx, plan, root, { rootReal: root });
    return ok([
      ...header,
      "",
      `Uploading in the background (job ${job.id}), ${CONCURRENCY} at a time, streamed from disk.`,
      `Call keepr_attach_status with job_id ${job.id} to see progress \u2014 every minute or so, not in a tight loop.`,
      "The job runs inside this server: if the app restarts, run the same folder again and it sends only what is missing."
    ].join("\n"), { ok: true, dryRun: false, job_id: job.id, counts: { files: going.length, refused: refused.length, unmatched: matched.unmatched.length, bytes } });
  }
};
async function keySource(ctx, args) {
  const matchElement = typeof args.match_element === "string" ? args.match_element.trim() : "";
  if (matchElement) {
    const resolved = ctx.resolveCollection(String(args.collection ?? ""));
    if (!resolved.ok)
      return { error: args.collection ? resolved.message : "match_element needs `collection`: the collection whose items the files belong to." };
    const keys2 = /* @__PURE__ */ new Map();
    let seen = 0;
    let total = null;
    for (let skip = 0; skip < ELEMENT_ITEMS_MAX; skip += LIST_PAGE) {
      const res = await ctx.http.request({
        path: "/api/items",
        query: { collection_id: resolved.row.id, limit: LIST_PAGE, skip },
        maxWaitMs: PLAN_WAIT_MS
      });
      if (res.status === 429)
        return { error: "keepr is busy for this key right now (its rate limit \u2014 an upload running in the background shares it). Nothing was sent; try the dry run again in a minute." };
      total = res.totalCount ?? total;
      if (!res.ok)
        return { error: `keepr would not list the items of ${quoted(resolved.row.name)} (HTTP ${res.status}).` };
      const page = Array.isArray(res.body) ? res.body : [];
      for (const it of page) {
        const v = it.elements?.[matchElement];
        if (typeof v !== "string" && typeof v !== "number")
          continue;
        const k = foldKey(String(v));
        if (!k)
          continue;
        if (!keys2.has(k))
          keys2.set(k, []);
        keys2.get(k).push(String(it._id));
      }
      seen += page.length;
      if (page.length < LIST_PAGE || res.totalCount !== null && seen >= res.totalCount)
        break;
    }
    if (!keys2.size)
      return { error: `No item in ${quoted(resolved.row.name)} has a value in "${matchElement}". ${ctx.filesOnly ? "Check the element's name on the card." : "Check the element's name with keepr_schema."}` };
    const cut = total !== null && total > seen;
    return {
      kind: "keys",
      keys: keys2,
      caseless: true,
      label: `"${matchElement}"`,
      ...cut ? { note: `Only the first ${seen} of ${total} items of ${quoted(resolved.row.name)} were read for "${matchElement}"; a file for a later item reads as unmatched \u2014 use a map, or this session's import, for those.` } : {}
    };
  }
  const runId = typeof args.run_id === "string" && args.run_id ? args.run_id : null;
  const runs = runId ? [ctx.ledger.byRunId(runId)].filter((r) => r !== null) : ctx.ledger.all();
  if (!runs.length) {
    return {
      error: runId ? `No committed keepr_ingest run "${runId}" in this session (${ctx.ledger.size ? `known: ${ctx.ledger.knownRunIds().join(", ")}` : "none is remembered"}).` : ctx.filesOnly ? "Nothing to match the files against: this server does not see imports made through the keepr connector. Pass `collection` + `match_element` (an element whose value the filenames carry), or `map` (item ids per file)." : "Nothing to match the files against: no keepr_ingest run in this session. Pass `map` (item ids per file), or `collection` + `match_element`."
    };
  }
  const keys = /* @__PURE__ */ new Map();
  for (const run2 of runs) {
    for (const [raw, itemId] of Object.entries(run2.itemsByExternalId)) {
      const ext = raw.normalize("NFC");
      if (!keys.has(ext))
        keys.set(ext, []);
      if (!keys.get(ext).includes(itemId))
        keys.get(ext).push(itemId);
    }
  }
  return { kind: "keys", keys, caseless: false, label: "external_id" };
}
function listSkipped(skipped) {
  const lines = skipped.slice(0, SHOWN).map((s) => `  ${s.rel}: ${s.reason}`);
  if (skipped.length > SHOWN)
    lines.push(`  \u2026 and ${skipped.length - SHOWN} more`);
  return lines.join("\n");
}
function listUnmatched(unmatched) {
  const lines = unmatched.slice(0, SHOWN).map((u) => `  ${u.file.rel}: ${u.reason}`);
  if (unmatched.length > SHOWN)
    lines.push(`  \u2026 and ${unmatched.length - SHOWN} more`);
  return lines.join("\n");
}
var attachStatusTool = {
  name: "keepr_attach_status",
  title: "Check folder upload progress",
  description: "Progress of a keepr_attach_folder upload: how many files are uploaded, skipped, failed and still waiting, and why each failure failed. The job runs in the background, and its counts change until it finishes.",
  annotations: READ_ONLY,
  inputSchema: {
    job_id: z.string().describe("The job id keepr_attach_folder returned.")
  },
  handler: async (args) => {
    const job = getJob(String(args.job_id ?? ""));
    if (!job) {
      return fail("No upload job with that id in this server. Jobs live only as long as the server process: if the app restarted, run keepr_attach_folder on the same folder again \u2014 it skips what already arrived.");
    }
    const t2 = summarise(job);
    const running = job.finishedAt === null;
    const total = job.files.length;
    const done = t2.uploaded + t2.skipped + t2.failed + t2.refused;
    const lines = [
      running ? `RUNNING \u2014 ${done} of ${total} files done: ${t2.uploaded} uploaded, ${t2.skipped} skipped, ${t2.failed} failed${t2.refused ? `, ${t2.refused} refused` : ""}; ${t2.queued + t2.uploading} to go.` : `${t2.failed || t2.bindErrors ? "FINISHED WITH PROBLEMS" : "FINISHED"} \u2014 ${t2.uploaded} uploaded, ${t2.skipped} skipped (already there), ${t2.failed} failed${t2.refused ? `, ${t2.refused} refused` : ""}.`
    ];
    if (job.error)
      lines.push(`STOPPED: ${job.error}. Running the same folder again sends only what is not there yet.`);
    if (job.element)
      lines.push(`Into "${job.element}": ${t2.bound} file${t2.bound === 1 ? "" : "s"} put in${t2.bindErrors ? `, ${t2.bindErrors} item${t2.bindErrors === 1 ? "" : "s"} refused the bind` : ""}.`);
    if (running && job.pausedUntil > Date.now())
      lines.push(`Paused for keepr's rate limit \u2014 resuming in about ${Math.ceil((job.pausedUntil - Date.now()) / 1e3)} s. Nothing failed for it.`);
    const failed = job.files.filter((f) => f.state === "failed");
    if (failed.length) {
      lines.push("", `FAILED (${failed.length}):`);
      for (const f of failed.slice(0, SHOWN))
        lines.push(`  ${f.rel} \u2014 ${f.reason}`);
      if (failed.length > SHOWN)
        lines.push(`  \u2026 and ${failed.length - SHOWN} more`);
    }
    const binds = [...job.items.values()].filter((i) => i.bindError);
    if (binds.length) {
      lines.push("", `NOT PUT INTO "${job.element}" (${binds.length}):`);
      for (const i of binds.slice(0, 20))
        lines.push(`  ${i.info.title} \u2014 ${i.bindError}`);
    }
    if (!running && failed.length)
      lines.push("", "Running the same folder again sends only what is not there yet.");
    return ok(lines.join("\n"), {
      ok: true,
      job_id: job.id,
      running,
      totals: t2,
      failed: failed.slice(0, 500).map((f) => ({ file: f.rel, itemId: f.itemId, reason: f.reason })),
      bindErrors: binds.map((i) => ({ itemId: i.info.id, item: i.info.title, reason: i.bindError }))
    });
  }
};
var { run_id: _runId, ...folderArgsWithoutRun } = attachFolderTool.inputSchema;
var attachFolderFilesOnlyTool = {
  ...attachFolderTool,
  title: "Attach a folder from this computer",
  // What it does and when it fits — no lines aimed at the model's behaviour,
  // no tool this server does not list (the Claude directory's review, KPR-251).
  description: "Attaches a whole folder of files (photos, receipts, scans, videos, up to 100 MB each) from this computer's disk to the keepr items they belong to; nothing passes through the conversation. keepr_attach_local_file fits one file or two. Files match items by subfolder or filename, against `collection` + `match_element` (an element whose value the filenames carry, such as a receipt number) or a `map` of item ids. Two calls: dry_run: true shows the match and returns a `confirm` token; the same arguments with dry_run: false and that token start the upload, followed with keepr_attach_status.",
  // Destructive ⚑ (the coordinator's call, KPR-256): by the narrow MCP sense
  // it only adds — a single file element that holds a file is left alone —
  // but it copies files off the person's computer, the riskiest thing any
  // keepr tool does, and the dry-run confirm is a step the model takes, not
  // a click by the person (the security review's F-246-1; the folder-root
  // fence is KPR-268). Claude always asks before a destructive tool runs, so
  // every bulk upload gets the person's click. Re-running skips what arrived.
  annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: false },
  inputSchema: {
    ...folderArgsWithoutRun,
    folder: z.string().min(1).describe("The folder, as a path this server can read: on Claude Code, the person's own disk; in Cowork, a folder the person selected for the session, under /sessions/<name>/mnt/. Files this server cannot read go up through the keepr connector's upload link instead."),
    dry_run: z.boolean().describe("REQUIRED. true shows the match, uploads nothing and returns a `confirm` token. false (with that token) starts the upload and returns a job id. Running a folder again skips files already on their items (same name and size)."),
    map: z.record(z.string(), z.union([z.string(), z.array(z.string())])).optional().describe('Explicit: {"<item_id>": ["file.jpg", "sub/other.jpg"]}, names relative to the folder. Beats filename matching.'),
    match_element: z.string().optional().describe(`Match the filename (or subfolder) to this element's value, e.g. "receiptNo", compared without case.`),
    element: z.string().optional().describe("Put the files INTO this file element of each item, by its name, instead of the item's other attachments. A single file element that already holds a file is left alone.")
  }
};

// dist/src/tools/connect.js
var CONNECT_WAIT_MS = 45e3;
function scopeWords(scopes) {
  const can = [];
  if (scopes.includes("read"))
    can.push("read");
  if (scopes.includes("write"))
    can.push("add and change items");
  if (scopes.includes("cards"))
    can.push("change cards");
  if (scopes.includes("delete"))
    can.push("delete records");
  if (!can.length)
    return "do nothing yet (no scopes were granted)";
  return can.length === 1 ? can[0] : `${can.slice(0, -1).join(", ")} and ${can.at(-1)}`;
}
var connectTool = {
  name: "keepr_connect",
  title: "Connect to keepr",
  description: "Connects this keepr server to the person's keepr account: it opens keepr in their browser, where they sign in if needed and click Allow; nothing to copy or paste. It is what the other keepr tools ask for when keepr is not connected. Until the person has clicked Allow it answers that it is waiting, with a link for when no browser tab opened; called again, it finishes the connection without opening a second tab.",
  // Writes this computer's connection and makes a grant in keepr; changes
  // nothing that was there. Connected already, it says so and does nothing.
  annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  inputSchema: {},
  unguarded: true,
  handler: async (_args, ctx) => {
    const connection = ctx.connection;
    if (!connection)
      return fail("This keepr server cannot connect itself: it is reached through a connector that is connected already.");
    if (ctx.config.apiKey) {
      return ok(`keepr is already connected with an API key (from ${keyWords.keyFrom(ctx.config.keySource)})${ctx.startup.accountEmail ? `, as ${ctx.startup.accountEmail}` : ""}. keepr_connect is for connecting without a key, and a key always wins over it. Nothing to do.`, { state: "key", account: ctx.startup.accountEmail });
    }
    if (connection.connected && ctx.startup.keyValid) {
      return ok(`Already connected to keepr as ${ctx.startup.accountEmail ?? "an account"}: this connection can ${scopeWords(ctx.knownScopes())}. To connect as someone else, call keepr_disconnect first.`, { state: "connected", account: ctx.startup.accountEmail, scopes: ctx.knownScopes() });
    }
    for (let attempt = 0; attempt < 2; attempt++) {
      const outcome = await connection.connect(CONNECT_WAIT_MS);
      if (outcome.state === "failed")
        return fail(cleanText(outcome.message, 600), { state: "failed" });
      if (outcome.state === "waiting") {
        return ok("Waiting for the person to approve the connection in their browser. " + (outcome.reused ? "The keepr page is still open from before. " : outcome.browserOpened ? "keepr has opened in their browser. " : "Their browser could not be opened from here. ") + `If they do not see it, give them this link: ${outcome.url}

Once they have clicked Allow, call keepr_connect again to finish. The link works for 5 minutes.`, { state: "waiting", url: outcome.url });
      }
      await ctx.restart();
      if (ctx.startup.keyValid) {
        const scopes = ctx.knownScopes();
        const n = ctx.knownCollections().length;
        return ok(`Connected to keepr as ${ctx.startup.accountEmail ?? "the person's account"}. This connection can ${scopeWords(scopes)}, in ${n} collection${n === 1 ? "" : "s"}. It is listed under Connected assistants on their keepr profile, where they can rename or disconnect it. ` + (ctx.filesOnly ? "keepr's local file tools work now. The rest of keepr's tools come from the keepr connector, which the person connects in their assistant." : "Every keepr tool works now."), { state: "connected", account: ctx.startup.accountEmail, scopes });
      }
      if (connection.connected) {
        return fail(`keepr is connected, but could not be reached to confirm it: ${ctx.startup.problem ?? "no answer"} Try again in a moment.`, { state: "unconfirmed" });
      }
    }
    return fail(`The connection was approved, but keepr then refused it: ${ctx.startup.problem ?? "no reason given"}`, { state: "failed" });
  }
};
var disconnectTool = {
  name: "keepr_disconnect",
  title: "Disconnect from keepr",
  description: "Disconnects this keepr server from the account keepr_connect connected it to: the connection is revoked in keepr and forgotten on this computer. It is for when the person asks to disconnect, sign out or switch accounts.",
  // Revokes a grant. Disconnected already, it says so and does nothing.
  annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: false },
  inputSchema: {},
  unguarded: true,
  handler: async (_args, ctx) => {
    const connection = ctx.connection;
    connection?.refreshFromDisk();
    if (!connection || !connection.connected && !connection.waiting) {
      return ok(ctx.config.apiKey ? keyWords.nothingToDisconnect : `${ctx.filesOnly ? "keepr's local file tools are" : "This server is"} not connected to keepr. Nothing to disconnect.`, { state: "not-connected" });
    }
    const account = ctx.config.apiKey ? null : ctx.startup.accountEmail;
    const { revokedOnServer, busy } = await connection.disconnect();
    if (busy)
      return fail("keepr is renewing this connection in another window right now. Try again in a moment.", { state: "busy" });
    await ctx.restart();
    return ok(`Disconnected${account ? ` from ${account}` : ""}${ctx.config.apiKey ? " the browser connection; this plugin keeps using its API key" : ""}. ` + (revokedOnServer ? "keepr no longer accepts this connection, and it is gone from Connected assistants." : "It is forgotten on this computer; keepr could not be reached to revoke it, so the person can remove it under Connected assistants on their profile."), { state: "disconnected", revokedOnServer });
  }
};
var connectFilesOnlyTool = {
  ...connectTool,
  description: "Connects keepr's local file tools on this computer \u2014 keepr_attach_local_file, keepr_attach_folder and keepr_attach_status \u2014 to the person's keepr account: it opens keepr in their browser, where they sign in if needed and click Allow; nothing to copy or paste. It signs in these tools only, not the keepr connector, whose tools the person connects in their assistant. Until the person has clicked Allow it answers that it is waiting, with a link for when no browser tab opened; called again, it finishes without opening a second tab."
};
var disconnectFilesOnlyTool = {
  ...disconnectTool,
  description: "Disconnects keepr's local file tools on this computer from the account keepr_connect connected them to: the connection is revoked in keepr and forgotten on this computer. The keepr connector is not affected. It is for when the person asks to disconnect, sign out or switch accounts."
};

// dist/src/tools/filesOnly.js
var FILES_ONLY_TOOLS = [
  attachLocalFileTool,
  attachFolderFilesOnlyTool,
  // The status tool as every mode lists it (its own title and annotations
  // since KPR-256); keepr_connect and keepr_disconnect with descriptions
  // that say they sign in these tools alone, not the connector.
  attachStatusTool,
  connectFilesOnlyTool,
  disconnectFilesOnlyTool
];

// dist/src/stdioLite.js
var PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"];
function serveStdio(ctx, tools, info, input, output) {
  const send = (msg) => {
    output.write(`${JSON.stringify(msg)}
`);
  };
  const reply = (id, result) => send({ jsonrpc: "2.0", id, result });
  const error = (id, code, message) => send({ jsonrpc: "2.0", id: id ?? null, error: { code, message } });
  const textError = (text) => ({ content: [{ type: "text", text }], isError: true });
  async function handle(msg) {
    const isRequest = msg.id !== void 0;
    if (!isRequest)
      return;
    switch (msg.method) {
      case "initialize": {
        const asked = String(msg.params?.protocolVersion ?? "");
        reply(msg.id, {
          protocolVersion: PROTOCOL_VERSIONS.includes(asked) ? asked : PROTOCOL_VERSIONS[0],
          capabilities: { tools: { listChanged: false } },
          serverInfo: info,
          instructions: ctx.instructions()
        });
        return;
      }
      case "ping":
        reply(msg.id, {});
        return;
      case "tools/list":
        reply(msg.id, {
          tools: tools.map((t2) => ({
            name: t2.name,
            ...t2.title ? { title: t2.title } : {},
            description: describeFor(t2, ctx),
            inputSchema: objectJson(t2.inputSchema),
            ...t2.annotations ? { annotations: t2.annotations } : {},
            // What the SDK server says of every tool (the tasks extension): no task mode.
            execution: { taskSupport: "forbidden" }
          }))
        });
        return;
      case "tools/call": {
        if (!isPlainObject(msg.params)) {
          error(msg.id, -32602, "Invalid params: tools/call takes an object with name and arguments.");
          return;
        }
        const args = msg.params.arguments;
        if (args !== void 0 && !isPlainObject(args)) {
          error(msg.id, -32602, "Invalid params: arguments must be an object.");
          return;
        }
        const name = String(msg.params.name ?? "");
        const tool = tools.find((t2) => t2.name === name);
        if (!tool) {
          reply(msg.id, textError(`MCP error -32602: Tool ${name} not found`));
          return;
        }
        if (args === void 0) {
          reply(msg.id, textError(`MCP error -32602: Input validation error: Invalid arguments for tool ${name}: Invalid input: expected object, received undefined`));
          return;
        }
        const parsed = parseArgs(tool.inputSchema, args);
        if (!parsed.ok) {
          reply(msg.id, textError(`MCP error -32602: Input validation error: Invalid arguments for tool ${name}: ${parsed.message}`));
          return;
        }
        reply(msg.id, await runTool(tool, ctx, parsed.value));
        return;
      }
      default:
        error(msg.id, -32601, `Method not found: ${msg.method}`);
    }
  }
  let buffer = "";
  input.setEncoding("utf8");
  input.on("data", (chunk) => {
    buffer += chunk;
    let nl;
    while ((nl = buffer.indexOf("\n")) !== -1) {
      const line = buffer.slice(0, nl).replace(/\r$/, "").trim();
      buffer = buffer.slice(nl + 1);
      if (!line)
        continue;
      let parsed;
      try {
        parsed = JSON.parse(line);
      } catch {
        error(null, -32700, "Parse error");
        continue;
      }
      const why = notAMessage(parsed);
      if (why) {
        process.stderr.write(`keepr-mcp: ignored a message on stdin: ${why}
`);
        continue;
      }
      const msg = parsed;
      const id = msg.id;
      handle(msg).catch((err) => {
        if (id !== void 0)
          error(id, -32603, `keepr-mcp failed internally: ${err?.message ?? String(err)}`);
      });
    }
  });
}
function isPlainObject(v) {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}
function notAMessage(v) {
  if (!isPlainObject(v))
    return `not a JSON object (${v === null ? "null" : Array.isArray(v) ? "an array" : typeof v})`;
  if (v.jsonrpc !== "2.0")
    return 'jsonrpc is not "2.0"';
  if (typeof v.method !== "string")
    return "no method (a response, or nothing)";
  if ("id" in v && !(typeof v.id === "string" || typeof v.id === "number" && Number.isInteger(v.id)))
    return "its id is not a string or an integer";
  if ("params" in v && v.params !== void 0 && !isPlainObject(v.params))
    return "its params are not an object";
  return null;
}

// dist/src/files-index.js
async function main() {
  const ctx = new KeeprContext({ ...process.env, KEEPR_TOOLS: "files" });
  await ctx.start();
  process.stderr.write(`keepr-mcp files ${ctx.config.baseUrl} [key: ${ctx.config.keySource ?? "none"}] [tools: files] \u2014 ${ctx.instructions()}
`);
  serveStdio(ctx, FILES_ONLY_TOOLS, {
    name: SERVER_NAME,
    title: "keepr file tools",
    version: SERVER_VERSION,
    websiteUrl: WEBSITE_URL,
    icons: brandIcons()
  }, process.stdin, process.stdout);
  const closeConnection = () => ctx.connection?.close();
  process.on("exit", closeConnection);
  process.stdin.on("end", () => {
    closeConnection();
    process.exit(0);
  });
}
main().catch((err) => {
  process.stderr.write(`keepr-mcp failed to start: ${err?.stack ?? String(err)}
`);
  process.exit(1);
});
