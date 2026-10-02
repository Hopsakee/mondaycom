"""Offline tests for the planning: splits, capacity, layers, the queue and its forecast."""

from __future__ import annotations

from datetime import date

import pytest

from builders import board_item, link
from mondaycom import burndown as bd
from mondaycom import planning as pl
from mondaycom.config import (
    CAPACITY_BOARD,
    DAM,
    DISTRIBUTION_BOARD,
    EPIC_BOARD,
    EPIC_GROUP_ACTIVE,
    EPIC_GROUP_BACKLOG,
    EPIC_GROUP_DISCUSS,
    NON_DAM,
)

DEFAULT = {"DE": 35.0, "DB": 30.0, "DS": 25.0, "PO/AT": 10.0}


def split(epic_id: str, todo: float, shares: dict[str, float | None] | None = None) -> pl.Split:
    return pl.Split(
        id=f"s-{epic_id}", name=epic_id, epic_id=epic_id, todo=todo, has_todo=True, shares=shares or DEFAULT
    )


def person(name: str, role: str, available: float = 100, overhead: float = 0, stp: float = 10) -> pl.Person:
    return pl.Person(
        name=name, role=role, stp=stp, sprint_available=available, quarter_available=available, overhead=overhead
    )


def epic(id: str, group: str = EPIC_GROUP_ACTIVE, priority: str = "High", due: date | None = None) -> pl.PlanEpic:
    return pl.PlanEpic(id=id, name=f"Epic {id}", group=group, priority=priority, due=due)


TEAM = [person("A", "DE"), person("B", "DB"), person("C", "DS"), person("D", "PO/AT")]

#: Six weeks from a Monday: two whole sprints, and three days over.
WINDOW = pl.Window(date(2026, 10, 5), date(2026, 11, 18))


def snapshot(epics: list[pl.PlanEpic], splits: list[pl.Split], people: list[pl.Person] = TEAM) -> pl.Snapshot:
    return pl.Snapshot(splits=splits, epics=epics, people=people, current_end=date(2026, 10, 4))


# --- reading the boards -----------------------------------------------------------------


def test_mirror_members_are_added_up() -> None:
    assert pl.parse_mirror("19, 3, 1") == 23
    assert pl.parse_mirror("2.5") == 2.5
    assert pl.parse_mirror("") == 0


def test_split_from_item_reads_link_mirror_and_blank_percentages() -> None:
    item = board_item(
        DISTRIBUTION_BOARD,
        "Waterbalans",
        epic=link("Waterbalans", "42"),
        todo={"text": None, "display_value": "19, 3, 1"},
        DE="50",
        DB="50",
        DS="",
        **{"PO/AT": None},
    )
    s = pl.Split.from_item(item)
    assert (s.epic_id, s.todo, s.has_todo) == ("42", 23, True)
    assert s.shares == {"DE": 50, "DB": 50, "DS": None, "PO/AT": None}
    assert s.is_valid
    assert s.share("DE") == 11.5


def test_a_split_must_be_filled_in_and_add_up_to_100() -> None:
    assert split("e", 10, dict.fromkeys(DEFAULT)).problem == "no split filled in"
    assert split("e", 10, {"DE": 40, "DB": 30, "DS": 20, "PO/AT": 0}).problem == "split adds up to 90%"
    assert split("e", 10, {"DE": 33.3, "DB": 33.3, "DS": 33.4, "PO/AT": None}).is_valid


def test_person_capacity_is_stp_times_availability_minus_overhead() -> None:
    p = pl.Person(name="Jelle", role="DS", stp=16, sprint_available=90, quarter_available=80, overhead=10)
    assert p.next_sprint == pytest.approx(16 * 0.9 * 0.9)
    assert p.per_sprint == pytest.approx(16 * 0.8 * 0.9)


def test_person_from_item() -> None:
    item = board_item(
        CAPACITY_BOARD,
        "Agnes Dubbink",
        role="DE",
        stp="16",
        sprint_available="100",
        quarter_available="90",
        overhead="10",
    )
    p = pl.Person.from_item(item)
    assert (p.role, p.stp, p.sprint_available, p.quarter_available, p.overhead) == ("DE", 16, 100, 90, 10)


