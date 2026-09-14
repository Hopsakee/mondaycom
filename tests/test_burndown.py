"""Offline tests for the burndown maths and its SVG. No network."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fasthtml.common import to_xml

from mondaycom import chart
from mondaycom.burndown import SprintItem, build, fmt, narrow, owned, people, sprint_window
from mondaycom.config import DAM, NON_DAM

# A three-week sprint: 2026-08-17 .. 2026-09-06 inclusive.
END = "2026-09-06"
START = date(2026, 8, 17)


def task(points: float, status: str = "To Do", done: str = "", due: str = END) -> SprintItem:
    return SprintItem(
        id="1",
        name="t",
        points=points,
        status=status,
        done_on=date.fromisoformat(done) if done else None,
        due_date=due,
    )


def test_the_window_is_three_weeks_back_from_the_common_due_date() -> None:
    items = [task(1, due=END), task(1, due=END), task(1, due="2026-08-31")]
    assert sprint_window(items) == (START, date(2026, 9, 6)), "the odd due date must not win"


def test_an_explicit_end_overrides_the_data() -> None:
    assert sprint_window([task(1)], end="2026-09-19")[1] == date(2026, 9, 19)


def test_no_due_dates_at_all_is_an_error_not_a_guess() -> None:
    with pytest.raises(ValueError, match="explicit end date"):
        sprint_window([task(1, due="")])


def test_committed_is_the_total_minus_cancelled() -> None:
    b = build([task(5), task(3), task(2, status="Vervallen")], end=END, today=date(2026, 8, 20))
    assert b.committed == 8, "Vervallen leaves the sprint rather than counting as work"
    assert b.cancelled == 2


def test_done_points_are_summed() -> None:
    b = build([task(5, "Done", "2026-08-19"), task(3)], end=END, today=date(2026, 8, 20))
    assert b.done == 5
    assert b.remaining == 3


def test_a_cancelled_task_is_never_counted_as_done() -> None:
    b = build([task(5, "Vervallen", "2026-08-19")], end=END, today=date(2026, 8, 20))
    assert b.done == 0 and b.committed == 0


def test_the_ideal_line_runs_from_committed_to_zero() -> None:
    b = build([task(10)], end=END, today=START)
    assert b.days[0].ideal == 10
    assert b.days[-1].ideal == 0
    assert b.days[-1].on == date(2026, 9, 6)
    assert len(b.days) == 21, "three weeks inclusive"


def test_a_task_burns_down_on_its_done_date_not_today() -> None:
    b = build([task(4, "Done", "2026-08-19"), task(6)], end=END, today=date(2026, 8, 21))
    by_day = {d.on: d.remaining for d in b.days}
    assert by_day[date(2026, 8, 18)] == 10, "still open the day before"
    assert by_day[date(2026, 8, 19)] == 6, "burned on the day it was finished"


def test_future_days_have_no_actual_value() -> None:
    b = build([task(10)], end=END, today=date(2026, 8, 20))
    assert all(d.remaining is not None for d in b.days if d.on <= date(2026, 8, 20))
    assert all(d.remaining is None for d in b.days if d.on > date(2026, 8, 20))


def test_work_finished_before_the_sprint_opened_lands_on_day_one() -> None:
    b = build([task(4, "Done", "2026-08-01"), task(6)], end=END, today=date(2026, 8, 20))
    assert b.days[0].remaining == 6, "already-done work does not sit above the line for three weeks"


def test_done_without_a_date_still_burns_rather_than_vanishing() -> None:
    b = build([task(4, "Done"), task(6)], end=END, today=date(2026, 8, 20))
    assert b.done == 4
    assert b.days[0].remaining == 6


def test_being_ahead_and_behind_the_line() -> None:
    halfway = date(2026, 8, 27)  # day 10 of 20, so the ideal is half of the total
    behind = build([task(100)], end=END, today=halfway)
    assert behind.remaining == 100 and not behind.on_track
    assert "behind" in behind.verdict

    ahead = build([task(100, "Done", "2026-08-18"), task(0)], end=END, today=halfway)
    assert ahead.on_track and "ahead" in ahead.verdict


def test_exactly_on_the_line_reads_as_on_track() -> None:
    b = build([task(50, "Done", "2026-08-18"), task(50)], end=END, today=date(2026, 8, 27))
    assert b.verdict == "on track"


def test_after_the_sprint_ends() -> None:
    finished = build([task(10, "Done", "2026-09-01")], end=END, today=date(2026, 9, 20))
    assert finished.verdict == "sprint over"
    unfinished = build([task(10)], end=END, today=date(2026, 9, 20))
    assert unfinished.verdict == "sprint over, 10 left"


def test_points_render_without_a_pointless_decimal() -> None:
    assert fmt(12.0) == "12"
    assert fmt(12.5) == "12.5"


def test_a_sprint_with_no_points_does_not_divide_by_zero() -> None:
    b = build([task(0)], end=END, today=START)
    assert b.committed == 0 and b.days[0].ideal == 0


# --- the chart ---------------------------------------------------------------


def test_axis_maximum_is_a_clean_number_above_the_data() -> None:
    for value, (top, step) in ((103, (120.0, 20.0)), (26, (30.0, 5.0)), (7, (8.0, 2.0))):
        assert chart.nice_ceiling(value) == (top, step)
        assert top >= value


def test_a_zero_axis_still_has_a_scale() -> None:
    assert chart.nice_ceiling(0) == (1.0, 1.0)


def svg(**kwargs: Any) -> str:
    b = build([task(4, "Done", "2026-08-19"), task(6)], end=END, today=date(2026, 8, 21), **kwargs)
    return to_xml(chart.burndown_svg(b))


def test_the_svg_draws_both_lines() -> None:
    out = svg()
    assert out.count("<path") == 2, "one ideal, one actual"
    assert "stroke-dasharray" in out, "the ideal line is dashed, so it is not hue-only"
    assert "var(--series-actual)" in out and "var(--series-ideal)" in out


def test_the_svg_carries_a_tooltip_for_every_day() -> None:
    assert svg().count("<title>") == 21


def test_the_svg_is_labelled_for_screen_readers() -> None:
    assert 'role="img"' in svg() and "aria-label" in svg()


def test_the_actual_line_stops_at_today() -> None:
    """Three points: the 17th, 18th... through the 21st — never into the future."""
    out = svg()
    actual = out.split('<path d="')[2].split('"')[0]
    assert actual.count("L") == 4, "17th plus four more days up to the 21st"


def test_the_table_view_lists_every_day() -> None:
    b = build([task(10)], end=END, today=date(2026, 8, 21))
    assert to_xml(chart.burndown_table(b)).count("<tr>") == 22, "21 days plus the header"


# --- the person and portfolio filters -------------------------------------------------


def assigned(owner: str = "", reviewer: str = "", epic_id: str = "", points: float = 1.0) -> SprintItem:
    return SprintItem(id="1", name="t", points=points, owner=owner, reviewer=reviewer, epic_id=epic_id, due_date=END)


def test_assigned_to_means_owner_or_reviewer() -> None:
    """What a person filter *shows*: your own work and the work you review."""
    assert assigned(owner="Jelle de Jong").assigned_to("Jelle de Jong")
    assert assigned(reviewer="Jelle de Jong").assigned_to("Jelle de Jong")
    assert not assigned(owner="Agnes Dubbink").assigned_to("Jelle de Jong")


def test_owned_by_means_the_trekker_alone() -> None:
    """What a person filter *counts*: the points land on the Trekker."""
    assert assigned(owner="Jelle de Jong").owned_by("Jelle de Jong")
    assert not assigned(reviewer="Jelle de Jong").owned_by("Jelle de Jong"), "reviewing is not owning"
    assert not assigned().owned_by("Jelle de Jong"), "a task with no Trekker counts for nobody"


def test_one_name_out_of_several_still_counts() -> None:
    assert assigned(reviewer="Agnes Dubbink, Jelle de Jong").assigned_to("Jelle de Jong")
    assert assigned(owner="Agnes Dubbink, Jelle de Jong").owned_by("Jelle de Jong")


def test_the_person_filter_keeps_the_tasks_they_own_and_the_ones_they_review() -> None:
    items = [assigned(owner="Jelle de Jong"), assigned(owner="Agnes Dubbink"), assigned(reviewer="Jelle de Jong")]
    assert len(narrow(items, person="Jelle de Jong")) == 2


def test_owned_keeps_only_the_points_that_are_that_persons() -> None:
    """The list holds review work, the burndown built from it does not."""
    items = [assigned(owner="Jelle de Jong", points=3), assigned(reviewer="Jelle de Jong", points=5)]
    kept = narrow(items, person="Jelle de Jong")
    assert len(kept) == 2
    assert [i.points for i in owned(kept, "Jelle de Jong")] == [3]
    assert build(owned(kept, "Jelle de Jong"), end=END).committed == 3, "the 5 are Agnes's"


def test_owned_without_a_person_narrows_nothing() -> None:
    items = [assigned(owner="Jelle de Jong"), assigned(reviewer="Agnes Dubbink")]
    assert owned(items) == items


def test_no_person_is_everybody() -> None:
    items = [assigned(owner="Jelle de Jong"), assigned(owner="Agnes Dubbink")]
    assert narrow(items) == items


def test_dam_splits_on_whether_the_epic_is_in_the_portfolio() -> None:
    inside, outside, nothing = assigned(epic_id="e1"), assigned(epic_id="e2"), assigned()
    items = [inside, outside, nothing]
    assert narrow(items, dam=DAM, dam_epics=frozenset({"e1"})) == [inside]
    assert narrow(items, dam=NON_DAM, dam_epics=frozenset({"e1"})) == [outside, nothing]


def test_a_task_with_no_epic_can_never_be_dam() -> None:
    assert narrow([assigned()], dam=DAM, dam_epics=frozenset({"e1"})) == []


def test_the_filters_stack() -> None:
    mine_inside = assigned(owner="Jelle de Jong", epic_id="e1")
    mine_outside = assigned(owner="Jelle de Jong", epic_id="e2")
    hers_inside = assigned(owner="Agnes Dubbink", epic_id="e1")
    kept = narrow(
        [mine_inside, mine_outside, hers_inside], person="Jelle de Jong", dam=DAM, dam_epics=frozenset({"e1"})
    )
    assert kept == [mine_inside]


def test_a_filtered_burndown_keeps_the_whole_groups_sprint_window() -> None:
    """One person's two tasks are far too small a sample to guess the sprint end from."""
    group = [task(3, due=END), task(3, due=END), task(2, due="2026-10-31")]
    mine = [group[2]]
    filtered = build(mine, today=START, window_from=group)
    assert (filtered.start, filtered.end) == (START, date(2026, 9, 6))
    assert filtered.committed == 2, "but the numbers are only the filtered slice"


