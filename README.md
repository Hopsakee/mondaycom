# mondaycom

Command-line tools around the [monday.com](https://monday.com) GraphQL API, for
pulling sprint work out of monday.com and into a terminal or an Obsidian vault.
Plus a small local web page that does the same with a date picker and a copy
button.

## Setup

```bash
uv sync
cp .env.example .env      # then paste your monday.com personal API token
uv run monday whoami      # confirms the token works
```

Get a token in monday.com: avatar (bottom left) → **Developers** → **My access tokens**.

## Usage

```bash
uv run monday sprint-tasks                  # tasks due by next Saturday, as Obsidian markdown
uv run monday sprint-tasks --end 2026-09-19 # explicit sprint end date
uv run monday sprint-tasks --open-only      # skip tasks that are already Done
uv run monday sprint-tasks --person all     # everyone's tasks, not just mine
uv run monday sprint-tasks --person Agnes   # one person's, by name or user id
uv run monday sprint-tasks --epic "EBO-EIS 6.3"  # only tasks linked to that epic
uv run monday sprint-tasks --dam dam        # only epics in the IV Portfolio
uv run monday people                        # who you can filter on, with ids
uv run monday epics                         # every epic, with ids
uv run monday burndown                      # sprint burndown, day by day
uv run monday burndown --quiet              # just the headline numbers
uv run monday burndown --person me          # one person's burndown
uv run monday burndown --dam non-dam        # everything outside the IV Portfolio
uv run monday epic-progress                 # every epic: state, trekker, portfolio, STP
uv run monday epic-progress --dam dam --sort remaining --desc
uv run monday epic-progress --stuck         # only the blocked epics, with their blockers
uv run monday portfolio                     # IV Portfolio items with their epics rolled up
uv run monday portfolio --item "EBO EIS"    # one item: its fields and every epic under it
uv run monday portfolio --stuck             # only the items with a blocked epic
uv run monday project DPR-223               # write an Obsidian project note for one epic
uv run monday project 223 --stdout          # same epic, printed instead of written
uv run monday project 2617136005 --out .    # by monday.com item id, into this directory
uv run monday columns --board sprint        # every column on a board, with ids and types
uv run monday query my-query.graphql        # run a raw GraphQL query
```

`--person` and `--epic` take an id or a case-insensitive part of the name;
an ambiguous name is refused rather than guessed. "Assigned to" means owner
**or** reviewer.

`--dam` splits the work by portfolio: an epic counts as **DAM** when it is linked
to an item on the IV Portfolio board, and **non-DAM** when it is not. A task with
no epic at all is non-DAM.

`--stuck` keeps only work that is blocked: an epic on **Impediment**, or one with a
task that is. The blocking tasks are listed under the table with a link to each on
monday.com, because "blocked" is only useful if you can reach the thing doing it.

`monday project` writes one epic out as an Obsidian project note, filling the vault's
template (`docs/Project.md`) with what the board already knows: the codes, the dates,
who is involved, and the epic's own metadata. It takes the project number with or
without its prefix (`DPR-223`, `223`) or the monday.com item id — a long number is read
as an item id, a short one as a project number. The note is named
`<Item>_<prj_nr>.md` and lands in the vault's projects folder, or wherever `--out`
says; an existing note is never overwritten without `--force`.

The bash wrappers in `scripts/` do the same from any directory, and
`./scripts/sprint-tasks.sh --copy` puts the result straight on the clipboard.

Output is [Obsidian Tasks](https://publish.obsidian.md/tasks/) syntax:

```
# Sprint 2026-08-17 - 2026-09-06

- [ ] #sprint Maak Sonar files script eenvoudig lokaal draaibaar [240m] ⏫ ➕ 2026-08-17 📅 2026-09-06
- [ ] #sprint Berekeningen fudura data in Azure 🤝reviewer [600m] ⏫ ➕ 2026-08-17 📅 2026-09-06
```

## Web interface

```bash
uv run monday web             # http://127.0.0.1:5001
uv run monday web --port 8080
uv run monday web --no-reload # without live reload
```

Three pages: **Sprint**, **Epics** and **Portfolio**. The app live-reloads — edit
anything under `src/mondaycom/` and the open tab refreshes itself, no restart needed.

**Sprint** is one read of the board's *Current sprint* group, shown four ways: the
headline tiles, the burndown chart, a small burndown per person (who is behind?), and
the task list with its Obsidian markdown. Pick who it is assigned to (**Me**,
**Everyone**, or one person), which **Epic** and which **Portfolio** half; every
filter scopes everything on the page. The Epic dropdown only lists epics that have
tasks in the current scope, so picking one never gives you an empty list. The sprint
end is guessed from the group's due dates and shown in the date field; override it there.

The row checkbox means *"copy this one"*, not *"done"* — finished tasks are shown
struck through and dimmed, and stay tickable. The markdown below the table updates as
you tick, and **Copy** puts it on the clipboard. Unticking does not re-query
monday.com — the tasks from the last fetch are cached in the server process.

**Epics** is every epic with its story points burnt down, summed from both sprint
boards. Status is a row of chips with counts, the other filters are Trekker, DAM,
progress and **Only stuck**, and every column sorts. Afgevallen and Overgedragen epics
are hidden until you flip **Show dropped**. The Portfolio column links through to the
portfolio item.

**Portfolio** is the IV Portfolio board with those epics grouped under it: one row per
portfolio item with its Doelstelling, Type, Urgentie, Projectleider, how many epics it
has and how far their story points are. Click an item to open it and see the epics
themselves — blocked ones first, then the most work left. Items with no epic linked
(166 of 177) are hidden until you flip **Show unlinked**.

Both pages carry a **Stuck** column. It is empty while things run; when an epic sits on
*Impediment*, or a task of it does, it shows a red marker you can open to get the epic
and every blocking task as a link to monday.com.

It binds to localhost only: the process holds your API token. Pass `--host` if
you really want it reachable from elsewhere on the network.

## Burndown

Story points for the current sprint, burned down against the ideal line. Sprint
membership comes from the board's **Current sprint** group and a task burns down on
its **Done Date**, so the chart reflects when work actually finished. Cancelled
(`Vervallen`) tasks leave the committed total rather than counting as progress.

```
# Sprint 2026-08-17 - 2026-09-06  (today 2026-09-04)
committed 103 · done 77 · remaining 26 · cancelled 4
ideal today 10.3 — 15.7 points behind
```

## Development

```bash
uv run poe check    # ruff format --diff, ruff check, mypy
uv run poe test     # pytest (offline, no API calls)
uv run poe format   # ruff format
```

The monday.com API and [FastHTML](https://fastht.ml) documentation are mirrored
offline under `docs/monday-api/` and `docs/fasthtml/`; refresh both with
`./scripts/sync-docs.sh`, or one with `./scripts/sync-docs.sh fasthtml`. See
`CLAUDE.md` for the board ids, column mappings, and the gotchas worth knowing.

### Burndown

Story points burnt down against the ideal line, for the board's current sprint
group. The same three filters as the CLI — sprint end, assignee, DAM or non-DAM —
and every filtered view says which slice it is showing, because "15.7 points
behind" means something very different for the sprint than for one person. The
sprint window itself always comes from the whole group; one person's handful of
tasks is far too thin a sample to guess a sprint end date from.

### Epics

Every epic with its **Status epic**, **Item**, **Stuck**, **Trekker**, linked
**Portfolio**, **Priority**, and a battery of how much of its story points are done against how
much is left. The totals are summed from the tasks on **Sprint bord, actief** and
**Sprint bord, done** — open tasks are remaining, archived ones are done.

Every column sorts (click its heading; click again to reverse) and every column
filters. An epic with no tasks yet gets an empty outlined battery rather than a
0% one, and sorts after a full one.

The first load reads both sprint boards end to end, so it takes about twenty
seconds behind a spinner; after that sorting and filtering are local re-renders.
**Refresh from monday.com** re-reads the boards. Tasks that are linked to no epic
are counted up and reported under the table rather than quietly dropped.

### Portfolio

A portfolio item has no progress of its own — its points are the points of the epics
linked to it, so the Portfolio page is the Epics page's numbers added up one level. The
link only exists on the epic side (the IV Portfolio board has no column pointing back),
so the epics are grouped by the item they name; one that names an item the board did not
return is reported under the table rather than dropped.

It shares the epic cache, so opening it after the Epics page costs one extra request
rather than another twenty seconds.
