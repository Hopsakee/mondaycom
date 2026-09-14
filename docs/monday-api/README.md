# monday.com Platform API — local reference

Offline snapshot of the monday.com developer documentation, fetched **2026-09-03**.
Read from here first; only hit the network when something is missing.

## Layout

| Path | What it is |
| --- | --- |
| `build-on-monday-with-ai.md` | Platform overview for AI agents: MCP servers, auth, rate limits |
| `llms.txt` | Full upstream index of every doc page (use to find pages not mirrored here) |
| `guides/` | How-to guides: auth, versioning, filtering, mutations, rate limits |
| `reference/` | Schema reference: objects, queries, and every column type |

## Fetching more pages

Every doc URL serves clean markdown when you append `.md`:

```bash
curl -sfL -o docs/monday-api/guides/<slug>.md \
  https://developer.monday.com/api-reference/docs/<slug>.md

curl -sfL -o docs/monday-api/reference/<slug>.md \
  https://developer.monday.com/api-reference/reference/<slug>.md
```

Slugs are listed in `llms.txt`. Refresh the whole set with `./scripts/sync-docs.sh`.

## Start here

New to this API? Read in this order:

1. `guides/basics.md` — what the API is, boards/items/columns data model
2. `guides/introduction-to-graphql.md` — GraphQL query/mutation shape
3. `guides/authentication.md` — token handling and headers
4. `reference/items-page.md` — **the** page for filtering board items (`query_params`)
5. `reference/column-types-reference.md` — how each column type reads and writes
6. `guides/rate-limits.md` — complexity budget, why you should not over-fetch

## Facts worth memorising

- Endpoint: `POST https://api.monday.com/v2`, headers `Authorization: <token>` and `API-Version: <version>`.
- Versions are date-named. As of 2026-09-03: **current `2026-07`**, maintenance `2026-04`, RC `2026-10`.
  Always pin an explicit version — omitting the header silently follows "current" and breaks on upgrades.
- The API returns **HTTP 200 on GraphQL errors**. Always inspect the `errors` key in the body.
- Boards cannot be queried for all items at once; use `items_page` with `query_params` and paginate via `cursor`.
- Filters match on **IDs, not labels** — status by index, people by user id or the literal `"assigned_to_me"`.
