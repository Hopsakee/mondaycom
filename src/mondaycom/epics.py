"""The epics overview: every epic, its state, and how much of it is burnt down.

An epic's progress is not recorded on the epic. The board carries "STP gedaan" and
friends as mirror columns, but a mirror returns its *members* over the API — a
`display_value` of ``"2, 1, 3"`` rather than the 6 the UI shows — so the totals here
are summed from the tasks themselves, on both sprint boards: what is still open on
"Sprint bord, actief" is remaining, what has been archived to "Sprint bord, done" is
done. Cancelled work leaves both sides, exactly as it does in the burndown.

"DAM" is the epic board's own formula ``IF({Portfolio#Count} > 0, …)``: an epic counts
as DAM work when it is linked to an item on the IV Portfolio board. We read that link
rather than the formula, so the two are the same question asked directly.

Being **stuck** is read the same way — from the work, not from a column. An epic is
stuck when it sits on Impediment itself *or* when any of its tasks does, and the tasks
that block it are carried along by name so the overview can link straight to them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from mondaycom import queries
from mondaycom.client import MondayClient
from mondaycom.config import (
    CANCELLED_STATUSES,
    DAM,
    DONE_STATUS,
    DUMMY_GROUPS,
    EPIC_BOARD,
    EPIC_DROPPED_STATUSES,
    EPIC_PRIORITIES,
    EPIC_STATUSES,
    IMPEDIMENT_STATUS,
    NON_DAM,
    TASK_BOARDS,
    Board,
    as_number,
    item_url,
)
from mondaycom.sorting import Sorting, label_key

#: An epic with no tasks at all sorts last on progress rather than as 0%: there is
#: nothing to be behind on. Anything above 1.0 does that without a special case.
NO_TASKS = 2.0


@dataclass(frozen=True)
class Impediment:
    """One task sitting on Impediment, and where to open it on monday.com.

    Named and addressed, not counted: "this epic is blocked" is only actionable if you
    can get to the thing doing the blocking. `board` is the board's own name, because
    a blocker parked on the done board reads very differently from one on the active one.
    """

    id: str
    name: str
    board: str
    url: str


@dataclass
class Points:
    """Story points for one epic, split the way the battery draws them."""

    done: float = 0.0
    remaining: float = 0.0
    #: Dropped work ("Vervallen"). Reported, never counted — it leaves the total.
    cancelled: float = 0.0
    tasks: int = 0

    def __add__(self, other: Points) -> Points:
        """Roll two batteries into one, so `sum(…, Points())` adds every field there is."""
        return Points(
            done=self.done + other.done,
            remaining=self.remaining + other.remaining,
            cancelled=self.cancelled + other.cancelled,
            tasks=self.tasks + other.tasks,
        )

    def record(self, status: str, points: float) -> None:
        """Fold one task in, on the side its status puts it. The only place that rule lives."""
        self.tasks += 1
        if status in CANCELLED_STATUSES:
            self.cancelled += points
        elif status == DONE_STATUS:
            self.done += points
        else:
            self.remaining += points

    @property
    def total(self) -> float:
        """Committed points, cancelled work excluded — the battery's full width."""
        return self.done + self.remaining

    @property
    def fraction_done(self) -> float:
        """How full the battery is, or `NO_TASKS` when there is nothing to fill it with."""
        return self.done / self.total if self.total else NO_TASKS

    @property
    def bucket(self) -> str:
        """Which progress filter this battery answers to."""
        if not self.total:
            return "no-tasks"
        if not self.done:
            return "not-started"
        return "complete" if not self.remaining else "in-progress"


@dataclass
class Epic:
    """One row of the epics overview."""

    id: str
    name: str
    owner: str = ""
    status: str = ""
    priority: str = ""
    #: The linked IV Portfolio item's name, from `display_value`; `text` is null here.
    portfolio: str = ""
    portfolio_ids: tuple[str, ...] = ()
    points: Points = field(default_factory=Points)
    #: The epic's own tasks that sit on Impediment. Empty is the normal case.
    impediments: tuple[Impediment, ...] = ()

    @property
    def is_dam(self) -> bool:
        """Linked to the IV Portfolio board, i.e. what the board's DAM formula calls true."""
        return bool(self.portfolio_ids)

    @property
    def is_blocked(self) -> bool:
        """Whether the epic itself was put on Impediment, tasks or no tasks."""
        return self.status == IMPEDIMENT_STATUS

    @property
    def is_stuck(self) -> bool:
        """Blocked from either side: the epic's own status, or a task holding it up."""
        return self.is_blocked or bool(self.impediments)

    @property
    def url(self) -> str:
        """The epic's page on monday.com."""
        return item_url(EPIC_BOARD, self.id)

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
        """How full the battery is, or `NO_TASKS` when there is nothing to fill it with."""
        return self.points.fraction_done

    @property
    def is_dropped(self) -> bool:
        """Left the workflow unfinished (Afgevallen, Overgedragen) — hidden unless asked for."""
        return self.status in EPIC_DROPPED_STATUSES

    @property
    def bucket(self) -> str:
        """Which progress filter this epic answers to."""
        return self.points.bucket

    @classmethod
    def from_item(cls, item: dict[str, Any], board: Board = EPIC_BOARD) -> Epic:
        cells = board.cells(item)
        return cls(
            id=str(item["id"]),
            name=item["name"],
            owner=cells.text("owner"),
            status=cells.text("status"),
            priority=cells.text("priority"),
            portfolio=cells.text("portfolio"),
            portfolio_ids=cells.linked("portfolio"),
        )


