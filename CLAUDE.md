# CLAUDE.md

Personal command-line tooling around the monday.com GraphQL API, for Jelle's
work at WDODelta. The first tool pulls the current sprint's tasks and renders
them as Obsidian Tasks checkboxes, from the terminal or a local web page;
the burndown, the epics overview and the IV Portfolio followed, and
`monday project` writes an epic out as an Obsidian project note.

## Ground rules

- **uv, not PDM.** `uv sync`, `uv run`, `uv add`. There is no `pdm` in this repo.
- **Python modules and bash scripts, not notebooks.** New functionality goes in
  `src/mondaycom/` with a CLI subcommand and, where it helps, a wrapper in
  `scripts/`. `nbs/legacy/` is a frozen exploration record — do not extend it,
  do not run `nbdev`.
- **Every tool is a `monday` subcommand.** Add it in `cli.py`, keep the logic in
  its own module, print plain text to stdout so it pipes.
- **The web UI is FastHTML + HTMX, server-rendered.** It lives in `web.py` and
  reuses `sprint.py`, `burndown.py`, `epics.py` and `portfolio.py`; it is a second
  front-end, never a second implementation. No React, Vue, or Svelte — FastHTML is not
  compatible with them.
- Dutch column titles and task names are normal here; keep them as-is.

## Commands

```bash
uv sync                              # install deps into .venv
uv run monday sprint-tasks           # the main tool
uv run monday sprint-tasks --person all --epic "EBO-EIS"   # filtered
uv run monday sprint-tasks --dam dam # only epics in the IV Portfolio
uv run monday people                 # user ids, for --person
uv run monday epics                  # epic item ids, for --epic
uv run monday burndown --quiet       # sprint points: committed, done, on track?
uv run monday burndown --person me --dam non-dam           # narrowed
uv run monday epic-progress          # every epic: state, trekker, portfolio, STP battery
uv run monday epic-progress --dam dam --sort remaining --desc
uv run monday epic-progress --stuck  # only the blocked ones, with links to the blocking tasks
uv run monday portfolio              # IV Portfolio items, epics and points rolled up per item
uv run monday portfolio --item "EBO EIS"   # one item: its fields and every epic under it
uv run monday portfolio --stuck --empty    # only blocked items / also the ones with no epics
uv run monday project DPR-223        # write an Obsidian project note for one epic
uv run monday project 223 --stdout   # same epic, printed instead of written
uv run monday project 2617136005 --out . --force   # by item id, into this directory
uv run monday columns --board epic   # discover column ids (sprint|done|epic|portfolio)
./scripts/sprint-tasks.sh --copy     # same, plus clipboard
uv run poe check                     # ruff format --diff, ruff check, mypy
uv run poe test                      # pytest
uv run poe format                    # ruff format
uv run monday web                    # web UI, live-reloading, on http://127.0.0.1:5001
uv run monday web --no-reload        # same, without the reloader
./scripts/sync-docs.sh               # refresh docs/ (or: sync-docs.sh fasthtml)
```

`API_KEY_MONDAY` comes from `.env` (gitignored; see `.env.example`). `OBSIDIAN_PROJECTS_DIR`
overrides where `monday project` writes.

## Layout

| Path | Purpose |
| --- | --- |
| `src/mondaycom/config.py` | Token, API version, board ids, **column ids**, status indexes |
| `src/mondaycom/client.py` | `MondayClient` — POSTs GraphQL, raises `MondayError` |
| `src/mondaycom/queries.py` | GraphQL query builders |
| `src/mondaycom/sprint.py` | `Task` model + Obsidian markdown rendering |
| `src/mondaycom/lookups.py` | People and epic id/name lists + the name resolver |
| `src/mondaycom/burndown.py` | Sprint-group points, done dates, ideal vs actual, the person/DAM filters |
| `src/mondaycom/epics.py` | Epic rows, per-epic STP totals, **impediments**, the overview's filters and sorting |
| `src/mondaycom/portfolio.py` | IV Portfolio items, the epics grouped under them, their filters and sorting |
| `src/mondaycom/project.py` | One epic → an Obsidian project note: reference parsing, the template |
| `src/mondaycom/sorting.py` | The one-string sort spec both tables share (`Sorting`, `label_key`) |
| `src/mondaycom/chart.py` | The burndown SVG, the palette and tone tokens, status/priority tags, avatars, the battery meter, the table view |
| `src/mondaycom/cli.py` | `monday` argparse entry point |
| `src/mondaycom/web.py` | FastHTML web UI — the Sprint, Epics and Portfolio pages, FT components, caches |
| `scripts/` | Bash wrappers so tools run from anywhere |
| `docs/Project.md` | The vault's project template, as Templater writes it — `project.py` renders it |
| `docs/monday-api/` | **Offline mirror of the monday.com API docs — read this first** |
| `docs/fasthtml/` | **Offline mirror of the FastHTML docs — read this first** |
| `tests/` | Offline tests; no network |
| `nbs/legacy/` | Frozen nbdev exploration notebook |

