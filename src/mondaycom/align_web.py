"""The alignment app: the kwartaalplanbord and monday.com side by side — temporary.

A separate FastHTML app on its own port (`monday align-web`, 5002), deliberately not a
page of `monday web`: it exists to get the two plans to agree, and goes when they do.
The logic is in `align.py`; this module only shows it and takes the decisions.

- **Vergelijking** (`/`): one row per epic — the board's STP and split, monday.com's
  STP-TODO and split, the difference (marked past 10% of monday.com's), and three fields
  to decide: the total we want, where to change it, and why. Every field saves on change.
- **Acties** (`/acties`): every open action grouped by person, with the message to send
  them already written — copy it, or open it in the mail client — and a status to track.

monday.com is read once (~20s, the sprint boards) and cached in `_MONDAY`; the board dump
and the decisions file are re-read on every request, so a new dump is picked up at once.
Every route that changes the decisions does so in `editing()`, and `ChangedMiddleware`
then tells the page (`HX-Trigger: gewijzigd`), so the "niet opgeslagen" banner follows.

**Only the app itself may use it.** It writes to monday.com with the token and to disk, so
every route that changes something is POST-only (`@app.post`), and `localonly.middleware()`
refuses what another website sends through the browser — see `localonly.py`.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fasthtml.common import (
    H1,
    H3,
    A,
    Button,
    Datalist,
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
    Option,
    P,
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
    Textarea,
    Th,
    Thead,
    Title,
    Tr,
    Ul,
    fast_app,
)
from starlette.middleware import Middleware
from starlette.responses import Response

from mondaycom import align, align_export, cards, chart, forms, localonly, lookups, planning, project, theme
from mondaycom.align import Row
from mondaycom.client import MondayClient, MondayError
from mondaycom.config import DISCIPLINES, ME, as_date

APP_NAME = "Afstemming kwartaalplanning"

FETCH_ERRORS = (MondayError, ValueError, RuntimeError, OSError)

#: The last monday.com read — see `monday`. Held under `_FETCH_LOCK`, so two cold requests
#: wait for one read instead of starting two.
_MONDAY: list[align.Monday] = []
_FETCH_LOCK = threading.Lock()

SORTS = {"dpr": "DPR", "verschil": "Grootste verschil (STP)", "procent": "Grootste verschil (%)"}
KINDS = {"": "Alle epics", **align.KINDS_NL}

CSS = """
main.afstem { max-width: 1600px; padding-inline: 1.5rem; }
.afstem table { font-size: .86rem; }
.afstem td, .afstem th { vertical-align: top; padding: .45rem .5rem; }
.afstem input, .afstem select, .afstem textarea, .afstem button.small {
  font-size: .82rem; padding: .25rem .45rem; margin: 0 0 .25rem; height: auto; }
.afstem textarea { min-height: 4.2rem; min-width: 14rem; }
.afstem input[name=wanted] { width: 5.5rem; }
.afstem .sub { display: block; color: var(--text-muted); font-size: .78rem; line-height: 1.35; }
.afstem .warn { display: block; color: var(--tone-warning); font-size: .78rem; }
.afstem .big { font-size: 1.05rem; font-weight: 700; }
.afstem td.flag { background: color-mix(in srgb, var(--tone-warning) 16%, transparent); }
.afstem td.flag .big { color: var(--heading); }
.afstem td.acties { min-width: 19rem; }
.afstem .acties ul { margin: 0 0 .35rem; padding: 0; list-style: none; }
.afstem .acties li { margin: 0 0 .35rem; padding: 0; list-style: none; }
.afstem .acties li.klaar { opacity: .55; text-decoration: line-through; }
.afstem .table-wrap { overflow-x: auto; }
.afstem .acties form { display: grid; grid-template-columns: 1fr 7rem auto; gap: .25rem; margin: 0; }
.afstem .acties select { width: auto; display: inline-block; }
.afstem form.koppel { display: flex; gap: .25rem; margin: .25rem 0 0; }
.afstem form.koppel input { width: 7rem; }
#filters .filters + .filters { border-top: 1px solid var(--line); padding-top: .6rem; margin-top: .2rem; }
.afstem .disc { max-width: 40rem; }
.afstem .bericht { white-space: pre-wrap; font-size: .82rem; background: var(--card-bg, transparent);
  border: 1px solid var(--line); border-radius: 6px; padding: .75rem; }
.opslag { border-left: 4px solid var(--tone, var(--line)); padding: .55rem .8rem; margin: 0 0 1rem;
  border-radius: 6px; background: color-mix(in srgb, var(--tone, var(--line)) 12%, transparent); }
.opslag.quiet { background: none; padding: .2rem .8rem; }
.opslag button.small { margin-left: .5rem; }
#opslaan-form .filters { grid-template-columns: 14rem minmax(20rem, 1fr) 18rem; }
.page-tools { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem 1rem; }
.autosave { display: flex; flex-wrap: wrap; align-items: center; gap: .3rem .6rem; }
.autosave label.switch { margin: 0; padding: 0; font-size: .9rem; }
.afstem .autosave select { width: auto; margin: 0; }
.page-tools .autosave { flex-wrap: nowrap; white-space: nowrap; }
.afstem .autosave .sub { margin: 0; align-self: center; line-height: 1.2; }
#opslaan-form .autosave { align-self: end; padding-bottom: var(--pico-spacing); }
.folder-field { display: flex; gap: .35rem; align-items: stretch; }
.folder-field input { flex: 1; margin-bottom: 0; }
.folder-field button { width: auto; margin: 0; white-space: nowrap; }
#mapkiezer { font-size: .9rem; }
#mapkiezer button.map-link { width: auto; display: inline-block; padding: .2rem .55rem; margin: 0 .3rem .3rem 0;
  font-size: .85rem; }