def test_without_window_from_the_window_still_comes_from_the_items() -> None:
    board = build([task(3), task(3)], today=START)
    assert board.end == date(2026, 9, 6)


def test_a_filtered_burndown_burns_down_only_what_it_kept() -> None:
    group = [task(4, status="Done", done="2026-08-20"), task(6)]
    board = build(narrow(group), today=date(2026, 8, 20), window_from=group)
    assert (board.committed, board.done) == (10, 4)


# --- the sprint page's use of the group -------------------------------------------------


def test_narrow_by_epic_keeps_only_that_epics_tasks() -> None:
    items = [
        SprintItem(id="1", name="A", epic_id="e1"),
        SprintItem(id="2", name="B", epic_id="e2"),
        SprintItem(id="3", name="C"),
    ]
    assert [i.id for i in narrow(items, epic="e1")] == ["1"]
    assert [i.id for i in narrow(items)] == ["1", "2", "3"], "no epic filter keeps tasks with no epic too"


def test_the_small_multiples_are_one_per_trekker() -> None:
    items = [
        SprintItem(id="1", name="A", owner="Jelle de Jong", reviewer="Agnes Dubbink"),
        SprintItem(id="2", name="B", owner="Agnes Dubbink, Rutger Feijen"),
        SprintItem(id="3", name="C"),
    ]
    assert people(items) == ["Agnes Dubbink", "Jelle de Jong", "Rutger Feijen"]