## monday.com API — what bites you

Full docs are mirrored in `docs/monday-api/` (start with its `README.md`).
The things that cost time here:

- **HTTP 200 does not mean success.** GraphQL errors come back in the `errors`
  key of a 200 response. `MondayClient.execute` already handles this; never
  `requests.post` directly.
- **Filters match ids, not labels.** A status is filtered by its index
  (`"To Do"` is `16`, not `"To Do"`), a person by user id or the literal
  `"assigned_to_me"`. `config.SPRINT_STATUS` holds the mapping.
- **You cannot query a board for all its items.** Use `items_page` with
  `query_params`, and paginate with `cursor` on big results — the done board is 2000+
  items. `client.all_board_items` follows the cursor to the end.
- **`limit` does not survive a `cursor`.** `items_page(cursor: "…")` on its own falls
  back to the *default 25*, not the page size you asked for first. Repeat `limit` on
  every page — `queries._page_args` does. Forgetting it turned five requests into
  sixty-three and the done board from 10 seconds into 45.
- **A mirror column returns its members, not the roll-up.** "STP gedaan" shows 6 in the
  UI and answers `display_value: "2, 1, 3"` over the API, `sum` setting and all. Any
  total you need has to be summed from the source board — which is why `epics.py`
  reads both sprint boards instead of the epic board's four STP mirrors.
- **Pin the API version.** `config.API_VERSION` is `2026-07` (the current
  version as of 2026-09-03). Versions go to maintenance after 3 months, so
  re-check `docs/monday-api/guides/api-versioning.md` when bumping.
- **Only request the columns you need** — complexity budget is per-minute and
  shared across reads.
- **Every filter value has its own shape.** A status is a bare index (`16`), a
  person is the string `"person-<user id>"` (or `"assigned_to_me"`), and a
  board_relation is a **number**, not a string. Mixing these up returns an empty
  list, not an error. `config.person_filter_value` handles the person case.
- **`board_relation` columns put their name in `display_value`,** not in `text`,
  which is `null`. Reading it needs `... on BoardRelationValue` in the query.
- **A formula column answers in `display_value` too**, as the string `"true"` /
  `"false"` for a boolean. Readable, but the epic board's DAM formula is just
  `IF({Portfolio#Count} > 0, …)`, so we read the link and skip the indirection.
- Discover column ids for a board with `uv run monday columns --board sprint`
  rather than guessing. `--board` takes `sprint`, `done`, `epic` or `portfolio`.

## FastHTML — what bites you

Full docs are mirrored in `docs/fasthtml/` (start with its `README.md`, then
`ref/concise-guide.md`). **Read those before writing web code** — FastHTML looks
like FastAPI and is not. The things that cost time here:

- **`fasthtml.common` does not export the Pico helpers.** `Container`, `Card`,
  and `Group` come from `fasthtml.pico`; everything else is in `common`.
- **Type annotations do the parsing.** `x: bool` reads a checkbox, `x: list[str]`
  collects repeated fields, a dataclass unpacks a whole form. Give every param a
  default, or a missing field is a 4xx instead of a page.
- **`@rt` names the route after the function**; `index` is `/`. Pass the handler
  itself as `hx_get=`/`href=` and it renders as its own path — do not hardcode
  URL strings.
- **Strings in FT children are escaped.** `Safe(...)` / `NotStr(...)` to opt out.
- **HTMX requests get the bare partial**, plain requests get a full document.
  Test partials with a `HX-Request: 1` header, as `tests/test_web.py` does.
- **FastHTML ships no `py.typed`.** `pyproject.toml` already carries the mypy
  overrides for it (`fasthtml.*`, `uvicorn.*`, plus `disallow_untyped_decorators`
  off for `mondaycom.web`); extend those rather than sprinkling `# type: ignore`.
- **The live-reload socket needs its own handler.** fasthtml 0.14's `live_reload_ws`
  loops on `websocket.receive()` and only catches `WebSocketDisconnect`, but starlette
  1.6 *returns* the `websocket.disconnect` message instead of raising — so every closed
  tab logged an ASGI `RuntimeError: Cannot call "receive" once a disconnect message has
  been received.` `web.live_reload_ws` stops on the message and is patched over
  `fasthtml.live_reload.live_reload_ws` **before** `fast_app(live=True)` runs, because
  that is when the route captures the function. Drop it when fasthtml fixes it upstream.
