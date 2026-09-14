#!/usr/bin/env bash
# Print the current sprint's tasks as Obsidian markdown.
#
#   ./scripts/sprint-tasks.sh                    # next Saturday, all statuses
#   ./scripts/sprint-tasks.sh --end 2026-09-19   # explicit sprint end
#   ./scripts/sprint-tasks.sh --open-only        # skip tasks that are Done
#   ./scripts/sprint-tasks.sh --copy             # also put it on the clipboard
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

copy=0
args=()
for arg in "$@"; do
  if [[ "$arg" == "--copy" ]]; then copy=1; else args+=("$arg"); fi
done

output="$(uv run --project "$REPO" monday sprint-tasks "${args[@]+"${args[@]}"}")"
printf '%s\n' "$output"

if [[ "$copy" -eq 1 ]]; then
  if command -v wl-copy >/dev/null 2>&1; then printf '%s' "$output" | wl-copy
  elif command -v xclip  >/dev/null 2>&1; then printf '%s' "$output" | xclip -selection clipboard
  elif command -v clip.exe >/dev/null 2>&1; then printf '%s' "$output" | clip.exe
  else echo "warning: no clipboard tool found (wl-copy, xclip, clip.exe)" >&2; fi
fi
