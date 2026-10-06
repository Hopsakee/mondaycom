"""The planning: how much work each discipline has, and how much it can do.

Three boards meet here. **Epics-STP-distribution** holds one row per epic, linked to it,
with the epic's remaining work (STP-TODO, a mirror of the epic board's "STP gepland")
and how that work splits over the four disciplines. **Capaciteit** holds one row per
person: their discipline, what they burn in a sprint at full availability, how available
they are, and any extra overhead expected. The **epic board** decides which layer an
epic is planned in, by its group and its due date.

- **monday.com is the source of truth.** STP-TODO is read as the board computes it, and
  only a *linked* distribution row counts — an epic without one, or with a split that
  does not add up to 100%, is left out of every number and listed as something to fix
  on monday.com, not patched up here. The one thing done in code is adding up the
  mirror's members, because a mirror answers ``"19, 3, 1"`` rather than 23.
- **Layers.** *Promised* is Actief or Bespreken, due on or before the quarter end (or
  with no due date). *Later* is Actief or Bespreken due after it. *Backlog* is Backlog.
- **The selection is the plan.** The layers ticked and the DAM filter pick the epics;
  the load and the forecast answer "if we do exactly this in the window, how far are we
  overbooked, and what finishes when?". Nothing outside the selection takes capacity.
- **One queue.** The selected epics in layer order, and within a layer by priority, then
  due date, then smallest first. Each discipline works down the queue on its own, and an
  epic is finished in the sprint its *last* discipline share is.
- **Strict per discipline.** DE work waits for DE capacity; nobody absorbs another
  discipline's share.
- **A sprint group counts by Trekker.** Its tasks have someone doing them, so their
  points go whole to that person's discipline; the split is only for the quarter's queue.
- **Capacity** per person per sprint is ``STP × available% × (1 − overhead%)``, with
  the quarter's availability for the plan and the current-sprint check, and the next
  sprint's for the next-sprint check.
- The window is **whole sprints only**: from the day after the current sprint ends to
  the quarter end, in blocks of three weeks.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from mondaycom import burndown as bd
from mondaycom import queries
from mondaycom.client import MondayClient
from mondaycom.config import (
    CANCELLED_STATUSES,
    CAPACITY_BOARD,
    DISTRIBUTION_BOARD,
    DONE_STATUS,
    EPIC_BOARD,
    EPIC_GROUP_BACKLOG,
    EPIC_PRIORITIES,
    NEXT_SPRINT_GROUP,
    PROMISED_GROUPS,
    SPRINT_LENGTH_WEEKS,
    Board,
    as_date,
    as_number,
    due_by,
    item_url,
    keeps_dam,
)
from mondaycom.config import DISCIPLINE_NAMES as DISCIPLINE_NAMES  # the page and the CLI read them here
from mondaycom.config import DISCIPLINES as DISCIPLINES
from mondaycom.sorting import label_key

PROMISED = "promised"
LATER = "later"
BACKLOG = "backlog"

#: The layers in queue order, with the words the page and the CLI use for them.
LAYERS = {
    PROMISED: "Promised",
    LATER: "Later",
    BACKLOG: "Backlog",
}

#: What each layer holds, in the words the page's hover text and help panel use. The
#: group is the epic board's own group, not its "Status epic" — the status is shown, it
#: does not decide.
#: The "This quarter" filter, in the words the page and the CLI use for it.
THIS_QUARTER_HELP = (
    "Only epics whose Due date on the epic board is on or before the quarter end. "
    "Epics without a due date drop out. Applies to every ticked layer."
)

LAYER_HELP = {
    PROMISED: "Epics in the Actief or Bespreken group on the epic board, due on or before the quarter end "
    "or with no due date: what we have promised to do this quarter.",
    LATER: "Epics in the Actief or Bespreken group whose due date lies after the quarter end: "
    "running, but not promised for this quarter.",
    BACKLOG: "Epics in the Backlog group on the epic board, whatever their due date: what we could be doing next.",
}

#: The same three, in Dutch, for the web page — the huisstijl wants every word on screen
#: in Dutch, the CLI keeps the English above. Change a rule, change both.
LAYERS_NL = {
    PROMISED: "Toegezegd",
    LATER: "Later",
    BACKLOG: "Backlog",
}

THIS_QUARTER_HELP_NL = (
    "Alleen epics met een Due date op het epic-bord op of vóór het kwartaaleinde. "
    "Epics zonder due date vallen af. Geldt voor elke aangevinkte laag."
)

LAYER_HELP_NL = {
    PROMISED: "Epics in de groep Actief of Bespreken op het epic-bord, met een due date op of vóór het "
    "kwartaaleinde of zonder due date: wat we dit kwartaal hebben toegezegd.",
    LATER: "Epics in de groep Actief of Bespreken met een due date na het kwartaaleinde: "
    "lopend, maar niet toegezegd voor dit kwartaal.",
    BACKLOG: "Epics in de groep Backlog op het epic-bord, ongeacht hun due date: wat we hierna zouden kunnen doen.",
}

#: `Planned.verdict`'s words, in Dutch. Looked up with `[]`, so a verdict added without
#: its Dutch fails loudly instead of showing English on the Dutch page.
VERDICTS_NL = {
    "no STP-TODO": "geen STP-TODO",
    "no capacity": "geen capaciteit",
    "late": "te laat",
    "nothing left": "niets meer te doen",
    "on time": "op tijd",
    "this quarter": "dit kwartaal",
    "after the quarter": "na het kwartaal",
}

#: A split within half a percent of 100 is 100: `33.3 + 33.3 + 33.4` is a valid split.
SPLIT_TOLERANCE = 0.5

SPRINT_DAYS = SPRINT_LENGTH_WEEKS * 7


def parse_mirror(text: str) -> float:
    """A number mirror's value: its members, added up.

    Over the API a mirror answers with what it mirrors, comma-joined — ``"19, 3, 1"`` for
    the 23 the UI shows — whatever the column's own `sum` setting says.
    """
    return sum(as_number(part.strip()) for part in (text or "").split(","))


# --- the three boards -------------------------------------------------------------------


@dataclass(frozen=True)
class Split:
    """One row of Epics-STP-distribution: an epic's remaining work and how it divides."""

    id: str
    name: str
    #: The linked epic's item id; empty when the row links to nothing yet.
    epic_id: str = ""
    #: STP-TODO, as monday.com computes it.
    todo: float = 0.0
    #: Whether STP-TODO holds anything at all — an empty mirror is not the same as 0.
    has_todo: bool = False
    #: Percentage per discipline. A blank cell is `None`, which is not the same as 0.
    shares: dict[str, float | None] = field(default_factory=dict)

    @property
    def total(self) -> float:
        return sum(v or 0.0 for v in self.shares.values())

    @property
    def problem_words(self) -> tuple[str, str]:
        """Why this split cannot be used, in English (the CLI) and Dutch (the web) — one
        decision, two languages; both empty when it can be used."""
        if all(self.shares.get(d) is None for d in DISCIPLINES):
            return "no split filled in", "geen verdeling ingevuld"
        if abs(self.total - 100) > SPLIT_TOLERANCE:
            return f"split adds up to {self.total:g}%", f"verdeling telt op tot {self.total:g}%"
        return "", ""

    @property
    def problem(self) -> str:
        """Why this split cannot be used, in a few words; empty when it can."""
        return self.problem_words[0]

    @property
    def is_valid(self) -> bool:
        return not self.problem

    def share(self, discipline: str) -> float:
        """The points this epic needs from one discipline."""
        return self.todo * (self.shares.get(discipline) or 0.0) / 100

    @property
    def url(self) -> str:
        return item_url(DISTRIBUTION_BOARD, self.id)

    @classmethod
    def from_item(cls, item: dict[str, Any], board: Board = DISTRIBUTION_BOARD) -> Split:
        cells = board.cells(item)
        linked = cells.linked("epic")
        todo = cells.text("todo")
        shares = {d: (as_number(cells.text(d)) if cells.text(d) else None) for d in DISCIPLINES}
        return cls(
            id=str(item["id"]),
            name=item["name"],
            epic_id=linked[0] if linked else "",
            todo=parse_mirror(todo),
            has_todo=bool(todo),
            shares=shares,
        )