- **`serve()` is for `python main.py`** and inspects `__main__` itself. This repo
  runs `uvicorn.run` from `web.run()` so it can be a CLI subcommand instead.
- The UI binds to **127.0.0.1 by default** — the process holds the API token.

## Burndown

`monday burndown` and the top of the web `/` page answer "are we on track?" in story points.

- **Sprint membership is the board group `backlog`** — whose title is "Current
  sprint", confusingly. That group is the truth; the due-date filter the task list
  uses is only a proxy for it.
- **Points are `numbers5` (Estimation).** The two `STP …` columns are mirrors from
  the epic board and are empty on tasks — do not reach for them.
- **A task burns down on its Done Date (`date`), not on the day you look.** Work
  finished before the sprint opened lands on day one rather than floating above
  the line; Done with no date also lands on day one; work finished *after* the sprint
  closed lands on the last day, so the line ends where the Remaining tile says it does.
- **`Vervallen` (cancelled) leaves the committed total.** Dropping a task lowers
  the bar instead of counting as progress, so it is excluded from both sides.
- Sprint boundaries still are not recorded anywhere, so the window is the due date
  **most of the group shares**, minus three weeks. `--end` overrides it.
- **A filtered burndown keeps the whole group's window.** One person's four tasks are
  far too thin a sample to guess a sprint end from, so `build(..., window_from=all)`
  takes the dates from the unfiltered group and the numbers from the slice.
- The person and DAM filters are applied **in Python** (`burndown.narrow`), not in the
  query: the group read deliberately carries no `query_params`, and it is 60 rows.
  The person is matched by *name*, because a group read returns owner and reviewer as
  text; the dropdown still speaks ids and `web.person_name` bridges the two.
- **A person filter shows owner *or* reviewer; the points count for the Trekker alone.**
  Two questions, two functions: `SprintItem.assigned_to` decides what is in your list,
  `SprintItem.owned_by` decides whose points they are. Every points view builds from
  `burndown.owned(kept, person)`, so the reviewed task sits in the table (with its 🤝)
  while its story points stay on the Trekker's side and the per-person totals still add
  up to the sprint's. Both the web page and `monday burndown --person` say
  "points counted as Trekker only" whenever a person is picked.
- Every filtered view **says which slice it is showing**. "15.7 points behind" means
  something very different for the sprint than for one person.
- **The web Sprint page shows a small burndown per person** under the big chart
  (`chart.multiple`, `chart.burndown_small`): the whole slice first, then every *Trekker*
  in it, each to its own scale on the sprint's window. Cards are points, so they hold
  the Trekker's points only (`bd.owned`) and somebody who merely reviews gets no card of
  their own (`SprintItem.people`) — an empty one says nothing. They follow the epic and
  portfolio filters but *not* the person filter — the question they answer is "who is
  behind?", which a person filter would make unanswerable.
- The chart is an **emphasis** chart, not two peer series: actual is the one accent
  hue, ideal is a recessive dashed gray. Colours come from the data-viz reference
  palette with their own dark-mode steps. If you touch them, re-run the validator
  rather than eyeballing.

## Board facts

Sprint board `757790388` ("Sprint bord, actief"), done board `757790418`
("Sprint bord, done"), Epic board `757753649`, IV Portfolio board `5097962810`.

| Alias | Column id | Title | Notes |
| --- | --- | --- | --- |
| `status` | `status_stories` | Status stories | To Do 16, Working on it 0, Wacht op Antwoord 6, Wacht op review 7, Done 1 |
| `due_date` | `date7` | Due Date | |
| `owner` | `person` | Trekker | filter with `assigned_to_me` |
| `reviewer` | `people` | Reviewer | Jelle here ⇒ the task is review work |
| `story_points` | `numbers5` | Estimation | 1 point = 120 minutes |
| `story_syntax` | `story_syntax` | Story syntax | long text |
| `epic` | `link_to_stories__main2` | Epic | board_relation → epic board; name is in `display_value` |
| `done_date` | `date` | Done Date | when it actually moved to Done — the burndown x-axis |

**The done board is not the active board with different rows — the column ids differ.**
Status is `status_stories1` (not `status_stories`), Epic is `link_to_stories__main`
(no trailing `2`), Due Date is `date8` (not `date7`). Only `numbers5`, `person`,
`people` and `date` are shared. Always go through `config.DONE_BOARD.column(...)`.

Epic board columns that matter:

