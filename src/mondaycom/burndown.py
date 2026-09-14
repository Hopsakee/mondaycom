"""Sprint burndown: how many story points are left, day by day, against the ideal line.

Sprint membership comes from the board's "Current sprint" group rather than from a
date filter, and a task burns down on its **Done Date**, not on the day you happen
to look. Points are the Estimation column; cancelled work ("Vervallen") leaves the
sprint total rather than counting as burned, so dropping a task lowers the bar
instead of faking progress.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from mondaycom import queries
from mondaycom.client import MondayClient
from mondaycom.config import (
    CANCELLED_STATUSES,
    CURRENT_SPRINT_GROUP,
    DAM,
    DONE_STATUS,
    ME,
    NON_DAM,
    SPRINT_BOARD,
    Board,
)
from mondaycom.sprint import Task, sprint_start


def _as_date(text: str) -> date | None:
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


@dataclass
class SprintItem:
    """One task in the sprint group, reduced to what a burndown needs."""

    id: str
    name: str
    points: float = 0.0
    status: str = ""
    done_on: date | None = None
    due_date: str = ""
    owner: str = ""
    reviewer: str = ""
    epic: str = ""
    epic_id: str = ""

    def assigned_to(self, name: str) -> bool:
        """Whether `name` owns *or* reviews this task — the app's meaning of "assigned".

        This decides what a person filter *shows*, not what it counts: the points land
        on the Trekker alone (`owned_by`). Both are `people` columns, so several names
        arrive comma-joined in one string; a substring test is what the task list does.
        """
        return name in self.owner or name in self.reviewer

    def owned_by(self, name: str) -> bool:
        """Whether `name` is the **Trekker** — whose story points these are.

        Reviewing a task puts it in your list (with the 🤝 marker) but never adds its
        points to your total, so per-person totals add up to the sprint's.
        """
        return name in self.owner if self.owner else False

    @property
    def is_done(self) -> bool:
        return self.status == DONE_STATUS

    @property
    def people(self) -> list[str]:
        """Whoever the task counts for: its Trekker(s), one name each. Reviewers are not."""
        names = [n.strip() for n in self.owner.split(",")]
        return list(dict.fromkeys(n for n in names if n))

    def as_task(self, me: str = ME) -> Task:
        """The same row as the task list sees it, so one group read can feed both.

        `me` is whose reviewer assignments earn the 🤝 marker — the person being
        filtered on, exactly as `sprint.fetch_tasks` takes it.
        """
        return Task(
            id=self.id,
            name=self.name,
            status=self.status,
            due_date=self.due_date,
            story_points=int(self.points),
            is_reviewer=me in self.reviewer,
            owner=self.owner,
            epic=self.epic,
            epic_id=self.epic_id,
        )

    @property
    def is_cancelled(self) -> bool:
        return self.status in CANCELLED_STATUSES

    @classmethod
    def from_item(cls, item: dict[str, Any], board: Board = SPRINT_BOARD) -> SprintItem:
        cells = board.cells(item)
        linked = cells.linked("epic")
        return cls(
            id=item["id"],
            name=item["name"],
            points=cells.number("story_points"),
            status=cells.text("status"),
            done_on=_as_date(cells.text("done_date")),
            due_date=cells.text("due_date"),
            owner=cells.text("owner"),
            reviewer=cells.text("reviewer"),
            epic=cells.text("epic"),
            epic_id=linked[0] if linked else "",
        )


@dataclass
class Day:
    """One point on the chart."""

    on: date
    ideal: float
    #: Points still open at end of day, or None for days that have not happened yet.
    remaining: float | None
    burned: float = 0.0


@dataclass
class Burndown:
    """A whole sprint's worth of burndown, ready to render."""

    start: date
    end: date
    days: list[Day]
    committed: float
    done: float
    cancelled: float
    counts: Counter[str]
    today: date

    @property
    def remaining(self) -> float:
        return self.committed - self.done

    @property
    def ideal_today(self) -> float:
        """Where the ideal line sits today, clamped to the sprint window."""
        for day in self.days:
            if day.on == self.today:
                return day.ideal
        return 0.0 if self.today > self.end else self.committed

    @property
    def ahead_by(self) -> float:
        """Points ahead of the ideal line. Negative means behind."""
        return self.ideal_today - self.remaining

    @property
    def on_track(self) -> bool:
        return self.ahead_by >= 0

    @property
    def verdict(self) -> str:
        if self.today > self.end:
            return "sprint over" if self.remaining <= 0 else f"sprint over, {fmt(self.remaining)} left"
        if abs(self.ahead_by) < 0.5:
            return "on track"
        return f"{fmt(abs(self.ahead_by))} points {'ahead' if self.on_track else 'behind'}"


def fmt(points: float) -> str:
    """Points are whole numbers far more often than not; do not print `12.0`."""
    return f"{points:g}"