@dataclass(frozen=True)
class Person:
    """One row of Capaciteit."""

    name: str
    role: str = ""
    #: STP per sprint at 100% availability.
    stp: float = 0.0
    sprint_available: float = 0.0
    quarter_available: float = 0.0
    #: Extra overhead this quarter, as a percentage of what is left after availability.
    overhead: float = 0.0

    def capacity(self, available: float) -> float:
        """Usable STP in one sprint: ``STP × available% × (1 − overhead%)``."""
        return self.stp * available / 100 * (1 - self.overhead / 100)

    @property
    def per_sprint(self) -> float:
        """What this person burns in an average sprint of the planned quarter."""
        return self.capacity(self.quarter_available)

    @property
    def next_sprint(self) -> float:
        """What this person burns in the coming sprint."""
        return self.capacity(self.sprint_available)

    @classmethod
    def from_item(cls, item: dict[str, Any], board: Board = CAPACITY_BOARD) -> Person:
        cells = board.cells(item)
        return cls(
            name=item["name"],
            role=cells.text("role"),
            stp=cells.number("stp"),
            sprint_available=cells.number("sprint_available"),
            quarter_available=cells.number("quarter_available"),
            overhead=cells.number("overhead"),
        )


@dataclass(frozen=True)
class PlanEpic:
    """An epic as the planning sees it: where it sits, how urgent it is, when it is due."""

    id: str
    name: str
    group: str = ""
    group_title: str = ""
    status: str = ""
    priority: str = ""
    due: date | None = None
    #: The IV Portfolio items it links to. Linked at all is what makes an epic DAM.
    portfolio_ids: tuple[str, ...] = ()

    @property
    def url(self) -> str:
        return item_url(EPIC_BOARD, self.id)

    def due_by(self, day: date) -> bool:
        """Has a due date, and it is on or before `day` — see `config.due_by`."""
        return due_by(self.due, day)

    @property
    def is_dam(self) -> bool:
        """Linked to the IV Portfolio board — the epic board's own DAM formula."""
        return bool(self.portfolio_ids)

    def layer(self, quarter_end: date) -> str:
        """Which layer the epic is planned in, or empty when it is not planned at all."""
        if self.group in PROMISED_GROUPS:
            return LATER if self.due and self.due > quarter_end else PROMISED
        return BACKLOG if self.group == EPIC_GROUP_BACKLOG else ""

    @classmethod
    def from_item(cls, item: dict[str, Any], board: Board = EPIC_BOARD) -> PlanEpic:
        cells = board.cells(item)
        group = item.get("group") or {}
        return cls(
            id=str(item["id"]),
            name=item["name"],
            group=group.get("id") or "",
            group_title=group.get("title") or "",
            status=cells.text("status"),
            priority=cells.text("priority"),
            due=as_date(cells.text("due_date")),
            portfolio_ids=cells.linked("portfolio"),
        )