| Alias | Column id | Title | Notes |
| --- | --- | --- | --- |
| — | `name` | Item | the epic's title |
| `status` | `status_stories_2` | Status epic | 13 labels; `config.EPIC_STATUSES` is the board's own order |
| `owner` | `person` | Trekker | a `people` column, so several names arrive comma-joined |
| `priority` | `color_mksqcf7n` | Priority | Very High → NNB; `config.EPIC_PRIORITIES` |
| `portfolio` | `board_relation_mm41w9ng` | Portfolio | board_relation → IV Portfolio; name in `display_value` |
| `prj_nr` | `pulse_id_mkrbpetp` | prj_nr | the project number, `DPR-223`. **Not** the item id |

The rest of the epic board — Funnel, Methode, Type, T-Estimation, Opdrachtgever, Domein
experts, the five dates, the two long texts — is aliased in `config.EPIC_BOARD` too, but
read by `project.py` alone. The overview pages ask for four columns, on purpose.

IV Portfolio board columns that matter. All of them are **plain text**, not statuses:

| Alias | Column id | Title | Notes |
| --- | --- | --- | --- |
| — | `name` | Name | the portfolio item's title |
| `goal` | `text_mm5rpj62` | Doelstelling | the programme it sits in; filled on all 177 |
| `urgency` | `text_mm5rjvsf` | Urgentie | Hoog / Middel / Laag; blank on 116 of them |
| `type` | `text_mm5rjs8m` | Type | Initiatief (123) or Project (54) |
| `lead` | `text_mm5rdssg` | Projectleider | a text column, so no avatar and no people filter |
| `start` | `date_mm41tpw3` | Start Date | filled on 8 items |
| `end` | `date_mm41mp1s` | Einddatum | **empty on every item today** |
| `link` | `link_mm5r9d80` | Link | the item's page in Fortes, the portfolio tool of record |
| `ref` | `text_mm5rpjaw` | ID | its Fortes id |

**The board carries no connect column back to the epics.** The link only exists on the
epic side (`board_relation_mm41w9ng`), so "which epics belong to this item" is answered
by inverting it — `portfolio.attach`. Its own "Portfolio" text column (`text_mm5rv1sb`)
says `IV portfolio` on all 177 items and is not read.

**Both sprint boards hold a "Dummy User stories" group** whose estimates are
epic-level guesses — 96 rows and 1705 points on the active board alone. Every
aggregate skips them (`config.DUMMY_GROUPS`); counting them swamps every real total.

A sprint runs 3 weeks inclusive: start = end − 3 weeks + 1 day.

## The web Sprint page

`/` is **one read of the sprint group** (`burndown.fetch_sprint_items`), narrowed once
(`burndown.narrow`, by person, portfolio and epic), and shown four ways: tiles, the
burndown, the per-person multiples, and the task list plus markdown. The task rows are
the same `SprintItem`s turned into `Task`s (`SprintItem.as_task`), so the chart and the
list can never disagree about what is in the sprint.

- The old separate Sprint tasks and Burndown pages are gone; they duplicated the filter
  row and, worse, defined sprint membership differently (due date versus group). The
  **group is the truth** on the web. The CLI's `sprint-tasks` still filters by due date
  server-side, because that is what its `--person`/`--epic` query rules are built on.
- **"Open only" is the one filter that does not scope everything**: it drops Done rows
  from the task list alone. A burndown without its done tasks is not a burndown.
- The page renders inline (a group read is a couple of seconds); the partial
  `/sprint_view` swaps `#sprint` with `outerHTML` and sends the epic list and the date
  field back out of band, so the dropdown only ever offers epics in the new scope and the
  field shows the window the group settled on.
- Default person is **Me** — the Obsidian paste is the daily use — and the per-person
  row keeps the whole team in view regardless.

## Filters

`sprint-tasks` and the web UI take the same narrowing filters. On the CLI the first
three are applied server-side in the GraphQL query where they can be; DAM never can. On
the web every filter is applied in Python to the group read:

| Filter | Default | "No filter" value | How it is matched |
| --- | --- | --- | --- |
| status | every status | — | `--open-only` applies `OPEN_STATUSES` |
| person | me | `--person all` / "Everyone" | owner **or** reviewer, as a nested `or` group; points count for the Trekker only |
| epic | every epic | omit `--epic` / "All epics" | `any_of` on board_relation (CLI); in Python (web) |
| DAM | both halves | `--dam all` / "Both" | in Python, against the DAM epic ids |

- "Assigned to" means **owner or reviewer**, never just owner — that is the whole
  point of the nested group in `queries.sprint_tasks`. **Points are the exception:**
  they land on the Trekker alone, see the Burndown section. A filter decides what you
  *see*; the Trekker decides what it *counts* for.
