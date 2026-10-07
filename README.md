# keepr-agent

Connect an AI assistant to the records you keep in [keepr](https://keepr.cloud).

This repository is the **distribution** of the keepr plugin, built and tested
in [`zbiewend/keepr-api`](https://github.com/zbiewend/keepr-api). Nothing here
is edited by hand: keepr-api's `skills/publish.sh` regenerates it, and the API
deploy publishes it.

The guided version of everything below is at
**[keepr.cloud/account/connect](https://keepr.cloud/account/connect)**, and the
guide is at [keepr.cloud/docs/guides/assistants](https://keepr.cloud/docs/guides/assistants).

## Claude — the keepr plugin

One plugin, three parts:

- **the keepr skill** — how to read, add and change records without guessing;
- **the keepr connector**, `https://mcp.keepr.cloud/mcp` — keepr's tools, run
  by keepr, so they are always current;
- **keepr's local file tools** — a small server that attaches files and
  folders from your computer to your items. It runs in Claude Code, and in
  Cowork when it runs on your computer; Claude chat leaves it out.

**In Claude Code:**

```
/plugin marketplace add zbiewend/keepr-agent
/plugin install keepr@keepr-agent
```

Then type `/mcp`, choose the keepr server and authenticate: keepr's page opens
in your browser, you sign in and press **Allow**. The first time you attach a
file, the local file tools open the same page once for themselves. To keep the
plugin current by itself: `/plugin`, open **Marketplaces**, choose
**keepr-agent** and pick **Enable auto-update**. The local file tools need a
`node` on your computer, which Claude Code itself already needs.

**On claude.ai, the desktop app, your phone and Cowork:** add the
`zbiewend/keepr-agent` marketplace where your Claude manages plugins, add the
keepr plugin, then open its **Connectors** tab and choose **Connect**.

Nobody copies a key. Every connection is listed on your keepr profile under
**Connected assistants**, where you can disconnect it.

## Without the plugin

- **Any assistant that takes a connector** (Claude, ChatGPT and others): add
  `https://mcp.keepr.cloud/mcp` and sign in when it asks. In Claude Code:
  `claude mcp add --transport http keepr https://mcp.keepr.cloud/mcp`, then
  `/mcp`. Connections made at `https://api.keepr.cloud/mcp` keep working.
- **Other coding agents — the skill on its own.** Paste this to an assistant
  that can run a script:

  > Install the keepr skill from https://api.keepr.cloud/api/docs/skill

  `GET /api/docs/skill` returns every file of the skill inline, with
  instructions for writing them down; the skill zip is also on each release.
  The assistant runs `keepr.py`, which makes ordinary HTTPS calls to
  `api.keepr.cloud`. A copy installed this way updates itself with
  `keepr.py update`.
- **The Claude desktop extension**,
  [`keepr.mcpb`](https://github.com/zbiewend/keepr-agent/releases/latest/download/keepr.mcpb),
  is still built for the people who use it, and is being retired. It does not
  update itself.

## What is in here

```
.claude-plugin/marketplace.json    the marketplace Claude adds
plugins/keepr/                     the plugin
  .claude-plugin/plugin.json
  .mcp.json                        the connector (keepr) and the local file tools (keepr-files)
  README.md                        what the plugin does, and everything it runs on your computer
  LICENSE
  skills/keepr/                    the skill, as the plugin carries it
  server/keepr-files.sh            starts the local file tools with your Node.js
  server/keepr-files.js            the local file tools, one readable file
mcpb/manifest.json                 the desktop extension's manifest, for reference
CHANGELOG.md
```

The `.mcpb` and the skill zip are release assets, not files in this
repository. Each release also carries them as `keepr.mcpb` and `keepr.zip`, so
`releases/latest/download/keepr.mcpb` (and `…/keepr.zip`) is always the newest.

The skill in the plugin leaves out what only a copy installed on its own
needs: how to update itself, the setup walkthrough and its tests.

## Versions

The plugin's version is the **skill's** version: the skill is what the
assistant reads, and it is the contract with the people running it. The
server's own version is `metadata.server` in `plugin.json` and the `version`
in `mcpb/manifest.json`. Both are listed per release in `CHANGELOG.md`.

## What it will not do

Nothing here deletes an item, a card or a collection. Those stay human actions
in the keepr web app, with sharing and keys. Every write is previewed first
and shown before it is committed, and a card change that would lose data says
so before it can be applied.

## Reporting a problem

[Issues](https://github.com/zbiewend/keepr-agent/issues) here. Never paste a
key or a token.

MIT — see [LICENSE](LICENSE).
