"""FastHTML web interface: the Sprint page, the Epics page and the Portfolio page.

The Sprint page is one read of the board's sprint group, shown four ways: headline
tiles, the burndown chart, a small burndown per person, and the task list with its
Obsidian markdown. The Epics page is every epic with its story points burnt down. The
Portfolio page is the IV Portfolio board with those epics grouped under it, as an
overview and a detail page per item. The library reference is mirrored under
docs/fasthtml/ — start with its README.md.

Fetched rows are cached in module-level state (`_TASKS`, `_EPICS`, …) so that ticking a
checkbox or clicking a header re-renders locally instead of spending complexity budget
on monday.com again. Single user, single process, localhost.
"""

from __future__ import annotations

import os
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from fasthtml import live_reload
from fasthtml.common import (
    H2,
    H3,
    A,
    Button,
    Caption,
    Code,
    Del,
    Details,
    Div,
    Fieldset,
    Form,
    Input,
    Label,
    Li,
    Nav,
    Option,
    P,
    Pre,
    Select,
    Small,
    Span,
    Strong,
    Style,
    Summary,
    Table,
    Tbody,
    Td,
    Th,
    Thead,
    Titled,
    Tr,
    Ul,
    fast_app,
)
from fasthtml.pico import Group  # Pico-only layout helpers are not re-exported by `common`
from starlette.websockets import WebSocketDisconnect

from mondaycom import burndown as bd
from mondaycom import chart, epics, lookups, portfolio, sprint
from mondaycom.client import MondayClient, MondayError
from mondaycom.config import ASSIGNED_TO_ME, DAM, DONE_STATUS, ME, NON_DAM, OPEN_STATUSES
from mondaycom.epics import Epic
from mondaycom.lookups import Choice
from mondaycom.portfolio import PortfolioItem
from mondaycom.sprint import Task

# Tasks from the last fetch, by monday.com item id, so the markdown route can re-render
# a selection without going back to monday.com.
_TASKS: dict[str, Task] = {}

# The people dropdown changes rarely and costs a query, so it is fetched once.
_PEOPLE: list[Choice] = []

# The epics overview costs six requests and a couple of thousand items, so it is fetched
# once and then sorted and filtered in Python. "Refresh" is the way to re-read it.
_EPICS: list[Epic] = []
_ORPHANS = epics.Points()

# The IV Portfolio board: one cheap request, but its epics come from `_EPICS`, so the
# two are joined on every request rather than stored joined — see `portfolio_cache`.
_PORTFOLIO: list[PortfolioItem] = []

# Epic ids carrying a portfolio link, for the DAM filter. One epic-board read; only
# fetched when something actually filters on it.
_DAM_EPICS: set[str] = set()

# Sentinels for the two "do not filter" dropdown options.
EVERYONE = "all"
ALL_EPICS = "all"

# "Do not filter on the portfolio at all", alongside config.DAM / config.NON_DAM.
ANY_PORTFOLIO = ""
PORTFOLIO_LABELS = ((ANY_PORTFOLIO, "Both"), (DAM, "DAM only"), (NON_DAM, "Non-DAM only"))

FETCH_ERRORS = (MondayError, ValueError, RuntimeError, OSError)


def people_choices() -> list[Choice]:
    """The people for the assignee dropdown, fetched once and then cached.

    A failure here must not cost you the page: the filter just falls back to
    "Me" and "Everyone", which is what the CLI does anyway.
    """
    if not _PEOPLE:
        try:
            with MondayClient() as client:
                _PEOPLE[:] = lookups.fetch_people(client)
        except FETCH_ERRORS:
            pass
    return _PEOPLE


def dam_epics() -> set[str]:
    """The epic ids with a portfolio link, fetched once. Empty on failure, which the
    caller reports as "cannot tell DAM from non-DAM" rather than as an empty result.

    The Epics page's cache already carries every epic and its portfolio link, so when it
    is warm the answer is a filter over rows we have rather than a second read of the
    same board — that read is ~6s and it is on the Sprint page's request path.
    """
    if not _DAM_EPICS:
        if _EPICS:
            _DAM_EPICS.update(epic.id for epic in _EPICS if epic.is_dam)
        else:
            with MondayClient() as client:
                _DAM_EPICS.update(epics.dam_epic_ids(client))
    return _DAM_EPICS


def person_name(person: str) -> str:
    """The name behind a person dropdown value, for the filters that match on text.

    The sprint group is read without `query_params`, so it is filtered on the Trekker
    *text* rather than on ids; the dropdown still speaks ids, like the CLI.
    `EVERYONE` means no filter, so it has no name.
    """
    if person in (EVERYONE, ""):
        return ""
    if person == ASSIGNED_TO_ME:
        return ME
    match = next((c.name for c in people_choices() if c.id == person), "")
    if not match:
        raise ValueError(f"Unknown person {person!r}. Pick one from the dropdown.")
    return match


def photo_for(name: str) -> str:
    """The profile picture behind a name, from the cached people list. Empty when unknown."""
    return next((c.photo for c in people_choices() if c.name == name), "")


def epic_choices(items: list[bd.SprintItem]) -> list[Choice]:
    """The epics actually linked to `items`, so picking one can never come back empty."""
    seen = {i.epic_id: i.epic for i in items if i.epic_id}
    return sorted((Choice(id=i, name=n) for i, n in seen.items()), key=lambda c: c.name.lower())