def test_plan_epic_from_item_reads_group_due_date_and_portfolio() -> None:
    item = board_item(
        EPIC_BOARD,
        "Waterbalans",
        "7",
        {"id": EPIC_GROUP_ACTIVE, "title": "Actief"},
        status="Working on it",
        priority="High",
        due_date="2026-12-31",
        portfolio=link("", "5097962811"),
    )
    e = pl.PlanEpic.from_item(item)
    assert (e.group, e.group_title, e.due) == (EPIC_GROUP_ACTIVE, "Actief", date(2026, 12, 31))
    assert e.is_dam


# --- the window -------------------------------------------------------------------------


def test_quarter_end() -> None:
    assert pl.quarter_end(date(2026, 9, 28)) == date(2026, 9, 30)
    assert pl.quarter_end(date(2026, 10, 1)) == date(2026, 12, 31)
    assert pl.quarter_end(date(2026, 12, 31)) == date(2026, 12, 31)
    assert pl.quarter_end(date(2027, 2, 1)) == date(2027, 3, 31)


def test_window_counts_whole_sprints_only() -> None:
    assert WINDOW.sprints == 2
    assert WINDOW.sprint_end(1) == date(2026, 10, 25)
    assert WINDOW.last_day == date(2026, 11, 15)


def test_default_window_is_the_quarter_the_first_sprint_ends_in() -> None:
    # The sprint that starts on 28 September ends in October: that is Q4 work.
    w = pl.window(date(2026, 9, 27))
    assert (w.start, w.end, w.sprints) == (date(2026, 9, 28), date(2026, 12, 31), 4)


def test_window_takes_explicit_dates_and_refuses_nonsense() -> None:
    w = pl.window(date(2026, 9, 27), start="2026-10-05", end="2026-11-18")
    assert w == WINDOW
    with pytest.raises(ValueError, match="not a date"):
        pl.window(date(2026, 9, 27), end="next week")
    with pytest.raises(ValueError, match="before the start"):
        pl.window(date(2026, 9, 27), start="2026-10-05", end="2026-10-01")


# --- layers -----------------------------------------------------------------------------


def test_layer_is_the_group_narrowed_by_the_due_date() -> None:
    end = date(2026, 12, 31)
    assert epic("a").layer(end) == pl.PROMISED
    assert epic("b", group=EPIC_GROUP_DISCUSS, due=end).layer(end) == pl.PROMISED
    assert epic("c", due=date(2027, 3, 31)).layer(end) == pl.LATER
    # A due date inside the quarter does not pull a Backlog epic into the promise.
    assert epic("d", group=EPIC_GROUP_BACKLOG, due=end).layer(end) == pl.BACKLOG
    assert epic("e", group="new_group10768").layer(end) == ""  # Afgerond


def test_parse_layers_keeps_queue_order_and_defaults_to_promised() -> None:
    assert pl.parse_layers(["backlog", "promised"]) == (pl.PROMISED, pl.BACKLOG)
    assert pl.parse_layers([]) == (pl.PROMISED,)
    assert pl.parse_layers(["nonsense"]) == (pl.PROMISED,)


# --- the plan ---------------------------------------------------------------------------


def test_only_linked_valid_splits_are_planned_and_the_rest_is_reported() -> None:
    epics = [epic("a"), epic("b"), epic("c"), epic("done", group="new_group10768")]
    splits = [
        split("a", 20),
        split("b", 20, {"DE": 50, "DB": None, "DS": None, "PO/AT": None}),
        split("done", 20),
        pl.Split(id="loose", name="c"),  # same name as nothing, linked to nothing
    ]
    p = pl.plan(snapshot(epics, splits), WINDOW)
    assert [q.epic.id for q in p.queue] == ["a"]
    assert [(pr.epic.id, pr.reason) for pr in p.problems] == [
        ("b", "split adds up to 50%"),
        ("c", "not linked on Epics-STP-distribution"),
    ]
    # A bad split points at the row to fix; a missing link points at the epic.
    assert "5105081537" in p.problems[0].url
    assert "757753649" in p.problems[1].url


