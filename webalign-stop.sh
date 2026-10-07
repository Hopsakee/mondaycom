#!/usr/bin/env bash
# Stop the alignment app that ./webalign.sh started (or whatever holds its port).
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/serve.sh" stop webalign 5002