CSS = """
#markdown { white-space: pre-wrap; }
td.tight, th.tight { width: 1%; white-space: nowrap; }
.htmx-request #spinner { display: inline; }
#spinner { display: none; }
/* The nav says where you are: the current page is ink, not a link colour. */
nav.pages ul:first-child { margin-left: -.5rem; }
nav.pages a[aria-current="page"] { color: var(--pico-h1-color, inherit); font-weight: 600; text-decoration: none; }
nav.pages a { padding: .25rem .5rem; }
p.lede { margin-top: -.5rem; color: var(--pico-muted-color); }
/* One tight actions row rather than a full-width primary button. */
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; margin-top: .6rem; }
.actions button, .actions [role="button"] { width: auto; margin-bottom: 0; }
.section-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: .4rem 1.25rem; margin-top: 1.75rem; }
.section-head h3 { margin-bottom: .2rem; }
.section-head small { color: var(--pico-muted-color); }
table td { vertical-align: middle; }
/* A finished task is shown as finished. The checkbox means "copy this one". */
tr.done td { opacity: .62; }
tr.done del { text-decoration-thickness: 1px; color: inherit; }
/* Eight columns do not fit a laptop; scroll them rather than crushing the names.
   Both wide tables live in a .table-wrap, so the per-column widths are scoped to
   their own table — the task list's roomy second column is the epics table's
   Status, which does not want 18rem of it. */
.table-wrap { overflow-x: auto; }
table.tasks { min-width: 52rem; }
table.tasks td:nth-child(2) { min-width: 18rem; }
caption.hint { caption-side: top; text-align: left; padding-bottom: .4rem; }

/* Sortable headers are buttons, so they are reachable by keyboard, but they have to
   read as table headings rather than as a row of controls. */
th button.sort {
  all: unset; cursor: pointer; font: inherit; font-weight: 600; white-space: nowrap;
}
th button.sort:focus-visible { outline: 2px solid var(--pico-primary-focus, #0172ad); outline-offset: 2px; }
th button.sort .arrow { opacity: .45; font-size: .8em; }
th button.sort[aria-sort] .arrow { opacity: 1; }

/* The epic filters in one block: a grid, so they stay compact and line up as the
   window changes, rather than rows of full-width Pico groups. */
.filters { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: .1rem .8rem;
           align-items: end; }
.filters label:first-child { grid-column: span 2; }
.filters label.switch { padding-bottom: .9rem; }
#epic-filters { margin-bottom: 1.2rem; border: 0; padding: 0; }
#epic-filters input, #epic-filters select { margin-bottom: .2rem; }

table.epics td, table.epics th { padding: .3rem .45rem; font-size: .88rem; }
table.epics { min-width: 62rem; }
table.epics td.owner { white-space: normal; min-width: 9rem; }
table.epics td.num { text-align: right; font-variant-numeric: tabular-nums; }
table.epics td.item { min-width: 12.5rem; }
/* Portfolio item names run long, so this is the one epics column allowed to wrap. */
table.epics td.portfolio, table.epics th.portfolio { max-width: 10rem; }
table.epics td.progress { padding-right: .6rem; }
/* The headline tiles sit above the table and the orphan note under them. */
.epic-head { margin-bottom: .75rem; }
.epic-head p { margin: 0; }

/* The portfolio table is the epics table with wider names: a portfolio item's title is
   a sentence. Doelstelling and Projectleider wrap rather than push the Progress column
   off the right edge — that column is the reason the page exists. */
table.portfolio { min-width: 58rem; }
table.portfolio td.item { min-width: 11rem; white-space: normal; }
/* Wrap between words, never inside one: "Watersysteem" broken across two lines reads
   as a typo. The column widens instead, which the wrapper can scroll. */
table.portfolio td.goal, table.portfolio th.goal { max-width: 8rem; white-space: normal;
                                                   overflow-wrap: normal; }
table.portfolio td.lead { white-space: normal; min-width: 6rem; max-width: 8rem; overflow-wrap: normal; }

/* One portfolio item's own fields: labelled facts, not a second table. */
.meta { display: flex; flex-wrap: wrap; gap: .35rem 1.5rem; margin: -.4rem 0 1rem; }
.meta .fact small { display: block; color: var(--text-muted); font-size: .75rem; line-height: 1.3; }
.meta .fact span { font-size: .9rem; }
"""

# `this` is the header checkbox; the rows live in the same form.
TOGGLE_ALL_JS = """
this.closest('form').querySelectorAll('input[name=task_id]').forEach(b => b.checked = this.checked);
htmx.trigger(this.closest('form'), 'change');
"""

# `this` is the copy button, so it can report back that it worked.
COPY_JS = """
navigator.clipboard.writeText(document.getElementById('markdown').innerText).then(() => {
    const label = this.textContent;
    this.textContent = 'Copied';
    setTimeout(() => { this.textContent = label; }, 1500);
});
"""

# `this` is a status chip inside the epic filter form: set the hidden field, then let the
# form's own change trigger do the request, so a chip and a dropdown take the same path.
CHIP_JS = """
const f = this.closest('form');
f.elements.namedItem('status').value = this.dataset.status;
htmx.trigger(f, 'change');
"""

# Live reload: `fast_app(live=True)` injects a socket that refreshes the browser when
# uvicorn restarts on a code change. Set MONDAY_WEB_LIVE=0 to serve without it.
LIVE = os.environ.get("MONDAY_WEB_LIVE", "1") != "0"

# Watch the package, not the whole repo, so docs/ and .venv/ do not trigger restarts.
SRC = Path(__file__).resolve().parent


async def live_reload_ws(websocket: Any) -> None:
    """The live-reload socket: hold it open until the browser goes away.

    fasthtml's own handler loops on `websocket.receive()` and only catches
    `WebSocketDisconnect`, but starlette *returns* the `websocket.disconnect` message
    rather than raising on it — the next call then raises `RuntimeError` and uvicorn
    logs an ASGI traceback every time a tab is closed or reloaded. Stop on the message
    instead. The route captures this function when `fast_app(live=True)` builds the
    app, so the patch below has to happen before that call.
    """
    await websocket.accept()
    with suppress(WebSocketDisconnect):
        while (await websocket.receive())["type"] != "websocket.disconnect":
            pass


live_reload.live_reload_ws = live_reload_ws

app, rt = fast_app(title="monday sprint", live=LIVE, hdrs=(Style(CSS), Style(chart.CHART_CSS)))


def page(title: str, *content: Any) -> Any:
    """Every page: the same nav, with the current page marked, then the route's content."""
    links = (("Sprint", index), ("Epics", epics_page), ("Portfolio", portfolio_page))
    return Titled(
        title,
        Nav(
            Ul(
                *[Li(A(label, href=target, aria_current="page" if label == title else None)) for label, target in links]
            ),
            cls="pages",
        ),
        *content,
    )


def lede(text: str) -> Any:
    """The one-line explanation under a page title."""
    return P(Small(text), cls="lede")


def error(exc: Exception, id: str) -> Any:
    return Div(P(Code(str(exc)), style="color: var(--pico-del-color, #b3261e)"), id=id)


# --- shared filter controls -------------------------------------------------------------


def epic_select(choices: list[Choice], selected: str = ALL_EPICS) -> Any:
    """Only epics linked to the tasks currently in scope, so a pick is never empty.

    Swapped out of band on every fetch, because which epics are in scope depends on
    the person and the portfolio filter.
    """
    if selected != ALL_EPICS and selected not in {c.id for c in choices}:
        selected = ALL_EPICS  # the epic left the current scope; do not filter on nothing
    return Select(
        Option("All epics", value=ALL_EPICS, selected=selected == ALL_EPICS),
        *[Option(c.name, value=c.id, selected=c.id == selected) for c in choices],
        name="epic",
        id="epic-select",
    )


def person_select(selected: str = ASSIGNED_TO_ME) -> Any:
    """The assignee dropdown. "Assigned to" means the Trekker; reviewing does not count."""
    return Select(
        Option("Me", value=ASSIGNED_TO_ME, selected=selected == ASSIGNED_TO_ME),
        Option("Everyone", value=EVERYONE, selected=selected == EVERYONE),
        *[Option(c.name, value=c.id, selected=c.id == selected) for c in people_choices()],
        name="person",
    )