- Dropping the person filter also returns tasks with **nobody** assigned, and
  dropping the epic filter returns tasks with **no epic** linked. That is wanted.
- The 🤝 marker means "this person reviews it", so it follows the person filter:
  `fetch_tasks(me=...)` takes the name being filtered on. Filtering on Agnes
  marks the tasks *Agnes* reviews, not the ones Jelle reviews.
- The CLI resolves `--person`/`--epic` from an id **or** a case-insensitive name
  substring (`lookups.resolve`), and refuses ambiguous ones rather than guessing.
- The person list is the sprint board's **subscribers** (12), not all account
  users (61).
- **The web epic dropdown only offers epics that have tasks in the current scope**
  (person and portfolio applied, epic not). It is built from the group rows and swapped
  in out of band (`hx-swap-oob`) on every fetch, so picking one can never come back
  empty; an epic that left the scope falls back to "All epics" in the data as well as in
  the dropdown. The CLI keeps the server-side rule and can filter on any of the 275
  epics via `lookups.fetch_epics`, which raises rather than silently truncating if
  the epic board ever outgrows one page.
- **There is no board dropdown any more.** It only ever offered `sprint` and `epic`,
  and the epic board has none of the columns the task list reads, so picking it showed
  nothing. `sprint-tasks` lost its `--board` flag with it; `columns --board` keeps it.
- **Owner and epic are shown in the web table but stay out of the markdown.**
  The vault format below is fixed; do not add columns to it.

## DAM

"DAM" is not a label anywhere. On the epic board it is the formula
`IF({Portfolio#Count} > 0, TRUE(), FALSE())` — **an epic is DAM when it is linked to an
item on the IV Portfolio board**, and non-DAM when it is not. We read the link, not the
formula. Today that splits the board 42 / 233.

- The IV Portfolio board's own "Portfolio" text column says `IV portfolio` on all 177
  items, so it distinguishes nothing. The *link* is the whole signal.
- A task with **no epic** can never be DAM, but it *is* non-DAM — dropping the filter
  and picking "Non-DAM" are different questions, and both are wanted.
- `epics.dam_epic_ids` is one epic-board read (~6s), so it is cached in `web._DAM_EPICS`
  and only fetched when something actually filters on it.

## Epics page

`monday epic-progress` and `/epics` answer "where does every epic stand?".

- **The STP totals are summed from the two sprint boards**, never from the epic board's
  STP mirrors — see the mirror gotcha above. Open tasks on the active board are
  *remaining*, tasks archived to the done board are *done*, and the **status decides,
  not the board**: the done board does hold the odd unfinished row.
- `Vervallen` leaves both sides, exactly as in the burndown.
- **Tasks linked to no epic are reported, not absorbed.** 150 of them carry 193 points
  today; the page says so under the table rather than quietly losing them. So are
  points on an epic the epic board did not return.
- **An epic with no tasks gets an empty outlined battery, not a 0% one** — there is
  nothing to be 0% of — and sorts *after* a full one (`epics.NO_TASKS`).
- Every column sorts. Sorting is one string (`"-done"` is done descending,
  `epics.parse_sort` / `next_sort`), so a header carries the *next* state and needs no
  memory: `sort` rides in from the form's hidden field, `resort` from a clicked header,
  the header wins, and the fresh value is swapped back into the form out of band.
- **The filters are: status chips, Item search, Trekker, DAM, Progress, Show dropped.**
  Portfolio item and Priority lost their dropdowns on purpose — they were never used to
  narrow, only to sort, and the columns still sort.
- **Status is a row of chips with counts** (`web.status_chips`, `epics.status_counts`):
  one per status the board actually has, counted under every *other* filter so a chip
  says exactly what clicking it yields, in the board's order. A chip sets the hidden
  `status` field and fires the form's own `change`, so it takes the same path as a
  dropdown. The chips come back out of band with **every** response, because the counts
  move with the filters; they hold no caret, so that is safe.
- **Dropped epics (`config.EPIC_DROPPED_STATUSES`: Afgevallen, Overgedragen) are hidden
  by default** behind the "Show dropped" switch — their batteries read as 100% because
  every open task was cancelled, which is the wrong story at a glance. Naming a dropped
  status outright (its chip) shows them regardless of the switch; `epics.matches` does
  both.
- **Status and Priority sort in the board's order**, not the alphabet — a workflow, not
  a word list. A label the board no longer offers sorts after every one it does.
- Every filter dropdown is built from the fetched rows, so no choice can come back
  empty. They arrive with the first table (`fields=1`), because a cold page load has no
  rows yet — and *only* then, since re-rendering them on every keystroke would take the
  caret out of the search box. (The chips are the exception, see above.)