#mapkiezer .map-snel, #mapkiezer .map-pad { margin-bottom: .6rem; }
#mapkiezer .map-pad .sep { color: var(--text-muted); margin-right: .3rem; }
#mapkiezer ul.map-lijst { list-style: none; padding: 0; margin: 0 0 .8rem; columns: 2 14rem; }
#mapkiezer ul.map-lijst li { list-style: none; break-inside: avoid; margin: 0; }
#mapkiezer ul.map-lijst button { text-align: left; }
#mapkiezer form.map-nieuw { display: flex; gap: .35rem; margin: 0 0 .8rem; }
#mapkiezer form.map-nieuw input { flex: 1; margin: 0; }
#mapkiezer form.map-nieuw button, #mapkiezer .map-kies button { width: auto; margin: 0; }
#mapkiezer .map-kies { display: flex; flex-wrap: wrap; align-items: center; gap: .6rem; margin-bottom: .6rem; }
#mapkiezer .map-nieuw { border-bottom: 1px solid var(--line); padding-bottom: .7rem; }
#mapkiezer .map-pad .map-link:last-child { margin-left: .6rem; }
.afstem .persoon { border-top: 1px solid var(--line); padding-top: 1rem; margin-top: 1rem; }
.afstem button.small, .afstem a.small[role=button] { width: auto; font-size: .82rem; padding: .25rem .6rem; margin: 0; }
"""

COPY_JS = """
function kiesMap(btn) {
  var field = document.querySelector('#opslaan-form [name=folder]');
  field.value = btn.dataset.folder;
  btn.closest('dialog').close();
  document.querySelector('#opslaan-form button[type=submit]').focus();
}
function kopieer(btn, id) {
  navigator.clipboard.writeText(document.getElementById(id).innerText).then(function () {
    var was = btn.textContent; btn.textContent = 'Gekopieerd'; setTimeout(function () { btn.textContent = was; }, 1500);
  });
}
"""


@cache
def monday_client() -> MondayClient:
    """The one client every route shares, made on first use."""
    return MondayClient()


def close_client() -> None:
    if monday_client.cache_info().currsize:
        monday_client().close()


#: The `gewijzigd` flag of the request being served — see `ChangedMiddleware`.
_CHANGED: ContextVar[list[bool] | None] = ContextVar("gewijzigd", default=None)


class ChangedMiddleware:
    """Adds `HX-Trigger: gewijzigd` to a response whose route changed the decisions.

    A route marks it through `editing()`, so no route has to remember the header. A plain
    ASGI middleware, like `web.WeergaveMiddleware`: the flag is a list set in the request's
    own context, which the thread a sync handler runs in shares.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        changed: list[bool] = []
        token = _CHANGED.set(changed)

        async def tell(message: Any) -> None:
            if message["type"] == "http.response.start" and changed:
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"hx-trigger"]
                before = [v for k, v in message.get("headers", []) if k.lower() == b"hx-trigger"]
                headers.append((b"hx-trigger", b", ".join([*before, b"gewijzigd"])))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, tell)
        finally:
            _CHANGED.reset(token)


@contextmanager
def editing() -> Iterator[align.State]:
    """`align.editing()`, and the response says the decisions changed."""
    with align.editing() as state:
        yield state
    flag = _CHANGED.get()
    if flag is not None:
        flag.append(True)


app, rt = fast_app(
    title=APP_NAME,
    hdrs=(
        theme.theme_script(),
        Script(COPY_JS),
        Style(theme.THEME_CSS),
        Style(chart.CHART_CSS),
        Style(forms.CSS),
        Style(cards.CARDS_CSS),  # the dialog's look, shared with the sprint board
        Style(CSS),
    ),
    htmlkw={"lang": "nl", "data-theme": "light"},
    middleware=[*localonly.middleware(), Middleware(ChangedMiddleware)],
    on_shutdown=[close_client],
)


def monday(refresh: bool = False) -> align.Monday:
    """monday.com as last read; read now when cold or asked to. Never call it holding
    `align.STATE_LOCK`: a cold read takes twenty seconds."""
    with _FETCH_LOCK:
        if refresh or not _MONDAY:
            _MONDAY[:] = [align.fetch_monday(monday_client())]
        return _MONDAY[0]


def default_quarter_end(board: align.Kwartaalbord, mon: align.Monday) -> date:
    """The Planning page's default quarter end: the quarter after the current sprint."""
    return planning.window(mon.current_end).end if mon.current_end else board.quarter_end


def all_rows(state: align.State, mon: align.Monday, board: align.Kwartaalbord | None = None) -> list[Row]:
    """Every row any filter could show — every layer — so a decision, a message or the copy
    can always find its row. Computed against `state` itself."""
    board = board or align.load_board()
    every = align.Selection(default_quarter_end(board, mon), layers=tuple(planning.LAYERS))
    return align.compare(board, mon, state, every)


def find_row(key: str, state: align.State, mon: align.Monday) -> Row | None:
    return next((r for r in all_rows(state, mon) if r.key == key), None)