def portfolio_select(selected: str = ANY_PORTFOLIO) -> Any:
    """DAM / non-DAM: whether the task's epic is linked to the IV Portfolio board."""
    return Select(
        *[Option(label, value=value, selected=value == selected) for value, label in PORTFOLIO_LABELS],
        name="dam",
    )


# --- the stuck marker -------------------------------------------------------------------
# "Blocked" is only actionable if you can reach the thing doing the blocking, so the
# marker is a disclosure: closed it is one critical tag, open it lists the blockers as
# links out to monday.com. Both tables build it from the same three helpers.


def blocker_links(epic: Epic) -> list[Any]:
    """One list item per task holding `epic` up: its name, linked, and which board it is on."""
    return [
        Li(A(imp.name, href=imp.url, target="_blank", rel="noopener"), Small(imp.board, cls="where"))
        for imp in epic.impediments
    ]


def stuck_reason(epic: Epic) -> str:
    """Why this epic is stuck, in the few words a table cell has room for."""
    tasks = len(epic.impediments)
    plural = "" if tasks == 1 else "s"
    if epic.is_blocked and tasks:
        return f"epic + {tasks} task{plural}"
    return "epic" if epic.is_blocked else f"{tasks} task{plural}"


def stuck_cell(epic: Epic) -> Any:
    """The Stuck column of an epics table: empty when it runs, a marker you can open when not.

    The epic itself is always the first link, so the disclosure has somewhere to go even
    when the block is the epic's own status and no task carries it.
    """
    if not epic.is_stuck:
        return ""
    on_monday = "Status epic: Impediment" if epic.is_blocked else "the epic on monday.com"
    return Details(
        Summary(chart.stuck_tag(stuck_reason(epic))),
        Ul(
            Li(A(epic.name, href=epic.url, target="_blank", rel="noopener"), Small(on_monday, cls="where")),
            *blocker_links(epic),
            cls="blockers",
        ),
        cls="stuck",
    )


def portfolio_stuck_cell(item: PortfolioItem) -> Any:
    """The same marker one level up: which epics are stuck, and what is blocking each."""
    if not item.is_stuck:
        return ""
    blocked = item.stuck_epics
    return Details(
        Summary(chart.stuck_tag(f"{len(blocked)} epic{'' if len(blocked) == 1 else 's'}")),
        Ul(
            *[
                Li(
                    A(epic.name, href=epic.url, target="_blank", rel="noopener"),
                    Small(stuck_reason(epic), cls="where"),
                    Ul(*blocker_links(epic)) if epic.impediments else None,
                    cls="epic",
                )
                for epic in blocked
            ],
            cls="blockers",
        ),
        cls="stuck",
    )


# --- the sprint page ------------------------------------------------------------------
# One read of the sprint group, narrowed once, shown four ways. Every filter scopes
# everything below it, with one exception: "Open only" drops Done rows from the task
# list alone, because a burndown without its done tasks is not a burndown.


def sprint_end_field(end: str) -> Any:
    """The date picker. It shows the window actually in use, not a blank."""
    return Input(type="date", name="end", value=end, id="sprint-end")


def sprint_controls(end: str, person: str, choices: list[Choice], epic: str, dam: str, open_only: bool) -> Any:
    """The filter row: sprint end, who, which epic, portfolio, and whether to drop Done."""
    return Form(
        Fieldset(
            Group(
                Label("Sprint end", sprint_end_field(end)),
                Label("Assigned to", person_select(person)),
            ),
            Group(
                Label("Epic", epic_select(choices, epic)),
                Label("Portfolio", portfolio_select(dam)),
            ),
            Label(
                Input(type="checkbox", name="open_only", role="switch", checked=open_only),
                "Open only (drop Done tasks from the list)",
            ),
        ),
        Div(Button("Update", type="submit"), Small(" loading…", id="spinner"), cls="actions"),
        hx_get=sprint_view,
        hx_target="#sprint",
        hx_swap="outerHTML",
        hx_trigger="change, submit",
        hx_indicator="closest form",
        id="sprint-filters",
    )


def task_row(task: Task) -> Any:
    """One task as a row you can include in, or leave out of, the copied markdown.

    The tick is a *selection*, not a status — so a finished task is marked by
    striking its name through and by the Status column, never by the checkbox.
    """
    done = task.status == DONE_STATUS
    return Tr(
        Td(
            Input(
                type="checkbox",
                name="task_id",
                value=task.id,
                checked=True,
                aria_label=f"Include {task.name} in the markdown",
            ),
            cls="tight",
        ),
        Td(Del(task.name) if done else task.name),
        Td(Span("🤝", title="Review work") if task.is_reviewer else "", cls="tight"),
        Td(chart.people(task.owner, photo_for), cls="tight"),
        Td(task.epic),
        Td(chart.status_tag(task.status), cls="tight"),
        Td(f"{task.duration_minutes}m" if task.duration_minutes else "", cls="tight"),
        Td(task.due_date, cls="tight"),
        cls="done" if done else None,
    )


def task_table(items: list[Task], end: str) -> Any:
    """The task picker. Any change re-renders the markdown from the cache."""
    header = Tr(
        Th(
            Input(type="checkbox", checked=True, onclick=TOGGLE_ALL_JS, aria_label="Select all tasks"),
            cls="tight",
        ),
        Th("Task"),
        Th(Span("🤝", title="Review work"), cls="tight", aria_label="Review"),
        Th("Owner", cls="tight"),
        Th("Epic"),
        Th("Status", cls="tight"),
        Th("Time", cls="tight"),
        Th("Due", cls="tight"),
    )
    return Form(
        Input(type="hidden", name="end", value=end),
        Div(
            Table(
                Caption("Tick the tasks to copy. Struck-through tasks are already Done.", cls="hint"),
                Thead(header),
                Tbody(*[task_row(task) for task in items]),
                cls="tasks",
            ),
            cls="table-wrap",
        ),
        hx_get=markdown,
        hx_target="#markdown-block",
        hx_trigger="change",
    )


def markdown_block(text: str) -> Any:
    """The Obsidian markdown, plus a button that puts it on the clipboard."""
    return Div(
        Button("Copy", onclick=COPY_JS, cls="secondary"),
        Pre(Code(text, id="markdown")),
        id="markdown-block",
    )


def task_summary(items: list[Task], own_points: int | None = None) -> Any:
    """The list's own totals. `own_points` is the share that counts for the person
    filtered on — spelled out, because the tiles above show that number and not this
    one whenever review work is in the list."""
    minutes = sum(task.duration_minutes for task in items)
    points = sum(task.story_points for task in items)
    tail = f" · {own_points} as Trekker" if own_points is not None and own_points != points else ""
    return Small(f"{len(items)} tasks · {points} points{tail} · {minutes} minutes")


