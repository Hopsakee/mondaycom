"""FastHTML web interface: the Sprint, Features, Portfolio and Planning pages.

The Sprint page is one read of the board's sprint group, shown four ways: headline
tiles, the burndown chart, a small burndown per person, and the task list with its
Obsidian markdown. The Features page (`/epics`) is every epic with its story points burnt down. The
Portfolio page is the IV Portfolio board with those epics grouped under it, as an
overview and a detail page per item. The library reference is mirrored under
docs/fasthtml/ — start with its README.md.

Every page wears the WDODelta huisstijl (`theme.py`) and speaks Dutch, and every page can
be read as a table or as cards (`cards.py`): the switch in the page head sets the
`weergave` cookie, which `WeergaveMiddleware` reads once per request for `as_cards()`.

Fetched rows are cached in module-level state (`_TASKS`, `_EPICS`, …) so that ticking a
checkbox or clicking a header re-renders locally instead of spending complexity budget
on monday.com again. Single user, single process, localhost.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from fasthtml import live_reload
from fasthtml.common import (
    H1,
    H2,
    H3,
    H4,
    A,
    Button,
    Caption,
    Code,
    Del,
    Details,
    Div,
    Fieldset,
    Form,
    Header,
    Input,
    Label,
    Legend,
    Li,
    Main,
    Nav,
    NotStr,
    Option,
    P,
    Pre,
    Script,
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
    Title,
    Tr,
    Ul,
    fast_app,
)
from fasthtml.pico import Group  # Pico-only layout helpers are not re-exported by `common`
from starlette.middleware import Middleware
from starlette.requests import HTTPConnection
from starlette.websockets import WebSocketDisconnect

from mondaycom import burndown as bd
from mondaycom import cards, chart, epics, lookups, planning, portfolio, sprint, theme
from mondaycom.cards import KAARTEN, TABEL
from mondaycom.client import MondayClient, MondayError
from mondaycom.config import ASSIGNED_TO_ME, DAM, DONE_STATUS, ME, NON_DAM, OPEN_STATUSES, as_date
from mondaycom.epics import Epic
from mondaycom.lookups import Choice
from mondaycom.portfolio import PortfolioItem
from mondaycom.sorting import Sorting
from mondaycom.sprint import Task

# Tasks from the last fetch, by monday.com item id, so the markdown route can re-render
# a selection without going back to monday.com.
_TASKS: dict[str, Task] = {}

# The sprint group from the last read — see `sprint_cache`.
_SPRINT: list[list[bd.SprintItem]] = []

# The people dropdown changes rarely and costs a query, so it is fetched once.
_PEOPLE: list[Choice] = []

# The epics overview costs six requests and a couple of thousand items, so it is fetched
# once and then sorted and filtered in Python. "Refresh" is the way to re-read it.
_EPICS: list[Epic] = []
_ORPHANS = epics.Points()

# The IV Portfolio board: one cheap request, but its epics come from `_EPICS`, so the
# two are joined on every request rather than stored joined — see `portfolio_cache`.
_PORTFOLIO: list[PortfolioItem] = []

# The epic board without its points, for the Sprint page's DAM and "Dit kwartaal"
# filters when `_EPICS` is cold — see `epic_rows`.
_EPIC_ROWS: list[Epic] = []

# The three planning boards and the two sprint groups, read once (~8s). Every date and
# layer a user tries is a re-plan of this, not another read; "Refresh" re-reads it.
_PLANNING: list[planning.Snapshot] = []

# Sentinels for the two "do not filter" dropdown options.
EVERYONE = "all"
ALL_EPICS = "all"

# "Do not filter on the portfolio at all", alongside config.DAM / config.NON_DAM.
ANY_PORTFOLIO = ""
PORTFOLIO_LABELS = ((ANY_PORTFOLIO, "Beide"), (DAM, "Alleen DAM"), (NON_DAM, "Alleen niet-DAM"))

#: The app's name in the brand bar and the browser tab.
APP_NAME = "Datalab sprintbord"

FETCH_ERRORS = (MondayError, ValueError, RuntimeError, OSError)


# The one client every route shares — see `monday_client`.
_CLIENT: list[MondayClient] = []
_CLIENT_LOCK = threading.Lock()


def monday_client() -> MondayClient:
    """The one client every route shares, made on first use and kept for the process.

    A client per route was a fresh TLS handshake per page render and filter change. The
    lock keeps two cold requests from making two; `close_client` runs on shutdown.
    """
    with _CLIENT_LOCK:
        if not _CLIENT:
            _CLIENT.append(MondayClient())
        return _CLIENT[0]


def close_client() -> None:
    """Close the shared client's connections, if it was ever made. It stays usable."""
    with _CLIENT_LOCK:
        if _CLIENT:
            _CLIENT[0].close()


def people_choices() -> list[Choice]:
    """The people for the assignee dropdown, fetched once and then cached.

    A failure here must not cost you the page: the filter just falls back to
    "Me" and "Everyone", which is what the CLI does anyway.
    """
    if not _PEOPLE:
        with suppress(*FETCH_ERRORS):
            _PEOPLE[:] = lookups.fetch_people(monday_client())
    return _PEOPLE


def dam_epics() -> set[str]:
    """The epic ids with a portfolio link, fetched once. Empty on failure, which the
    caller reports as "cannot tell DAM from non-DAM" rather than as an empty result.

    The Epics page's cache already carries every epic and its portfolio link, so when it
    is warm the answer is a filter over rows we have rather than a second read of the
    same board — that read is ~6s and it is on the Sprint page's request path.
    """
    return {epic.id for epic in epic_rows() if epic.is_dam}


def epic_rows() -> list[Epic]:
    """Every epic with its portfolio link and due date: the Features page's cache when it
    is warm, otherwise one read of the epic board without the points (~6s), kept."""
    if _EPICS:
        return _EPICS
    if not _EPIC_ROWS:
        _EPIC_ROWS[:] = epics.fetch_epic_rows(monday_client())
    return _EPIC_ROWS


def quarter_end(sprint_end: date | None = None) -> date:
    """The last day "Dit kwartaal" counts, on every page: `planning.this_quarter_end` of
    the current sprint, so the Sprint, Features and Portfolio pages mean the quarter the
    Planning page plans. The planning's cached read knows the sprint's end; otherwise the
    sprint group does."""
    if sprint_end is None:
        sprint_end = _PLANNING[0].current_end if _PLANNING else bd.sprint_window(sprint_cache())[1]
    return planning.this_quarter_end(sprint_end)


def due_epic_ids(day: date) -> frozenset[str]:
    """The epics due on or before `day`. No due date is never due."""
    return frozenset(epic.id for epic in epic_rows() if epic.due_by(day))


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
        raise ValueError(f"Onbekende persoon {person!r}. Kies iemand uit de lijst.")
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
#spinner { display: none; color: var(--muted); }
/* One tight actions row rather than a full-width primary button. */
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; margin-top: .6rem; }
.actions button, .actions [role="button"] { width: auto; margin-bottom: 0; }
.section-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: .4rem 1.25rem; margin: 2rem 0 .6rem; }
.section-head h3 { margin-bottom: 0; font-size: 1.2rem; }
.section-head small { color: var(--muted); }
#sprint > h2, #planning > h2, #portfolio-item > h2 { margin-top: .4rem; }
.lede-scope { color: var(--muted); margin-top: -.2rem; }
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
th button.sort:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
th button.sort .arrow { opacity: .45; font-size: .8em; }
th button.sort[aria-sort] .arrow { opacity: 1; }

/* The epic filters in one block: a grid, so they stay compact and line up as the
   window changes, rather than rows of full-width Pico groups. */
.filters { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: .1rem .8rem;
           align-items: end; }
.filters label:first-child { grid-column: span 2; }
.filters label.switch { padding-bottom: .9rem; }
#epic-filters input, #epic-filters select { margin-bottom: .2rem; }
/* A date field: the ISO text and a calendar button in one control. The native picker is
   kept, invisible, under the button — only for the calendar it opens. */
.date-field { position: relative; display: flex; gap: .35rem; align-items: stretch;
              margin-bottom: var(--pico-spacing); }  /* the margin Pico gives every other input */
.date-field input[type=text] { flex: 1; margin-bottom: 0; font-variant-numeric: tabular-nums; }
.date-field input.date-picker { position: absolute; right: 0; bottom: 0; width: 1px; height: 1px; padding: 0;
                                margin: 0; border: 0; opacity: 0; pointer-events: none; }
.date-field button.date-button { width: auto; margin: 0; padding: 0 .65rem; background: var(--surface);
                                 border: 1px solid var(--line); color: var(--ink); }
.date-field button.date-button:hover { border-color: var(--accent); }
.markdown-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem;
                 margin: 1.5rem 0 .4rem; }
.markdown-head h3 { margin: 0; font-size: 1.1rem; }
.markdown-head button { width: auto; margin: 0; }
#markdown-block pre { border: 1px solid var(--line); box-shadow: var(--shadow); }

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
.meta { display: flex; flex-wrap: wrap; gap: .5rem 1.75rem; margin: -.2rem 0 1rem; }
.meta .fact small { display: block; color: var(--text-muted); font-size: .75rem; line-height: 1.3; }
.meta .fact span { font-size: .9rem; }

/* The planning page: the window row, and the tables. The epic queue is the longest. */
.back { margin: -.4rem 0 .8rem; font-size: .9rem; }
#planning-filters .filters { grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); }
#planning-filters .filters label:first-child { grid-column: auto; }
#planning-filters fieldset.layers { display: flex; flex-wrap: wrap; gap: .2rem 1rem; align-items: center;
                                    margin: 0; padding-bottom: .9rem; border: 0; }
#planning-filters fieldset.layers legend { font-size: .9rem; padding: 0; margin-bottom: .2rem; }
#planning > h2 { margin-top: 1.5rem; }
table.plan { min-width: 56rem; }
table.plan td.split { color: var(--text-secondary); font-size: .8rem; white-space: nowrap; }
table.plan td.finish small { display: block; color: var(--text-muted); font-size: .75rem; }
table.plan tr.layer-start td { border-top: 2px solid var(--hairline); }
ul.left-out { font-size: .88rem; columns: 2 26rem; }
ul.left-out li { break-inside: avoid; }
ul.left-out small { color: var(--text-muted); margin-left: .4rem; }
/* The page's own documentation: closed by default, a readable column when opened. */
details.how { margin: .2rem 0 1rem; }
details.how > summary { color: var(--pico-primary); font-size: .92rem; }
details.how > div { max-width: 52rem; font-size: .9rem; }
details.how h4 { font-size: .95rem; margin: 1rem 0 .3rem; }
details.how p, details.how ul { margin-bottom: .5rem; }
table.help td { padding: .3rem .5rem; vertical-align: top; font-size: .88rem; }
table.help td:first-child { white-space: nowrap; }
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
    this.textContent = 'Gekopieerd';
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

