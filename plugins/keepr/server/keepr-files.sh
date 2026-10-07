#!/bin/sh
# keepr's local file tools: starts keepr-files.js, beside this file, with the
# Node.js already on this computer. The plugin's .mcp.json runs this script
# (server "keepr-files"); Claude chat ignores it, Claude Code and Cowork on
# this computer start it.
#
# It downloads nothing, installs nothing, and reads no key: keepr-files.js
# signs in only through keepr's consent page in the browser (keepr_connect).
# Generated into keepr-agent by keepr-api's skills/publish.sh; edit it there.
set -eu

# CLAUDE_PLUGIN_ROOT is the installed plugin's folder; without it (a run by
# hand), the folder above this script.
root=${CLAUDE_PLUGIN_ROOT:-$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)}
server="$root/server/keepr-files.js"

# A desktop app starts this with a short PATH that may not include where Node
# was installed, so after the PATH, look in the usual places.
node=$(command -v node 2>/dev/null || true)
if [ -z "$node" ]; then
	for candidate in /opt/homebrew/bin/node /usr/local/bin/node /usr/bin/node \
		"$HOME/.volta/bin/node" "$HOME/.local/share/fnm/aliases/default/bin/node" \
		"$HOME/.asdf/shims/node"; do
		if [ -x "$candidate" ]; then node=$candidate; break; fi
	done
fi
if [ -z "$node" ]; then
	# nvm: the last match, which sorts as the newest version installed.
	for candidate in "$HOME"/.nvm/versions/node/*/bin/node; do
		if [ -x "$candidate" ]; then node=$candidate; fi
	done
fi
if [ -z "$node" ]; then
	echo "keepr-files: Node.js 18 or newer is needed for keepr's local file tools, and none was found. Install it from https://nodejs.org, then restart Claude." >&2
	exit 127
fi

exec "$node" "$server"