def sprint_scope(person: str, dam: str, epic: str, kept: int, total: int) -> str:
    """A one-line description of what the sprint was narrowed to.

    Said out loud because a filtered burndown is easy to mistake for the sprint's, and
    "3 points behind" means something else per person. A person's slice also says that
    the numbers above it are the Trekker's, since the list below holds review work whose
    points belong to somebody else.
    """
    if kept == total and not person and not dam and not epic:
        return ""
    parts = [person or "everyone"]
    parts += [label.lower() for value, label in PORTFOLIO_LABELS if value == dam and value]
    if epic:
        parts.append(epic)
    line = f"{' · '.join(parts)} — {kept} of {total} tasks in the sprint group"
    return f"{line} · points counted as Trekker only" if person else line


def per_person(items: list[bd.SprintItem], end: str, window_from: list[bd.SprintItem]) -> list[Any]:
    """One small burndown per Trekker in `items`, the whole slice first.

    All on the group's window, each to its own scale: the question is "who is behind?",
    and a person with three points would be a flat line on the sprint's axis. These are
    points, so they are the Trekker's alone (`bd.owned`) — review work would count the
    same points twice and no card would add up.
    """
    cards = [chart.multiple(Strong("Everyone"), bd.build(items, end=end or None, window_from=window_from))]
    for name in bd.people(items):
        mine = bd.owned(items, name)
        cards.append(
            chart.multiple(
                chart.person(name, photo_for(name)), bd.build(mine, end=end or None, window_from=window_from)
            )
        )
    return cards


def sprint_section(
    b: bd.Burndown, scope: str, multiples: list[Any], tasks: list[Task], own_points: int | None = None
) -> Any:
    """Everything under the filters: tiles, chart, per-person charts, tasks, markdown."""
    end = str(b.end)
    return Div(
        H2(f"Sprint {b.start} – {b.end}"),
        P(Small(scope), cls="lede") if scope else None,
        chart.kpis(b),
        chart.legend(),
        chart.burndown_svg(b),
        Details(Summary("Day by day"), chart.burndown_table(b)),
        Div(
            H3("Per person"),
            Small("every Trekker in this slice · each chart to its own scale, on the sprint's window"),
            cls="section-head",
        ),
        Div(*multiples, cls="multiples"),
        Div(H3("Tasks"), task_summary(tasks, own_points), cls="section-head"),
        task_table(tasks, end) if tasks else P("No tasks in this slice."),
        markdown_block(sprint.tasklist_markdown(tasks, end)),
        cls="viz",
        id="sprint",
    )


@dataclass
class SprintPage:
    """What one pass over the sprint group produced: the view, and what the filters need."""

    view: Any
    end: str
    choices: list[Choice]


def _sprint(end: str, person: str, epic: str, dam: str, open_only: bool) -> SprintPage:
    """Read the group once, narrow it, and render every view of it."""
    try:
        name = person_name(person)
        with MondayClient() as client:
            items = bd.fetch_sprint_items(client)
        dam_scope = frozenset(dam_epics() if dam else ())
        # The epic list is built from the person's and the portfolio's scope, so a pick
        # can never come back empty; an epic that left the scope falls back to "all".
        in_scope = bd.narrow(items, person=name, dam=dam, dam_epics=dam_scope)
        choices = epic_choices(in_scope)
        epic_id = epic if epic in {c.id for c in choices} else ""
        kept = bd.narrow(in_scope, epic=epic_id)
        # The list keeps the review work; the points do not. The window comes from the
        # whole group: one person's handful of tasks is far too small a sample to guess
        # the sprint's end date from.
        board = bd.build(bd.owned(kept, name), end=end or None, window_from=items)
        team = bd.narrow(items, dam=dam, dam_epics=dam_scope, epic=epic_id)
        multiples = per_person(team, end, items)
    except FETCH_ERRORS as exc:
        return SprintPage(error(exc, id="sprint"), end, [])

    # The 🤝 marker means "this person reviews it", so it follows the person filter.
    listed = [item for item in kept if item.status in OPEN_STATUSES] if open_only else kept
    tasks = [item.as_task(me=name or ME) for item in listed]
    _TASKS.clear()
    _TASKS.update({task.id: task for task in tasks})

    epic_name = next((c.name for c in choices if c.id == epic_id), "")
    scope = sprint_scope(name, dam, epic_name, len(kept), len(items))
    own_points = int(sum(item.points for item in bd.owned(listed, name))) if name else None
    return SprintPage(sprint_section(board, scope, multiples, tasks, own_points), str(board.end), choices)


@rt
def index(
    end: str = "",
    person: str = ASSIGNED_TO_ME,
    epic: str = ALL_EPICS,
    dam: str = ANY_PORTFOLIO,
    open_only: bool = False,
) -> Any:
    """The sprint: filters on top, then tiles, chart, per-person charts, tasks, markdown."""
    result = _sprint(end, person, epic, dam, open_only)
    return page(
        "Sprint",
        lede("The current sprint group: points burnt down, who stands where, and the tasks as Obsidian checkboxes."),
        sprint_controls(result.end, person, result.choices, epic, dam, open_only),
        result.view,
    )


@rt
def sprint_view(
    end: str = "",
    person: str = ASSIGNED_TO_ME,
    epic: str = ALL_EPICS,
    dam: str = ANY_PORTFOLIO,
    open_only: bool = False,
) -> Any:
    """The section under the filters, on its own, so a filter change swaps it in place.

    The date field and the epic list ride along out of band: the first shows the window
    the group settled on, the second only offers epics in the new scope.
    """
    result = _sprint(end, person, epic, dam, open_only)
    return (
        result.view,
        sprint_end_field(result.end)(hx_swap_oob="true"),
        epic_select(result.choices, epic)(hx_swap_oob="true"),
    )


@rt
def markdown(end: str = "", task_id: list[str] | None = None) -> Any:
    """Re-render the markdown for the currently checked tasks, from the cache."""
    end = end or sprint.default_sprint_end()
    selected = [_TASKS[tid] for tid in (task_id or []) if tid in _TASKS]
    return markdown_block(sprint.tasklist_markdown(selected, end))


# --- the epics overview ---------------------------------------------------------------
# Every epic, its state, and how far its story points have burnt down. The whole board
# is fetched once into `_EPICS`; sorting and filtering then happen in Python, so a
# dropdown or a header click costs a render and not six monday.com requests.

#: Column key -> heading. The order here is the order of the table.
EPIC_COLUMNS = (
    ("name", "Item"),
    ("status", "Status epic"),
    ("stuck", "Stuck"),
    ("owner", "Trekker"),
    ("portfolio", "Portfolio"),
    ("priority", "Priority"),
    ("done", "STP done"),
    ("remaining", "STP left"),
    ("progress", "Progress"),
)