# `this` is one half of the view switch. The cookie is what the routes read; the page's
# own filter form then re-asks for its section, so the switch costs a re-render from the
# cache rather than a reload. A page without such a form (one portfolio item) reloads.
WEERGAVE_JS = """
function setWeergave(btn) {
  const v = btn.dataset.weergave;
  document.cookie = 'weergave=' + v + '; path=/; max-age=31536000; samesite=lax';
  btn.parentElement.querySelectorAll('button')
    .forEach(b => b.setAttribute('aria-pressed', b === btn ? 'true' : 'false'));
  const f = document.querySelector('form[data-refilter]');
  if (f) htmx.trigger(f, 'change'); else location.reload();
}
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

#: The view this request asked for — see `WeergaveMiddleware`.
_WEERGAVE: ContextVar[str] = ContextVar("weergave", default=TABEL)


class WeergaveMiddleware:
    """Reads the `weergave` cookie once per request, so no route or helper has to carry it.

    A plain ASGI middleware rather than Beforeware: it runs in the request's own context,
    which the thread a sync handler runs in inherits — a value set in Beforeware does not
    reach it. Anything but `kaarten` is the table.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            _WEERGAVE.set(KAARTEN if HTTPConnection(scope).cookies.get("weergave") == KAARTEN else TABEL)
        await self.app(scope, receive, send)


def as_cards() -> bool:
    """Whether this request shows cards rather than tables."""
    return _WEERGAVE.get() == KAARTEN


app, rt = fast_app(
    title=APP_NAME,
    live=LIVE,
    hdrs=(
        theme.theme_script(),
        Script(WEERGAVE_JS),
        Style(theme.THEME_CSS),
        Style(chart.CHART_CSS),
        Style(cards.CARDS_CSS),
        Style(CSS),
    ),
    # Light is the huisstijl default; the brand bar's switch makes it dark.
    htmlkw={"lang": "nl", "data-theme": "light"},
    middleware=[Middleware(WeergaveMiddleware)],
    on_shutdown=[close_client],
)


#: The two halves of the view switch: value, label, a small icon in the label's colour.
WEERGAVEN = (
    (TABEL, "Tabel", "M2 3h12v2H2zm0 4h12v2H2zm0 4h12v2H2z"),
    (KAARTEN, "Kaarten", "M2 2h5v5H2zm7 0h5v5H9zM2 9h5v5H2zm7 0h5v5H9z"),
)


def view_switch() -> Any:
    """Table or cards. Every page carries it, and it remembers the choice for all of them."""
    weergave = _WEERGAVE.get()
    return Div(
        *[
            Button(
                NotStr(f'<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="{icon}"/></svg>'),
                label,
                type="button",
                data_weergave=value,
                aria_pressed="true" if value == weergave else "false",
                onclick="setWeergave(this)",
            )
            for value, label, icon in WEERGAVEN
        ],
        cls="seg",
        role="group",
        aria_label="Weergave",
        title="Bekijk deze pagina als tabel of als kaarten",
    )


def page(title: str, about: str, *content: Any) -> Any:
    """Every page: the brand bar, the title with its lede and the view switch, the tabs
    with the current page marked, the route's content, and the footer."""
    links = (("Sprint", index), ("Features", epics_page), ("Portfolio", portfolio_page), ("Planning", planning_page))
    return (
        Title(f"{title} · {APP_NAME}"),
        theme.brandbar(APP_NAME),
        Main(
            Header(
                Div(H1(title), P(about, cls="lede")),
                view_switch(),
                cls="page-head",
            ),
            Nav(
                Ul(
                    *[
                        Li(A(label, href=target, aria_current="page" if label == title else None))
                        for label, target in links
                    ]
                ),
                cls="tabs",
                aria_label="Pagina's",
            ),
            *content,
            cls="container page",
        ),
        theme.site_footer(),
    )


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
        Option("Alle epics", value=ALL_EPICS, selected=selected == ALL_EPICS),
        *[Option(c.name, value=c.id, selected=c.id == selected) for c in choices],
        name="epic",
        id="epic-select",
    )


def person_select(selected: str = ASSIGNED_TO_ME) -> Any:
    """The assignee dropdown. "Assigned to" means the Trekker; reviewing does not count."""
    return Select(
        Option("Ik", value=ASSIGNED_TO_ME, selected=selected == ASSIGNED_TO_ME),
        Option("Iedereen", value=EVERYONE, selected=selected == EVERYONE),
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
    word = "taak" if tasks == 1 else "taken"
    if epic.is_blocked and tasks:
        return f"epic + {tasks} {word}"
    return "epic" if epic.is_blocked else f"{tasks} {word}"


def stuck_cell(epic: Epic) -> Any:
    """The Stuck column of an epics table: empty when it runs, a marker you can open when not.

    The epic itself is always the first link, so the disclosure has somewhere to go even
    when the block is the epic's own status and no task carries it.
    """
    if not epic.is_stuck:
        return ""
    on_monday = "Status epic: Impediment" if epic.is_blocked else "de epic op monday.com"
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
        Summary(chart.stuck_tag(f"{epics_word(len(blocked))} vast")),
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


#: "Dit kwartaal" on the pages other than the planning (`planning.THIS_QUARTER_HELP_NL`):
#: the same quarter end, the same rule that an epic without a due date drops out.
THIS_QUARTER_SPRINT = (
    "Alleen taken op een epic met een Due date op of vóór het kwartaaleinde dat de Planning gebruikt. "
    "Taken zonder epic, of op een epic zonder due date, vallen af."
)
THIS_QUARTER_FEATURES = (
    "Alleen epics met een Due date op het epic-bord op of vóór het kwartaaleinde dat de Planning gebruikt. "
    "Epics zonder due date vallen af."
)
THIS_QUARTER_PORTFOLIO = (
    "Onder elk item tellen alleen de epics met een Due date op of vóór het kwartaaleinde dat de Planning "
    "gebruikt. Een item zonder zo'n epic valt af, tenzij “Toon ongekoppelde” aan staat."
)


#: `this` is a date field's hidden native picker: write the picked date into the text
#: field as ISO. Its own `change` then bubbles to the form, which asks for the section.
DATE_PICKED_JS = "this.parentElement.querySelector('input[type=text]').value = this.value"


def date_field(name: str, value: str, id: str | None = None) -> Any:
    """A date as the page writes it everywhere, `2026-12-31`, with a calendar button.

    Not a bare `<input type="date">`: that one *shows* its value in the browser's locale
    (09/28/2026 on an English browser) whatever the page asks for. The text field is what
    is submitted and must read `JJJJ-MM-DD` (the browser blocks the request otherwise);
    the native picker sits hidden behind the button only for its calendar.
    """
    return Span(
        Input(
            type="text",
            name=name,
            value=value,
            inputmode="numeric",
            pattern=r"\d{4}-\d{2}-\d{2}",
            placeholder="JJJJ-MM-DD",
            title="Een datum als JJJJ-MM-DD, bijvoorbeeld 2026-12-31",
            autocomplete="off",
        ),
        Input(type="date", value=value, tabindex="-1", aria_hidden="true", cls="date-picker", onchange=DATE_PICKED_JS),
        Button(
            "📅",
            type="button",
            cls="date-button",
            aria_label="Kies een datum in de kalender",
            onclick="this.parentElement.querySelector('.date-picker').showPicker()",
        ),
        cls="date-field",
        id=id,
    )


def sprint_end_field(end: str) -> Any:
    """The sprint's end date. It shows the window actually in use, not a blank."""
    return date_field("end", end, id="sprint-end")


def refresh_button(route: Any, form: str, target: str) -> Any:
    """Re-read the page's boards: `route` with `refresh` on it, sent with the `form`'s
    filters so the fresh read comes back in the same slice, swapped over `target`."""
    return Button(
        "Opnieuw ophalen van monday.com",
        type="button",
        cls="secondary outline",
        hx_get=route,
        hx_include=form,
        hx_target=target,
        hx_swap="outerHTML",
        hx_indicator=form,
    )


def sprint_controls(
    end: str, person: str, choices: list[Choice], epic: str, dam: str, open_only: bool, this_quarter: bool
) -> Any:
    """The filter row: sprint end, who, which epic, portfolio, whether to drop Done, and
    whether to keep only work on epics due this quarter."""
    return Form(
        Fieldset(
            Group(
                Label("Einde sprint", sprint_end_field(end)),
                Label("Toegewezen aan", person_select(person)),
            ),
            Group(
                Label("Epic", epic_select(choices, epic)),
                Label("Portfolio", portfolio_select(dam)),
            ),
            switch("open_only", "Alleen open taken (Done valt uit de lijst)", open_only, ""),
            switch("this_quarter", "Dit kwartaal", this_quarter, THIS_QUARTER_SPRINT),
        ),
        Div(
            Button("Bijwerken", type="submit"),
            refresh_button(sprint_view.to(refresh=1), "#sprint-filters", "#sprint"),
            Small(" laden…", id="spinner"),
            cls="actions",
        ),
        hx_get=sprint_view,
        hx_target="#sprint",
        hx_swap="outerHTML",
        hx_trigger="change, submit",
        hx_indicator="closest form",
        id="sprint-filters",
        cls="panel",
        data_refilter="1",
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
                aria_label=f"Neem {task.name} op in de markdown",
            ),
            cls="tight",
        ),
        Td(Del(task.name) if done else task.name),
        Td(Span("🤝", title="Reviewwerk") if task.is_reviewer else "", cls="tight"),
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
            Input(type="checkbox", checked=True, onclick=TOGGLE_ALL_JS, aria_label="Selecteer alle taken"),
            cls="tight",
        ),
        Th("Taak"),
        Th(Span("🤝", title="Reviewwerk"), cls="tight", aria_label="Review"),
        Th("Trekker", cls="tight"),
        Th("Epic"),
        Th("Status", cls="tight"),
        Th("Tijd", cls="tight"),
        Th("Due", cls="tight"),
    )
    return task_form(
        end,
        Div(
            Table(
                Caption("Vink de taken aan die je wilt kopiëren. Doorgestreept is al Done.", cls="hint"),
                Thead(header),
                Tbody(*[task_row(task) for task in items]),
                cls="tasks",
            ),
            cls="table-wrap",
        ),
    )


def task_form(end: str, *content: Any) -> Any:
    """The selection form both task views sit in: any tick re-renders the markdown."""
    return Form(
        Input(type="hidden", name="end", value=end),
        *content,
        hx_get=markdown,
        hx_target="#markdown-block",
        hx_trigger="change",
    )


