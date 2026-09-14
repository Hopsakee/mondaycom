#!/usr/bin/env bash
# Re-download the vendored documentation under docs/.
#
#   ./scripts/sync-docs.sh            # both doc sets
#   ./scripts/sync-docs.sh monday     # just docs/monday-api/
#   ./scripts/sync-docs.sh fasthtml   # just docs/fasthtml/
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

get() { # get <url> <dest>
  curl -sfL -o "$2" "$1" || echo "failed: ${2#"$REPO/"} <- $1" >&2
}

# Refreshes exactly the pages already present, plus the upstream index.
sync_monday() {
  local base="https://developer.monday.com/api-reference"
  local docs="$REPO/docs/monday-api"

  get "$base/llms.txt" "$docs/llms.txt"
  get "$base/docs/build-on-monday-with-ai.md" "$docs/build-on-monday-with-ai.md"

  for kind in guides:docs reference:reference; do
    local dir="${kind%%:*}" path="${kind##*:}"
    for file in "$docs/$dir"/*.md; do
      get "$base/$path/$(basename "$file" .md).md" "$file"
    done
  done
  echo "refreshed $docs"
}

# The FastHTML set is a hand-picked subset of llms.txt, so the mapping is explicit.
# Add a line here when you mirror another page; README.md documents the layout.
sync_fasthtml() {
  local ft="https://www.fastht.ml/docs"
  local raw="https://raw.githubusercontent.com"
  local docs="$REPO/docs/fasthtml"

  get "$ft/llms.txt"                                 "$docs/llms.txt"
  get "$ft/ref/concise_guide.html.md"                "$docs/ref/concise-guide.md"
  get "$ft/apilist.txt"                              "$docs/ref/apilist.txt"
  get "$ft/ref/handlers.html.md"                     "$docs/ref/handlers.md"
  get "$ft/ref/live_reload.html.md"                  "$docs/ref/live-reload.md"
  get "$ft/ref/defining_xt_component.md"             "$docs/ref/custom-components.md"
  get "$ft/explains/routes.html.md"                  "$docs/explains/routes.md"
  get "$ft/explains/websockets.html.md"              "$docs/explains/websockets.md"
  get "$ft/explains/faq.html.md"                     "$docs/explains/faq.md"
  get "$ft/explains/minidataapi.html.md"             "$docs/explains/minidataapi.md"
  get "$ft/explains/oauth.html.md"                   "$docs/explains/oauth.md"
  get "$ft/explains/explaining_xt_components.html.md" "$docs/explains/ft-components.md"
  get "$ft/tutorials/by_example.html.md"             "$docs/tutorials/by-example.md"
  get "$ft/tutorials/e2e.html.md"                    "$docs/tutorials/e2e-walkthrough.md"
  get "$ft/tutorials/jupyter_and_fasthtml.html.md"   "$docs/tutorials/jupyter.md"

  get "$raw/AnswerDotAI/fasthtml/main/examples/adv_app.py"          "$docs/examples/adv_app.py"
  get "$raw/AnswerDotAI/fasthtml/main/examples/basic_ws.py"         "$docs/examples/basic_ws.py"
  get "$raw/bigskysoftware/htmx/master/www/content/reference.md"    "$docs/external/htmx-reference.md"
  get "$raw/AnswerDotAI/MonsterUI/refs/heads/main/docs/apilist.txt" "$docs/external/monsterui-apilist.txt"
  get "$raw/AnswerDotAI/surreal/main/README.md"                     "$docs/external/surreal.md"
  get "https://gist.githubusercontent.com/jph00/e91192e9bdc1640f5421ce3c904f2efb/raw/61a2774912414029edaf1a55b506f0e283b93c46/starlette-quick.md" \
      "$docs/external/starlette-quick.md"
  get "https://gist.githubusercontent.com/jph00/809e4a4808d4510be0e3dc9565e9cbd3/raw/9b717589ca44cedc8aaf00b2b8cacef922964c0f/starlette-sml.md" \
      "$docs/external/starlette-full.md"
  echo "refreshed $docs"
}

case "${1:-all}" in
  monday)   sync_monday ;;
  fasthtml) sync_fasthtml ;;
  all)      sync_monday; sync_fasthtml ;;
  *)        echo "usage: $0 [all|monday|fasthtml]" >&2; exit 2 ;;
esac