def epic_cache(refresh: bool = False) -> tuple[list[Epic], epics.Points]:
    """The epic board, fetched on first use and then reused. `refresh` re-reads it."""
    global _ORPHANS
    if refresh or not _EPICS:
        with MondayClient() as client:
            rows, orphans = epics.fetch_epics(client)
        _EPICS[:] = rows
        _ORPHANS = orphans
        # The DAM set is a view of these rows, so it goes stale with them.
        _DAM_EPICS.clear()
    return _EPICS, _ORPHANS


def sort_header(heading: str, active: bool, desc: bool, rows: Any, at: str, cls: str | None = None) -> Any:
    """One sortable heading: a submit-free button that asks for the next sort state.

    The direction lives in the URL and the filters ride along from the form, so the
    header needs no state of its own — see `sorting.Sorting.next`. `rows` is the partial
    route with the next spec already on it, and `at` names both the form it sends and
    the wrapper it swaps, which every table keeps in step (`#epic-filters` / `#epic-table`).
    """
    return Th(
        Button(
            heading,
            Span(" ↓" if (active and desc) else " ↑" if active else " ↕", cls="arrow"),
            cls="sort",
            type="button",
            aria_sort=("descending" if desc else "ascending") if active else None,
            hx_get=rows,
            hx_include=f"#{at}-filters",
            hx_target=f"#{at}-table",
            hx_swap="outerHTML",
            hx_indicator=f"#{at}-filters",
        ),
        cls=cls,
    )


def epic_sort_header(column: str, heading: str, spec: str) -> Any:
    """The epics table's version: its own sort vocabulary, its own wrappers."""
    current, desc = epics.parse_sort(spec)
    return sort_header(
        heading,
        active=column == current,
        desc=desc,
        rows=epic_table_rows.to(resort=epics.next_sort(column, spec)),
        at="epic",
        cls="portfolio" if column == "portfolio" else "tight" if column != "name" else None,
    )


def portfolio_link(epic: Epic) -> Any:
    """The epic's IV Portfolio item, as a way into the Portfolio page rather than as text."""
    if not epic.portfolio_ids:
        return Span("—", style="opacity:.5")
    return A(epic.portfolio or "portfolio item", href=portfolio_item.to(item=epic.portfolio_ids[0]))


def epic_row(epic: Epic) -> Any:
    """One epic. The battery is the story; the two numbers beside it are the same data
    spelled out, which is also what makes the meter's recessive track legible."""
    return Tr(
        Td(epic.name, cls="item"),
        Td(chart.status_tag(epic.status), cls="tight"),
        Td(stuck_cell(epic), cls="tight"),
        Td(chart.people(epic.owner, photo_for), cls="owner"),
        Td(portfolio_link(epic), cls="portfolio"),
        Td(chart.priority_tag(epic.priority), cls="tight"),
        Td(bd.fmt(epic.done) if epic.done else "", cls="num tight"),
        Td(bd.fmt(epic.remaining) if epic.remaining else "", cls="num tight"),
        Td(chart.battery(epic.done, epic.remaining), cls="tight progress"),
    )


def epic_summary(shown: list[Epic], everything: list[Epic], orphans: epics.Points) -> Any:
    """What the selection adds up to, as stat tiles, and what it could not account for.

    The selection's own battery is the wide one: the same meter as every row, at double
    length, so the headline reads as "the whole of what you filtered to".
    """
    total = epics.totals(shown)
    tiles = [
        chart.tile("Epics", str(len(shown)), f"of {len(everything)} on the epic board"),
        *chart.points_tiles(total),
        chart.progress_tile(total),
    ]
    note = None
    if orphans.tasks:
        note = P(
            Small(
                f"{orphans.tasks} sprint tasks ({bd.fmt(orphans.done + orphans.remaining)} points) "
                "are linked to no epic and are in none of these rows.",
                style="opacity:.7",
            )
        )
    return Div(Div(*tiles, cls="kpis"), note, cls="epic-head")


def epic_table(shown: list[Epic], everything: list[Epic], orphans: epics.Points, spec: str) -> Any:
    """The table, header included: the one thing a sort or a filter swaps.

    Every response carries this `#epic-table` wrapper, so everything that targets it
    swaps `outerHTML` — an innerHTML swap would nest a second wrapper inside the first.
    """
    if not everything:
        body = P("The epic board came back empty.")
    elif not shown:
        body = P("No epics match these filters.")
    else:
        body = Div(
            Table(
                Thead(Tr(*[epic_sort_header(key, heading, spec) for key, heading in EPIC_COLUMNS])),
                Tbody(*[epic_row(epic) for epic in shown]),
                cls="epics",
            ),
            cls="table-wrap",
        )
    return Div(epic_summary(shown, everything, orphans), body, cls="viz", id="epic-table")


def status_chips(rows: list[Epic], f: epics.Filters) -> Any:
    """The status filter as chips with counts, plus the hidden field they set.

    Built from the rows under every *other* filter, so each chip says exactly how many
    epics clicking it shows, and the board's shape is visible before anything is chosen.
    Swapped out of band on every response, because the counts move with the filters.
    """
    counts = epics.status_counts(rows, f)
    # "All" is what clearing the status shows — which, unlike a dropped status's own
    # chip, still hides dropped epics unless the switch is on.
    everything = sum(1 for epic in rows if epics.matches(epic, replace(f, status="")))

    def chip(label: Any, value: str, count: int) -> Any:
        return Button(
            label,
            Span(str(count), cls="count"),
            type="button",
            cls="chip",
            data_status=value,
            aria_pressed="true" if f.status == value else "false",
            onclick=CHIP_JS,
        )

    return Div(
        Input(type="hidden", name="status", value=f.status),
        chip("All", "", everything),
        *[chip(chart.status_tag(status), status, count) for status, count in counts],
        cls="chips",
        id="status-chips",
        role="group",
        aria_label="Status epic",
    )


def filter_select(name: str, label: str, any_of: str, values: list[str], selected: str) -> Any:
    """One column's filter, on either overview. Built from the values actually on the
    board, so no choice in it can come back empty — the same rule as the sprint page's
    epic dropdown."""
    return Label(
        label,
        Select(
            Option(any_of, value="", selected=not selected),
            *[Option(v, value=v, selected=v == selected) for v in values],
            name=name,
        ),
    )