#: The sprint board's lanes, by the tone of a task's status: the same grouping the
#: status tags already wear, so a lane and the dot on its cards always agree.
LANES = (
    ("neutral", "Te doen"),
    ("active", "Bezig"),
    ("warning", "Wacht"),
    ("critical", "Geblokkeerd"),
    ("good", "Klaar"),
    ("off", "Vervallen"),
)


def task_card(task: Task) -> Any:
    """One task as a card on the sprint board. The card is its checkbox's label, so a click
    anywhere on it takes the task in or out of the markdown; an unticked card fades."""
    done = task.status == DONE_STATUS
    tone = chart.STATUS_TONES.get(task.status, "neutral")
    return Label(
        Input(
            type="checkbox",
            name="task_id",
            value=task.id,
            checked=True,
            aria_label=f"Neem {task.name} op in de markdown",
        ),
        Span(task.name, cls="t"),
        Div(
            chart.people(task.owner, photo_for) if task.owner else None,
            Span("🤝", title="Reviewwerk") if task.is_reviewer else None,
            cards.pill(f"{bd.fmt(task.story_points)} STP") if task.story_points else None,
            Span(f"📅 {task.due_date}") if task.due_date else None,
            Span(task.epic, title="Epic") if task.epic else None,
            cls="m",
        ),
        cls=f"taak tone-{tone} done" if done else f"taak tone-{tone}",
        title=task.status,
    )


def task_board(items: list[Task], end: str) -> Any:
    """The task picker as a board: one lane per state, a card per task."""
    lanes = []
    for tone, label in LANES:
        mine = [task for task in items if chart.STATUS_TONES.get(task.status, "neutral") == tone]
        if not mine:
            continue
        points = sum(task.story_points for task in mine)
        lanes.append(
            Div(
                Header(chart.tag(label, tone), Small(f"{len(mine)} · {bd.fmt(points)} STP")),
                *[task_card(task) for task in mine],
                cls="lane",
                aria_label=label,
            )
        )
    return task_form(
        end,
        Div(
            Label(
                Input(type="checkbox", checked=True, onclick=TOGGLE_ALL_JS, aria_label="Selecteer alle taken"),
                "Alles selecteren",
            ),
            Span("Klik op een kaart om hem in of uit de markdown te halen."),
            cls="kanban-tools",
        ),
        Div(*lanes, cls="kanban"),
    )


def markdown_block(text: str) -> Any:
    """The Obsidian markdown, plus a button that puts it on the clipboard."""
    return Div(
        Div(
            H3("Markdown voor Obsidian"),
            Button("Kopiëren", onclick=COPY_JS, cls="secondary outline"),
            cls="markdown-head",
        ),
        Pre(Code(text, id="markdown")),
        id="markdown-block",
    )


def task_summary(items: list[Task], own_points: int | None = None) -> Any:
    """The list's own totals. `own_points` is the share that counts for the person
    filtered on — spelled out, because the tiles above show that number and not this
    one whenever review work is in the list."""
    minutes = sum(task.duration_minutes for task in items)
    points = sum(task.story_points for task in items)
    tail = f" · {own_points} als Trekker" if own_points is not None and own_points != points else ""
    return Small(f"{len(items)} taken · {points} punten{tail} · {minutes} minuten")


def sprint_scope(person: str, dam: str, epic: str, kept: int, total: int, due: date | None = None) -> str:
    """A one-line description of what the sprint was narrowed to.

    Said out loud because a filtered burndown is easy to mistake for the sprint's, and
    "3 points behind" means something else per person. A person's slice also says that
    the numbers above it are the Trekker's, since the list below holds review work whose
    points belong to somebody else.
    """
    if kept == total and not person and not dam and not epic and not due:
        return ""
    parts = [person or "iedereen"]
    parts += [dam_label(dam).lower()] if dam_label(dam) else []
    if epic:
        parts.append(epic)
    if due:
        parts.append(f"epic due uiterlijk {due}")
    line = f"{' · '.join(parts)} — {kept} van {total} taken in de sprintgroep"
    return f"{line} · punten tellen alleen voor de Trekker" if person else line


def per_person(items: list[bd.SprintItem], end: str, window_from: list[bd.SprintItem]) -> list[Any]:
    """One small burndown per Trekker in `items`, the whole slice first.

    All on the group's window, each to its own scale: the question is "who is behind?",
    and a person with three points would be a flat line on the sprint's axis. These are
    points, so they are the Trekker's alone (`bd.owned`) — review work would count the
    same points twice and no card would add up.
    """
    shown = [chart.multiple(Strong("Iedereen"), bd.build(items, end=end or None, window_from=window_from))]
    for name in bd.people(items):
        mine = bd.owned(items, name)
        shown.append(
            chart.multiple(
                chart.person(name, photo_for(name)), bd.build(mine, end=end or None, window_from=window_from)
            )
        )
    return shown