def test_queue_order_is_layer_priority_due_date_then_smallest() -> None:
    end = WINDOW.end
    epics = [
        epic("backlog", group=EPIC_GROUP_BACKLOG, priority="Very High"),
        epic("later", priority="Very High", due=date(2027, 1, 31)),
        epic("medium", priority="Medium"),
        epic("high-big", priority="High"),
        epic("high-small", priority="High"),
        epic("high-due", priority="High", due=end),
        epic("no-prio", priority=""),
    ]
    sizes = {"high-big": 30, "high-small": 3}
    p = pl.plan(
        snapshot(epics, [split(e.id, sizes.get(e.id, 10)) for e in epics]), WINDOW, (pl.PROMISED, pl.LATER, pl.BACKLOG)
    )
    assert [q.epic.id for q in p.queue] == [
        "high-due",
        "high-small",
        "high-big",
        "medium",
        "no-prio",
        "later",
        "backlog",
    ]


def test_each_discipline_works_down_the_queue_and_the_slowest_share_decides() -> None:
    # 10 STP per person per sprint. Epic a is all DE, 15 points: DE is through it in
    # sprint 2. Epic b is all DB, 5 points: sprint 1, even though it queues behind a.
    epics = [epic("a", priority="Very High"), epic("b", priority="Low"), epic("c", priority="Low")]
    splits = [
        split("a", 15, {"DE": 100}),
        split("b", 5, {"DB": 100}),
        split("c", 20, {"DE": 50, "DB": 50}),
    ]
    p = pl.plan(snapshot(epics, splits), WINDOW)
    finish = {q.epic.id: q.finish_sprint for q in p.queue}
    # c needs 10 more DE after a's 15 (25 → sprint 3) and 10 more DB after b's 5 (15 → sprint 2).
    assert finish == {"a": 2, "b": 1, "c": 3}
    by_id = {q.epic.id: q for q in p.queue}
    assert by_id["a"].finish == date(2026, 11, 15)
    assert by_id["a"].fits(WINDOW) and not by_id["c"].fits(WINDOW)
    assert by_id["c"].verdict(WINDOW) == ("after the quarter", "warning")


def test_an_exact_fit_does_not_spill_into_the_next_sprint() -> None:
    p = pl.plan(snapshot([epic("a")], [split("a", 20, {"DE": 100})]), WINDOW)
    assert p.queue[0].finish_sprint == 2


def test_nobody_in_a_discipline_means_no_capacity() -> None:
    team = [person("A", "DE")]
    p = pl.plan(snapshot([epic("a")], [split("a", 10)], team), WINDOW)
    q = p.queue[0]
    assert q.finish_sprint is None
    assert q.verdict(WINDOW) == ("no capacity", "critical")
    ds = next(d for d in p.disciplines if d.key == "DS")
    assert ds.sprints_needed is None
    assert ds.load(WINDOW.sprints) is None


def test_late_against_the_epics_own_due_date() -> None:
    p = pl.plan(snapshot([epic("a", due=date(2026, 10, 20))], [split("a", 15, {"DE": 100})]), WINDOW)
    q = p.queue[0]
    assert q.late
    assert q.verdict(WINDOW) == ("late", "critical")


def test_on_time_and_nothing_left() -> None:
    epics = [epic("a", due=WINDOW.end), epic("b")]
    splits = [split("a", 5, {"DE": 100}), split("b", 0)]
    p = pl.plan(snapshot(epics, splits), WINDOW)
    verdicts = {q.epic.id: q.verdict(WINDOW)[0] for q in p.queue}
    assert verdicts == {"a": "on time", "b": "nothing left"}


def test_an_empty_stp_todo_is_flagged_not_counted_as_done() -> None:
    s = pl.Split(id="s", name="a", epic_id="a", shares=DEFAULT)
    p = pl.plan(snapshot([epic("a")], [s]), WINDOW)
    assert p.queue[0].verdict(WINDOW) == ("no STP-TODO", "neutral")