@dataclass
class BoardTally:
    """What one walk over a task board yields — the three questions the overview asks."""

    #: Points per linked epic id.
    tally: dict[str, Points] = field(default_factory=dict)
    #: Points on tasks that link to no epic: real work the overview cannot place.
    orphans: Points = field(default_factory=Points)
    #: Blocked tasks, by the epic they are holding up.
    impediments: dict[str, list[Impediment]] = field(default_factory=dict)


def walk_tasks(items: list[dict[str, Any]], board: Board) -> BoardTally:
    """One pass over a board's tasks: points per epic, the orphans, and the blockers.

    Three questions, one walk — all three read the same epic link, status and estimate
    off the same row, and there are 2400 of them. A task on the done board is done and a
    task on the active board usually is not, but the status is what decides: the done
    board does hold the odd unfinished row. Tasks in a board's dummy-story group are
    placeholders and are skipped entirely.
    """
    skip = DUMMY_GROUPS.get(board.id, set())
    epic_col, points_col, status_col = (board.column(a) for a in ("epic", "story_points", "status"))
    out = BoardTally()
    for item in items:
        if (item.get("group") or {}).get("id") in skip:
            continue
        raw = {col["id"]: col for col in item.get("column_values", [])}
        linked = raw.get(epic_col, {}).get("linked_item_ids") or []
        points = as_number(raw.get(points_col, {}).get("text") or "")
        status = raw.get(status_col, {}).get("text") or ""

        if not linked:
            # Reported under the table rather than silently absorbed.
            out.orphans.record(status, points)
            continue

        # A task linked to two epics would otherwise be counted twice; credit the first.
        epic_id = str(linked[0])
        out.tally.setdefault(epic_id, Points()).record(status, points)
        if status == IMPEDIMENT_STATUS:
            item_id = str(item["id"])
            out.impediments.setdefault(epic_id, []).append(
                Impediment(
                    id=item_id,
                    name=item.get("name") or f"Task {item_id}",
                    board=board.name,
                    url=item_url(board, item_id),
                )
            )
    return out


def tally_tasks(items: list[dict[str, Any]], board: Board) -> dict[str, Points]:
    """Sum one board's task points per linked epic id."""
    return walk_tasks(items, board).tally


def find_impediments(items: list[dict[str, Any]], board: Board) -> dict[str, list[Impediment]]:
    """One board's blocked tasks, by the epic they are holding up.

    A blocker linked to no epic blocks nothing this overview can show, so it is skipped —
    the orphan note below the table already reports that work exists.
    """
    return walk_tasks(items, board).impediments


def fetch_epic_rows(client: MondayClient, board: Board = EPIC_BOARD) -> list[Epic]:
    """Every epic on the board, without any point totals yet."""
    items = client.all_board_items(lambda cursor: queries.epic_rows(board, cursor))
    return [Epic.from_item(item, board=board) for item in items]


def dam_epic_ids(client: MondayClient, board: Board = EPIC_BOARD) -> set[str]:
    """The ids of the epics that carry a portfolio link — the DAM half of the board."""
    return {epic.id for epic in fetch_epic_rows(client, board) if epic.is_dam}


def fetch_epics(
    client: MondayClient,
    board: Board = EPIC_BOARD,
    task_boards: tuple[Board, ...] = TASK_BOARDS,
) -> tuple[list[Epic], Points]:
    """Every epic with its point totals, plus the totals of tasks linked to no epic.

    Six requests and a couple of thousand items on the done board, so callers are
    expected to cache the result rather than fetch it per keystroke.
    """
    epics = fetch_epic_rows(client, board)
    tally: dict[str, Points] = {}
    blocked: dict[str, list[Impediment]] = {}
    orphans = Points()
    for task_board in task_boards:
        items = client.all_board_items(lambda cursor, b=task_board: queries.board_tasks(b, cursor))  # type: ignore[misc]
        walked = walk_tasks(items, task_board)
        for epic_id, points in walked.tally.items():
            tally[epic_id] = tally.get(epic_id, Points()) + points
        for epic_id, found in walked.impediments.items():
            blocked.setdefault(epic_id, []).extend(found)
        orphans = orphans + walked.orphans

    known = {epic.id for epic in epics}
    rows = [
        replace(epic, points=tally.get(epic.id, Points()), impediments=tuple(blocked.get(epic.id, ())))
        for epic in epics
    ]
    return rows, _with_unknown(orphans, tally, known)


def _with_unknown(orphans: Points, tally: dict[str, Points], known: set[str]) -> Points:
    """Fold in tasks linked to an epic the epic board did not return, so nothing is lost."""
    return sum((points for epic_id, points in tally.items() if epic_id not in known), orphans)


