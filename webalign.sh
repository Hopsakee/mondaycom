#!/usr/bin/env bash
# Start the alignment app (`monday align-web`: the kwartaalplanbord next to monday.com) in
# the background, on http://127.0.0.1:5002, from anywhere. ./webalign-stop.sh stops it.
# The log is .run/webalign.log.
#
#   ./webalign.sh               # without the reloader
#   ./webalign.sh --reload      # restart on code changes
#   ./webalign.sh --port 5003   # any other `monday align-web` option passes through
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/serve.sh" start webalign 5002 align-web "$@"