def sprint_section(
    b: bd.Burndown,
    scope: str,
    multiples: list[Any],
    tasks: list[Task],
    own_points: int | None = None,
) -> Any:
    """Everything under the filters: tiles, chart, per-person charts, tasks, markdown.
    The cards view swaps the task table for a board; everything above it is the same."""
    end = str(b.end)
    picker = task_board if as_cards() else task_table
    return Div(
        H2(f"Sprint {b.start} – {b.end}"),
        P(Small(scope), cls="lede-scope") if scope else None,
        chart.kpis(b),
        Div(chart.legend(), chart.burndown_svg(b), cls="panel chart-panel"),
        Details(Summary("Dag voor dag"), chart.burndown_table(b)),
        Div(
            H3("Per persoon"),
            Small("elke Trekker in deze selectie · elke grafiek op eigen schaal, binnen de sprint"),
            cls="section-head",
        ),
        Div(*multiples, cls="multiples"),
        Div(H3("Taken"), task_summary(tasks, own_points), cls="section-head"),
        picker(tasks, end) if tasks else P("Geen taken in deze selectie."),
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


def sprint_cache(refresh: bool = False) -> list[bd.SprintItem]:
    """The sprint group, read on first use and then reused. `refresh` re-reads it.

    Every filter on the page is applied in Python to the same ~60 rows (the read
    carries no `query_params`), so a filter change re-reading them would fetch identical
    bytes. A page load and the "Refresh" button do re-read, so reloading is still how
    you see a task you just moved on monday.com.
    """
    if refresh or not _SPRINT:
        _SPRINT[:] = [bd.fetch_sprint_items(monday_client())]
    return _SPRINT[0]


def _sprint(
    end: str, person: str, epic: str, dam: str, open_only: bool, this_quarter: bool = False, refresh: bool = False
) -> SprintPage:
    """Take the group (from the cache unless `refresh`), narrow it, and render every view of it."""
    try:
        name = person_name(person)
        items = sprint_cache(refresh)
        dam_scope = frozenset(dam_epics() if dam else ())
        # "Dit kwartaal" keeps the tasks on an epic due by the quarter end; like the DAM
        # filter it scopes everything, and like it the epic board is only read when it is on.
        due_by = quarter_end(bd.sprint_window(items, end or None)[1]) if this_quarter else None
        due = due_epic_ids(due_by) if due_by else None
        # The epic list is built from the person's, the portfolio's and the quarter's
        # scope, so a pick can never come back empty; an epic that left it falls back to "all".
        in_scope = bd.narrow(items, person=name, dam=dam, dam_epics=dam_scope, due_epics=due)
        choices = epic_choices(in_scope)
        epic_id = epic if epic in {c.id for c in choices} else ""
        kept = bd.narrow(in_scope, epic=epic_id)
        # The list keeps the review work; the points do not. The window comes from the
        # whole group: one person's handful of tasks is far too small a sample to guess
        # the sprint's end date from.
        board = bd.build(bd.owned(kept, name), end=end or None, window_from=items)
        team = bd.narrow(items, dam=dam, dam_epics=dam_scope, epic=epic_id, due_epics=due)
        multiples = per_person(team, end, items)
    except FETCH_ERRORS as exc:
        return SprintPage(error(exc, id="sprint"), end, [])

    # The 🤝 marker means "this person reviews it", so it follows the person filter.
    listed = [item for item in kept if item.status in OPEN_STATUSES] if open_only else kept
    tasks = [item.as_task(me=name or ME) for item in listed]
    _TASKS.clear()
    _TASKS.update({task.id: task for task in tasks})

    epic_name = next((c.name for c in choices if c.id == epic_id), "")
    scope = sprint_scope(name, dam, epic_name, len(kept), len(items), due_by)
    own_points = int(sum(item.points for item in bd.owned(listed, name))) if name else None
    return SprintPage(sprint_section(board, scope, multiples, tasks, own_points), str(board.end), choices)


@rt
def index(
    end: str = "",
    person: str = ASSIGNED_TO_ME,
    epic: str = ALL_EPICS,
    dam: str = ANY_PORTFOLIO,
    open_only: bool = False,
    this_quarter: bool = False,
) -> Any:
    """The sprint: filters on top, then tiles, chart, per-person charts, tasks, markdown.
    A page load always reads the group afresh (`sprint_cache`)."""
    result = _sprint(end, person, epic, dam, open_only, this_quarter, refresh=True)
    return page(
        "Sprint",
        "De huidige sprintgroep: punten afgebrand, wie waar staat, en de taken als Obsidian-checkboxes.",
        sprint_controls(result.end, person, result.choices, epic, dam, open_only, this_quarter),
        result.view,
    )


@rt
def sprint_view(
    end: str = "",
    person: str = ASSIGNED_TO_ME,
    epic: str = ALL_EPICS,
    dam: str = ANY_PORTFOLIO,
    open_only: bool = False,
    this_quarter: bool = False,
    refresh: bool = False,
) -> Any:
    """The section under the filters, on its own, so a filter change swaps it in place.

    It narrows the cached group unless `refresh` (`sprint_cache`). The date field and the
    epic list ride along out of band: the first shows the window the group settled on,
    the second only offers epics in the new scope.
    """
    result = _sprint(end, person, epic, dam, open_only, this_quarter, refresh)
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

#: Column key, heading, header class. The order here is the order of the table.
EPIC_COLUMNS = (
    ("name", "Epic", None),
    ("status", "Status epic", "tight"),
    ("stuck", "Vast", "tight"),
    ("owner", "Trekker", "tight"),
    ("portfolio", "Portfolio", "portfolio"),
    ("priority", "Prioriteit", "tight"),
    ("done", "STP klaar", "tight"),
    ("remaining", "STP te gaan", "tight"),
    ("progress", "Voortgang", "tight"),
)


def epic_cache(refresh: bool = False) -> tuple[list[Epic], epics.Points]:
    """The epic board, fetched on first use and then reused. `refresh` re-reads it."""
    global _ORPHANS
    if refresh or not _EPICS:
        rows, orphans = epics.fetch_epics(monday_client())
        _EPICS[:] = rows
        _ORPHANS = orphans
        # The light rows are a view of this board, so they go stale with it.
        _EPIC_ROWS.clear()
    return _EPICS, _ORPHANS


@dataclass(frozen=True)
class TableView:
    """One overview table — the Epics page's or the Portfolio page's — described once,
    so the header, the table, the filter form and the partial route exist once each.

    `at` names every wrapper the page swaps: `#<at>-filters` (the form),
    `#<at>-table` (what a sort or filter replaces), `#<at>-sort` (the hidden spec) and
    `#<at>-filter-fields` (the dropdowns).
    """

    at: str
    title: str
    about: str
    loading: str
    sorting: Sorting
    #: Column key, heading, header class — in the table's order.
    columns: tuple[tuple[str, str, str | None], ...]
    #: `refresh` -> (every row, whatever the summary reports beside them).
    load: Callable[[bool], tuple[list[Any], Any]]
    #: (rows, filters, sort=, desc=) -> the rows shown, in order.
    arrange: Callable[..., list[Any]]
    row: Callable[[Any], Any]
    #: (rows, quarter end) -> the rows "Dit kwartaal" keeps.
    narrow: Callable[[list[Any], date], list[Any]]
    #: The same row as a card, for the cards view.
    card: Callable[[Any], Any]
    #: (shown, every row, the extra from `load`) -> the tiles above the table.
    summary: Callable[[list[Any], list[Any], Any], Any]
    #: (rows, filters) -> the filter controls, swapped in once with the first table.
    fields: Callable[[list[Any], Any], tuple[Any, ...]]
    rows_route: Any
    page_route: Any
    table_cls: str
    board_empty: str
    none_match: str
    caption: str | None = None
    #: (rows, filters) -> controls above the fields that come back with *every* response.
    chips: Callable[[list[Any], Any], Any] | None = None
    #: Wider cards, for rows that carry a list of their own (a portfolio item's epics).
    wide_cards: bool = False


def sort_button(view: TableView, column: str, heading: str, spec: str) -> Any:
    """One sort control: a submit-free button that asks for the next sort state.

    The direction lives in the URL and the filters ride along from the form, so the
    button needs no state of its own — see `sorting.Sorting.next`. A table heading and
    the cards view's sort row are the same button.
    """
    current, desc = view.sorting.parse(spec)
    active = column == current
    return Button(
        heading,
        Span(" ↓" if (active and desc) else " ↑" if active else " ↕", cls="arrow"),
        cls="sort",
        type="button",
        aria_sort=("descending" if desc else "ascending") if active else None,
        hx_get=view.rows_route.to(resort=view.sorting.next(column, spec)),
        hx_include=f"#{view.at}-filters",
        hx_target=f"#{view.at}-table",
        hx_swap="outerHTML",
        hx_indicator=f"#{view.at}-filters",
    )


def sort_header(view: TableView, column: str, heading: str, cls: str | None, spec: str) -> Any:
    """One sortable table heading."""
    return Th(sort_button(view, column, heading, spec), cls=cls)


def view_cards(view: TableView, shown: list[Any], spec: str) -> Any:
    """The cards view of the same rows, in the same order, with the headings as a sort row."""
    return Div(
        Div(
            Small("Sorteer op"),
            *[sort_button(view, key, heading, spec) for key, heading, _ in view.columns],
            cls="sortbar",
            aria_label="Sorteren",
        ),
        cards.grid((view.card(row) for row in shown), size="wide" if view.wide_cards else ""),
    )


def view_table(view: TableView, shown: list[Any], everything: list[Any], extra: Any, spec: str) -> Any:
    """The table (or the cards), header included: the one thing a sort or a filter swaps.

    Every response carries this `#<at>-table` wrapper, so everything that targets it
    swaps `outerHTML` — an innerHTML swap would nest a second wrapper inside the first.
    """
    if not everything:
        body: Any = P(view.board_empty)
    elif not shown:
        body = P(view.none_match)
    elif as_cards():
        body = view_cards(view, shown, spec)
    else:
        body = Div(
            Table(
                Caption(view.caption, cls="hint") if view.caption else None,
                Thead(Tr(*[sort_header(view, key, heading, cls, spec) for key, heading, cls in view.columns])),
                Tbody(*[view.row(row) for row in shown]),
                cls=view.table_cls,
            ),
            cls="table-wrap",
        )
    return Div(view.summary(shown, everything, extra), body, cls="viz", id=f"{view.at}-table")


def sort_field(view: TableView, spec: str) -> Any:
    """The current sort, hidden in the form. Every response swaps it out of band, so a
    header click and a dropdown change each keep what the other chose."""
    return Input(type="hidden", name="sort", value=spec, id=f"{view.at}-sort")


def filter_fields(view: TableView, rows: list[Any], f: Any) -> Any:
    """The view's filter controls, in the wrapper the first table swaps out of band."""
    return Div(*view.fields(rows, f), cls="filters", id=f"{view.at}-filter-fields")


def view_filters(view: TableView, f: Any, spec: str) -> Any:
    """The page shell's filter form: chips (if any), fields, and the hidden current sort.

    Built from *no* rows: it carries every filter's value, and the options and counts
    arrive with the first table — see `view_page`.
    """
    return Form(
        view.chips([], f) if view.chips else None,
        filter_fields(view, [], f),
        sort_field(view, spec),
        Div(
            Button("Toepassen", type="submit"),
            A("Wissen", href=view.page_route, role="button", cls="secondary outline"),
            refresh_button(view.rows_route.to(refresh=1, fields=1), f"#{view.at}-filters", f"#{view.at}-table"),
            Small(" laden…", id="spinner"),
            cls="actions",
        ),
        hx_get=view.rows_route,
        hx_target=f"#{view.at}-table",
        hx_swap="outerHTML",
        hx_trigger="change, search, submit, input changed delay:400ms from:input[name=search]",
        hx_indicator="closest form",
        id=f"{view.at}-filters",
        cls="panel",
        data_refilter="1",
    )


def view_page(view: TableView, f: Any, sort: str) -> Any:
    """The page shell: the filters, and the table deferred to its own `load` request,
    because a cold cache means reading the epic board and both sprint boards.

    The shell's controls are built from no rows, warm cache or cold; their options and
    counts arrive with that first table (`fields=1`, plus the chips that come with every
    response). Building them here as well computed the filter block twice per page load.
    """
    return page(
        view.title,
        view.about,
        view_filters(view, f, sort),
        Div(
            P(Small(view.loading), aria_busy="true"),
            id=f"{view.at}-table",
            hx_get=view.rows_route.to(**{"sort": sort, "fields": 1, **_set(f)}),
            hx_trigger="load",
            hx_swap="outerHTML",
        ),
    )


def view_rows(view: TableView, f: Any, sort: str, resort: str, refresh: int, fields: int) -> Any:
    """The table on its own: the target of every sort click and every filter change.

    `sort` rides in from the form's hidden field and `resort` from a clicked header, so
    the two never collide; the header wins, and the fresh value is swapped back into the
    form out of band. The chips come back with every response, because their counts
    depend on the other filters; the fields only when asked (`fields`), with the first
    table, because re-rendering them on a keystroke takes the caret out of the search box.
    """
    spec = resort or sort
    try:
        everything, extra = view.load(bool(refresh))
        # "Dit kwartaal" narrows the rows themselves, so the table, the chips' counts and
        # the dropdowns all speak of the quarter; the summary still counts the whole board.
        rows = view.narrow(everything, quarter_end()) if f.this_quarter else everything
    except FETCH_ERRORS as exc:
        return Div(error(exc, id=f"{view.at}-table"), id=f"{view.at}-table")

    column, desc = view.sorting.parse(spec)
    shown = view.arrange(rows, f, sort=column, desc=desc)
    out = [
        view_table(view, shown, everything, extra, spec),
        sort_field(view, spec)(hx_swap_oob="true"),
    ]
    if view.chips:
        out.append(view.chips(rows, f)(hx_swap_oob="true"))
    if fields:
        out.append(filter_fields(view, rows, f)(hx_swap_oob="true"))
    return tuple(out)


def search_field(placeholder: str, aria_label: str, value: str) -> Any:
    """The title search both overviews open their fields with."""
    return Label(
        "Zoeken",
        Input(type="search", name="search", value=value, placeholder=placeholder, aria_label=aria_label),
    )


def progress_field(bucket: str) -> Any:
    """The battery column's filter: a bucket, not a number."""
    return Label(
        "Voortgang",
        Select(
            Option("Elke voortgang", value="", selected=not bucket),
            *[Option(BUCKETS_NL[value], value=value, selected=value == bucket) for value in epics.BUCKETS],
            name="bucket",
        ),
    )


#: `epics.BUCKETS`' labels in Dutch, by the same keys.
BUCKETS_NL = {
    "not-started": "Niet begonnen",
    "in-progress": "Onderweg",
    "complete": "Klaar",
    "no-tasks": "Nog geen taken",
}


def switch(name: str, label: str, checked: bool, title: str) -> Any:
    """A filter that is on or off, with its rule in the hover."""
    return Label(Input(type="checkbox", name=name, role="switch", checked=checked), label, cls="switch", title=title)


def portfolio_link(epic: Epic) -> Any:
    """The epic's IV Portfolio item, as a way into the Portfolio page rather than as text."""
    if not epic.portfolio_ids:
        return Span("—", style="opacity:.5")
    return A(epic.portfolio or "portfolio-item", href=portfolio_item.to(item=epic.portfolio_ids[0]))


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


def epics_word(n: int) -> str:
    """`1 epic`, `3 epics`."""
    return f"{n} epic{'' if n == 1 else 's'}"


def epic_tone(epic: Epic) -> str:
    """The tone a card's top rule wears: stuck beats every status."""
    return "critical" if epic.is_stuck else chart.STATUS_TONES.get(epic.status, "neutral")


def epic_card(epic: Epic, show_portfolio: bool = True) -> Any:
    """One epic as a card: the row's cells, laid out around the battery. Under one
    portfolio item every card shares the item, so it can leave the line out."""
    total = epic.done + epic.remaining
    sub = (portfolio_link(epic) if epic.portfolio_ids else "Geen portfolio") if show_portfolio else None
    return cards.card(
        cards.head(
            A(epic.name, href=epic.url, target="_blank", rel="noopener", title="Open op monday.com"),
            sub=sub,
            big=cards.percent(epic.done, total),
            big_note=f"{bd.fmt(epic.done)} van {bd.fmt(total)} STP" if total else "geen taken",
        ),
        cards.tags(chart.status_tag(epic.status), chart.priority_tag(epic.priority), stuck_cell(epic)),
        chart.battery(epic.done, epic.remaining),
        cards.foot(
            chart.people(epic.owner, photo_for) or Span("geen Trekker"),
            Span(Strong(bd.fmt(epic.remaining)), " STP te gaan") if epic.remaining else None,
        ),
        tone=epic_tone(epic),
    )


def epic_summary(shown: list[Epic], everything: list[Epic], orphans: epics.Points) -> Any:
    """What the selection adds up to, as stat tiles, and what it could not account for.

    The selection's own battery is the wide one: the same meter as every row, at double
    length, so the headline reads as "the whole of what you filtered to".
    """
    total = epics.totals(shown)
    tiles = [
        chart.tile("Features", str(len(shown)), f"van de {len(everything)} op het epic-bord", "tone-brand"),
        *chart.points_tiles(total),
        chart.progress_tile(total),
    ]
    note = None
    if orphans.tasks:
        note = P(
            Small(
                f"{orphans.tasks} sprinttaken ({bd.fmt(orphans.done + orphans.remaining)} punten) "
                "hangen aan geen enkele epic en staan dus in geen van deze rijen.",
                style="opacity:.7",
            )
        )
    return Div(Div(*tiles, cls="kpis"), note, cls="epic-head")


def status_chips(rows: list[Epic], f: epics.Filters) -> Any:
    """The status filter as chips with counts, plus the hidden field they set.

    Built from the rows under every *other* filter, so each chip says exactly how many
    epics clicking it shows, and the board's shape is visible before anything is chosen.
    Swapped out of band on every response, because the counts move with the filters.
    """
    field = Input(type="hidden", name="status", value=f.status)
    wrapper = {"cls": "chips", "id": "status-chips", "role": "group", "aria_label": "Status epic"}
    if not rows:
        # Nothing to count (the page shell, or an empty board): the field, no "All 0" chip.
        return Div(field, **wrapper)
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
        field,
        chip("Alle", "", everything),
        *[chip(chart.status_tag(status), status, count) for status, count in counts],
        **wrapper,
    )