- **The whole board is cached in `web._EPICS`.** The first fetch is six requests and
  ~2400 items (~19s), so the table loads on its own `hx_trigger="load"` request behind a
  spinner and every sort or filter after that is a local re-render. "Refresh from
  monday.com" is the way to re-read it.
- The battery is a **meter**, not two series: one fill on a track that is a lighter step
  of the same blue ramp (light `#cde2fb`, dark `#104281`). Its numbers are always
  spelled out beside it — the track is deliberately low-contrast, and that is exactly
  the relief the palette validator's contrast WARN demands.
- **Every battery track is the same fixed width** (`7rem`; the headline one is `14rem`),
  so two rows compare by fill alone. A row's value is the percentage only, because the
  STP done / STP left columns beside it already hold the points; the headline battery
  in the summary tiles spells out done/total as well. Never let the value text or the
  cell width decide the track length again.
- **The summary is a row of stat tiles** (epics shown, done, left, cancelled, and the
  selection's own wide battery), with the orphan note under it.

## Portfolio page

`monday portfolio` and `/portfolio` answer "where does every IV Portfolio item stand?".

- **A portfolio item has no progress of its own.** Its points are the points of the
  epics linked to it, which are themselves summed from the two sprint boards. Every
  number on the page comes from `epics.fetch_epics`; `portfolio.py` adds one cheap
  board read and the inversion of the link.
- **The web page caches the two halves apart and joins them per request**
  (`web._PORTFOLIO` plus `web._EPICS`, `web.portfolio_cache`). The epic board is the
  twenty-second read and the Epics page already holds it; re-attaching on every request
  is microseconds and keeps the two from drifting when one is refreshed.
- **166 of the 177 items have no epic linked**, so they are hidden behind "Show
  unlinked" — the same shape as the Epics page's "Show dropped". Eleven items carry all
  42 DAM epics.
- **An epic naming a portfolio item the board did not return is reported, not dropped**
  (`portfolio.orphan_epics`), exactly as the Epics page reports tasks with no epic.
- Default sort is **progress ascending**: least complete first, which is what the page
  is for. Urgentie sorts in the board's own order (Hoog, Middel, Laag), not the alphabet.
- The overview is one row per item with the epics rolled up; **clicking the name opens
  the item** (`/portfolio_item?item=<id>`), which lists the epics themselves — blocked
  first, then most work left. That order is fixed and the detail table does not sort:
  it is one item's handful of rows, not a board.
- The **Epics page's Portfolio column is a link into it**, so the two pages are one
  thing seen from two ends.
- Both pages defer their table to an `hx_trigger="load"` request behind a spinner,
  because a cold cache means reading the epic board and both sprint boards.

## Project notes

`monday project <ref>` turns one epic into an Obsidian project note, rendering
`docs/Project.md` with the board's values already in it.

- **The reference is one of three shapes, and the board decides which column it is.**
  `DPR-223` and a bare `223` are the epic board's `prj_nr`; a long number is the item id.
  Bare digits are ambiguous by shape alone, so **length decides**
  (`config.PROJECT_NUMBER_MAX_DIGITS`): `prj_nr` counts in the hundreds, an item id is
  ten digits. `223` is padded to the column's own width first, so `7` finds `DPR-07`.
- **`prj_nr` is an `item_id`-type column with a custom key**, not a text column, and it
  filters on the text it *displays* — `any_of` with `"DPR-223"`, never the bare digits.
  `any_of` is also the only operator it configures; `contains_text` comes back as
  `no_operator_config`. An item id skips the board entirely via `items(ids:)`.
- **`prj_nr` is `Datalab_nr` in the note and the item id is `MondayCom_nr`** — two
  different numbers, one line apart in the frontmatter. The item id is **quoted**: ten
  digits are a number to YAML and Dataview would render it in scientific notation, which
  is why the vault's existing notes quote it too.
- **The file name is `<Item>_<prj_nr>.md`** — "Data validatie hydrologisch modelleren
  het vervolg_DPR-223.md". Characters a path or Obsidian will not take (`/`, `:`, `#`,
  `[]`, `^`, …) are stripped; an epic with no project number falls back to its item id.
- **`docs/Project.md` is a Templater template, and the note is not.** `<% tp.* %>` is
  evaluated by Obsidian when *it* creates a file; we create the file, so those are
  resolved here — the creation stamp is now, and `tp.file.move` becomes the directory we
  write into. The `&=choice(...)` expressions are **Dataview**, evaluated when the note
  is *read*, and are copied through untouched. A test asserts no `<%` survives.
