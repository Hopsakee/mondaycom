#!/usr/bin/env bash
# Start the web UI (`monday web`) in the background, on http://127.0.0.1:5001, from anywhere.
# You get the terminal back; ./webview-stop.sh stops it. The log is .run/webview.log.
#
#   ./webview.sh               # live-reloading
#   ./webview.sh --no-reload   # without the reloader
#   ./webview.sh --port 5003   # any other `monday web` option passes through
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/serve.sh" start webview 5001 web "$@"