@dataclass
class Snapshot:
    """Everything the planning reads from monday.com, before any date is chosen.

    Kept apart from `plan` so the web page can fetch once and re-plan for every date
    and layer a user tries, without another request.
    """

    splits: list[Split]
    epics: list[PlanEpic]
    people: list[Person]
    #: The end of the sprint running now, as the Sprint page guesses it.
    current_end: date
    #: Tasks in the "Next sprint" group, for the next-sprint check.
    next_sprint: list[bd.SprintItem] = field(default_factory=list)
    #: Tasks in the current sprint group, for the current-sprint check.
    current_sprint: list[bd.SprintItem] = field(default_factory=list)


def fetch(client: MondayClient) -> Snapshot:
    """Read the three planning boards and the two sprint groups the window needs.

    The epic board is the slow one (~6s); the rest are a request each.
    """
    splits = [
        Split.from_item(i)
        for i in client.all_board_items(lambda cursor: queries.distribution_rows(DISTRIBUTION_BOARD, cursor))
    ]
    epics = [
        PlanEpic.from_item(i) for i in client.all_board_items(lambda cursor: queries.planning_epics(EPIC_BOARD, cursor))
    ]
    people = [Person.from_item(i) for i in client.board_items(queries.capacity_rows(CAPACITY_BOARD))]
    current = bd.fetch_sprint_items(client)
    _, current_end = bd.sprint_window(current)
    upcoming = bd.fetch_sprint_items(client, group=NEXT_SPRINT_GROUP)
    return Snapshot(
        splits=splits,
        epics=epics,
        people=people,
        current_end=current_end,
        next_sprint=upcoming,
        current_sprint=current,
    )