def filter_select(name: str, label: str, any_of: str, values: list[str], selected: str) -> Any:
    """One column's filter, on either overview. Built from the values actually on the
    board, so no choice in it can come back empty — the same rule as the sprint page's
    epic dropdown. Before there are rows to offer (the page shell) the selected value is
    its only option, so the form does not quietly drop a filter it was given."""
    offered = values or ([selected] if selected else [])
    return Label(
        label,
        Select(
            Option(any_of, value="", selected=not selected),
            *[Option(v, value=v, selected=v == selected) for v in offered],
            name=name,
        ),
    )


def epic_filter_fields(rows: list[Epic], f: epics.Filters) -> tuple[Any, ...]:
    """The dropdowns themselves, their options from the fetched rows."""
    return (
        search_field("Zoek in epic-titels…", "Zoek in epic-titels", f.search),
        filter_select("owner", "Trekker", "Elke Trekker", epics.options(rows, "owner"), f.owner),
        Label("DAM", portfolio_select(f.dam)),
        progress_field(f.bucket),
        switch("stuck", "Alleen vastgelopen", f.stuck, "Epics op Impediment, of met een taak die dat is"),
        switch("this_quarter", "Dit kwartaal", f.this_quarter, THIS_QUARTER_FEATURES),
        switch(
            "dropped",
            "Toon afgevallen",
            f.dropped,
            "Afgevallen en Overgedragen epics zijn verborgen tenzij dit aan staat",
        ),
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
    this_quarter: bool = False,
    sort: str = epics.DEFAULT_SORT,
) -> Any:
    """The Features page: every epic, sortable on every column and filterable on the ones worth filtering.

    The table arrives on its own request (`hx_trigger="load"`) because the first fetch
    reads both sprint boards end to end — a few thousand items — and a spinner beats a
    blank tab for twenty seconds.
    """
    f = epics.Filters(
        search=search,
        status=status,
        owner=owner,
        dam=dam,
        bucket=bucket,
        stuck=stuck,
        dropped=dropped,
        this_quarter=this_quarter,
    )
    return view_page(EPIC_VIEW, f, sort)


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
    this_quarter: bool = False,
    sort: str = epics.DEFAULT_SORT,
    resort: str = "",
    refresh: int = 0,
    fields: int = 0,
) -> Any:
    """The table on its own — see `view_rows`."""
    f = epics.Filters(
        search=search,
        status=status,
        owner=owner,
        dam=dam,
        bucket=bucket,
        stuck=stuck,
        dropped=dropped,
        this_quarter=this_quarter,
    )
    return view_rows(EPIC_VIEW, f, sort, resort, refresh, fields)


# --- the portfolio page -----------------------------------------------------------------
# The IV Portfolio board with the epics grouped under it. Two views of one dataset: the
# overview, which is the epics table's numbers added up per portfolio item, and a detail
# page per item listing the epics themselves.
#
# The link only exists on the epic side, so both views are `portfolio.attach` over the
# cached epic board — see `portfolio_cache`. Nothing here reads a board the Epics page
# does not already read, apart from one cheap request for the portfolio items themselves.

#: Column key, heading, header class. The order here is the order of the table.
PORTFOLIO_COLUMNS = (
    ("name", "Portfolio-item", None),
    ("stuck", "Vast", "tight"),
    ("goal", "Doelstelling", "goal"),
    ("type", "Type", "tight"),
    ("urgency", "Urgentie", "tight"),
    ("lead", "Projectleider", "lead"),
    ("epics", "Epics", "tight"),
    ("done", "STP klaar", "tight"),
    ("remaining", "STP te gaan", "tight"),
    ("progress", "Voortgang", "tight"),
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
        _PORTFOLIO[:] = portfolio.fetch_items(monday_client())
    return portfolio.attach(_PORTFOLIO, rows), rows


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


#: How many of an item's epics its card lists before it points at the item's own page.
CARD_EPICS = 5


def portfolio_card(item: PortfolioItem) -> Any:
    """One portfolio item as a card: the row's figures, and the first few of its epics.
    The name is the way in, as in the table — the card lists, the item's page explains."""
    total = item.done + item.remaining
    listed = [
        Li(
            Span(chart.tag(epic.name, epic_tone(epic)), cls="n", title=epic.name),
            Span(f"{bd.fmt(epic.done)}/{bd.fmt(epic.done + epic.remaining)}", cls="v")
            if epic.done + epic.remaining
            else Span("geen taken", cls="v"),
        )
        for epic in item.epics[:CARD_EPICS]
    ]
    if len(item.epics) > CARD_EPICS:
        listed.append(
            Li(A(f"en nog {len(item.epics) - CARD_EPICS} epics", href=portfolio_item.to(item=item.id)), cls="more")
        )
    return cards.card(
        cards.head(
            A(item.name, href=portfolio_item.to(item=item.id)),
            sub=" · ".join(filter(None, [item.goal, item.type])),
            big=cards.percent(item.done, total),
            big_note=epics_word(len(item.epics)) if item.epics else "geen epics",
        ),
        cards.tags(
            chart.urgency_tag(item.urgency),
            Span("Projectleider: ", item.lead) if item.lead else None,
            portfolio_stuck_cell(item),
        ),
        chart.battery(item.done, item.remaining),
        Ul(*listed, cls="elist") if listed else P(Small("Nog geen epics gekoppeld."), style="margin:0"),
        cards.foot(
            Span(Strong(bd.fmt(item.done)), " STP klaar"),
            Span(Strong(bd.fmt(item.remaining)), " STP te gaan"),
        )
        if total
        else None,
        tone="critical" if item.is_stuck else "" if item.epics else "off",
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
        chart.tile(
            "Portfolio-items", str(len(shown)), f"van de {len(everything)} op het bord · {linked} epics", "tone-brand"
        ),
        *chart.points_tiles(total),
    ]
    if stuck:
        tiles.append(chart.tile("Vastgelopen", str(stuck), "hebben een geblokkeerde epic", "tone-critical"))
    tiles.append(chart.progress_tile(total))
    note = None
    if orphans:
        points = sum(e.total for e in orphans)
        note = P(
            Small(
                f"{len(orphans)} epics ({bd.fmt(points)} punten) noemen een portfolio-item dat het "
                "IV Portfolio-bord niet teruggaf, en staan in geen van deze rijen.",
                style="opacity:.7",
            )
        )
    return Div(Div(*tiles, cls="kpis"), note, cls="epic-head")


def portfolio_filter_fields(rows: list[PortfolioItem], f: portfolio.Filters) -> tuple[Any, ...]:
    """The dropdowns, built from the rows actually fetched — so no choice comes back empty."""
    return (
        search_field("Zoek in portfolio-items…", "Zoek in de titels van portfolio-items", f.search),
        filter_select("goal", "Doelstelling", "Elke doelstelling", portfolio.options(rows, "goal"), f.goal),
        filter_select("type", "Type", "Elk type", portfolio.options(rows, "type"), f.type),
        filter_select("urgency", "Urgentie", "Elke urgentie", portfolio.options(rows, "urgency"), f.urgency),
        filter_select("lead", "Projectleider", "Iedereen", portfolio.options(rows, "lead"), f.lead),
        progress_field(f.bucket),
        switch(
            "stuck",
            "Alleen vastgelopen",
            f.stuck,
            "Portfolio-items met een epic op Impediment, of met een taak die dat is",
        ),
        switch("this_quarter", "Dit kwartaal", f.this_quarter, THIS_QUARTER_PORTFOLIO),
        switch(
            "empty",
            "Toon ongekoppelde",
            f.empty,
            "166 van de 177 items hebben geen epic gekoppeld en dus geen voortgang om te tonen",
        ),
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
    this_quarter: bool = False,
    sort: str = portfolio.DEFAULT_SORT,
) -> Any:
    """Every IV Portfolio item with the epics under it burnt down."""
    f = portfolio.Filters(
        search=search,
        goal=goal,
        type=type,
        urgency=urgency,
        lead=lead,
        bucket=bucket,
        stuck=stuck,
        empty=empty,
        this_quarter=this_quarter,
    )
    return view_page(PORTFOLIO_VIEW, f, sort)


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
    this_quarter: bool = False,
    sort: str = portfolio.DEFAULT_SORT,
    resort: str = "",
    refresh: int = 0,
    fields: int = 0,
) -> Any:
    """The table on its own — see `view_rows`."""
    f = portfolio.Filters(
        search=search,
        goal=goal,
        type=type,
        urgency=urgency,
        lead=lead,
        bucket=bucket,
        stuck=stuck,
        empty=empty,
        this_quarter=this_quarter,
    )
    return view_rows(PORTFOLIO_VIEW, f, sort, resort, refresh, fields)