def de_of(p: pl.Plan) -> pl.Discipline:
    return next(d for d in p.disciplines if d.key == "DE")


def test_the_load_is_exactly_the_selection() -> None:
    epics = [epic("a"), epic("b", due=date(2027, 1, 31)), epic("c", group=EPIC_GROUP_BACKLOG)]
    splits = [split("a", 10, {"DE": 100}), split("b", 20, {"DE": 100}), split("c", 30, {"DE": 100})]
    snap = snapshot(epics, splits)

    everything = de_of(pl.plan(snap, WINDOW, (pl.PROMISED, pl.LATER, pl.BACKLOG)))
    assert everything.demand == {pl.PROMISED: 10, pl.LATER: 20, pl.BACKLOG: 30}
    assert everything.load(WINDOW.sprints) == 3

    promised = de_of(pl.plan(snap, WINDOW))
    assert promised.total == 10
    assert promised.sprints_needed == 1
    assert promised.load(WINDOW.sprints) == 0.5

    # Backlog alone is the backlog alone: nothing outside the selection takes capacity.
    backlog = pl.plan(snap, WINDOW, (pl.BACKLOG,))
    assert de_of(backlog).total == 30
    assert [(q.epic.id, q.finish_sprint) for q in backlog.queue] == [("c", 3)]


def test_the_dam_filter_narrows_queue_load_problems_and_next_sprint() -> None:
    dam_epic = pl.PlanEpic(id="d", name="DAM", group=EPIC_GROUP_ACTIVE, portfolio_ids=("p1",))
    unlinked_dam = pl.PlanEpic(id="u", name="DAM, no split", group=EPIC_GROUP_ACTIVE, portfolio_ids=("p1",))
    snap = snapshot([dam_epic, unlinked_dam, epic("n")], [split("d", 10, {"DE": 100}), split("n", 30, {"DE": 100})])
    snap.next_sprint = [
        bd.SprintItem(id="1", name="t1", points=4, status="To Do", epic_id="d"),
        bd.SprintItem(id="2", name="t2", points=6, status="To Do", epic_id="n"),
        bd.SprintItem(id="3", name="t3", points=2, status="To Do"),
    ]

    dam = pl.plan(snap, WINDOW, dam=DAM)
    assert [q.epic.id for q in dam.queue] == ["d"]
    assert de_of(dam).total == 10
    assert [pr.epic.id for pr in dam.problems] == ["u"]
    assert dam.next_sprint.load["DE"] == 4

    non_dam = pl.plan(snap, WINDOW, dam=NON_DAM)
    assert [q.epic.id for q in non_dam.queue] == ["n"]
    assert non_dam.problems == []
    # A task with no epic is non-DAM, and has no split to put it on a discipline.
    assert (non_dam.next_sprint.load["DE"], non_dam.next_sprint.unplaced) == (6, 2)

    both = pl.plan(snap, WINDOW)
    assert de_of(both).total == 40


def test_most_overbooked_puts_the_heaviest_first_and_empty_last() -> None:
    epics = [epic("a")]
    splits = [split("a", 30, {"DE": 80, "DB": 20})]
    p = pl.plan(snapshot(epics, splits, [person("A", "DE"), person("B", "DB"), person("C", "DS")]), WINDOW)
    order = [d.key for d in pl.most_overbooked(p)]
    # PO/AT has nobody and no work: load 0, not "nobody", so it does not lead.
    assert order[:2] == ["DE", "DB"]


def test_people_with_an_unknown_role_are_reported() -> None:
    p = pl.plan(snapshot([], [], [*TEAM, person("Z", "Scrum master")]), WINDOW)
    assert [x.name for x in p.unassigned_people] == ["Z"]