def test_people_leaves_out_someone_who_only_reviews() -> None:
    items = [SprintItem(id="1", name="A", owner="Jelle de Jong", reviewer="Rutger Feijen")]
    assert people(items) == ["Jelle de Jong"], "a card with none of its own points says nothing"


def test_a_sprint_item_becomes_the_task_the_list_shows() -> None:
    item = SprintItem(
        id="7",
        name="Taak",
        points=2.0,
        status="To Do",
        due_date="2026-09-06",
        owner="Agnes Dubbink",
        reviewer="Jelle de Jong",
        epic="Waterbalans",
        epic_id="e1",
    )
    task = item.as_task(me="Jelle de Jong")
    assert (task.id, task.name, task.status, task.due_date) == ("7", "Taak", "To Do", "2026-09-06")
    assert task.story_points == 2 and task.duration_minutes == 240
    assert task.is_reviewer and not item.as_task(me="Agnes Dubbink").is_reviewer
    assert (task.owner, task.epic, task.epic_id) == ("Agnes Dubbink", "Waterbalans", "e1")


def test_work_finished_after_the_sprint_closed_burns_on_the_last_day() -> None:
    items = [
        SprintItem(id="1", name="Late", points=4, status="Done", done_on=date(2026, 9, 8), due_date="2026-09-06"),
        SprintItem(id="2", name="Open", points=6, status="To Do", due_date="2026-09-06"),
    ]
    b = build(items, today=date(2026, 9, 9))
    assert b.days[-1].remaining == 6 == b.remaining, "the line ends where the tiles say it does"
    assert b.days[-1].burned == 4
