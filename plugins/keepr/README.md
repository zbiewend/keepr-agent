# keepr

Read, add and change the records you keep in [keepr](https://keepr.cloud) from
Claude: look things up, add items from a sentence or a spreadsheet, have keepr
total them by month or by category, change your cards, set up a collection,
and attach files from your computer to the right items.

## What it adds

- **The keepr skill.** How to work with keepr: read a collection's schema
  before anything else, show you what will be written before it is saved,
  never invent a value. It loads everywhere you use Claude.
- **The keepr connector,** `https://mcp.keepr.cloud/mcp`. keepr's tools, run
  by keepr. In Claude on the web, the desktop app, your phone and Cowork, open
  this plugin's **Connectors** tab and choose **Connect**. In Claude Code, type
  `/mcp`, choose the keepr server and authenticate. Either way keepr's own page
  opens: sign in, choose which collections Claude may use and whether it may
  change them, and press **Allow**.
- **keepr's local file tools** (the server `keepr-files`). They run only in
  Claude Code, and in Cowork when it runs on your computer; Claude chat leaves
  them out. They attach a file or a whole folder from your computer to your
  items without passing the files through the conversation:
  `keepr_attach_local_file`, `keepr_attach_folder` and `keepr_attach_status`,
  plus `keepr_connect` and `keepr_disconnect` to sign them in and out.

## Using it

Ask in your own words: "what's in my Books collection", "add these receipts
to Expenses", "how much did I spend on travel by month", "attach the photos in
my house folder to the Rooms items". Before anything is written, Claude shows
you what keepr will do and waits for you to agree. A folder is matched to
items by a value the filenames carry, such as a receipt number, and you see
every match before a file is sent.

## What runs on your computer

The local file tools are `server/keepr-files.js`, one readable file started by
`server/keepr-files.sh` with the Node.js already on your computer. Nothing is
downloaded or installed. They:

- **read only the files and folders you name.** Hidden files, and anything in
  a hidden folder of your home folder (such as `~/.ssh`), are refused. They
  list or read nothing else.
- **talk only to keepr** (`api.keepr.cloud`): the files you asked for go to
  your keepr account, and nothing goes anywhere else.
- **sign in through keepr's consent page.** The first time they need keepr,
  they open that page in your browser (with `open`, `xdg-open` or `rundll32`).
  While you sign in, and for five minutes at most, they listen on `127.0.0.1`,
  on a port chosen at random, for keepr's answer. They never ask for a
  password or a key, and read no key from your environment.
- **store that connection in `~/.config/keepr/credentials`**, readable only by
  you, and renew it there. `keepr_disconnect` revokes it and deletes it. keepr
  lists it under **My Profile → Connected assistants**, where you can
  disconnect it too.

Nothing else in the plugin runs. The skill is instructions only: it carries
no scripts, and nothing in the plugin reads an API key or any other
credential from your environment.

## What it will not do

It never deletes an item, a card or a collection. Sharing, deleting, undoing
changes and managing keys stay yours, in the keepr web app. A rule that would
notify people, change other records or run on a schedule arrives paused, and
only you can turn it on.

## Updates and help

New versions are published to
[zbiewend/keepr-agent](https://github.com/zbiewend/keepr-agent). The guide is
at [keepr.cloud/docs/guides/assistants](https://keepr.cloud/docs/guides/assistants).
Report a problem in the repository's
[issues](https://github.com/zbiewend/keepr-agent/issues).

MIT licensed: see `LICENSE`.