def slug(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", key)


def people_names(board: align.Kwartaalbord, mon: align.Monday) -> list[str]:
    """monday.com's full names, plus the planners' first names nobody on monday.com has."""
    full = [p.name for p in mon.people]
    extra = [n for n in board.people if not any(f.lower().startswith(n.lower()) for f in full)]
    return sorted(set(full + extra))


def email_for(name: str, mon: align.Monday) -> str:
    """The e-mail of the one person on monday.com the name means — the exact name, else
    the `--person` rule (`lookups.resolve`); nothing when it is ambiguous or unknown."""
    if not name:
        return ""
    exact = [p for p in mon.people if p.name.casefold() == name.casefold()]
    try:
        return (exact[0] if exact else lookups.resolve(mon.people, name)).email
    except lookups.NoMatch:
        return ""


# --- the page around it -----------------------------------------------------------------


def page(title: str, about: str, *content: Any, tools: Any = None) -> Any:
    """Every page: the save banner, the title with its lede and the page's `tools` on the
    right, the two tabs, and the content. Saving is not a tab: it is a button among the tools."""
    links = (("Vergelijking", index), ("Acties", acties))
    return (
        Title(f"{title} · {APP_NAME}"),
        theme.brandbar(APP_NAME),
        Main(
            # The poller holds the banner (`#opslag`) rather than being it: an innerHTML swap
            # into a wrapper of the same id would nest a second `#opslag` on every poll.
            Div(id="opslag-wrap", hx_get=opslag_status, hx_trigger=f"load, every {POLL}s, gewijzigd from:body"),
            Header(
                Div(H1(title), P(about, cls="lede")),
                Div(tools, cls="page-tools") if tools else "",
                cls="page-head",
            ),
            Nav(
                Ul(*[Li(A(label, href=t, aria_current="page" if label == title else None)) for label, t in links]),
                cls="tabs",
                aria_label="Pagina's",
            ),
            *content,
            cls="container page afstem",
        ),
        theme.site_footer(),
    )


def error(exc: Exception) -> Any:
    return Div(P(Strong("monday.com lezen lukte niet: "), str(exc)), id="vergelijking")


# --- the comparison ---------------------------------------------------------------------


def breakdown(points: dict[str, float]) -> str:
    parts = [f"{align.SHORT[d]} {align.fmt(points[d])}" for d in DISCIPLINES if points.get(d)]
    return " · ".join(parts) or "geen punten"


def diff_cell(r: Row) -> Any:
    if r.diff is None:
        return Td("—", Small("alleen " + ("monday.com" if r.monday else "database"), cls="sub"))
    ratio = r.ratio or 0.0
    pct = "∞" if ratio == float("inf") else f"{ratio * 100:+.0f}%"
    words = "meer in de database" if r.diff > 0 else "minder in de database" if r.diff < 0 else "gelijk"
    body = Span(f"{r.diff:+g}".replace("+0", "0"), cls="big"), Small(f"{pct} · {words}", cls="sub")
    if r.flagged:
        return Td(*body, chart.tag("> 10%", "warning"), cls="flag", title="Meer dan 10% van monday.com af")
    return Td(*body)


def link_form(epic: align.BoardEpic, current_dpr: str, open_: bool) -> Any:
    form = Form(
        Input(name="dpr", value=current_dpr, placeholder="DPR-…", aria_label="DPR-nummer"),
        Input(type="hidden", name="epic", value=epic.id),
        Button("Koppel", cls="small secondary"),
        hx_post=koppel,
        hx_swap="none",
        cls="koppel",
    )
    if open_:
        return form
    return Details(Summary(Small("koppeling wijzigen")), form)


def board_cell(r: Row) -> Any:
    if not r.board:
        return Td("—", Small("niet in het kwartaalplanbord", cls="sub"))
    return Td(
        Span(align.fmt(r.board_total), cls="big"),
        Small(breakdown(r.board_points), cls="sub"),
        Small(f"verdeling {align.split_text(r.board_split)}", cls="sub"),
    )


def monday_cell(r: Row) -> Any:
    sid = f"monday-{slug(r.key)}"
    if not r.monday:
        return Td("—", Small("geen epic op monday.com", cls="sub"), id=sid)
    m = r.monday
    shares = {d: r.monday_share(d) for d in DISCIPLINES}
    parts: list[Any] = [
        Span(align.fmt(m.todo), cls="big"),
        Small("STP-TODO" if m.split and m.split.has_todo else "geen STP-TODO", cls="sub"),
        Small(breakdown(shares), cls="sub"),
        Small(f"verdeling {align.split_text(r.monday_split)}", cls="sub"),
        Small(f"sprintborden: {align.fmt(m.points.remaining)} open · {align.fmt(m.points.done)} klaar", cls="sub"),
    ]
    if r.split_differs:
        target = align.split_text(r.board_split)
        parts.append(
            Button(
                f"Verdeling {target} → monday.com",
                hx_post=verdeling,
                hx_vals={"key": r.key},
                hx_target=f"#{sid}",
                hx_swap="outerHTML",
                hx_confirm=f"De verdeling van {r.dpr} op monday.com op {target} zetten?",
                cls="small secondary",
            )
        )
    return Td(*parts, id=sid)


def wanted_words(r: Row, d: align.Decision) -> str:
    if d.wanted is None:
        return ""
    out = []
    if r.monday:
        out.append(f"monday.com {d.wanted - r.monday.todo:+g}")
    if r.board:
        out.append(f"database {d.wanted - r.board_total:+g}")
    return " · ".join(out)


def wanted_span(r: Row, d: align.Decision, oob: bool = False) -> Any:
    return Small(wanted_words(r, d), cls="sub", id=f"gewenst-{slug(r.key)}", hx_swap_oob="true" if oob else None)


def decision_cells(r: Row, state: align.State) -> list[Any]:
    d = state.decision(r.key)
    group = f"b-{slug(r.key)}"
    save = {
        "hx_post": bewaar,
        "hx_include": f".{group}",
        "hx_vals": {"key": r.key},
        "hx_swap": "none",
        "cls": group,
    }
    return [
        Td(
            Input(
                type="number",
                name="wanted",
                value="" if d.wanted is None else f"{d.wanted:g}",
                step="any",
                min="0",
                aria_label="Gewenste STP",
                hx_trigger="change",
                **save,
            ),
            Select(
                *[Option(label, value=k, selected=k == d.where) for k, label in align.WHERE.items()],
                name="where",
                aria_label="Waar aanpassen",
                hx_trigger="change",
                **save,
            ),
            wanted_span(r, d),
        ),
        Td(
            Textarea(
                d.note,
                name="note",
                placeholder="Waarom?",
                aria_label="Toelichting",
                hx_trigger="change, keyup changed delay:1s",
                **save,
            )
        ),
    ]


def status_select(a: align.Action, **hx: Any) -> Any:
    """An action's status, saved the moment it changes."""
    return Select(
        *[Option(s, value=s, selected=s == a.status) for s in align.ACTION_STATES],
        name="status",
        aria_label="Status",
        hx_post=actie_status,
        **hx,
    )


def actions_cell(key: str, state: align.State) -> Any:
    cid = f"acties-{slug(key)}"
    items = [
        Li(
            Strong(a.who or "niemand"),
            " — ",
            a.text,
            " ",
            status_select(a, hx_vals={"id": a.id}, hx_target=f"#{cid}", hx_swap="outerHTML"),
            cls=a.status,
        )
        for a in state.actions_for(key)
    ]
    return Td(
        Ul(*items) if items else "",
        Form(
            Input(name="tekst", placeholder="Nieuwe actie…", aria_label="Actie", required=True),
            Input(name="wie", list="mensen", placeholder="Wie", aria_label="Wie"),
            Button("+", cls="small", title="Actie toevoegen"),
            hx_post=actie,
            hx_vals={"key": key},
            hx_target=f"#{cid}",
            hx_swap="outerHTML",
        ),
        id=cid,
        cls="acties",
    )


def name_cell(r: Row, state: align.State) -> Any:
    parts: list[Any] = []
    if r.monday:
        parts.append(A(r.monday.name, href=r.monday.url, target="_blank", rel="noopener"))
        layer = planning.LAYERS_NL[r.layer] if r.layer else "niet gepland"
        parts.append(Small(f"{r.monday.group_title} · {layer}", cls="sub"))
        if not r.selected:
            parts.append(chart.tag("buiten de selectie", "neutral"))
    for e in r.board:
        label = f"database: {e.name}" if r.monday else e.name
        extra = f" · {e.portfolio}" if e.portfolio else ""
        parts.append(Small(label + extra, cls="sub"))
        if e.afh:
            parts.append(Small(f"afhankelijk van: {e.afh}", cls="sub"))
        parts.append(link_form(e, state.link(e), open_=r.monday is None))
    parts += [Small(w, cls="warn") for w in r.warnings]
    return Td(*parts)


def row_view(r: Row, state: align.State) -> Any:
    dpr = A(r.dpr, href=r.monday.url, target="_blank", rel="noopener") if r.monday and r.dpr else r.dpr or "—"
    return Tr(
        Td(Strong(dpr)),
        name_cell(r, state),
        board_cell(r),
        monday_cell(r),
        diff_cell(r),
        *decision_cells(r, state),
        actions_cell(r.key, state),
        id=f"rij-{slug(r.key)}",
    )


def comparison_table(rows: list[Row], state: align.State) -> Any:
    heads = [
        ("DPR", ""),
        ("Epic", "monday.com-naam, groep; daaronder de naam in de database"),
        ("Database STP", "De punten op het kwartaalplanbord, per discipline, en de verdeling die daaruit volgt"),
        ("monday.com STP", "STP-TODO op Epics-STP-distribution, de verdeling, en wat de sprintborden nu hebben"),
        ("Verschil", "Database min monday.com. Gemarkeerd bij meer dan 10% van monday.com"),
        ("Gewenst STP", "Het totaal dat we willen, en waar dat moet worden aangepast"),
        ("Toelichting", "Waarom we dat besloten"),
        ("Acties", "Wat iemand eerst moet uitzoeken of doen"),
    ]
    return Div(
        Table(
            Thead(Tr(*[Th(h, title=t or None) for h, t in heads])),
            Tbody(*[row_view(r, state) for r in rows]),
        ),
        cls="table-wrap",
    )


def summary(rows: list[Row], state: align.State) -> Any:
    board_total = sum(r.board_total for r in rows)
    monday_total = sum(r.monday_total or 0.0 for r in rows)
    flagged = sum(r.flagged for r in rows)
    decided = sum(state.decision(r.key).wanted is not None for r in rows)
    keys = {r.key for r in rows}
    open_actions = sum(a.status != "klaar" for a in state.actions if a.key in keys)
    tiles = [
        chart.tile("Database", align.fmt(board_total), "STP op het kwartaalplanbord"),
        chart.tile("monday.com", align.fmt(monday_total), "STP-TODO"),
        chart.tile("Verschil", f"{board_total - monday_total:+g}", "database min monday.com"),
        chart.tile(
            "Meer dan 10% af", str(flagged), f"van {len(rows)} epics", "tone-warning" if flagged else "", title=None
        ),
        chart.tile("Besloten", str(decided), "met een gewenst totaal"),
        chart.tile("Open acties", str(open_actions), "nog niet klaar"),
    ]
    per = []
    for d in DISCIPLINES:
        board = sum(r.board_points.get(d, 0.0) for r in rows)
        mon = sum(r.monday_share(d) for r in rows)
        label = f"{d} ({align.SHORT[d]})" if align.SHORT[d] != d else d
        per.append(Tr(Td(label), Td(align.fmt(board)), Td(align.fmt(mon)), Td(f"{board - mon:+.1f}")))
    return Div(
        Div(*tiles, cls="kpis"),
        Details(
            Summary("Per discipline"),
            Table(
                Thead(Tr(Th("Discipline"), Th("Database"), Th("monday.com"), Th("Verschil"))),
                Tbody(*per),
                cls="disc",
            ),
            Small(
                "monday.com per discipline is STP-TODO × de verdeling op Epics-STP-distribution. "
                "Database: Vis = DB, DE = DE, AT = PO/AT, DS = DS.",
                cls="sub",
            ),
            open=True,
        ),
    )


def narrow(rows: list[Row], state: align.State, zoek: str, afwijkend: bool, soort: str, onbesloten: bool) -> list[Row]:
    needle = zoek.strip().lower()
    out = []
    for r in rows:
        if needle and needle not in f"{r.dpr} {r.name} {' '.join(e.name for e in r.board)}".lower():
            continue
        if afwijkend and not r.flagged:
            continue
        if soort and r.kind != soort:
            continue
        if onbesloten and state.decision(r.key).wanted is not None:
            continue
        out.append(r)
    return out


def ordered(rows: list[Row], sorteer: str) -> list[Row]:
    if sorteer == "verschil":
        return sorted(rows, key=lambda r: -abs(r.diff) if r.diff is not None else 1)
    if sorteer == "procent":
        return sorted(rows, key=lambda r: -abs(r.ratio) if r.ratio is not None else 1)
    return rows


def selection_text(sel: align.Selection) -> str:
    due = f"due ≤ {sel.quarter_end.isoformat()}" if sel.this_quarter else ""
    parts = [planning.layers_text_nl(sel.layers), forms.dam_label(sel.dam), due]
    return f"Selectie op monday.com: {' · '.join(p for p in parts if p)}, kwartaal tot {sel.quarter_end.isoformat()}."


def filters(layers: tuple[str, ...] = (planning.PROMISED,)) -> Any:
    """The Planning page's filter row, then the comparison's own. The first picks which
    monday.com epics are planned, exactly as the Planning page does; the second narrows the table."""
    return Form(
        forms.selection_fields("", "", layers, forms.ANY_PORTFOLIO, False),
        Div(
            Label("Zoek", Input(type="search", name="zoek", placeholder="DPR of naam")),
            Label("Toon", Select(*[Option(v, value=k) for k, v in KINDS.items()], name="soort")),
            Label("Sorteer", Select(*[Option(v, value=k) for k, v in SORTS.items()], name="sorteer")),
            Fieldset(
                Legend("Alleen"),
                forms.switch(
                    "afwijkend", "meer dan 10% af", False, "Alleen rijen die meer dan 10% van monday.com afwijken"
                ),
                forms.switch("onbesloten", "nog niet besloten", False, "Alleen rijen zonder gewenst totaal"),
                forms.switch("buiten", "ook buiten de selectie", False, OUTSIDE_HELP),
                cls="layers",
            ),
            cls="filters",
        ),
        Div(
            Button("Toepassen", type="submit"),
            A("Herstellen", href=index, role="button", cls="secondary outline"),
            forms.refresh_button(vergelijking.to(vernieuw=1), "#filters", "#vergelijking"),
            A("Exporteer (markdown)", href=export, role="button", cls="secondary outline"),
            Small(" laden…", id="spinner"),
            cls="actions",
        ),
        id="filters",
        cls="panel",
        hx_get=vergelijking,
        hx_target="#vergelijking",
        hx_swap="outerHTML",
        hx_trigger="change, submit, input delay:300ms from:input[name=zoek], refilter from:body",
        hx_indicator="closest form",
    )


OUTSIDE_HELP = (
    "Ook de epics uit het kwartaalplanbord die op monday.com buiten de selectie vallen, "
    "bijvoorbeeld omdat ze daar in de Backlog staan. Standaard verborgen, zodat de monday.com-totalen "
    "gelijk zijn aan die van de Planning-pagina."
)


def autosave_control(state: align.State) -> Any:
    """The autosave switch and its interval. Each change is saved the moment it is made — it
    is not part of any form's submit — so the switch shows what is stored, on every page.
    Without a folder there is nowhere to save to, so it waits for one."""
    s = state.saving
    live = {
        "hx_post": autosave_zetten,
        "hx_include": "#autosave",
        "hx_target": "#autosave",
        "hx_swap": "outerHTML",
        "hx_trigger": "change",
    }
    where = (
        Small(f"naar {align_export.windows_path(align_export.to_path(s.folder))}", cls="sub")
        if s.folder
        else Small(A("kies eerst een map", href=opslaan), cls="sub")
    )
    return Div(
        Label(
            Input(
                type="checkbox",
                name="autosave",
                role="switch",
                checked=s.autosave and bool(s.folder),
                disabled=not s.folder,
                **live,
            ),
            "Automatisch opslaan",
            cls="switch",
            title="Sla wijzigingen op in je eigen map, hooguit eens per interval",
        ),
        Select(
            *[Option(f"elke {m} min", value=str(m), selected=m == s.minutes) for m in align.AUTOSAVE_MINUTES],
            name="minutes",
            aria_label="Interval",
            disabled=not s.folder,
            **live,
        ),
        where,
        id="autosave",
        cls="autosave",
    )


def save_tools(state: align.State) -> Any:
    """The page head's saving tools: autosave, and the way to the settings page."""
    return (autosave_control(state), A("Opslaan…", href=opslaan, role="button", cls="secondary outline small"))


@app.post
def autosave_zetten(autosave: bool = False, minutes: int = 5) -> Any:
    """Store the switch and the interval. Turned on with changes no copy holds yet, it saves
    at once rather than leaving them for the next poll."""
    turning_on = autosave and not align.State.load().saving.autosave
    mon = monday() if turning_on else None
    with editing() as state:
        s = state.saving
        s.autosave = autosave and bool(s.folder)
        s.minutes = minutes if minutes in align.AUTOSAVE_MINUTES else 5
        if mon is not None and s.autosave and state.unsaved:
            save_now(state, mon)
    return autosave_control(state)


@rt
def index() -> Any:
    return page(
        "Vergelijking",
        "Het kwartaalplanbord naast monday.com, gekoppeld op DPR-nummer. De bovenste rij kiest de "
        "monday.com-epics zoals de Planning-pagina dat doet; de tweede rij filtert de tabel.",
        filters(),
        Div(
            P("monday.com lezen… (de sprintborden duren zo'n twintig seconden)", aria_busy="true"),
            id="vergelijking",
            hx_get=vergelijking,
            hx_trigger="load",
            hx_swap="outerHTML",
        ),
        tools=save_tools(align.State.load()),
    )


@rt
def vergelijking(
    sprint_end: str = "",
    end: str = "",
    layer: list[str] | None = None,
    dam: str = "",
    this_quarter: bool = False,
    zoek: str = "",
    soort: str = "",
    sorteer: str = "dpr",
    afwijkend: bool = False,
    onbesloten: bool = False,
    buiten: bool = False,
    vernieuw: bool = False,
) -> Any:
    """The table and its summary. The dates go back out of band, as on the Planning page,
    so the fields show the quarter the selection settled on."""
    layers = planning.parse_layers(layer)
    try:
        mon = monday(refresh=vernieuw)
        board = align.load_board()
        sprint = as_date(sprint_end) if sprint_end else mon.current_end
        if sprint_end and sprint is None:
            raise ValueError(f"{sprint_end!r} is geen datum: verwacht JJJJ-MM-DD")
        w = planning.window(sprint, end=end) if sprint else None
        quarter = w.end if w else default_quarter_end(board, mon)
        sel = align.Selection(quarter, layers, dam, this_quarter)
    except FETCH_ERRORS as exc:
        return error(exc)
    state = align.State.load()
    rows = align.compare(board, mon, state, sel)
    outside = [r for r in rows if not r.selected]
    scoped = rows if buiten else [r for r in rows if r.selected]
    shown = ordered(narrow(scoped, state, zoek, afwijkend, soort, onbesloten), sorteer)
    return (
        Div(
            P(Small(selection_text(sel)), cls="sub"),
            summary(shown, state),
            outside_note(outside) if outside and not buiten else "",
            comparison_table(shown, state),
            Datalist(*[Option(value=n) for n in people_names(board, mon)], id="mensen"),
            id="vergelijking",
        ),
        forms.planning_date_fields(str(sprint or ""), str(quarter))(hx_swap_oob="true"),
    )


def outside_note(outside: list[Row]) -> Any:
    """The board's epics the selection leaves out: hidden, but never silently."""
    stp = sum(r.board_total for r in outside)
    names = ", ".join(
        f"{r.dpr or r.name} ({planning.LAYERS_NL[r.layer] if r.layer else 'niet gepland'})" for r in outside
    )
    return P(
        Small(
            f"{len(outside)} epics uit het kwartaalplanbord ({align.fmt(stp)} STP) vallen op monday.com buiten "
            f"deze selectie en staan niet in de tabel: {names}. Zet “ook buiten de selectie” aan om ze te zien.",
            cls="warn",
        )
    )


def parse_wanted(text: str) -> float | None:
    """The wanted total as typed: blank is "not decided", and a Dutch comma is a point."""
    text = (text or "").strip().replace(",", ".")
    try:
        return float(text) if text else None
    except ValueError:
        return None


@app.post
def bewaar(key: str, wanted: str = "", where: str = "", note: str = "") -> Any:
    mon = monday()
    with editing() as state:
        where = where if where in align.WHERE else ""
        state.decisions[key] = align.Decision(wanted=parse_wanted(wanted), where=where, note=note)
    row = find_row(key, state, mon)
    return wanted_span(row, state.decision(key), oob=True) if row else ""


@app.post
def actie(key: str, tekst: str = "", wie: str = "") -> Any:
    with editing() as state:
        if tekst.strip():
            state.add_action(key, tekst, wie)
    return actions_cell(key, state)


@app.post
def actie_status(id: str, status: str = "open", terug: str = "") -> Any:
    with editing() as state:
        action = state.set_status(id, status)
    if terug == "acties":
        return Response(headers={"HX-Refresh": "true"})
    return actions_cell(action.key, state) if action else ""


@app.post
def koppel(epic: str, dpr: str = "") -> Any:
    text = dpr.strip().upper()
    if text.isdigit():
        text = project.project_number(text)
    with editing() as state:
        state.links[epic] = text
    return Response(headers={"HX-Trigger": "refilter"})


@app.post
def verdeling(key: str) -> Any:
    mon = monday()
    row = find_row(key, align.State.load(), mon)
    if row is None or row.monday is None:
        return ""
    if not row.split_differs:  # nothing to write — and never on the client's word alone
        return monday_cell(row)
    try:
        [written] = align.apply_splits(monday_client(), [row], align.backup_file())
    except FETCH_ERRORS as exc:
        return Td(Small(f"Schrijven lukte niet: {exc}", cls="warn"), id=f"monday-{slug(key)}")
    mon.with_split(written)
    return monday_cell(replace(row, monday=replace(row.monday, split=written)))


# --- the actions ------------------------------------------------------------------------


def mailto(email: str, body: str) -> str:
    subject = quote("Afstemming kwartaalplanning: je acties")
    return f"mailto:{quote(email)}?subject={subject}&body={quote(body)}"


@rt
def acties() -> Any:
    try:
        mon = monday()
    except FETCH_ERRORS as exc:
        return page("Acties", "Open acties per persoon.", error(exc))
    state = align.State.load()
    by_key = {r.key: r for r in all_rows(state, mon)}
    open_ = [a for a in state.actions if a.status != "klaar"]
    people: dict[str, list[align.Action]] = {}
    for a in open_:
        people.setdefault(a.who, []).append(a)
    blocks = []
    for n, (who, items) in enumerate(sorted(people.items(), key=lambda kv: (not kv[0], kv[0].lower()))):
        email = email_for(who, mon)
        text = align.message(who, items, by_key, state, ME)
        pid = f"bericht-{n}"
        blocks.append(
            Div(
                H3(who or "Nog niemand toegewezen", Small(f"  {email}", cls="sub") if email else ""),
                Ul(*[action_line(a, by_key) for a in items]),
                Div(text, id=pid, cls="bericht"),
                Div(
                    Button("Kopieer bericht", type="button", cls="small secondary", onclick=f"kopieer(this, '{pid}')"),
                    " ",
                    A("Open in mail", href=mailto(email, text), role="button", cls="small secondary") if who else "",
                    " ",
                    Button(
                        "Markeer als verstuurd",
                        type="button",
                        cls="small",
                        hx_post=verstuurd,
                        hx_vals={"ids": json.dumps([a.id for a in items if a.status == "open"])},
                        hx_swap="none",
                    )
                    if any(a.status == "open" for a in items)
                    else "",
                ),
                cls="persoon",
            )
        )
    done = [a for a in state.actions if a.status == "klaar"]
    return page(
        "Acties",
        "Open acties per persoon, met het bericht om te sturen. De status houdt bij wat al verstuurd is.",
        *(blocks or [P("Nog geen open acties. Voeg ze toe op de Vergelijking.")]),
        Details(Summary(f"Klaar ({len(done)})"), Ul(*[action_line(a, by_key) for a in done])) if done else "",
        tools=A("Opslaan…", href=opslaan, role="button", cls="secondary outline small"),
    )


def action_line(a: align.Action, by_key: dict[str, Row]) -> Any:
    row = by_key.get(a.key)
    stamp = f"verstuurd {a.sent[:10]}" if a.sent else f"aangemaakt {a.created[:10]}"
    return Li(
        Strong(row.title if row else a.key),
        " — ",
        a.text,
        " ",
        Small(stamp, cls="sub"),
        status_select(a, hx_vals={"id": a.id, "terug": "acties"}, style="width:auto"),
    )


@app.post
def verstuurd(ids: str = "[]") -> Any:
    with editing() as state:
        for action_id in json.loads(ids):
            state.set_status(action_id, "verstuurd")
    return Response(headers={"HX-Refresh": "true"})


@rt
def export() -> Any:
    mon = monday()
    state = align.State.load()
    return Response(
        align.export_markdown(all_rows(state, mon), state),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="afstemming.md"'},
    )


# --- saving a copy ----------------------------------------------------------------------
# The decisions file sits in docs/tmp, which git ignores and nothing backs up. The banner
# says so for as long as there are changes no copy holds yet; the Opslaan tab writes one
# to a folder of the user's choosing, by hand or every few minutes.

#: How often the banner asks — and so how often autosave can notice it is due.
POLL = 60


def when(stamp: str) -> str:
    """`14:05` today, `2026-10-06 14:05` before that."""
    if not stamp:
        return ""
    day, _, time = stamp.partition("T")
    return time[:5] if day == date.today().isoformat() else f"{day} {time[:5]}"


def save_now(state: align.State, mon: align.Monday) -> None:
    """Write the copy and keep the outcome in `state`; an error is shown, not raised. The
    caller saves `state` — `align.editing()` does."""
    try:
        align_export.save_copy(state, all_rows(state, mon))
    except FETCH_ERRORS as exc:
        state.saving.error = str(exc)


def _banner(tone: str, *body: Any, role: str | None = None) -> Any:
    return Div(*body, id="opslag", cls=f"opslag {tone}".strip(), role=role)


def banner(state: align.State) -> Any:
    """Where the decisions are, and how far the user's own copy is behind."""
    s = state.saving
    here = f"docs/tmp/{align.state_path().name}"
    if s.error:
        return _banner(
            "tone-critical", Strong("Opslaan lukte niet: "), s.error, " ", A("Naar Opslaan", href=opslaan), role="alert"
        )
    if not state.unsaved:
        if not s.saved_at:
            return _banner("quiet", Small(f"Je wijzigingen worden lokaal bewaard in {here}."))
        auto = f" Automatisch opslaan: elke {s.minutes} min." if s.autosave and s.folder else ""
        return _banner("quiet tone-good", Small(f"Alles is opgeslagen — {when(s.saved_at)} in {s.saved_to}.{auto}"))
    if not s.folder:
        return _banner(
            "tone-warning",
            Strong("Niet opgeslagen. "),
            f"Je wijzigingen staan alleen in {here}: niet in git, en nergens geback-upt. ",
            A("Kies een map of download een kopie", href=opslaan),
            ".",
            role="status",
        )
    since = f" sinds {when(s.saved_at)}" if s.saved_at else ""
    auto = f" Wordt automatisch opgeslagen (elke {s.minutes} min)." if s.autosave else " Automatisch opslaan staat uit."
    return _banner(
        "tone-warning",
        Strong(f"Niet opgeslagen{since}. "),
        f"Je eigen kopie in {s.folder} loopt achter.{auto} ",
        Button("Nu opslaan", type="button", cls="small", hx_post=nu_opslaan, hx_target="#opslag", hx_swap="outerHTML"),
        role="status",
    )


@rt
def opslag_status() -> Any:
    """The banner — and the moment autosave writes, when it is due. monday.com is only
    asked for when it is: the copy needs the rows, the banner does not."""
    state = align.State.load()
    if align_export.autosave_due(state):
        mon = monday()
        with align.editing() as state:
            if align_export.autosave_due(state):
                save_now(state, mon)
    return banner(state)


@app.post
def nu_opslaan() -> Any:
    mon = monday()
    with align.editing() as state:
        save_now(state, mon)
    return banner(state)


def saving_form(state: align.State) -> Any:
    s = state.saving
    return Form(
        Div(
            Label(
                "Formaat",
                Select(
                    *[Option(label, value=k, selected=k == s.format) for k, label in align.FORMATS.items()],
                    name="format",
                ),
            ),
            Label(
                "Map",
                Span(
                    Input(
                        name="folder",
                        value=s.folder,
                        list="mappen",
                        placeholder=r"bijv. C:\Users\jij\OneDrive - WDODelta\Planning",
                        autocomplete="off",
                    ),
                    Button(
                        "Bladeren…",
                        type="button",
                        cls="secondary outline",
                        title="Kies een map, of maak er een",
                        hx_get=mappen,
                        hx_include="#opslaan-form [name=folder]",
                        hx_target="#mapkiezer",
                        hx_swap="outerHTML",
                        onclick="document.getElementById('mapkiezer-dialog').showModal()",
                    ),
                    cls="folder-field",
                ),
                Datalist(*[Option(value=f) for f in align_export.suggested_folders()], id="mappen"),
                title="Een map buiten de repository. Een Windows-pad (C:\\…) mag ook.",
            ),
            autosave_control(state),
            cls="filters",
        ),
        Div(
            Button("Bewaren en nu opslaan", type="submit"),
            Small(" opslaan…", id="spinner"),
            cls="actions",
        ),
        P(
            Small(
                f"Het bestand heet {align_export.FILE_STEM}.<formaat> en wordt bij elke keer opslaan "
                "overschreven. Excel en Calc krijgen twee tabbladen, Afstemming en Acties; CSV is één tabel "
                "(met ; voor een Nederlandse Excel) met de acties in een kolom; JSON bevat alles.",
                cls="sub",
            )
        ),
        id="opslaan-form",
        cls="panel",
        hx_post=opslaan_instellen,
        hx_target="#opslaan-uitkomst",
        hx_swap="outerHTML",
        hx_indicator="closest form",
    )


def outcome(state: align.State) -> Any:
    s = state.saving
    if s.error:
        body: Any = P(Strong("Opslaan lukte niet: "), s.error, cls="warn")
    elif s.saved_at:
        body = P(f"Laatst opgeslagen {when(s.saved_at)} in ", Strong(s.saved_to), ".")
    else:
        body = P("Nog niet opgeslagen.")
    return Div(body, id="opslaan-uitkomst")


@rt
def opslaan() -> Any:
    state = align.State.load()
    return page(
        "Opslaan",
        f"Je besluiten en acties staan lokaal in docs/tmp/{align.state_path().name}. Die map staat niet in git "
        "(de repository is openbaar) en wordt nergens geback-upt. Bewaar hier een kopie in een eigen map.",
        H3("In een map"),
        saving_form(state),
        outcome(state),
        cards.dialog(
            "Kies een map",
            "Waar je eigen kopie komt. Een map in de repository kan niet: die is openbaar.",
            Div(P("Mappen lezen…", aria_busy="true"), id="mapkiezer"),
        )(id="mapkiezer-dialog"),
        H3("Of download een kopie"),
        P(
            *[
                (
                    A(
                        label,
                        href=download.to(fmt=k),
                        role="button",
                        cls="secondary outline",
                        onclick="setTimeout(function () { htmx.trigger(document.body, 'gewijzigd'); }, 1500)",
                    ),
                    " ",
                )
                for k, label in align.FORMATS.items()
            ]
        ),
        P(
            Small(
                "Je browser bewaart een download in de map die hij daarvoor gebruikt, of vraagt waar. "
                "Een download telt als opgeslagen; automatisch opslaan kan alleen naar een map hierboven.",
                cls="sub",
            )
        ),
        tools=A("← Terug naar de vergelijking", href=index, role="button", cls="secondary outline small"),
    )


def quick_label(folder: str) -> str:
    path = Path(folder)
    return "Thuismap" if path == Path.home() else path.name


def folder_listing(listing: align_export.Listing) -> Any:
    """The dialog's body: quick links, the path, its subfolders, a new folder, and the choice."""

    def go(path: Path, label: str) -> Any:
        return Button(
            label,
            type="button",
            cls="map-link secondary outline",
            hx_get=mappen,
            hx_vals={"folder": str(path)},
            hx_target="#mapkiezer",
            hx_swap="outerHTML",
        )

    path = listing.path
    # On a Windows drive the path starts at `C:`, as its user knows it, not at `/mnt/c`.
    drive = len(path.parts) >= 3 and path.parts[:2] == ("/", "mnt") and len(path.parts[2]) == 1
    crumbs: list[Any] = []
    for depth in range(3 if drive else 1, len(path.parts) + 1):
        part = Path(*path.parts[:depth])
        label = f"{part.name.upper()}:" if drive and depth == 3 else part.name or "/"
        crumbs += [go(part, label), Span("›", cls="sep")]
    folders = [Li(go(f, f"📁 {f.name}")) for f in listing.folders]
    # The choice and "new folder" come before the list: a folder of a hundred subfolders
    # would otherwise push them out of sight.
    choose = Div(
        Strong(align_export.windows_path(path)),
        Button(
            "Kies deze map",
            type="button",
            cls="small",
            data_folder=align_export.windows_path(path),
            onclick="kiesMap(this)",
            disabled=bool(listing.problem),
        ),
        Small(listing.problem, cls="warn") if listing.problem else "",
        cls="map-kies",
    )
    new = Form(
        Input(name="naam", value=listing.missing, placeholder="Nieuwe map hierin", aria_label="Naam nieuwe map"),
        Button("Maak map", cls="small secondary"),
        hx_post=map_maken,
        hx_vals={"folder": str(path)},
        hx_target="#mapkiezer",
        hx_swap="outerHTML",
        cls="map-nieuw",
    )
    return Div(
        Div(
            Small("Snel naar: "),
            *[go(Path(f), quick_label(f)) for f in align_export.suggested_folders()],
            cls="map-snel",
        ),
        Div(*crumbs[:-1], go(listing.parent, "⬆ Omhoog") if listing.parent else "", cls="map-pad"),
        choose,
        "" if listing.problem else new,  # where nothing can be saved, nothing is made either
        P(Small(listing.error, cls="warn")) if listing.error else "",
        Ul(*folders, cls="map-lijst") if folders else P(Small("Hier staan geen mappen.", cls="sub")),
        P(Small(f"Alleen de eerste {align_export.MAX_FOLDERS} mappen.", cls="sub")) if listing.cut else "",
        id="mapkiezer",
    )


@rt
def mappen(folder: str = "") -> Any:
    """One folder of this machine for the dialog — where `folder` points, or the nearest one
    above it that exists. Read-only."""
    return folder_listing(align_export.browse(folder))


@app.post
def map_maken(folder: str = "", naam: str = "") -> Any:
    """Make a folder inside `folder` and open it in the dialog."""
    return folder_listing(align_export.make_folder(folder, naam))


@app.post
def opslaan_instellen(format: str = "xlsx", folder: str = "") -> Any:
    """Store the format and the folder, and save there now. The autosave switch stores itself
    (`autosave_zetten`); it comes back out of band, since a folder is what lets it turn on."""
    mon = monday()
    with editing() as state:
        s = state.saving
        s.format = format if format in align.FORMATS else "xlsx"
        s.folder = folder.strip()
        s.autosave = s.autosave and bool(s.folder)
        save_now(state, mon)
    return outcome(state), autosave_control(state)(hx_swap_oob="true")


@rt
def download(fmt: str = "xlsx") -> Any:
    if fmt not in align.FORMATS:
        return Response("Onbekend formaat", status_code=400)
    try:
        mon = monday()
    except FETCH_ERRORS as exc:
        return Response(f"monday.com lezen lukte niet: {exc}", status_code=502)
    with align.editing() as state:
        data = align_export.render(fmt, all_rows(state, mon), state)
        align_export.record_saved(state, f"een download ({align_export.download_name(fmt)})")
    return Response(
        data,
        media_type=align_export.MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{align_export.download_name(fmt)}"'},
    )


def run(host: str = "127.0.0.1", port: int = 5002, reload: bool = False) -> None:
    import uvicorn

    if reload:
        uvicorn.run(
            "mondaycom.align_web:app", host=host, port=port, reload=True, reload_dirs=[str(Path(__file__).parent)]
        )
    else:
        uvicorn.run(app, host=host, port=port)