def epic_filter_fields(rows: list[Epic], f: epics.Filters) -> Any:
    """The dropdowns themselves.

    Their options come from the fetched rows, which on a cold page load do not exist
    yet — so the table response swaps this block in out of band once, rather than on
    every keystroke, which would take the caret out of the search box.
    """
    return Div(
        Label(
            "Item",
            Input(
                type="search",
                name="search",
                value=f.search,
                placeholder="Search epic titles…",
                aria_label="Search epic titles",
            ),
        ),
        filter_select("owner", "Trekker", "Any trekker", epics.options(rows, "owner"), f.owner),
        Label("DAM", portfolio_select(f.dam)),
        Label(
            "Progress",
            Select(
                Option("Any progress", value="", selected=not f.bucket),
                *[Option(label, value=value, selected=value == f.bucket) for value, label in epics.BUCKETS.items()],
                name="bucket",
            ),
        ),
        Label(
            Input(type="checkbox", name="stuck", role="switch", checked=f.stuck),
            "Only stuck",
            cls="switch",
            title="Epics on Impediment, or with a task that is",
        ),
        Label(
            Input(type="checkbox", name="dropped", role="switch", checked=f.dropped),
            "Show dropped",
            cls="switch",
            title="Afgevallen and Overgedragen epics are hidden unless this is on",
        ),
        cls="filters",
        id="epic-filter-fields",
    )


def epic_filters(rows: list[Epic], f: epics.Filters, spec: str) -> Any:
    """The chips, a filter per remaining column, and the hidden current sort."""
    return Form(
        status_chips(rows, f),
        epic_filter_fields(rows, f),
        # Updated out of band by every response, so a header click and a dropdown change
        # each keep what the other chose.
        Input(type="hidden", name="sort", value=spec, id="epic-sort"),
        Div(
            Button("Apply", type="submit"),
            A("Clear", href=epics_page, role="button", cls="secondary outline"),
            Button(
                "Refresh from monday.com",
                type="button",
                cls="secondary outline",
                hx_get=epic_table_rows.to(refresh=1, fields=1),
                hx_include="#epic-filters",
                hx_target="#epic-table",
                hx_swap="outerHTML",
                hx_indicator="#epic-filters",
            ),
            Small(" loading…", id="spinner"),
            cls="actions",
        ),
        hx_get=epic_table_rows,
        hx_target="#epic-table",
        hx_swap="outerHTML",
        hx_trigger="change, search, submit, input changed delay:400ms from:input[name=search]",
        hx_indicator="closest form",
        id="epic-filters",
    )


@rt("/epics")
def epics_page(
    search: str = "",
    status: str = "",
    owner: str = "",
    dam: str = ANY_PORTFOLIO,
    bucket: str = "",
    stuck: bool = False,
    dropped: bool = False,
    sort: str = epics.DEFAULT_SORT,
) -> Any:
    """Every epic, sortable on every column and filterable on the ones worth filtering.

    The table arrives on its own request (`hx_trigger="load"`) because the first fetch
    reads both sprint boards end to end — a few thousand items — and a spinner beats a
    blank tab for twenty seconds.
    """
    f = epics.Filters(search=search, status=status, owner=owner, dam=dam, bucket=bucket, stuck=stuck, dropped=dropped)
    return page(
        "Epics",
        lede("Story points per epic, summed from the active and the done sprint board."),
        epic_filters(_EPICS, f, sort),
        Div(
            P(Small("Loading the epic board…"), aria_busy="true"),
            id="epic-table",
            hx_get=epic_table_rows.to(**{"sort": sort, "fields": 1, **_set(f)}),
            hx_trigger="load",
            hx_swap="outerHTML",
        ),
    )


def _set(f: epics.Filters | portfolio.Filters) -> dict[str, str]:
    """Only the filters that are actually set, so the load URL stays readable.

    Read off the dataclass itself rather than re-listing its fields, so a new filter
    survives the deferred `hx_trigger="load"` request without a second edit here — the
    one place that only a cold page load would have caught.
    """
    return {k: ("1" if v is True else str(v)) for k, v in asdict(f).items() if v}


@rt
def epic_table_rows(
    search: str = "",
    status: str = "",
    owner: str = "",
    dam: str = ANY_PORTFOLIO,
    bucket: str = "",
    stuck: bool = False,
    dropped: bool = False,
    sort: str = epics.DEFAULT_SORT,
    resort: str = "",
    refresh: int = 0,
    fields: int = 0,
) -> Any:
    """The table on its own: the target of every sort click and every filter change.

    `sort` rides in from the form's hidden field and `resort` from a clicked header, so
    the two never collide; the header wins, and the fresh value is swapped back into the
    form out of band. The status chips come back with every response, because their
    counts depend on the other filters.
    """
    spec = resort or sort
    try:
        rows, orphans = epic_cache(refresh=bool(refresh))
    except FETCH_ERRORS as exc:
        return Div(error(exc, id="epic-table"), id="epic-table")

    f = epics.Filters(search=search, status=status, owner=owner, dam=dam, bucket=bucket, stuck=stuck, dropped=dropped)
    column, desc = epics.parse_sort(spec)
    shown = epics.arrange(rows, f, sort=column, desc=desc)
    out = [
        epic_table(shown, rows, orphans, spec),
        Input(type="hidden", name="sort", value=spec, id="epic-sort", hx_swap_oob="true"),
        status_chips(rows, f)(hx_swap_oob="true"),
    ]
    if fields:
        out.append(epic_filter_fields(rows, f)(hx_swap_oob="true"))
    return tuple(out)


# --- the portfolio page -----------------------------------------------------------------
# The IV Portfolio board with the epics grouped under it. Two views of one dataset: the
# overview, which is the epics table's numbers added up per portfolio item, and a detail
# page per item listing the epics themselves.
#
# The link only exists on the epic side, so both views are `portfolio.attach` over the
# cached epic board — see `portfolio_cache`. Nothing here reads a board the Epics page
# does not already read, apart from one cheap request for the portfolio items themselves.

#: Column key -> heading. The order here is the order of the table.
PORTFOLIO_COLUMNS = (
    ("name", "Item"),
    ("stuck", "Stuck"),
    ("goal", "Doelstelling"),
    ("type", "Type"),
    ("urgency", "Urgentie"),
    ("lead", "Projectleider"),
    ("epics", "Epics"),
    ("done", "STP done"),
    ("remaining", "STP left"),
    ("progress", "Progress"),
)


def portfolio_cache(refresh: bool = False) -> tuple[list[PortfolioItem], list[Epic]]:
    """The portfolio items with their epics attached, and the epic rows behind them.

    The board itself is one request and 177 rows; the *epics* are the twenty-second read,
    and they are already cached for the Epics page. So the two halves are cached apart
    and joined on every request — cheap, and it keeps them from drifting when one of
    them is refreshed.
    """
    rows, _ = epic_cache(refresh=refresh)
    if refresh or not _PORTFOLIO:
        with MondayClient() as client:
            _PORTFOLIO[:] = portfolio.fetch_items(client)
    return portfolio.attach(_PORTFOLIO, rows), rows


def portfolio_sort_header(column: str, heading: str, spec: str) -> Any:
    """The portfolio table's version of `sort_header`."""
    current, desc = portfolio.parse_sort(spec)
    return sort_header(
        heading,
        active=column == current,
        desc=desc,
        rows=portfolio_table_rows.to(resort=portfolio.next_sort(column, spec)),
        at="portfolio",
        cls=column if column in ("goal", "lead") else "tight" if column != "name" else None,
    )


