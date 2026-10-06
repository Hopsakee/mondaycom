#!/usr/bin/env bash
# Start the web UI on http://127.0.0.1:5001, from anywhere.
#
#   ./webview.sh               # live-reloading
#   ./webview.sh --no-reload   # without the reloader
#   ./webview.sh --port 5002   # any other `monday web` option passes through
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --project "$REPO" monday web "$@"