# --- the window -------------------------------------------------------------------------


def quarter_end(day: date) -> date:
    """The last day of the calendar quarter `day` falls in."""
    first_of_next = date(day.year + (day.month > 9), (((day.month - 1) // 3 + 1) * 3) % 12 + 1, 1)
    return first_of_next - timedelta(days=1)


@dataclass(frozen=True)
class Window:
    """The stretch being planned, in whole sprints."""

    start: date
    end: date

    @property
    def sprints(self) -> int:
        """How many whole three-week sprints fit between `start` and `end`, both inclusive."""
        days = (self.end - self.start).days + 1
        return max(days // SPRINT_DAYS, 0)

    def sprint_end(self, n: int) -> date:
        """The last day of the `n`-th sprint from `start`. Sprint 1 ends 20 days in."""
        return self.start + timedelta(days=n * SPRINT_DAYS - 1)

    @property
    def last_day(self) -> date:
        """The end of the last whole sprint — where the planned capacity runs out."""
        return self.sprint_end(self.sprints) if self.sprints else self.start - timedelta(days=1)


def window(current_end: date, start: str = "", end: str = "") -> Window:
    """The window to plan: from the day after the current sprint to a quarter's end.

    The quarter is the one the *first sprint ends in*, not the one it starts in: a
    sprint starting on 28 September is Q4 work, and planning the two days left of Q3
    would hold no whole sprint at all. Either end can be given as ``YYYY-MM-DD``.
    """
    begin = as_date(start) if start else current_end + timedelta(days=1)
    if begin is None:
        raise ValueError(f"{start!r} is not a date: expected YYYY-MM-DD")
    finish = as_date(end) if end else quarter_end(begin + timedelta(days=SPRINT_DAYS - 1))
    if finish is None:
        raise ValueError(f"{end!r} is not a date: expected YYYY-MM-DD")
    if finish < begin:
        raise ValueError(f"The quarter end {finish} lies before the start {begin}.")
    return Window(begin, finish)


def this_quarter_end(current_end: date) -> date:
    """The quarter end "Dit kwartaal" means while the sprint ending `current_end` runs: the
    planning window's default end, so every page that narrows on it agrees with this one."""
    return window(current_end).end


# --- the plan ---------------------------------------------------------------------------


@dataclass
class Discipline:
    """One discipline's side of the plan: who does it, how much they can do, how much there is."""

    key: str
    people: list[Person] = field(default_factory=list)
    #: Points the selection needs from this discipline, per layer.
    demand: dict[str, float] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return DISCIPLINE_NAMES.get(self.key, self.key)

    @property
    def per_sprint(self) -> float:
        return sum(p.per_sprint for p in self.people)

    @property
    def total(self) -> float:
        """Every point the selection needs from this discipline."""
        return sum(self.demand.values())

    @property
    def sprints_needed(self) -> float | None:
        """Sprints to get through the selection. `None` when nobody does this work."""
        total = self.total
        if not total:
            return 0.0
        return total / self.per_sprint if self.per_sprint else None

    def capacity(self, sprints: int) -> float:
        """What the discipline can do in `sprints` whole sprints."""
        return self.per_sprint * sprints

    def full_capacity(self, sprints: int) -> float:
        """What the discipline could do in `sprints` if everybody were 100% available — the
        overhead still applies: the ceiling the availability percentages take a share of."""
        return sum(p.capacity(100) for p in self.people) * sprints

    def load(self, sprints: int) -> float | None:
        """The selection's points as a fraction of what the window holds. Above 1 is
        overbooked; `None` is work with nobody to do it."""
        capacity = self.capacity(sprints)
        if not capacity:
            return None if self.total else 0.0
        return self.total / capacity


@dataclass
class Planned:
    """One epic in the queue, with its forecast."""

    epic: PlanEpic
    split: Split
    layer: str
    #: The sprint, counted from the window's start, in which its last share is done.
    #: 0 when there is nothing left to do; `None` when a discipline it needs has nobody.
    finish_sprint: int | None = 0
    finish: date | None = None

    @property
    def todo(self) -> float:
        return self.split.todo

    @property
    def late(self) -> bool:
        """Forecast to finish after its own due date."""
        if not self.epic.due:
            return False
        return self.finish_sprint is None or (self.finish is not None and self.finish > self.epic.due)

    def fits(self, w: Window) -> bool:
        """Finished within the window's whole sprints."""
        return self.finish_sprint is not None and self.finish_sprint <= w.sprints

    def verdict(self, w: Window) -> tuple[str, str]:
        """The forecast in a few words, and the tone it wears."""
        if not self.split.has_todo:
            return "no STP-TODO", "neutral"
        if self.finish_sprint is None:
            return "no capacity", "critical"
        if self.late:
            return "late", "critical"
        if not self.finish_sprint:
            return "nothing left", "good"
        if self.fits(w):
            return ("on time" if self.epic.due else "this quarter"), "good"
        return "after the quarter", "warning"


@dataclass(frozen=True)
class Problem:
    """An epic the plan had to leave out, and what to fix on monday.com."""

    epic: PlanEpic
    layer: str
    reason: str
    url: str
    #: `reason`, in Dutch, for the web page.
    reason_nl: str = ""


@dataclass
class SprintLoad:
    """One sprint group: capacity per discipline against the work in the group."""

    capacity: dict[str, float]
    load: dict[str, float]
    tasks: int = 0
    #: Points on tasks whose Trekker has no discipline on Capaciteit, by Trekker, so the
    #: page can name who is missing. `""` is no Trekker at all.
    unmatched: dict[str, float] = field(default_factory=dict)

    @property
    def unplaced(self) -> float:
        """Every point no discipline could take."""
        return sum(self.unmatched.values())


@dataclass
class Plan:
    """The whole answer for one selection: the window, the disciplines, the queue, and
    the epics in the selection it had to leave out."""

    window: Window
    disciplines: list[Discipline]
    queue: list[Planned]
    problems: list[Problem]
    next_sprint: SprintLoad
    #: The sprint running now: everything committed in its group, against the quarter's
    #: availability — Capaciteit has no column for the sprint that is already under way.
    current_sprint: SprintLoad
    #: People on Capaciteit whose role is not one of the four disciplines.
    unassigned_people: list[Person] = field(default_factory=list)
    layers: tuple[str, ...] = ()
    dam: str = ""
    #: Only epics due on or before the quarter end — see `THIS_QUARTER_HELP`.
    this_quarter: bool = False


def queue_key(p: Planned) -> tuple[Any, ...]:
    """Layer, then priority in the board's order, then earliest due date, then smallest."""
    return (
        list(LAYERS).index(p.layer),
        (not p.epic.priority, label_key(EPIC_PRIORITIES, p.epic.priority)),
        (p.epic.due is None, p.epic.due or date.max),
        p.todo,
        p.epic.name.lower(),
    )


def forecast(queue: list[Planned], disciplines: list[Discipline], w: Window) -> None:
    """Walk the queue once, each discipline on its own, and date every epic's finish.

    A discipline's cumulative points divided by its capacity per sprint is the sprint in
    which it gets through that epic; the epic is done when its slowest share is.
    """
    per_sprint = {d.key: d.per_sprint for d in disciplines}
    cumulative = dict.fromkeys(per_sprint, 0.0)
    for p in queue:
        finish: int | None = 0
        for key in per_sprint:
            share = p.split.share(key)
            if not share:
                continue
            cumulative[key] += share
            if not per_sprint[key]:
                finish = None
                continue
            if finish is not None:
                # A hair under a whole number is that whole number, not the next sprint.
                finish = max(finish, math.ceil(cumulative[key] / per_sprint[key] - 1e-9))
        p.finish_sprint = finish
        # Nothing left to do has no finish date to forecast: it is finished already.
        p.finish = w.sprint_end(finish) if finish else None


def capacity_person(people: list[Person], trekker: str) -> Person | None:
    """The Capaciteit row for a Trekker as the sprint board names them.

    Capaciteit's Person column is empty, so the link is the name, and its names are not
    written alike: "Agnes Dubbink" in full, "Andor" for "Andor Ton". The full name wins;
    otherwise a Capaciteit name that is the Trekker's first word(s), if only one row is.
    """
    if not trekker:
        return None
    exact = [p for p in people if p.name == trekker]
    if exact:
        return exact[0]
    prefix = [p for p in people if p.name and trekker.startswith(p.name + " ")]
    return prefix[0] if len(prefix) == 1 else None


def sprint_load(
    snapshot: Snapshot,
    items: list[bd.SprintItem],
    dam: str,
    per_person: Callable[[Person], float],
    with_done: bool,
) -> SprintLoad:
    """Weigh one sprint group per discipline, by each task's **Trekker**.

    A task on the sprint board has someone doing it, so its points go whole to that
    person's discipline on Capaciteit — never split by the epic's percentages, which are
    a forecast for work nobody has picked up yet. A task with two Trekkers counts for the
    first, as a task linked to two epics does. A Trekker with no discipline is reported.

    The DAM filter applies — a task with no epic is non-DAM — but the layers do not: the
    group is what the sprint holds, whatever layer its epics sit in. Cancelled work never
    counts; Done work counts only `with_done`, for a sprint already under way.
    """
    dam_epics = frozenset(e.id for e in snapshot.epics if e.is_dam) if dam else frozenset()
    load = dict.fromkeys(DISCIPLINES, 0.0)
    unmatched: dict[str, float] = {}
    tasks = 0
    for item in bd.narrow(items, dam=dam, dam_epics=dam_epics):
        if item.status in CANCELLED_STATUSES or not item.points:
            continue
        if item.status == DONE_STATUS and not with_done:
            continue
        tasks += 1
        trekker = item.people[0] if item.people else ""
        person = capacity_person(snapshot.people, trekker)
        if person is None or person.role not in load:
            unmatched[trekker] = unmatched.get(trekker, 0.0) + item.points
            continue
        load[person.role] += item.points
    capacity = {key: sum(per_person(p) for p in snapshot.people if p.role == key) for key in DISCIPLINES}
    return SprintLoad(capacity=capacity, load=load, tasks=tasks, unmatched=unmatched)


def next_sprint(snapshot: Snapshot, dam: str = "") -> SprintLoad:
    """The Next sprint group's open tasks, against "% beschikbaar komende sprint"."""
    return sprint_load(snapshot, snapshot.next_sprint, dam, lambda p: p.next_sprint, with_done=False)


def current_sprint(snapshot: Snapshot, dam: str = "") -> SprintLoad:
    """The current sprint group: everything committed to it, Done included — the sprint is
    under way, and finished work was part of what it took on — against the quarter's
    availability, the only one Capaciteit has for a sprint that already started."""
    return sprint_load(snapshot, snapshot.current_sprint, dam, lambda p: p.per_sprint, with_done=True)


def plan(
    snapshot: Snapshot,
    w: Window,
    layers: tuple[str, ...] = (PROMISED,),
    dam: str = "",
    this_quarter: bool = False,
) -> Plan:
    """Queue the selected epics, forecast them, and weigh them against capacity.

    The selection is every epic in one of `layers` that passes the DAM filter. Only
    those take capacity, so the load answers "can we do exactly this in the window?".
    """
    # First valid link wins; a second row on the same epic would count its work twice.
    splits: dict[str, Split] = {}
    bad: dict[str, Split] = {}
    for split in snapshot.splits:
        if not split.epic_id:
            continue
        if split.is_valid:
            splits.setdefault(split.epic_id, split)
        else:
            bad.setdefault(split.epic_id, split)

    queue: list[Planned] = []
    problems: list[Problem] = []
    for epic in snapshot.epics:
        layer = epic.layer(w.end)
        if layer not in layers or not keeps_dam(dam, epic.is_dam):
            continue
        if this_quarter and not epic.due_by(w.end):
            continue
        split = splits.get(epic.id)
        if split is not None:
            queue.append(Planned(epic=epic, split=split, layer=layer))
        elif epic.id in bad:
            en, nl = bad[epic.id].problem_words
            problems.append(Problem(epic, layer, en, bad[epic.id].url, nl))
        else:
            problems.append(
                Problem(
                    epic,
                    layer,
                    "not linked on Epics-STP-distribution",
                    epic.url,
                    "niet gekoppeld op Epics-STP-distribution",
                )
            )
    queue.sort(key=queue_key)

    disciplines = [Discipline(key, [p for p in snapshot.people if p.role == key]) for key in DISCIPLINES]
    for d in disciplines:
        for p in queue:
            d.demand[p.layer] = d.demand.get(p.layer, 0.0) + p.split.share(d.key)
    forecast(queue, disciplines, w)

    problems.sort(key=lambda pr: (list(LAYERS).index(pr.layer), pr.epic.name.lower()))
    return Plan(
        window=w,
        disciplines=disciplines,
        queue=queue,
        problems=problems,
        next_sprint=next_sprint(snapshot, dam),
        current_sprint=current_sprint(snapshot, dam),
        unassigned_people=[p for p in snapshot.people if p.role not in DISCIPLINES],
        layers=layers,
        dam=dam,
        this_quarter=this_quarter,
    )


def layers_text(layers: tuple[str, ...]) -> str:
    """The layers in words, as both front-ends print them: "Promised + Backlog"."""
    return " + ".join(LAYERS[layer] for layer in layers)


def parse_layers(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    """The layers asked for, in queue order. Nothing, or nothing known, means Promised."""
    picked = tuple(layer for layer in LAYERS if layer in (values or ()))
    return picked or (PROMISED,)


def most_overbooked(p: Plan) -> list[Discipline]:
    """The disciplines, heaviest load first. Nobody to do the work sorts on top."""

    def key(d: Discipline) -> float:
        load = d.load(p.window.sprints)
        return -math.inf if load is None else -load

    return sorted(p.disciplines, key=key)


def layers_text_nl(layers: tuple[str, ...]) -> str:
    """`layers_text` in Dutch: "Toegezegd + Later"."""
    return " + ".join(LAYERS_NL[key] for key in layers)


#: A load's tone in words, for the web: the same band as `load_tone`.
LOAD_WORDS = {"active": "ruimte over", "good": "op doel", "critical": "overboekt"}

#: The load that counts as on target: between 90% and 110% of capacity. Below it there is
#: room left, above it the discipline is overbooked. Every load colour follows this.
LOAD_BAND = (0.9, 1.1)


def load_tone(load: float | None) -> str:
    """A load as a tone: `active` (blue) under the band, `good` inside it, `critical`
    above it — and `critical` for work with nobody to do it."""
    if load is None or load > LOAD_BAND[1]:
        return "critical"
    return "good" if load >= LOAD_BAND[0] else "active"


def overflow(d: Discipline, sprints: int) -> float:
    """The discipline's points that do not fit in the window's whole sprints."""
    return max(d.total - d.capacity(sprints), 0.0)


@dataclass(frozen=True)
class Share:
    """One epic's share for one discipline, and the sprints in which the discipline does it."""

    planned: Planned
    #: The epic's place in the whole queue, 1-based — the same number on every discipline.
    position: int
    points: float
    #: Sprints counted from the window's start, 1-based. `None` when nobody does the work.
    first: int | None
    last: int | None


def discipline_shares(queue: list[Planned], d: Discipline) -> list[Share]:
    """The queue as one discipline works it: each epic's share, and its sprints.

    The same walk `forecast` does, kept for one discipline: cumulative points before and
    after the epic, divided by what the discipline does per sprint.
    """
    shares = []
    cumulative = 0.0
    per = d.per_sprint
    for position, p in enumerate(queue, start=1):
        points = p.split.share(d.key)
        if not points:
            continue
        before, cumulative = cumulative, cumulative + points
        if not per:
            shares.append(Share(p, position, points, None, None))
            continue
        first = math.floor(before / per + 1e-9) + 1
        last = max(first, math.ceil(cumulative / per - 1e-9))
        shares.append(Share(p, position, points, first, last))
    return shares