def portfolio_row(item: PortfolioItem) -> Any:
    """One portfolio item. The name is the way in — its epics are a page of their own."""
    return Tr(
        Td(A(item.name, href=portfolio_item.to(item=item.id)), cls="item"),
        Td(portfolio_stuck_cell(item), cls="tight"),
        Td(item.goal, cls="goal"),
        Td(item.type, cls="tight"),
        Td(chart.urgency_tag(item.urgency), cls="tight"),
        Td(item.lead or Span("—", style="opacity:.5"), cls="lead"),
        Td(str(len(item.epics)) if item.epics else "", cls="num tight"),
        Td(bd.fmt(item.done) if item.done else "", cls="num tight"),
        Td(bd.fmt(item.remaining) if item.remaining else "", cls="num tight"),
        Td(chart.battery(item.done, item.remaining), cls="tight progress"),
    )


def portfolio_summary(shown: list[PortfolioItem], everything: list[PortfolioItem], orphans: list[Epic]) -> Any:
    """What the selection adds up to, and the epics it could not place.

    An epic pointing at a portfolio item this board did not return is reported here for
    the same reason the Epics page reports tasks with no epic: the points are real and
    they are in none of the rows above.
    """
    total = portfolio.totals(shown)
    linked = sum(len(item.epics) for item in shown)
    stuck = sum(1 for item in shown if item.is_stuck)
    tiles = [
        chart.tile("Portfolio items", str(len(shown)), f"of {len(everything)} on the board · {linked} epics"),
        *chart.points_tiles(total),
    ]
    if stuck:
        tiles.append(chart.tile("Stuck", str(stuck), "have a blocked epic", "tone-critical"))
    tiles.append(chart.progress_tile(total))
    note = None
    if orphans:
        points = sum(e.total for e in orphans)
        note = P(
            Small(
                f"{len(orphans)} epics ({bd.fmt(points)} points) name a portfolio item the "
                "IV Portfolio board did not return, and are in none of these rows.",
                style="opacity:.7",
            )
        )
    return Div(Div(*tiles, cls="kpis"), note, cls="epic-head")


def portfolio_table(shown: list[PortfolioItem], everything: list[PortfolioItem], orphans: list[Epic], spec: str) -> Any:
    """The table, header included: the one thing a sort or a filter swaps."""
    if not everything:
        body: Any = P("The IV Portfolio board came back empty.")
    elif not shown:
        body = P("No portfolio items match these filters.")
    else:
        body = Div(
            Table(
                Caption("Click an item to see its epics.", cls="hint"),
                Thead(Tr(*[portfolio_sort_header(key, heading, spec) for key, heading in PORTFOLIO_COLUMNS])),
                Tbody(*[portfolio_row(item) for item in shown]),
                cls="epics portfolio",
            ),
            cls="table-wrap",
        )
    return Div(portfolio_summary(shown, everything, orphans), body, cls="viz", id="portfolio-table")


def portfolio_filter_fields(rows: list[PortfolioItem], f: portfolio.Filters) -> Any:
    """The dropdowns, built from the rows actually fetched — so no choice comes back empty.

    Swapped in out of band once, with the first table, for the same reason the Epics
    page does it: re-rendering them on every keystroke takes the caret out of the search box.
    """
    return Div(
        Label(
            "Item",
            Input(
                type="search",
                name="search",
                value=f.search,
                placeholder="Search portfolio items…",
                aria_label="Search portfolio item titles",
            ),
        ),
        filter_select("goal", "Doelstelling", "Any doelstelling", portfolio.options(rows, "goal"), f.goal),
        filter_select("type", "Type", "Any type", portfolio.options(rows, "type"), f.type),
        filter_select("urgency", "Urgentie", "Any urgentie", portfolio.options(rows, "urgency"), f.urgency),
        filter_select("lead", "Projectleider", "Anyone", portfolio.options(rows, "lead"), f.lead),
        Label(
            "Progress",
            Select(
                Option("Any progress", value="", selected=not f.bucket),
                *[Option(label, value=value, selected=value == f.bucket) for value, label in portfolio.BUCKETS.items()],
                name="bucket",
            ),
        ),
        Label(
            Input(type="checkbox", name="stuck", role="switch", checked=f.stuck),
            "Only stuck",
            cls="switch",
            title="Portfolio items with an epic on Impediment, or with a task that is",
        ),
        Label(
            Input(type="checkbox", name="empty", role="switch", checked=f.empty),
            "Show unlinked",
            cls="switch",
            title="166 of the 177 items have no epic linked and therefore no progress to show",
        ),
        cls="filters",
        id="portfolio-filter-fields",
    )


def portfolio_filters(rows: list[PortfolioItem], f: portfolio.Filters, spec: str) -> Any:
    """A filter per column worth filtering on, and the hidden current sort."""
    return Form(
        portfolio_filter_fields(rows, f),
        # Updated out of band by every response, so a header click and a dropdown change
        # each keep what the other chose.
        Input(type="hidden", name="sort", value=spec, id="portfolio-sort"),
        Div(
            Button("Apply", type="submit"),
            A("Clear", href=portfolio_page, role="button", cls="secondary outline"),
            Button(
                "Refresh from monday.com",
                type="button",
                cls="secondary outline",
                hx_get=portfolio_table_rows.to(refresh=1, fields=1),
                hx_include="#portfolio-filters",
                hx_target="#portfolio-table",
                hx_swap="outerHTML",
                hx_indicator="#portfolio-filters",
            ),
            Small(" loading…", id="spinner"),
            cls="actions",
        ),
        hx_get=portfolio_table_rows,
        hx_target="#portfolio-table",
        hx_swap="outerHTML",
        hx_trigger="change, search, submit, input changed delay:400ms from:input[name=search]",
        hx_indicator="closest form",
        id="portfolio-filters",
    )


@rt("/portfolio")
def portfolio_page(
    search: str = "",
    goal: str = "",
    type: str = "",
    urgency: str = "",
    lead: str = "",
    bucket: str = "",
    stuck: bool = False,
    empty: bool = False,
    sort: str = portfolio.DEFAULT_SORT,
) -> Any:
    """Every IV Portfolio item with the epics under it burnt down.

    The table arrives on its own request for the same reason the Epics page's does: a
    cold cache means reading the epic board and both sprint boards.
    """
    f = portfolio.Filters(
        search=search, goal=goal, type=type, urgency=urgency, lead=lead, bucket=bucket, stuck=stuck, empty=empty
    )
    return page(
        "Portfolio",
        lede("The IV Portfolio board: story points per portfolio item, summed over the epics linked to it."),
        portfolio_filters(portfolio.attach(_PORTFOLIO, _EPICS), f, sort),
        Div(
            P(Small("Loading the portfolio…"), aria_busy="true"),
            id="portfolio-table",
            hx_get=portfolio_table_rows.to(**{"sort": sort, "fields": 1, **_set(f)}),
            hx_trigger="load",
            hx_swap="outerHTML",
        ),
    )