- **The board's 13 statuses map onto the six words the vault's `projectstatus` field
  actually uses** (`config.PROJECT_STATUSES`: verkenning, backlog, loopt, pauze,
  afgerond, afgevallen). They are different vocabularies — one tracks a sprint workflow,
  the other tracks whether a project runs. An unknown label maps to **nothing**, not to a
  guess: a word the vault does not use reads as a typo.
- `rol` is `trekker` only when the epic is Jelle's. The board knows who pulls an epic; it
  does not know what his part is when that is somebody else, so the note asks.
- **Dates fall back rather than stay blank**: `start-project` is the planned start, else
  when work began, else when it was submitted; `eind-project` is the planned delivery,
  else the deadline, else when it finished.
- Everything the template has no field for — Funnel, Type, Methode, Prioriteit,
  Portfolio, the T-shirt size, the budget and all five dates — goes in one **"Epic op
  monday.com" table**, the only block the template does not have. Empty fields leave no
  row.
- **It refuses to overwrite** without `--force`: an existing note is the user's own work,
  and this command only ever writes the starting point. `--stdout` prints instead.
- Default output is the vault's projects folder (`config.OBSIDIAN_PROJECTS_DIR`, an env
  var), falling back to the working directory when it is not there — the vault lives on
  the Windows side of WSL and is not on every machine this repo is checked out on.

## Stuck

An epic or a portfolio item is **stuck** when work on it is blocked. Read from the work,
never from a column of its own:

- **An epic is stuck when it sits on `Impediment` itself, or when any of its tasks
  does.** `Epic.is_blocked` is the first, `Epic.is_stuck` is either
  (`config.IMPEDIMENT_STATUS`). A **portfolio item is stuck when any of its epics is**.
- **The blocking tasks travel by name and address**, not as a count:
  `epics.Impediment` carries the task's id, name, board and URL, collected by
  `epics.find_impediments` on the same rows `tally_tasks` already walks. "Blocked" is
  only actionable if you can reach the thing doing the blocking.
- **The marker is a `<details>`**: closed it is one critical tag (`chart.stuck_tag`),
  open it lists the epic and its blockers as links out to monday.com
  (`web.stuck_cell`, `web.portfolio_stuck_cell`). A running epic gets an *empty cell* —
  a quiet table is the point. Suppressing the disclosure triangle takes three rules;
  Pico draws its own chevron with `summary::after` on top of the UA marker.
- The column sorts and there is an **"Only stuck"** switch on both pages, plus
  `--stuck` on `epic-progress` and `portfolio`. The CLI prints `⛔` beside the name and
  lists every blocker with its URL under the table.
- **URLs are built, not fetched.** `config.item_url` composes them from
  `ACCOUNT_SLUG` and the board id; asking monday.com for `ItemType.url` would carry the
  field over 2400 rows to serve a handful of links. `queries.board_tasks` does now ask
  for `name`, which it needs for the blocker list.
- Today the boards hold **two Impediment epics and no Impediment tasks**, so the
  task list is exercised by the tests rather than by live data.

## State as colour

Status and priority labels wear a **tone**: a small coloured mark beside the label,
the label itself staying in ink. `chart.STATUS_TONES`, `chart.PRIORITY_TONES` and
`chart.URGENCY_TONES` map the boards' labels to the seven tones; an unknown label is
`neutral`, never an error. Urgentie is the IV Portfolio's priority in Dutch, so it wears
the same square mark: Hoog `serious`, Middel `warning`, Laag `neutral`.

| Tone | Means | Status labels | Priority |
| --- | --- | --- | --- |
| `good` | finished | Done | |
| `active` | being worked | Working on it, Ongoing, Onderhouden | |
| `warning` | waiting on something | Wacht op …, On hold, Overleg, Wachten op Epic | Medium |
| `serious` | | | High |
| `critical` | blocked / urgent | Impediment, **the stuck marker** | Very High |
| `neutral` | not started | To Do, To Refine, Gerefined, Making ready, … | Low |
| `off` | dropped / unknown (hollow mark) | Vervallen, Afgevallen, Overgedragen | Very Low, NNB |

- The four severity tones are the data-viz reference **status palette**, which is fixed
  across themes and distinct from the categorical slots; `active` is the accent blue the
  chart and the battery already use. Warning and serious sit below 3:1 on the light
  surface by design, so a tone is **never colour alone** — always dot + label.
- A status dot is round; a priority mark is a small square (`.tag.priority`), so the two
  columns never read as the same thing.
- The burndown's Remaining tile carries the verdict's tone (`chart.verdict_tone`); the
  count tiles carry none, because a row of coloured tiles says nothing.
