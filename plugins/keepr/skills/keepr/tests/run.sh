#!/bin/sh
# Offline test suite for the keepr skill. No key, no network, no installs:
# a stub keepr API runs on localhost and the real script is driven against it.
set -e
cd "$(dirname "$0")/.."
python3 tests/test_keepr.py "$@"
