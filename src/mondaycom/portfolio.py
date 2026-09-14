"""The IV Portfolio: every portfolio item, the epics under it, and how far they are.

A portfolio item has no progress of its own. Its story points are the story points of
the epics linked to it, which are themselves summed from the two sprint boards — so
this module is one board read plus an inversion of a link, and every number in it comes
from `epics.fetch_epics`.

**The link only exists on the epic side.** The IV Portfolio board carries no connect
column back to the epic board, so "which epics belong to this item" is answered by
walking the epics and grouping them by their `portfolio_ids`. An epic naming a
portfolio item the board does not return is reported rather than dropped, exactly as
`epics` reports tasks that belong to no epic.

A portfolio item is **stuck** when any of its epics is: on Impediment itself, or held
up by a task that is. The blocked epics travel with the item so a row can name them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cached_property
from typing import Any

from mondaycom import queries
from mondaycom.client import MondayClient
from mondaycom.config import PORTFOLIO_BOARD, PORTFOLIO_URGENCIES, Board, item_url
from mondaycom.epics import BUCKETS as BUCKETS  # the four progress buckets are an epic's, unchanged
from mondaycom.epics import Epic, Points, fetch_epics
from mondaycom.sorting import Sorting, label_key


@dataclass
class PortfolioItem:
    """One row of the portfolio overview: an IV Portfolio item and the epics under it."""

    id: str
    name: str
    #: "Doelstelling" — the programme the item sits in. Filled on every item today.
    goal: str = ""
    #: "Urgentie": Hoog / Middel / Laag, and blank on two thirds of the board.
    urgency: str = ""
    #: "Type": Initiatief or Project.
    type: str = ""
    #: "Projectleider" — a text column, not a people column, so there is no avatar.
    lead: str = ""
    start: str = ""
    end: str = ""
    #: The item's page in Fortes, the portfolio tool of record.
    link: str = ""
    #: Its Fortes id, which is how people refer to it in Fortes.
    ref: str = ""
    #: The epics linked to this item, already carrying their own point totals.
    epics: tuple[Epic, ...] = ()

    @property
    def url(self) -> str:
        """The item's page on monday.com."""
        return item_url(PORTFOLIO_BOARD, self.id)

    @cached_property
    def points(self) -> Points:
        """The epics' points, added up. Cancelled work leaves the total, as everywhere.

        Cached because a rendered row asks for it a dozen times over — and `attach`
        builds fresh items per request, so there is nothing here to go stale.
        """
        return sum((e.points for e in self.epics), Points())

    @property
    def done(self) -> float:
        return self.points.done

    @property
    def remaining(self) -> float:
        return self.points.remaining

    @property
    def total(self) -> float:
        """Committed points, cancelled work excluded — the battery's full width."""
        return self.points.total

    @property
    def fraction_done(self) -> float:
        """How full the battery is, or `epics.NO_TASKS` when there is nothing to fill it."""
        return self.points.fraction_done

    @property
    def bucket(self) -> str:
        """Which progress filter this item answers to — the same four as an epic's."""
        return self.points.bucket

    @property
    def is_empty(self) -> bool:
        """No epics link here at all. 166 of the board's 177 items are like this today."""
        return not self.epics

    @property
    def stuck_epics(self) -> tuple[Epic, ...]:
        """The epics holding this item up, blocked ones first, then the biggest blockers."""
        blocked = (e for e in self.epics if e.is_stuck)
        return tuple(sorted(blocked, key=lambda e: (not e.is_blocked, -len(e.impediments), e.name.lower())))

    @property
    def is_stuck(self) -> bool:
        return any(e.is_stuck for e in self.epics)

    @property
    def impediments(self) -> int:
        """How many tasks are blocking this item, across all of its epics."""
        return sum(len(e.impediments) for e in self.epics)

    @classmethod
    def from_item(cls, item: dict[str, Any], board: Board = PORTFOLIO_BOARD) -> PortfolioItem:
        raw = {col["id"]: (col.get("text") or "").strip() for col in item.get("column_values", [])}
        return cls(
            id=str(item["id"]),
            name=item["name"],
            goal=raw.get(board.column("goal"), ""),
            urgency=raw.get(board.column("urgency"), ""),
            type=raw.get(board.column("type"), ""),
            lead=raw.get(board.column("lead"), ""),
            start=raw.get(board.column("start"), ""),
            end=raw.get(board.column("end"), ""),
            link=raw.get(board.column("link"), ""),
            ref=raw.get(board.column("ref"), ""),
        )


def fetch_items(client: MondayClient, board: Board = PORTFOLIO_BOARD) -> list[PortfolioItem]:
    """Every IV Portfolio item, without its epics. One page covers the board today."""
    items = client.all_board_items(lambda cursor: queries.portfolio_rows(board, cursor))
    return [PortfolioItem.from_item(item, board=board) for item in items]


#: Epics sit under a portfolio item in the order the overview reads best: blocked first,
#: then the most work left, so what needs attention is at the top.
def _epic_order(epic: Epic) -> tuple[Any, ...]:
    return (not epic.is_stuck, -epic.remaining, -epic.done, epic.name.lower())