def portfolio_rows(refresh: bool) -> tuple[list[PortfolioItem], list[Epic]]:
    """The portfolio items, and the epics naming an item the board did not return."""
    rows, epic_rows = portfolio_cache(refresh=refresh)
    return rows, portfolio.orphan_epics(rows, epic_rows)


EPIC_VIEW = TableView(
    at="epic",
    title="Features",
    about="Story points per feature (een epic op het epic-bord), opgeteld uit het actieve en het done-sprintbord.",
    loading="Het epic-bord wordt geladen…",
    sorting=epics.SORTING,
    columns=EPIC_COLUMNS,
    load=epic_cache,
    arrange=epics.arrange,
    row=epic_row,
    narrow=epics.due_only,
    card=epic_card,
    summary=epic_summary,
    fields=epic_filter_fields,
    chips=status_chips,
    rows_route=epic_table_rows,
    page_route=epics_page,
    table_cls="epics",
    board_empty="Het epic-bord kwam leeg terug.",
    none_match="Geen epics die aan deze filters voldoen.",
)

PORTFOLIO_VIEW = TableView(
    at="portfolio",
    title="Portfolio",
    about="Het IV Portfolio-bord: story points per portfolio-item, opgeteld over de epics die eraan hangen.",
    loading="Het portfolio wordt geladen…",
    sorting=portfolio.SORTING,
    columns=PORTFOLIO_COLUMNS,
    load=portfolio_rows,
    arrange=portfolio.arrange,
    row=portfolio_row,
    narrow=portfolio.due_only,
    card=portfolio_card,
    wide_cards=True,
    summary=portfolio_summary,
    fields=portfolio_filter_fields,
    rows_route=portfolio_table_rows,
    page_route=portfolio_page,
    table_cls="epics portfolio",
    board_empty="Het IV Portfolio-bord kwam leeg terug.",
    none_match="Geen portfolio-items die aan deze filters voldoen.",
    caption="Klik op een item om zijn epics te zien.",
)


# --- one portfolio item -----------------------------------------------------------------
# The epics under a single item. The same numbers as the overview row, opened up: the
# epics are the rows and the item's own fields sit above them.

#: The epic columns on the detail page. No Portfolio column — every row shares it — and
#: no sorting: the order is fixed at "blocked first, then most work left".
DETAIL_COLUMNS = ("Epic", "Status epic", "Vast", "Trekker", "Prioriteit", "STP klaar", "STP te gaan", "Voortgang")


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
        ("Fortes", external_link(item.ref or "openen", item.link) if item.link else ""),
        ("monday.com", A("open het item", href=item.url, target="_blank", rel="noopener")),
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
        chart.tile("Epics", str(len(item.epics)), "gekoppeld aan dit item", "tone-brand"),
        *chart.points_tiles(total),
    ]
    if item.is_stuck:
        tiles.append(chart.tile("Vastgelopen", str(len(item.stuck_epics)), portfolio_stuck_cell(item), "tone-critical"))
    tiles.append(chart.progress_tile(total))

    if item.epics and as_cards():
        body: Any = Div(
            P(Small("Geblokkeerde epics eerst, dan die met het meeste werk."), cls="lede-scope"),
            cards.grid(epic_card(epic, show_portfolio=False) for epic in item.epics),
        )
    elif item.epics:
        body = Div(
            Table(
                Caption("Geblokkeerde epics eerst, dan die met het meeste werk.", cls="hint"),
                Thead(Tr(*[Th(h, cls=None if h == "Epic" else "tight") for h in DETAIL_COLUMNS])),
                Tbody(*[portfolio_epic_row(epic) for epic in item.epics]),
                cls="epics",
            ),
            cls="table-wrap",
        )
    else:
        body = P("Er zijn geen epics aan dit portfolio-item gekoppeld.")

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
        "Eén portfolio-item: de epics die eraan hangen, hun stand en hun story points.",
        P(A("← Alle portfolio-items", href=portfolio_page), cls="back"),
        Div(
            P(Small("Het portfolio wordt geladen…"), aria_busy="true"),
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
            P("Er is geen portfolio-item met dat id. ", A("Terug naar het portfolio", href=portfolio_page)),
            id="portfolio-item",
        )
    return portfolio_detail(found)


# --- the planning page ------------------------------------------------------------------
# Work per discipline against the team's capacity, and which epics that lets us finish.
# The numbers are `planning.plan` over a cached `planning.Snapshot`: the dates and the
# layers are the page's own inputs, so changing them re-plans without a monday.com read.


def planning_cache(refresh: bool = False) -> planning.Snapshot:
    """The planning boards, fetched on first use and then reused. `refresh` re-reads them."""
    if refresh or not _PLANNING:
        _PLANNING[:] = [planning.fetch(monday_client())]
    return _PLANNING[0]


def planning_date_fields(sprint_end: str, end: str) -> Any:
    """The window's two dates: the end of the current sprint (the plan starts the day after)
    and the end of the quarter. They show the window in use, so they come back out of band."""
    return Div(
        Label("Einde sprint", date_field("sprint_end", sprint_end)),
        Label("Einde kwartaal", date_field("end", end)),
        id="planning-dates",
        style="display: contents",
    )


DAM_HELP = (
    "DAM: epics die gekoppeld zijn aan een item op het IV Portfolio-bord. Niet-DAM: epics zonder die koppeling. "
    "De bezetting, de prognose en de checks op de huidige en de volgende sprint volgen allemaal dit filter."
)


def planning_filters(sprint_end: str, end: str, layers: tuple[str, ...], dam: str, this_quarter: bool) -> Any:
    """The window, the layers, the DAM half and "This quarter". Together they are the
    selection: only the epics they pick take capacity, so every number below answers
    "can we do exactly this?"."""
    return Form(
        Div(
            planning_date_fields(sprint_end, end),
            Label("Portfolio", portfolio_select(dam), title=DAM_HELP),
            Fieldset(
                Legend("Plannen"),
                *[
                    Label(
                        Input(type="checkbox", name="layer", value=key, checked=key in layers),
                        label,
                        title=planning.LAYER_HELP_NL[key],
                    )
                    for key, label in planning.LAYERS_NL.items()
                ],
                Label(
                    Input(type="checkbox", name="this_quarter", role="switch", checked=this_quarter),
                    "Dit kwartaal",
                    title=planning.THIS_QUARTER_HELP_NL,
                ),
                cls="layers",
            ),
            cls="filters",
        ),
        Div(
            Button("Toepassen", type="submit"),
            A("Herstellen", href=planning_page, role="button", cls="secondary outline"),
            refresh_button(planning_view.to(refresh=1), "#planning-filters", "#planning"),
            Small(" laden…", id="spinner"),
            cls="actions",
        ),
        hx_get=planning_view,
        hx_target="#planning",
        hx_swap="outerHTML",
        hx_trigger="change, submit",
        hx_indicator="closest form",
        id="planning-filters",
        cls="panel",
        data_refilter="1",
    )


def _sprints(value: float | None) -> str:
    return "niemand" if value is None else f"{value:.1f}"


def dam_label(dam: str) -> str:
    """The filter's label ("Alleen DAM" / "Alleen niet-DAM"), or empty when it is off — or set
    to a value it does not know, which every DAM check treats as both (`config.keeps_dam`)."""
    return next((label for value, label in PORTFOLIO_LABELS if value == dam and value), "")


def selection_text(p: planning.Plan) -> str:
    """The selection in words, for the heading: "Toegezegd + Later · Alleen DAM · due uiterlijk …"."""
    due = f"due uiterlijk {p.window.end}" if p.this_quarter else ""
    return " · ".join(filter(None, [planning.layers_text_nl(p.layers), dam_label(p.dam), due]))


def planning_tiles(p: planning.Plan) -> Any:
    """The headline: how long the window is, what fits, what is late, who is the bottleneck."""
    w = p.window
    counted = [q for q in p.queue if q.split.has_todo]
    fitting = sum(1 for q in counted if q.fits(w))
    late = sum(1 for q in p.queue if q.late)
    tiles = [
        chart.tile(
            "Sprints",
            str(w.sprints),
            f"hele sprints, tot {w.last_day}" if w.sprints else "er past er geen",
            "tone-brand",
        ),
        chart.tile("Epics die passen", f"{fitting} van {len(counted)}", "klaar binnen de periode"),
        chart.tile("Te laat", str(late), "ten opzichte van hun eigen due date", "tone-critical" if late else ""),
    ]
    heaviest = planning.most_overbooked(p)
    if heaviest:
        top = heaviest[0]
        load = top.load(w.sprints)
        text = "niemand" if load is None else f"{load:.0%}"
        tiles.append(
            chart.tile(
                "Zwaarst bezet",
                text,
                f"{top.key} · {top.name}",
                f"tone-{planning.load_tone(load)}",
                title="De STP van de selectie voor deze discipline, als deel van haar capaciteit over de hele sprints",
            )
        )
    if p.problems:
        tiles.append(
            chart.tile(
                "Buiten beschouwing", str(len(p.problems)), "epics om op monday.com te herstellen", "tone-warning"
            )
        )
    return Div(*tiles, cls="kpis")


def discipline_table(p: planning.Plan, heaviest: list[planning.Discipline]) -> Any:
    """One row per discipline, heaviest first: who, how much they can do, how much there is."""
    sprints = p.window.sprints
    heads = [
        Th("Discipline"),
        Th("Mensen"),
        Th("STP / sprint", cls="tight", title="Σ STP per sprint × beschikbaarheid kwartaal × (1 − overhead)"),
        Th("Capaciteit", cls="tight", title=f"STP / sprint × {sprints} hele sprints"),
        *[Th(planning.LAYERS_NL[key], cls="tight", title=planning.LAYER_HELP_NL[key]) for key in p.layers],
        Th("Totaal", cls="tight", title="Alle STP die de selectie van deze discipline vraagt"),
        Th("Sprints nodig", cls="tight", title="Totaal ÷ STP per sprint"),
        Th(
            "Bezetting",
            cls="tight",
            title=f"Totaal ÷ capaciteit. {planning.LOAD_BAND[0]:.0%}–{planning.LOAD_BAND[1]:.0%} is op doel, "
            f"boven {planning.LOAD_BAND[1]:.0%} is overboekt",
        ),
    ]
    rows = [
        Tr(
            Td(Strong(d.key), " ", Small(d.name)),
            Td(chart.people(", ".join(person.name for person in d.people)) if d.people else "—", cls="owner"),
            Td(f"{d.per_sprint:.1f}", cls="num tight"),
            Td(f"{d.capacity(sprints):.1f}", cls="num tight"),
            *[Td(f"{d.demand.get(key, 0.0):.1f}" if d.demand.get(key) else "", cls="num tight") for key in p.layers],
            Td(Strong(f"{d.total:.1f}"), cls="num tight"),
            Td(f"{_sprints(d.sprints_needed)} van {sprints}", cls="num tight"),
            Td(chart.load_meter(d.total, d.capacity(sprints)), cls="tight progress"),
        )
        for d in heaviest
    ]
    return Div(
        Table(Thead(Tr(*heads)), Tbody(*rows), cls="epics"),
        cls="table-wrap",
    )


