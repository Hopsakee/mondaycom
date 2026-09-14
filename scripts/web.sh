#!/usr/bin/env bash
# Serve the sprint tasklist and burndown as a local web page.
#
#   ./scripts/web.sh                # http://127.0.0.1:5001, live-reloading
#   ./scripts/web.sh --port 8080    # another port
#   ./scripts/web.sh --no-reload    # without the reloader
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec uv run --project "$REPO" monday web "$@"