def attach(items: list[PortfolioItem], epics: list[Epic]) -> list[PortfolioItem]:
    """Group `epics` under the portfolio items they link to, and return fresh rows.

    Cheap enough to redo on every request, which is what the web UI does: the epic board
    is the expensive read and it is cached separately, so re-attaching keeps the two
    from drifting when one of them is refreshed.
    """
    grouped: dict[str, list[Epic]] = {}
    for epic in epics:
        for portfolio_id in epic.portfolio_ids:
            grouped.setdefault(portfolio_id, []).append(epic)
    return [replace(item, epics=tuple(sorted(grouped.get(item.id, ()), key=_epic_order))) for item in items]


def orphan_epics(items: list[PortfolioItem], epics: list[Epic]) -> list[Epic]:
    """Epics linked to a portfolio item this board did not return — reported, not dropped."""
    known = {item.id for item in items}
    return [e for e in epics if e.portfolio_ids and not any(p in known for p in e.portfolio_ids)]


def fetch_portfolio(client: MondayClient) -> tuple[list[PortfolioItem], list[Epic]]:
    """The whole picture in one call, for the CLI: portfolio items with epics attached.

    Reads the epic board and both sprint boards, so it is the same twenty seconds
    `epics.fetch_epics` costs plus one cheap request. The web UI does not use this — it
    caches the two halves separately.
    """
    rows, _ = fetch_epics(client)
    return attach(fetch_items(client), rows), rows


# --- sorting and filtering -------------------------------------------------------------


#: Every column the overview shows, and how it sorts. Urgentie sorts most-urgent-first
#: rather than alphabetically; blank text sorts last either way.
SORTS: dict[str, Any] = {
    "name": lambda p: (not p.name, p.name.lower()),
    "goal": lambda p: (not p.goal, p.goal.lower()),
    "type": lambda p: (not p.type, p.type.lower()),
    "urgency": lambda p: (not p.urgency, label_key(PORTFOLIO_URGENCIES, p.urgency)),
    "lead": lambda p: (not p.lead, p.lead.lower()),
    "stuck": lambda p: (p.is_stuck, p.impediments),
    "epics": lambda p: len(p.epics),
    "done": lambda p: p.done,
    "remaining": lambda p: p.remaining,
    "progress": lambda p: (p.fraction_done, p.total),
}

#: Least complete first. Progress is what the page is about, and "how far is everything"
#: is more useful opened on the emptiest batteries than on the alphabet. An item with no
#: points at all sorts last, exactly as it does on the epics page.
DEFAULT_SORT = "progress"

#: Columns whose first click sorts high-to-low — the counts and the meters.
NUMERIC_SORTS = frozenset({"epics", "done", "remaining", "progress", "stuck"})

SORTING = Sorting(keys=SORTS, default=DEFAULT_SORT, numeric=NUMERIC_SORTS)


@dataclass(frozen=True)
class Filters:
    """One narrowing value per column. Empty means "do not filter on this one".

    `empty` is the odd one out: it *widens*. 166 of the board's 177 items have no epics
    linked and therefore no progress to show, so they are hidden unless it is set.
    """

    search: str = ""
    goal: str = ""
    type: str = ""
    urgency: str = ""
    lead: str = ""
    bucket: str = ""
    stuck: bool = False
    empty: bool = False


def matches(item: PortfolioItem, f: Filters) -> bool:
    """Whether `item` survives every filter that is set."""
    if item.is_empty and not f.empty:
        return False
    if f.search and f.search.casefold() not in item.name.casefold():
        return False
    if f.goal and item.goal != f.goal:
        return False
    if f.type and item.type != f.type:
        return False
    if f.urgency and item.urgency != f.urgency:
        return False
    if f.lead and f.lead not in item.lead:
        return False
    if f.stuck and not item.is_stuck:
        return False
    return not (f.bucket and item.bucket != f.bucket)


def arrange(
    items: list[PortfolioItem], filters: Filters | None = None, sort: str = DEFAULT_SORT, desc: bool = False
) -> list[PortfolioItem]:
    """Filter, then sort. An unknown sort key falls back to the default rather than raising."""
    kept = [item for item in items if matches(item, filters or Filters())]
    return SORTING.apply(kept, sort, desc)


def parse_sort(spec: str) -> tuple[str, bool]:
    """Split a sort spec into its column and direction: ``"-done"`` is done, descending."""
    return SORTING.parse(spec)


def next_sort(column: str, spec: str) -> str:
    """The spec a click on `column`'s header should ask for, given the current one."""
    return SORTING.next(column, spec)


def totals(items: list[PortfolioItem]) -> Points:
    """The headline numbers above the table: the whole selection as one battery."""
    return sum((i.points for i in items), Points())


def options(items: list[PortfolioItem], of: str) -> list[str]:
    """The distinct values of one column, for that column's filter dropdown.

    Built from the rows actually fetched, so no dropdown offers a choice that comes back
    empty. Urgentie keeps its own order; everything else goes alphabetical.
    """
    seen = {getattr(item, of) for item in items}
    seen.discard("")
    if of == "urgency":
        return sorted(seen, key=lambda v: label_key(PORTFOLIO_URGENCIES, v))
    return sorted(seen, key=str.lower)