def how_it_works(p: planning.Plan) -> Any:
    """The page's own documentation, with this selection's numbers in it.

    Worked through on the heaviest discipline, so "122%" is never a number without a
    sum behind it.
    """
    w = p.window
    layer_rows = [
        Tr(Td(Strong(planning.LAYERS_NL[key])), Td(planning.LAYER_HELP_NL[key])) for key in planning.LAYERS_NL
    ]
    heaviest = planning.most_overbooked(p)
    example = None
    if heaviest and w.sprints and heaviest[0].per_sprint:
        d = heaviest[0]
        load = d.load(w.sprints) or 0.0
        example = P(
            f"Uitgerekend voor {d.key}: {d.total:.1f} STP ÷ ({d.per_sprint:.1f} STP per sprint × {w.sprints} sprints "
            f"= {d.capacity(w.sprints):.1f}) = {load:.0%}."
        )
    return Details(
        Summary("Hoe wordt dit berekend?"),
        Div(
            H4("Wat er in elke laag zit"),
            P(
                "De laag volgt uit de ",
                Strong("groep"),
                " van de epic op het epic-bord, en zijn Due date ten opzichte van het kwartaaleinde dat je "
                "instelt. De Status epic wordt getoond maar beslist niet. Afgerond wordt nooit gepland.",
            ),
            Table(Tbody(*layer_rows), cls="help"),
            H4("Wat er meetelt"),
            P(
                "Een epic telt mee als hij in een aangevinkte laag zit, door het Portfolio-filter komt (en, met "
                "“Dit kwartaal” aan, een Due date op of vóór het kwartaaleinde heeft), en een rij op "
                "Epics-STP-distribution heeft die eraan gekoppeld is, met een verdeling over DE / DB / DS / PO/AT "
                "die optelt tot 100%. Zijn werk is de STP-TODO van die rij, precies zoals monday.com die "
                "berekent. Al het andere staat onder de epics als buiten beschouwing, met een link om het op "
                "monday.com te herstellen."
            ),
            H4("Hoe de bezetting (% overboekt) wordt berekend"),
            Ul(
                Li(
                    f"De periode loopt van {w.start}, de dag na het einde van de huidige sprint, tot het kwartaaleinde "
                    f"{w.end}. Daar passen {w.sprints} hele sprints van drie weken in, tot "
                    f"{w.last_day}; de dagen daarna tellen niet mee."
                ),
                Li(
                    "Per persoon: STP per sprint × “Beschikbaar komend kwartaal” × (1 − Overhead), "
                    "van het Capaciteit-bord. De STP per sprint van een discipline is de som over haar mensen."
                ),
                Li("Capaciteit = STP per sprint × het aantal hele sprints."),
                Li("Totaal = de som van de STP-TODO van elke gekozen epic × het percentage van die discipline."),
                Li(
                    "Bezetting = Totaal ÷ Capaciteit. Boven 100% past de selectie niet in de periode. "
                    "Alleen de selectie neemt capaciteit: werk dat je niet aanvinkt, wordt verondersteld niet "
                    "gedaan te worden."
                ),
            ),
            example,
            H4("De twee grafieken (kaartweergave)"),
            P(
                "Links de capaciteit van elke discipline over de hele sprints: donker wat het Capaciteit-bord "
                "geeft (STP per sprint × “Beschikbaar komend kwartaal” × (1 − Overhead)), licht wat het zou zijn "
                "als iedereen 100% beschikbaar was — de overhead blijft dan staan. Rechts de STP die de "
                f"selectie van de discipline vraagt, als deel van die beschikbare capaciteit. Tussen "
                f"{planning.LOAD_BAND[0]:.0%} en {planning.LOAD_BAND[1]:.0%} is op doel (groen), daaronder is er "
                "ruimte over (blauw), daarboven is de discipline overboekt (rood)."
            ),
            H4("Hoe de prognose wordt berekend"),
            P(
                "De gekozen epics staan in de rij op laag, dan prioriteit, dan due date, dan de kleinste eerst. "
                "Elke discipline werkt de rij zelfstandig af, en niemand neemt het deel van een andere "
                "discipline over. Een epic is klaar in de sprint waarin zijn traagste discipline erdoorheen is; "
                "hij is te laat als dat na zijn eigen due date valt."
            ),
            H4("Huidige en volgende sprint"),
            P(
                "Een taak op het sprintbord heeft een Trekker, dus haar STP gaan in hun geheel naar de discipline "
                "van die Trekker op het Capaciteit-bord — niet verdeeld volgens de percentages van de epic; die "
                "gelden alleen voor de epics hierboven, waar nog niemand aan werkt. Heeft een taak twee Trekkers, "
                "dan telt hij voor de eerste. Een Trekker die niet op Capaciteit staat, wordt onder de tabel "
                "genoemd. Vervallen telt niet mee; het Portfolio-filter geldt hier, de lagen en “Dit kwartaal” niet."
            ),
            Ul(
                Li(
                    "Huidige sprint: alle taken in de huidige sprintgroep, Done meegeteld (de sprint loopt al, en "
                    "wat af is hoorde bij wat hij op zich nam), tegen de STP per sprint met “Beschikbaar komend "
                    "kwartaal” — het Capaciteit-bord heeft geen beschikbaarheid voor een sprint die al begonnen is."
                ),
                Li("Volgende sprint: de open taken in de groep Next sprint, tegen “% beschikbaar komende sprint”."),
            ),
        ),
        cls="how",
    )


def split_text(split: planning.Split) -> str:
    """The four percentages in the board's order, compact: `35 / 30 / 25 / 10`."""
    return " / ".join(f"{split.shares.get(key) or 0:g}" for key in planning.DISCIPLINES)


def queue_row(q: planning.Planned, w: planning.Window, first_of_layer: bool) -> Any:
    """One epic in the queue: where it sits, what is left, and when it is forecast to finish."""
    verdict, tone = q.verdict(w)
    finish = (str(q.finish), Small(f"sprint {q.finish_sprint}")) if q.finish else ()
    return Tr(
        Td(planning.LAYERS_NL[q.layer], cls="tight"),
        Td(A(q.epic.name, href=q.epic.url, target="_blank", rel="noopener"), cls="item"),
        Td(chart.status_tag(q.epic.status), cls="tight"),
        Td(chart.priority_tag(q.epic.priority), cls="tight"),
        Td(str(q.epic.due or ""), cls="tight"),
        Td(bd.fmt(q.todo) if q.split.has_todo else "", cls="num tight"),
        Td(A(split_text(q.split), href=q.split.url, target="_blank", rel="noopener"), cls="split"),
        Td(*finish, cls="tight finish"),
        Td(chart.tag(planning.VERDICTS_NL[verdict], tone), cls="tight"),
        cls="layer-start" if first_of_layer else None,
    )


#: What the queue says when nothing in the selection can be planned.
NO_USABLE_SPLIT = "Geen epic in deze selectie heeft al een bruikbare verdeling op Epics-STP-distribution."


def queue_table(p: planning.Plan) -> Any:
    shown = p.queue
    if not shown:
        return P(NO_USABLE_SPLIT)
    heads = ("Laag", "Epic", "Status epic", "Prioriteit", "Due", "STP-TODO", "DE / DB / DS / PO", "Klaar", "Prognose")
    rows = [queue_row(q, p.window, i == 0 or shown[i - 1].layer != q.layer) for i, q in enumerate(shown)]
    return Div(
        Table(
            Caption(
                "In de volgorde van de rij: laag, dan prioriteit, dan due date, dan de kleinste eerst.", cls="hint"
            ),
            Thead(Tr(*[Th(h, cls=None if h == "Epic" else "tight") for h in heads])),
            Tbody(*rows),
            cls="epics plan",
        ),
        cls="table-wrap",
    )


def unplaced_note(n: planning.SprintLoad) -> Any:
    """The points no discipline could take, and whose they are — so the fix is obvious."""
    if not n.unplaced:
        return None
    who = ", ".join(f"{name or 'geen Trekker'} ({bd.fmt(points)})" for name, points in sorted(n.unmatched.items()))
    return P(
        Small(
            f"Nog {bd.fmt(n.unplaced)} punten staan op taken waarvan de Trekker geen discipline heeft op "
            f"Capaciteit, en tellen dus nergens mee: {who}.",
            style="opacity:.7",
        )
    )


def sprint_load_table(n: planning.SprintLoad) -> Any:
    """One sprint group: what is in it per discipline, against that sprint's capacity."""
    rows = [
        Tr(
            Td(Strong(key), " ", Small(planning.DISCIPLINE_NAMES[key])),
            Td(bd.fmt(n.load[key]), cls="num tight"),
            Td(f"{n.capacity[key]:.1f}", cls="num tight"),
            Td(chart.load_meter(n.load[key], n.capacity[key]), cls="tight progress"),
        )
        for key in planning.DISCIPLINES
    ]
    note = unplaced_note(n)
    return Div(
        Div(
            Table(
                Thead(
                    Tr(
                        Th("Discipline"),
                        Th("Gepland", cls="tight"),
                        Th("Capaciteit", cls="tight"),
                        Th("Bezetting", cls="tight"),
                    )
                ),
                Tbody(*rows),
                cls="epics",
                style="min-width: 0",
            ),
            cls="table-wrap",
        ),
        note,
    )


def left_out(p: planning.Plan) -> Any:
    """The epics in the selection the plan could not count, each with a link to the fix."""
    if not p.problems:
        return None
    return Details(
        Summary(f"{len(p.problems)} epics tellen nergens mee — herstel ze op monday.com"),
        Ul(
            *[
                Li(
                    A(pr.epic.name, href=pr.url, target="_blank", rel="noopener"),
                    Small(f"{planning.LAYERS_NL[pr.layer]} · {pr.reason_nl}"),
                )
                for pr in p.problems
            ],
            cls="left-out",
        ),
    )


def discipline_charts(p: planning.Plan, shown: list[planning.Discipline]) -> Any:
    """The two charts above the discipline cards, side by side, one row per discipline in
    the cards' order: what each discipline can do this quarter (and could at 100%
    availability), and how much of that the selection books."""
    sprints = p.window.sprints
    capacity = [(d.key, d.name, d.capacity(sprints), d.full_capacity(sprints)) for d in shown]
    booked = [(d.key, d.name, d.load(sprints), d.total, d.capacity(sprints)) for d in shown]
    return Div(
        Div(
            H4("Capaciteit in het kwartaal", Small(f"STP over {sprints} hele sprints")),
            chart.capacity_chart(capacity),
            cls="panel chart-half",
        ),
        Div(
            H4("Geboekt", Small("de STP van de selectie ÷ de beschikbare capaciteit")),
            chart.booked_chart(booked),
            cls="panel chart-half",
        ),
        cls="chart-pair",
    )