- The tokens live on `:root` (with dark steps under both the media query and the
  `data-theme` scope), so a tag in the task list and a tile above a chart share them.

## People

- **Avatars come from `photo_url { thumb_small }`** on the board's subscribers
  (`queries.board_people`), the 2026-07 shape; the flat `photo_thumb_small` is gone
  in 2026-10. `lookups.Choice.photo` carries it; `web.photo_for(name)` looks it up by
  name, because owner columns arrive as text.
- **Initials are always rendered under the photo**, and the `img` removes itself on
  error, so a dead URL degrades to letters rather than a broken-image glyph.
- A `people` column joins several names with a comma; `chart.people` splits it into one
  avatar + name per person.

## Output format

Obsidian Tasks plugin syntax, pasted into the vault:

```
- [ ] #sprint <name> [🤝reviewer] [<minutes>m] ⏫ ➕ <sprint start> 📅 <due date>
```

## Web UI notes

- **The app live-reloads.** `fast_app(live=True)` plus `uvicorn --reload` means an
  edit under `src/mondaycom/` refreshes the open browser tab by itself. `--no-reload`
  turns both off together — `MONDAY_WEB_LIVE` is read at *import* time, so `cli.py`
  sets it before importing `web`.
- **The row checkbox is a selection, not a status.** It says "copy this one into the
  markdown". Done-ness is shown by striking the name through and dimming the row,
  never by the tick — every task stays selectable whether it is finished or not.
- **The nav marks the current page** with `aria-current="page"`, matched on the page
  title, so `page(title, …)` must be called with the nav label (`Sprint`, `Epics`,
  `Portfolio`). One portfolio item's page is titled `Portfolio` too, and puts the item's
  own name in an `H2` inside the swapped partial — which is also the only place it is
  known before the boards are read.
- **The Sprint page's date field shows the window it settled on**, not a blank: the page
  route computes the board first, and the HTMX partial swaps the field out of band.
- **Everything that swaps a wrapper the response also carries (`#sprint`,
  `#epic-table`, `#portfolio-table`, `#portfolio-item`) swaps `outerHTML`.** An
  innerHTML swap nests a second wrapper inside the first on every filter change — it
  did, for a while.
- **A sortable header is `web.sort_header`, shared by both tables.** It takes the route
  with the next spec already on it plus one `at` prefix, and derives `#<at>-filters` and
  `#<at>-table` from it — so the two tables' ids have to stay in that shape.
- **The portfolio table fits 1280px closed and scrolls a little when a stuck marker is
  opened.** The blockers panel is in flow rather than absolutely positioned: the
  `.table-wrap` clips on both axes, so an overlay would be cut off on the bottom rows.
- Screenshot the real pages before and after a visual change (Playwright is installed,
  `chromium` too): the tests check markup, not whether a column clips at 1280px.

## Open questions

- `sprint-tasks` returns **every** status by default, including Done, because
  that is what the notebook did. `--open-only` applies the four open statuses.
  Decide which should be the default.
- `default_sprint_end()` guesses "next Saturday" for the CLI. The web page guesses from
  the group's due dates instead. Sprint boundaries are still not encoded anywhere; pass
  `--end` (or type in the date field) when it matters.
- The CLI `sprint-tasks` and the web Sprint page define membership differently (due
  date versus group). Moving the CLI to the group read would make them one thing, at the
  cost of the server-side person/epic rules.
- The web UI caches the last fetch in module-level state (`web._TASKS`, `web._EPICS`,
  `web._PORTFOLIO`, `web._DAM_EPICS`), so the markdown route can re-render a selection
  and the epics table can re-sort without re-querying. Fine for one person on localhost; it would
  need a session if the UI is ever shared or run under multiple workers.
- A task's points can be read twice on the Sprint page: the tiles hold the Trekker's
  share and the list's own total holds every listed task ("24 points · 13 as Trekker").
  Two true numbers, one line apart — watch that it stays legible if more totals arrive.
- `epic-progress` reads both sprint boards end to end every time it runs (~19s). The
  web UI caches it; the CLI cannot. A points-per-epic cache on disk would fix that.
- "Sprint bord, afgevallen" (`1715341388`) is a third task board nothing reads yet.
  Its points are in no total, done or remaining.
- `web._DAM_EPICS` re-reads the epic board on its own, even when `_EPICS` already holds
  every row and their portfolio links. One cache could serve both.
- The IV Portfolio's Einddatum is empty on all 177 items, so a portfolio item has no
  deadline to be measured against — the page can say how far it is, never whether it is
  on time. If that column ever fills, it deserves the burndown's "on track?" treatment.