@rt
def portfolio_table_rows(
    search: str = "",
    goal: str = "",
    type: str = "",
    urgency: str = "",
    lead: str = "",
    bucket: str = "",
    stuck: bool = False,
    empty: bool = False,
    sort: str = portfolio.DEFAULT_SORT,
    resort: str = "",
    refresh: int = 0,
    fields: int = 0,
) -> Any:
    """The table on its own: the target of every sort click and every filter change."""
    spec = resort or sort
    try:
        rows, epic_rows = portfolio_cache(refresh=bool(refresh))
    except FETCH_ERRORS as exc:
        return Div(error(exc, id="portfolio-table"), id="portfolio-table")

    f = portfolio.Filters(
        search=search, goal=goal, type=type, urgency=urgency, lead=lead, bucket=bucket, stuck=stuck, empty=empty
    )
    column, desc = portfolio.parse_sort(spec)
    shown = portfolio.arrange(rows, f, sort=column, desc=desc)
    out = [
        portfolio_table(shown, rows, portfolio.orphan_epics(rows, epic_rows), spec),
        Input(type="hidden", name="sort", value=spec, id="portfolio-sort", hx_swap_oob="true"),
    ]
    if fields:
        out.append(portfolio_filter_fields(rows, f)(hx_swap_oob="true"))
    return tuple(out)


# --- one portfolio item -----------------------------------------------------------------
# The epics under a single item. The same numbers as the overview row, opened up: the
# epics are the rows and the item's own fields sit above them.

#: The epic columns on the detail page. No Portfolio column — every row shares it — and
#: no sorting: the order is fixed at "blocked first, then most work left".
DETAIL_COLUMNS = ("Epic", "Status epic", "Stuck", "Trekker", "Priority", "STP done", "STP left", "Progress")


#: The schemes an `href` out of the boards may carry. Every other link on these pages
#: is built by `config.item_url`, but the IV Portfolio's Fortes link is a free-text
#: column typed by hand — and a `javascript:` URL in an anchor runs in this page's own
#: origin, so an address we do not recognise is shown as text rather than linked.
LINK_SCHEMES = ("https://", "http://")


def external_link(text: str, url: str) -> Any:
    """`text` as a link out to `url`, or as plain text when `url` is not a web address."""
    if not url.lower().startswith(LINK_SCHEMES):
        return text
    return A(text, href=url, target="_blank", rel="noopener")


def portfolio_meta(item: PortfolioItem) -> Any:
    """The item's own fields, as a row of labelled facts rather than a second table."""
    facts = [
        ("Doelstelling", item.goal),
        ("Type", item.type),
        ("Urgentie", chart.urgency_tag(item.urgency) if item.urgency else ""),
        ("Projectleider", item.lead),
        ("Start", item.start),
        ("Einddatum", item.end),
        ("Fortes", external_link(item.ref or "open", item.link) if item.link else ""),
        ("monday.com", A("open the item", href=item.url, target="_blank", rel="noopener")),
    ]
    return Div(*[Div(Small(label), Span(value), cls="fact") for label, value in facts if value], cls="meta")


def portfolio_epic_row(epic: Epic) -> Any:
    """One epic under a portfolio item — the epics table's row, minus the shared column."""
    return Tr(
        Td(A(epic.name, href=epic.url, target="_blank", rel="noopener"), cls="item"),
        Td(chart.status_tag(epic.status), cls="tight"),
        Td(stuck_cell(epic), cls="tight"),
        Td(chart.people(epic.owner, photo_for), cls="owner"),
        Td(chart.priority_tag(epic.priority), cls="tight"),
        Td(bd.fmt(epic.done) if epic.done else "", cls="num tight"),
        Td(bd.fmt(epic.remaining) if epic.remaining else "", cls="num tight"),
        Td(chart.battery(epic.done, epic.remaining), cls="tight progress"),
    )


def portfolio_detail(item: PortfolioItem) -> Any:
    """One portfolio item: what it is, how far it is, and every epic under it."""
    total = item.points
    tiles = [
        chart.tile("Epics", str(len(item.epics)), "linked to this item"),
        *chart.points_tiles(total),
    ]
    if item.is_stuck:
        tiles.append(chart.tile("Stuck", str(len(item.stuck_epics)), portfolio_stuck_cell(item), "tone-critical"))
    tiles.append(chart.progress_tile(total))

    if item.epics:
        body: Any = Div(
            Table(
                Caption("Blocked epics first, then the most work left.", cls="hint"),
                Thead(Tr(*[Th(h, cls=None if h == "Epic" else "tight") for h in DETAIL_COLUMNS])),
                Tbody(*[portfolio_epic_row(epic) for epic in item.epics]),
                cls="epics",
            ),
            cls="table-wrap",
        )
    else:
        body = P("No epics are linked to this portfolio item.")

    return Div(
        H2(item.name),
        portfolio_meta(item),
        Div(*tiles, cls="kpis"),
        body,
        cls="viz",
        id="portfolio-item",
    )


@rt
def portfolio_item(item: str = "") -> Any:
    """One portfolio item's page. The content arrives on its own request, behind a spinner."""
    return page(
        "Portfolio",
        lede("One portfolio item: the epics linked to it, their state, and their story points."),
        P(A("← All portfolio items", href=portfolio_page)),
        Div(
            P(Small("Loading the portfolio…"), aria_busy="true"),
            id="portfolio-item",
            hx_get=portfolio_item_view.to(item=item),
            hx_trigger="load",
            hx_swap="outerHTML",
        ),
    )


@rt
def portfolio_item_view(item: str = "") -> Any:
    """The item itself, so the page can render its shell before the boards are read."""
    try:
        rows, _ = portfolio_cache()
    except FETCH_ERRORS as exc:
        return Div(error(exc, id="portfolio-item"), id="portfolio-item")
    found = next((row for row in rows if row.id == item), None)
    if found is None:
        return Div(
            P("No portfolio item with that id. ", A("Back to the portfolio", href=portfolio_page)),
            id="portfolio-item",
        )
    return portfolio_detail(found)


def run(host: str = "127.0.0.1", port: int = 5001, reload: bool = True) -> None:
    """Serve the app with uvicorn. Localhost by default — the API token lives here.

    With `reload`, uvicorn restarts on a code change and `fast_app(live=True)` pushes
    the browser to refresh itself, so an edit shows up without touching the server.
    """
    import uvicorn

    if reload:
        uvicorn.run("mondaycom.web:app", host=host, port=port, reload=True, reload_dirs=[str(SRC)])
    else:
        uvicorn.run(app, host=host, port=port)