def test_next_sprint_weighs_open_tasks_by_their_epic_split() -> None:
    snap = snapshot([epic("a")], [split("a", 10, {"DE": 50, "DB": 50})])
    snap.next_sprint = [
        bd.SprintItem(id="1", name="t1", points=4, status="To Do", epic_id="a"),
        bd.SprintItem(id="2", name="t2", points=3, status="Done", epic_id="a"),
        bd.SprintItem(id="3", name="t3", points=2, status="To Do", epic_id="unlinked"),
    ]
    n = pl.plan(snap, WINDOW).next_sprint
    assert n.tasks == 2
    assert (n.load["DE"], n.load["DB"], n.load["DS"]) == (2, 2, 0)
    assert n.unplaced == 2
    assert n.capacity["DE"] == 10


def test_this_quarter_keeps_only_epics_due_by_the_quarter_end() -> None:
    epics = [
        epic("due", due=WINDOW.end),
        epic("undated"),
        epic("later", due=date(2027, 1, 31)),
        epic("backlog-due", group=EPIC_GROUP_BACKLOG, due=date(2026, 10, 30)),
        epic("unlinked-due", due=date(2026, 11, 1)),
    ]
    splits = [split(e.id, 10) for e in epics if e.id != "unlinked-due"]
    every_layer = (pl.PROMISED, pl.LATER, pl.BACKLOG)

    p = pl.plan(snapshot(epics, splits), WINDOW, every_layer, this_quarter=True)
    # Every ticked layer is narrowed, Backlog included; no due date never counts as due.
    assert [q.epic.id for q in p.queue] == ["due", "backlog-due"]
    assert [pr.epic.id for pr in p.problems] == ["unlinked-due"]
    assert p.this_quarter

    # The layers still decide on their own: unticked Backlog stays out.
    assert [q.epic.id for q in pl.plan(snapshot(epics, splits), WINDOW, this_quarter=True).queue] == ["due"]
    assert len(pl.plan(snapshot(epics, splits), WINDOW, every_layer).queue) == 4


# --- the cards view's per-discipline figures -----------------------------------------------


def test_full_capacity_is_everybody_at_100_percent_with_their_overhead_kept() -> None:
    d = pl.Discipline("DS", people=[person("A", "DS", available=50, overhead=10), person("B", "DS", available=80)])
    assert d.per_sprint == 10 * 0.5 * 0.9 + 10 * 0.8
    assert d.full_capacity(4) == 4 * 19 and d.capacity(4) == 4 * 12.5


def test_the_load_band_is_blue_under_green_on_and_red_over_target() -> None:
    assert pl.load_tone(0.5) == "active" and pl.load_tone(0.89) == "active"
    assert pl.load_tone(0.9) == "good" and pl.load_tone(1.1) == "good"
    assert pl.load_tone(1.11) == "critical" and pl.load_tone(None) == "critical"


def test_discipline_shares_follow_the_queue_into_the_sprints_they_land_in() -> None:
    a = pl.Planned(epic=epic("a"), split=split("a", todo=15, shares={"DE": 100.0}), layer=pl.PROMISED)
    b = pl.Planned(epic=epic("b"), split=split("b", todo=10, shares={"DE": 50.0, "DB": 50.0}), layer=pl.PROMISED)
    c = pl.Planned(epic=epic("c"), split=split("c", todo=20, shares={"DE": 100.0}), layer=pl.PROMISED)
    d = pl.Discipline("DE", people=[person("A", "DE")])
    shares = pl.discipline_shares([a, b, c], d)
    assert [(s.planned.epic.id, s.position, s.points, s.first, s.last) for s in shares] == [
        ("a", 1, 15.0, 1, 2),
        ("b", 2, 5.0, 2, 2),
        ("c", 3, 20.0, 3, 4),
    ]
    nobody = pl.discipline_shares([a], pl.Discipline("DE"))
    assert (nobody[0].first, nobody[0].last) == (None, None), "no capacity, no sprints"


def test_the_left_out_reasons_have_dutch_words_for_the_web() -> None:
    assert split("e", 10, dict.fromkeys(DEFAULT)).problem_words == ("no split filled in", "geen verdeling ingevuld")
    assert split("e", 10, {"DE": 90}).problem_words[1] == "verdeling telt op tot 90%"
    assert all(word in pl.VERDICTS_NL for word in ("no capacity", "late", "on time", "after the quarter"))
