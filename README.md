# keepr-agent

Connect an AI assistant to the records you keep in [keepr](https://keepr.cloud).

This repository is the **distribution** of two things that are built and tested
in [`zbiewend/keepr-api`](https://github.com/zbiewend/keepr-api): the `keepr`
skill (the judgement — how to read, add and change records without guessing)
and `keepr-mcp` (the transport — nine tools over the keepr API). Nothing here
is edited by hand; `skills/publish.sh` in keepr-api regenerates it.

You need a keepr account and an API key: in keepr, **My Profile → API keys →
Create key**. A key is shown once. Read-only keys read; tick *Can write* to add
records and *Can change cards* to change a collection's schema.

The guided version of everything below is at
**[keepr.cloud/account/connect](https://keepr.cloud/account/connect)**, and the
guide is at [keepr.cloud/docs/guides/assistants](https://keepr.cloud/docs/guides/assistants).

## Three ways in

### 1. Claude desktop and Cowork — the extension

Download `keepr-<version>.mcpb` from the
[latest release](https://github.com/zbiewend/keepr-agent/releases/latest) and
open it. Claude desktop asks for the API key in its own settings field and
keeps it in the OS keychain; it also supplies the Node runtime, so nothing
else needs to be installed. Then ask Claude: *what keepr collections can you
reach?*

### 2. Claude Code — the plugin

```
/plugin marketplace add zbiewend/keepr-agent
/plugin install keepr@keepr-agent
```

Then, **in your own terminal**, store the key once. `keepr.py` is in the
installed plugin (ask Claude Code where its `keepr` plugin lives), or fetch a
copy:

```
curl -fsSLo keepr.py https://raw.githubusercontent.com/zbiewend/keepr-agent/main/plugins/keepr/skills/keepr/scripts/keepr.py
python3 keepr.py login
```

The key is typed with no echo and stored in `~/.config/keepr/credentials`
(mode 600). The MCP server the plugin starts reads that file, so there is no
environment to configure. `keepr.py logout` forgets it. The plugin needs a
`node` on your PATH, which Claude Code itself already needs.

### 3. Any other assistant — the skill on its own

Paste this to an assistant that can run a script:

> Install the keepr skill from https://api.keepr.cloud/api/docs/skill

`GET /api/docs/skill` returns every file of the skill inline with instructions
for writing them down. The skill zip is also on each release. The assistant
runs `keepr.py`, which makes ordinary HTTPS calls to `api.keepr.cloud`; you
run `keepr.py login` yourself, or set `KEEPR_API_KEY`.

## What is in here

```
.claude-plugin/marketplace.json    the marketplace Claude Code adds
plugins/keepr/                     the plugin
  .claude-plugin/plugin.json
  .mcp.json                        starts server/keepr-mcp.js with node
  skills/keepr/                    the skill, as published
  server/keepr-mcp.js              keepr-mcp, one file, SDK inlined
mcpb/manifest.json                 the extension manifest, for reference
CHANGELOG.md
```

The `.mcpb` itself and the skill zip are release assets, not files in this
repository.

## Versions

The plugin's version is the **skill's** version — the skill is what the
assistant reads, and it is the contract with the people running it. The
server's own version is `metadata.server` in `plugin.json` and the `version`
in `mcpb/manifest.json`. Both are listed per release in `CHANGELOG.md`.

## What it will not do

`delete_item`, `delete_card` and `archive_collection` are not exposed. Those
stay human actions in the keepr web app. Every write is dry-run first and
shown before it is committed, and a card change that would lose data says so
before it can be applied.

## Reporting a problem

[Issues](https://github.com/zbiewend/keepr-agent/issues) here. Never paste a
key; the first ten characters (`kpr_` + six) are what keepr itself shows and
are enough to identify one.

MIT — see [LICENSE](LICENSE).
