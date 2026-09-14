# FastHTML — local reference

Offline snapshot of the FastHTML documentation, fetched **2026-09-04** from the
pages listed in `llms.txt`. Read from here first; only hit the network when
something is missing.

FastHTML is Starlette + Uvicorn + HTMX + fastcore's `FT` "FastTags". It renders
HTML on the server and ships partials over HTMX. It is **not** FastAPI, and it
is not for building JSON APIs.

## Layout

| Path | What it is |
| --- | --- |
| `llms.txt` | Upstream index of every doc page (use to find pages not mirrored here) |
| `ref/concise-guide.md` | **Start here.** The whole idiom in one page |
| `ref/apilist.txt` | Every function and method in fasthtml, with signatures |
| `ref/handlers.md` | How route handlers take params and return responses |
| `ref/live-reload.md` | Auto-restart while developing |
| `ref/custom-components.md` | Writing your own FT components |
| `explains/routes.md` | How routing and path/query params resolve |
| `explains/ft-components.md` | What FastTags are and how they render |
| `explains/websockets.md`, `explains/oauth.md`, `explains/minidataapi.md`, `explains/faq.md` | Topic guides |
| `tutorials/by-example.md` | Four complete apps, idiomatic HTMX patterns |
| `tutorials/e2e-walkthrough.md` | One app end to end, including deployment |
| `tutorials/jupyter.md` | Developing inside notebooks (not used in this repo) |
| `examples/adv_app.py` | Full CRUD app — the reference for idiomatic structure |
| `examples/basic_ws.py` | Minimal websockets app |
| `external/htmx-reference.md` | Every `hx-*` attribute, header, and event |
| `external/starlette-quick.md`, `external/starlette-full.md` | The Starlette underneath |
| `external/monsterui-apilist.txt` | MonsterUI, a shadcn-like component library (not used here) |
| `external/surreal.md` | Tiny JS helper library included by default |

## Fetching more pages

Most doc URLs serve markdown when you append `.md` to the HTML page name:

```bash
curl -sfL -o docs/fasthtml/<dir>/<slug>.md \
  https://www.fastht.ml/docs/<section>/<slug>.html.md
```

Slugs are listed in `llms.txt`. Refresh the whole set with `./scripts/sync-docs.sh`.

## Start here

1. `ref/concise-guide.md` — the minimal app, FastTags, responses, forms, auth
2. `explains/routes.md` — why `@rt` on `def foo()` gives you `/foo`
3. `ref/handlers.md` — type annotations drive param parsing
4. `external/htmx-reference.md` — when you need an `hx-*` attribute you don't know
5. `ref/apilist.txt` — grep this before guessing a signature

## Facts worth memorising

- `from fasthtml.common import *` is the idiomatic import. **Pico-only helpers
  (`Container`, `Card`, `Group`) are not in `common`** — import them from
  `fasthtml.pico`.
- `@rt` with no path uses the function name as the route; `index` maps to `/`.
  A handler used as an `href`/`hx_get` value renders as its own path, and
  `.to(**kw)` builds it with query params.
- Type annotations drive parsing: `x: int` coerces, `x: bool` reads a checkbox,
  `x: list[str]` collects repeated fields, a dataclass annotation unpacks a
  whole form body. Give every param a default or a missing field is a 4xx.
- Returning a tuple returns concatenated partials. `HEAD` tags in the tuple are
  hoisted into `<head>`. A full document is only wrapped around the response for
  non-HTMX requests — an `HX-Request` gets the bare partial.
- Strings in FT children are **escaped**. Use `Safe(...)` / `NotStr(...)` to
  inject real HTML.
- `cls` becomes `class`, `_for`/`fr` becomes `for`, `True` renders a bare
  attribute and `False` omits it entirely.
- `serve()` is for `python main.py` scripts; it inspects `__main__` itself, so
  never wrap it in `if __name__ == "__main__"`. This repo calls `uvicorn.run`
  from a CLI subcommand instead (see `src/mondaycom/web.py`).
- FastHTML ships **no `py.typed`**, so `mypy --strict` needs the overrides
  already present in `pyproject.toml`.
- Use `async` handlers wherever you do IO, or one slow request blocks others.
- Compatible with vanilla JS and web components; **not** with React, Vue, or
  Svelte.