def discipline_card(d: planning.Discipline, p: planning.Plan) -> Any:
    """One discipline as a card: how booked it is, and the epics it works through in queue
    order — each with the sprints the forecast puts it in."""
    sprints = p.window.sprints
    load = d.load(sprints)
    tone = planning.load_tone(load) if d.total else "neutral"
    per = d.per_sprint
    shares = planning.discipline_shares(p.queue, d)
    over = planning.overflow(d, sprints)
    if load is None:
        verdict = chart.tag("niemand om het te doen", "critical")
    elif not d.total:
        verdict = chart.tag("niets gepland", "neutral")
    else:
        verdict = chart.tag(planning.LOAD_WORDS[tone], tone)
    count = epics_word(len(shares))
    return cards.card(
        cards.head(
            f"{d.key} · {d.name}",
            sub=", ".join(person.name for person in d.people) or "niemand op Capaciteit",
            big=None if load is None else f"{load:.0%}",
            big_note=f"{d.total:.1f} van {d.capacity(sprints):.1f} STP",
        ),
        cards.tags(verdict, Span(f"{per:.1f} STP per sprint"), Span(f"{_sprints(d.sprints_needed)} sprints nodig")),
        P(chart.tag(f"{over:.1f} STP past niet in de periode", "critical"), cls="overflow", style="margin:0")
        if over and per
        else None,
        cards.foot(
            Span(Strong(count), " in de rij"),
            Button(
                "Bekijk de epics",
                type="button",
                cls="secondary outline open-list",
            ),
        )
        if shares
        else P(Small("Geen werk voor deze discipline in de selectie."), style="margin:0"),
        discipline_dialog(d, p, shares) if shares else None,
        tone=tone,
        cls="opens" if shares else "",
        onclick=cards.OPEN_JS if shares else None,
        title="Klik om de epics te zien" if shares else None,
    )


def strip_help(d: planning.Discipline, sprints: int) -> Any:
    """What the sprint cells mean, in words, under the list."""
    return P(
        f"De blokjes zijn de {sprints} sprints van de periode (S1–S{sprints}). ",
        cards.strip(sprints, 1, 1),
        f" Donkerblauw: een sprint waarin {d.key} volgens de prognose aan deze epic werkt — de rij wordt op "
        "volgorde afgewerkt, met de volledige capaciteit van de discipline. Licht: in die sprint niet. ",
        cards.strip(sprints, sprints, sprints + 1),
        " Rood in de laatste sprint: (een deel van) het werk valt na de periode — staat er geen donkerblauw "
        "voor, dan begint het er pas na.",
        cls="strip-help",
    )


def discipline_dialog(d: planning.Discipline, p: planning.Plan, shares: list[planning.Share]) -> Any:
    """Every epic this discipline works on, in queue order, for the card's pop-up."""
    sprints = p.window.sprints
    rows = [
        Tr(
            Td(f"#{s.position}", cls="tight"),
            Td(A(s.planned.epic.name, href=s.planned.epic.url, target="_blank", rel="noopener")),
            Td(planning.LAYERS_NL[s.planned.layer], cls="tight"),
            Td(str(s.planned.epic.due or "—"), cls="tight"),
            Td(f"{s.points:.1f}", cls="num tight"),
            Td(cards.strip(sprints, s.first, s.last), cls="tight"),
        )
        for s in shares
    ]
    return cards.dialog(
        f"{d.key} · {d.name}",
        f"{len(shares)} epics in de rij · {d.total:.1f} STP van {d.capacity(sprints):.1f} STP capaciteit",
        Table(
            Thead(
                Tr(
                    Th("#", title="Plek in de rij"),
                    Th("Epic"),
                    Th("Laag"),
                    Th("Due"),
                    Th("STP", title=f"Het deel van {d.key} in de STP-TODO van de epic"),
                    Th(cards.strip_head(sprints), title="Sprints volgens de prognose"),
                )
            ),
            Tbody(*rows),
        ),
        strip_help(d, sprints),
    )


def queue_card(q: planning.Planned, w: planning.Window) -> Any:
    """One epic in the queue as a card: what is left, how it splits, and when it is done."""
    verdict, tone = q.verdict(w)
    shares = [cards.pill(f"{key} {q.split.shares[key]:g}%") for key in planning.DISCIPLINES if q.split.shares.get(key)]
    return cards.card(
        cards.head(
            A(q.epic.name, href=q.epic.url, target="_blank", rel="noopener"),
            sub=f"due {q.epic.due}" if q.epic.due else "geen due date",
            big=bd.fmt(q.todo) if q.split.has_todo else None,
            big_note="STP-TODO",
        ),
        cards.tags(
            chart.tag(planning.VERDICTS_NL[verdict], tone),
            chart.status_tag(q.epic.status),
            chart.priority_tag(q.epic.priority),
        ),
        A(*shares, href=q.split.url, target="_blank", rel="noopener", cls="tags", title="De verdeling op monday.com")
        if shares
        else None,
        cards.foot(
            Span("Klaar ", Strong(str(q.finish)), f" · sprint {q.finish_sprint}")
            if q.finish
            else Span("Geen einddatum voorspeld"),
        ),
        tone=tone,
    )


def queue_cards(p: planning.Plan) -> Any:
    """The queue as cards, one grid per layer, in queue order."""
    if not p.queue:
        return P(NO_USABLE_SPLIT)
    groups = []
    for key in p.layers:
        mine = [q for q in p.queue if q.layer == key]
        if mine:
            groups += [
                H4(
                    planning.LAYERS_NL[key],
                    Small(epics_word(len(mine))),
                    title=planning.LAYER_HELP_NL[key],
                    cls="layer",
                ),
                cards.grid(queue_card(q, p.window) for q in mine),
            ]
    return Div(*groups)


def sprint_load_cards(n: planning.SprintLoad) -> Any:
    """One sprint group, one small card per discipline."""
    shown = []
    for key in planning.DISCIPLINES:
        load, capacity = n.load[key], n.capacity[key]
        share = load / capacity if capacity else None
        shown.append(
            cards.card(
                cards.head(
                    f"{key} · {planning.DISCIPLINE_NAMES[key]}",
                    big=cards.percent(load, capacity),
                    big_note=f"{bd.fmt(load)} van {capacity:.1f} STP",
                ),
                chart.load_meter(load, capacity),
                tone=planning.load_tone(share) if load else "neutral",
            )
        )
    return Div(cards.grid(shown, size="narrow"), unplaced_note(n))


def planning_section(p: planning.Plan) -> Any:
    """Everything under the filters: tiles, disciplines, the queue, the gaps, the current and
    the next sprint."""
    w = p.window
    dam = f" · {dam_label(p.dam)}" if dam_label(p.dam) else ""
    sprint_load = sprint_load_cards if as_cards() else sprint_load_table
    heaviest = planning.most_overbooked(p)  # one order for the charts, the cards and the table
    unassigned = [
        P(Small(f"{person.name} heeft op Capaciteit geen discipline als rol, en telt dus voor niemand."))
        for person in p.unassigned_people
    ]
    return Div(
        H2(f"{w.start} – {w.end}"),
        P(Small(selection_text(p)), cls="lede-scope"),
        how_it_works(p),
        planning_tiles(p),
        Div(
            H3("Per discipline"),
            Small("zwaarste bezetting eerst · strikt: niemand neemt het deel van een andere discipline over"),
            cls="section-head",
        ),
        Div(discipline_charts(p, heaviest), cards.grid((discipline_card(d, p) for d in heaviest), size="wide"))
        if as_cards()
        else discipline_table(p, heaviest),
        *unassigned,
        Div(H3("Epics"), Small("klaar in de sprint waarin de traagste discipline erdoorheen is"), cls="section-head"),
        queue_cards(p) if as_cards() else queue_table(p),
        left_out(p),
        Div(
            H3("Huidige sprint"),
            Small(
                f"{p.current_sprint.tasks} taken in de huidige sprintgroep, Done meegeteld · "
                f"beschikbaarheid voor het kwartaal{dam}"
            ),
            cls="section-head",
        ),
        sprint_load(p.current_sprint),
        Div(
            H3("Volgende sprint"),
            Small(
                f"{p.next_sprint.tasks} open taken in de groep Next sprint · "
                f"beschikbaarheid voor de komende sprint{dam}"
            ),
            cls="section-head",
        ),
        sprint_load(p.next_sprint),
        cls="viz",
        id="planning",
    )


@rt("/planning")
def planning_page(
    sprint_end: str = "",
    end: str = "",
    layer: list[str] | None = None,
    dam: str = ANY_PORTFOLIO,
    this_quarter: bool = False,
) -> Any:
    """The planning. The numbers arrive on their own request, behind a spinner: a cold
    cache means reading the epic board and four smaller reads."""
    layers = planning.parse_layers(layer)
    return page(
        "Planning",
        "Geplande STP per discipline tegen de capaciteit, en welke epics we daarmee afkrijgen.",
        planning_filters(sprint_end, end, layers, dam, this_quarter),
        Div(
            P(Small("De planningsborden worden geladen…"), aria_busy="true"),
            id="planning",
            hx_get=planning_view.to(
                sprint_end=sprint_end,
                end=end,
                layer=list(layers),
                dam=dam,
                **({"this_quarter": 1} if this_quarter else {}),
            ),
            hx_trigger="load",
            hx_swap="outerHTML",
        ),
    )


@rt
def planning_view(
    sprint_end: str = "",
    end: str = "",
    layer: list[str] | None = None,
    dam: str = ANY_PORTFOLIO,
    this_quarter: bool = False,
    refresh: int = 0,
) -> Any:
    """The section under the filters. The dates ride back out of band, so the fields show
    the window the plan settled on rather than a blank. The plan starts the day after the
    sprint end — the Sprint page's guess unless one is typed in."""
    layers = planning.parse_layers(layer)
    try:
        snapshot = planning_cache(refresh=bool(refresh))
        current = as_date(sprint_end) if sprint_end else snapshot.current_end
        if current is None:
            raise ValueError(f"{sprint_end!r} is geen datum: verwacht JJJJ-MM-DD")
        w = planning.window(current, end=end)
    except FETCH_ERRORS as exc:
        return error(exc, id="planning")
    p = planning.plan(snapshot, w, layers, dam, this_quarter)
    return (
        planning_section(p),
        planning_date_fields(str(current), str(w.end))(hx_swap_oob="true"),
    )


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