def sprint_window(items: list[SprintItem], end: str | None = None) -> tuple[date, date]:
    """The sprint's start and end.

    Sprint boundaries are not recorded anywhere on the board, so unless `end` is
    given we take the due date shared by most of the group — which is what a sprint
    end date actually is here — and work back three weeks.
    """
    if end:
        finish = datetime.strptime(end, "%Y-%m-%d").date()
    else:
        due = Counter(item.due_date for item in items if item.due_date)
        if not due:
            raise ValueError("No due dates in the sprint group; pass an explicit end date.")
        finish = datetime.strptime(due.most_common(1)[0][0], "%Y-%m-%d").date()
    return datetime.strptime(sprint_start(finish.isoformat()), "%Y-%m-%d").date(), finish


def narrow(
    items: list[SprintItem],
    person: str = "",
    dam: str = "",
    dam_epics: frozenset[str] = frozenset(),
    epic: str = "",
) -> list[SprintItem]:
    """The sprint items a person / portfolio / epic filter keeps.

    Applied in Python, not in the query: the group read deliberately has no
    `query_params` (the group *is* the sprint), and the group is 60 rows.

    `person` is a name, matched against the Trekker **and** the Reviewer text, because
    the group read returns both as text rather than as ids — you want the work you
    review in your list. Whose *points* those are is a separate question; run the
    result through `owned` before building a burndown from it. `dam` is ``config.DAM``
    or ``config.NON_DAM``, resolved against the epic ids that carry a portfolio link —
    a task with no epic can never be DAM. `epic` is an epic-board item id.
    """
    kept = items
    if person:
        kept = [item for item in kept if item.assigned_to(person)]
    if dam == DAM:
        kept = [item for item in kept if item.epic_id in dam_epics]
    elif dam == NON_DAM:
        kept = [item for item in kept if item.epic_id not in dam_epics]
    if epic:
        kept = [item for item in kept if item.epic_id == epic]
    return kept


def owned(items: list[SprintItem], person: str = "") -> list[SprintItem]:
    """The rows whose story points count for `person`: the ones they are Trekker of.

    `narrow(person=...)` keeps review work too, so a person's slice holds tasks whose
    points are somebody else's. Every points view — the tiles, the chart, the small
    multiples — is built from this, so the per-person totals still add up to the
    sprint's. No person means no narrowing.
    """
    if not person:
        return items
    return [item for item in items if item.owned_by(person)]


def people(items: list[SprintItem]) -> list[str]:
    """Every Trekker in `items`, alphabetically — the per-person small multiples."""
    return sorted({name for item in items for name in item.people}, key=str.lower)


def build(
    items: list[SprintItem],
    end: str | None = None,
    today: date | None = None,
    window_from: list[SprintItem] | None = None,
) -> Burndown:
    """Turn sprint items into an ideal line and an actual line.

    `window_from` is the group *before* filtering. The sprint window is guessed from
    the due date most of the group shares, and one person's four tasks are far too thin
    a sample for that — so a filtered burndown keeps the whole group's window.
    """
    today = today or date.today()
    start, finish = sprint_window(window_from if window_from is not None else items, end)

    live = [i for i in items if not i.is_cancelled]
    committed = sum(i.points for i in live)
    cancelled = sum(i.points for i in items if i.is_cancelled)
    done = sum(i.points for i in live if i.is_done)

    # Work finished before the sprint opened still counts as burned on day one, and work
    # finished after it closed on the last day — otherwise the line would end above what
    # the Done tile says, with the difference burned on a day the chart does not show.
    burned_on: dict[date, float] = {}
    for item in live:
        if item.is_done and item.done_on:
            when = min(max(item.done_on, start), finish)
            burned_on[when] = burned_on.get(when, 0.0) + item.points
    # Anything Done without a date has to land somewhere; day one is the honest guess.
    undated = sum(i.points for i in live if i.is_done and not i.done_on)
    if undated:
        burned_on[start] = burned_on.get(start, 0.0) + undated

    span = (finish - start).days
    days: list[Day] = []
    running = 0.0
    for offset in range(span + 1):
        on = start + timedelta(days=offset)
        running += burned_on.get(on, 0.0)
        ideal = committed * (1 - offset / span) if span else 0.0
        days.append(
            Day(
                on=on,
                ideal=round(ideal, 2),
                remaining=round(committed - running, 2) if on <= today else None,
                burned=burned_on.get(on, 0.0),
            )
        )

    return Burndown(
        start=start,
        end=finish,
        days=days,
        committed=committed,
        done=done,
        cancelled=cancelled,
        counts=Counter(i.status or "(no status)" for i in items),
        today=today,
    )


def fetch_sprint_items(
    client: MondayClient,
    board: Board = SPRINT_BOARD,
    group: str = CURRENT_SPRINT_GROUP,
) -> list[SprintItem]:
    """Every task in the sprint group."""
    data = client.execute(queries.sprint_group_tasks(board, group))
    boards = data.get("boards") or []
    if not boards or not boards[0].get("groups"):
        raise ValueError(f"Board {board.name!r} has no group {group!r}.")
    page = boards[0]["groups"][0]["items_page"]
    if page.get("cursor"):
        raise ValueError("The sprint group no longer fits in one page; queries.sprint_group_tasks needs a cursor.")
    return [SprintItem.from_item(item, board=board) for item in page["items"]]
