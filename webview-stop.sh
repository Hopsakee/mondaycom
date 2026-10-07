#!/usr/bin/env bash
# Stop the web UI that ./webview.sh started (or whatever holds its port).
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/serve.sh" stop webview 5001