# --- sorting and filtering -------------------------------------------------------------


#: Every column the overview shows, and how it sorts. Blank text sorts last either way,
#: so "no owner" does not lead the ascending list. Status and Priority sort in the
#: board's own order rather than the alphabet — see `sorting.label_key`.
SORTS: dict[str, Any] = {
    "name": lambda e: (not e.name, e.name.lower()),
    "status": lambda e: (not e.status, label_key(EPIC_STATUSES, e.status)),
    "stuck": lambda e: (e.is_stuck, len(e.impediments), e.is_blocked),
    "owner": lambda e: (not e.owner, e.owner.lower()),
    "portfolio": lambda e: (not e.portfolio, e.portfolio.lower()),
    "priority": lambda e: (not e.priority, label_key(EPIC_PRIORITIES, e.priority)),
    "done": lambda e: e.done,
    "remaining": lambda e: e.remaining,
    "progress": lambda e: (e.fraction_done, e.total),
}

DEFAULT_SORT = "priority"


#: Columns whose first click should sort high-to-low. Nobody opens a progress column
#: wanting to see the emptiest batteries first, or a stuck column to be shown the
#: epics that are running fine.
NUMERIC_SORTS = frozenset({"done", "remaining", "progress", "stuck"})

SORTING = Sorting(keys=SORTS, default=DEFAULT_SORT, numeric=NUMERIC_SORTS)

#: The progress column filters by bucket rather than by a number.
BUCKETS = {
    "not-started": "Not started",
    "in-progress": "In progress",
    "complete": "Complete",
    "no-tasks": "No tasks yet",
}


@dataclass(frozen=True)
class Filters:
    """One narrowing value per column. Empty means "do not filter on this one".

    `dropped` is the odd one out: it *widens*. Dropped epics are hidden unless it is set,
    or unless `status` names a dropped status outright — clicking the "Afgevallen" chip
    has to show them, switch or no switch.
    """

    search: str = ""
    status: str = ""
    owner: str = ""
    portfolio: str = ""
    priority: str = ""
    dam: str = ""
    bucket: str = ""
    dropped: bool = False
    #: "Only the stuck ones" — narrows, unlike `dropped`.
    stuck: bool = False


def matches(epic: Epic, f: Filters) -> bool:
    """Whether `epic` survives every filter that is set."""
    if epic.is_dropped and not f.dropped and f.status != epic.status:
        return False
    if f.search and f.search.casefold() not in epic.name.casefold():
        return False
    if f.status and epic.status != f.status:
        return False
    if f.owner and f.owner not in epic.owner:
        return False
    if f.portfolio and epic.portfolio != f.portfolio:
        return False
    if f.priority and epic.priority != f.priority:
        return False
    if f.dam == DAM and not epic.is_dam:
        return False
    if f.dam == NON_DAM and epic.is_dam:
        return False
    if f.stuck and not epic.is_stuck:
        return False
    return not (f.bucket and epic.bucket != f.bucket)


def arrange(
    epics: list[Epic], filters: Filters | None = None, sort: str = DEFAULT_SORT, desc: bool = False
) -> list[Epic]:
    """Filter, then sort. An unknown sort key falls back to the default rather than raising."""
    kept = [epic for epic in epics if matches(epic, filters or Filters())]
    return SORTING.apply(kept, sort, desc)


def parse_sort(spec: str) -> tuple[str, bool]:
    """Split a sort spec into its column and direction: ``"-done"`` is done, descending."""
    return SORTING.parse(spec)


def next_sort(column: str, spec: str) -> str:
    """The spec a click on `column`'s header should ask for, given the current one."""
    return SORTING.next(column, spec)


def status_counts(epics: list[Epic], f: Filters) -> list[tuple[str, int]]:
    """How many epics each status chip would show, given every *other* filter.

    Counted with the status filter cleared and dropped epics included, so a chip says
    exactly what clicking it yields; statuses with no epics behind them get no chip.
    The order is the board's own.
    """
    others = replace(f, status="", dropped=True)
    counts: dict[str, int] = {}
    for epic in epics:
        if epic.status and matches(epic, others):
            counts[epic.status] = counts.get(epic.status, 0) + 1
    return sorted(counts.items(), key=lambda kv: label_key(EPIC_STATUSES, kv[0]))


def totals(epics: list[Epic]) -> Points:
    """The headline numbers under the table: the whole selection as one battery."""
    return sum((e.points for e in epics), Points())


def options(epics: list[Epic], of: str) -> list[str]:
    """The distinct values of one column, for that column's filter dropdown.

    Built from the rows actually fetched — the same reason the sprint page builds its
    epic dropdown from its results — so no dropdown offers a choice that comes back empty.
    Status and Priority keep the board's order; the free-text columns go alphabetical.
    """
    seen = {getattr(epic, of) for epic in epics}
    seen.discard("")
    if of == "status":
        return sorted(seen, key=lambda v: label_key(EPIC_STATUSES, v))
    if of == "priority":
        return sorted(seen, key=lambda v: label_key(EPIC_PRIORITIES, v))
    return sorted(seen, key=str.lower)
