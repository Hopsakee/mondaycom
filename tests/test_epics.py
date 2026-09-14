"""Offline tests for the epics overview: the point totals, the filters, the sorting."""

from __future__ import annotations

from typing import Any

import pytest

from mondaycom import epics as ep
from mondaycom.config import DAM, DONE_BOARD, DUMMY_GROUPS, EPIC_BOARD, NON_DAM, SPRINT_BOARD, Board


def epic_item(
    item_id: str, name: str, owner: str = "", status: str = "", priority: str = "", portfolio: str = ""
) -> dict[str, Any]:
    """An epic board item as `queries.epic_rows` returns it. Portfolio is a
    board_relation, so its name arrives in `display_value` and `text` is null."""
    return {
        "id": item_id,
        "name": name,
        "column_values": [
            {"id": EPIC_BOARD.column("owner"), "text": owner},
            {"id": EPIC_BOARD.column("status"), "text": status},
            {"id": EPIC_BOARD.column("priority"), "text": priority},
            {
                "id": EPIC_BOARD.column("portfolio"),
                "text": None,
                "display_value": portfolio,
                "linked_item_ids": [f"p-{portfolio}"] if portfolio else [],
            },
        ],
    }


def task_item(
    item_id: str, points: str, status: str, epic_id: str = "", group: str = "backlog", board: Board = SPRINT_BOARD
) -> dict[str, Any]:
    """A sprint board item as `queries.board_tasks` returns it."""
    return {
        "id": item_id,
        "group": {"id": group},
        "column_values": [
            {"id": board.column("story_points"), "text": points},
            {"id": board.column("status"), "text": status},
            {"id": board.column("epic"), "text": None, "linked_item_ids": [epic_id] if epic_id else []},
        ],
    }


def epic(name: str = "E", **kw: Any) -> ep.Epic:
    done = kw.pop("done", 0.0)
    remaining = kw.pop("remaining", 0.0)
    return ep.Epic(id=kw.pop("id", "1"), name=name, points=ep.Points(done=done, remaining=remaining), **kw)


# --- reading an epic ------------------------------------------------------------------


def test_an_epic_reads_its_four_columns() -> None:
    row = ep.Epic.from_item(epic_item("7", "Waterbalans", "Agnes Dubbink", "Working on it", "High", "E-DNA BWSD"))
    assert (row.id, row.name, row.owner) == ("7", "Waterbalans", "Agnes Dubbink")
    assert (row.status, row.priority, row.portfolio) == ("Working on it", "High", "E-DNA BWSD")


def test_a_portfolio_link_is_what_makes_an_epic_dam() -> None:
    """The epic board's own formula is `IF({Portfolio#Count} > 0, TRUE(), FALSE())`."""
    assert ep.Epic.from_item(epic_item("7", "In het portfolio", portfolio="E-DNA BWSD")).is_dam
    assert not ep.Epic.from_item(epic_item("8", "Niet in het portfolio")).is_dam


# --- the point totals -----------------------------------------------------------------


def test_open_tasks_are_remaining_and_done_tasks_are_done() -> None:
    items = [task_item("1", "3", "To Do", "e1"), task_item("2", "2", "Done", "e1")]
    assert ep.tally_tasks(items, SPRINT_BOARD) == {"e1": ep.Points(done=2, remaining=3, tasks=2)}


def test_the_status_decides_not_the_board() -> None:
    """The done board holds the odd unfinished row, so it is read like any other."""
    items = [task_item("1", "5", "Wacht op Antwoord", "e1", board=DONE_BOARD)]
    assert ep.tally_tasks(items, DONE_BOARD)["e1"] == ep.Points(remaining=5, tasks=1)


def test_cancelled_work_leaves_the_total_instead_of_counting_as_progress() -> None:
    items = [task_item("1", "4", "Done", "e1"), task_item("2", "9", "Vervallen", "e1")]
    tally = ep.tally_tasks(items, SPRINT_BOARD)
    assert tally["e1"] == ep.Points(done=4, remaining=0, cancelled=9, tasks=2)


def test_dummy_user_stories_are_skipped() -> None:
    """Their estimates are epic-level guesses — 1705 points on the active board alone."""
    dummy = next(iter(DUMMY_GROUPS[SPRINT_BOARD.id]))
    items = [task_item("1", "2", "To Do", "e1"), task_item("2", "600", "User story", "e1", group=dummy)]
    assert ep.tally_tasks(items, SPRINT_BOARD)["e1"] == ep.Points(remaining=2, tasks=1)


def test_tasks_with_no_epic_are_not_folded_into_someone_elses_total() -> None:
    assert ep.tally_tasks([task_item("1", "3", "To Do")], SPRINT_BOARD) == {}


def test_unreadable_points_count_as_zero_rather_than_crashing() -> None:
    items = [task_item("1", "n/a", "Done", "e1"), task_item("2", "", "To Do", "e1")]
    assert ep.tally_tasks(items, SPRINT_BOARD)["e1"] == ep.Points(tasks=2)


def test_fetch_epics_sums_both_boards_and_reports_what_it_could_not_place(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        EPIC_BOARD.id: [epic_item("e1", "Waterbalans", portfolio="E-DNA BWSD"), epic_item("e2", "Droogte")],
        SPRINT_BOARD.id: [task_item("1", "3", "To Do", "e1"), task_item("2", "1", "To Do")],
        DONE_BOARD.id: [
            task_item("3", "8", "Done", "e1", board=DONE_BOARD),
            task_item("4", "2", "Done", board=DONE_BOARD),
        ],
    }

    class Fake:
        def all_board_items(self, build: Any) -> list[dict[str, Any]]:
            query = build(None)
            return next(items for bid, items in pages.items() if str(bid) in query)

    rows, orphans = ep.fetch_epics(Fake())  # type: ignore[arg-type]
    by_id = {row.id: row for row in rows}
    assert (by_id["e1"].done, by_id["e1"].remaining) == (8, 3)
    assert by_id["e2"].total == 0, "an epic with no tasks has nothing to sum"
    assert orphans == ep.Points(done=2, remaining=1, tasks=2)


def test_points_on_an_epic_the_board_did_not_return_are_reported_as_orphans() -> None:
    orphans = ep._with_unknown(ep.Points(), {"gone": ep.Points(done=5, tasks=1)}, known={"e1"})
    assert orphans == ep.Points(done=5, tasks=1)


# --- the battery ----------------------------------------------------------------------


def test_progress_buckets() -> None:
    assert epic(done=0, remaining=0).bucket == "no-tasks"
    assert epic(done=0, remaining=4).bucket == "not-started"
    assert epic(done=2, remaining=4).bucket == "in-progress"
    assert epic(done=6, remaining=0).bucket == "complete"


def test_an_epic_with_no_tasks_sorts_after_a_full_one_rather_than_as_empty() -> None:
    """There is nothing to be 0% of, so it does not lead the "least done" list."""
    assert epic(done=0, remaining=0).fraction_done == ep.NO_TASKS
    assert epic(done=0, remaining=0).fraction_done > epic(done=9, remaining=0).fraction_done


def test_cancelled_points_are_in_neither_side_of_the_battery() -> None:
    row = ep.Epic(id="1", name="E", points=ep.Points(done=2, remaining=1, cancelled=40))
    assert row.total == 3


# --- filtering ------------------------------------------------------------------------

ROWS = [
    epic("Waterbalans", id="1", status="Working on it", owner="Agnes Dubbink", priority="High", done=6, remaining=2),
    epic("Droogte", id="2", status="Done", owner="Fransje van Oorschot", priority="Very High", done=9),
    epic("Energiemodel", id="3", status="On hold", owner="Rutger Feijen", priority="Medium", remaining=5),
]
DAM_ROW = ep.Epic(id="4", name="Kernregistratie", portfolio="Kernregistratie", portfolio_ids=("p-1",), status="To Do")


def test_search_is_a_case_insensitive_substring_of_the_title() -> None:
    assert [e.name for e in ep.arrange(ROWS, ep.Filters(search="ener"))] == ["Energiemodel"]


def test_each_column_filters_on_its_own_value() -> None:
    assert [e.id for e in ep.arrange(ROWS, ep.Filters(status="Done"))] == ["2"]
    assert [e.id for e in ep.arrange(ROWS, ep.Filters(owner="Rutger Feijen"))] == ["3"]
    assert [e.id for e in ep.arrange(ROWS, ep.Filters(priority="High"))] == ["1"]
    assert [e.id for e in ep.arrange(ROWS, ep.Filters(bucket="complete"))] == ["2"]


def test_the_trekker_filter_matches_one_name_out_of_several() -> None:
    """`person` columns arrive comma-joined, so an epic with two trekkers still matches."""
    both = epic("Samen", id="9", owner="Agnes Dubbink, Rutger Feijen")
    assert ep.matches(both, ep.Filters(owner="Rutger Feijen"))


def test_dam_and_non_dam_split_the_board_between_them() -> None:
    rows = [*ROWS, DAM_ROW]
    assert [e.id for e in ep.arrange(rows, ep.Filters(dam=DAM))] == ["4"]
    assert sorted(e.id for e in ep.arrange(rows, ep.Filters(dam=NON_DAM))) == ["1", "2", "3"]
    assert len(ep.arrange(rows, ep.Filters())) == 4, "no portfolio filter keeps both halves"


def test_filters_stack() -> None:
    assert ep.arrange(ROWS, ep.Filters(status="Done", owner="Agnes Dubbink")) == []


def test_no_filters_is_the_whole_board() -> None:
    assert len(ep.arrange(ROWS)) == len(ROWS)


# --- sorting --------------------------------------------------------------------------


def test_status_and_priority_sort_in_the_boards_order_not_alphabetically() -> None:
    statuses = [e.status for e in ep.arrange(ROWS, sort="status")]
    assert statuses == ["Working on it", "Done", "On hold"], "the workflow's order"
    assert statuses != sorted(statuses), "and emphatically not the alphabet"
    assert [e.priority for e in ep.arrange(ROWS, sort="priority")] == ["Very High", "High", "Medium"]


def test_a_label_the_board_no_longer_offers_sorts_after_every_one_it_does() -> None:
    rows = [epic("A", id="1", status="Verzonnen"), epic("B", id="2", status="Done")]
    assert [e.id for e in ep.arrange(rows, sort="status")] == ["2", "1"]


def test_numbers_sort_as_numbers() -> None:
    assert [e.done for e in ep.arrange(ROWS, sort="done", desc=True)] == [9, 6, 0]
    assert [e.remaining for e in ep.arrange(ROWS, sort="remaining")] == [0, 2, 5]


def test_blank_values_sort_last_either_way() -> None:
    rows = [epic("A", id="1", owner=""), epic("B", id="2", owner="Agnes Dubbink")]
    assert [e.id for e in ep.arrange(rows, sort="owner")] == ["2", "1"]


def test_every_column_the_page_shows_is_sortable() -> None:
    for column in ("name", "status", "owner", "portfolio", "priority", "done", "remaining", "progress"):
        assert len(ep.arrange(ROWS, sort=column)) == len(ROWS)


def test_an_unknown_sort_key_falls_back_instead_of_raising() -> None:
    """It arrives from a query string, so it is not trustworthy."""
    assert ep.parse_sort("../../etc/passwd") == (ep.DEFAULT_SORT, False)
    assert len(ep.arrange(ROWS, sort="nonsense")) == len(ROWS)


def test_a_sort_spec_round_trips_through_its_header() -> None:
    assert ep.parse_sort("-done") == ("done", True)
    assert ep.next_sort("done", "priority") == "-done", "numbers open high-to-low"
    assert ep.next_sort("name", "priority") == "name", "text opens A-to-Z"
    assert ep.next_sort("done", "-done") == "done", "clicking again flips it back"


# --- the dropdown option lists --------------------------------------------------------


def test_options_come_from_the_rows_so_no_choice_can_come_back_empty() -> None:
    assert ep.options(ROWS, "owner") == ["Agnes Dubbink", "Fransje van Oorschot", "Rutger Feijen"]
    assert ep.options(ROWS, "status") == ["Working on it", "Done", "On hold"], "board order, not alphabetical"
    assert ep.options(ROWS, "priority") == ["Very High", "High", "Medium"]


def test_blank_values_are_not_offered_as_a_choice() -> None:
    assert ep.options([epic("A", id="1", status="")], "status") == []


def test_totals_add_up_the_selection() -> None:
    assert ep.totals(ROWS) == ep.Points(done=15, remaining=7, tasks=0)


# --- dropped epics and the status chips -------------------------------------------------

DROPPED = ep.Epic(id="9", name="Oud plan", status="Afgevallen", owner="Agnes Dubbink")


def test_dropped_epics_are_hidden_unless_asked_for() -> None:
    assert DROPPED.is_dropped
    assert "9" not in [e.id for e in ep.arrange([*ROWS, DROPPED])]
    assert "9" in [e.id for e in ep.arrange([*ROWS, DROPPED], ep.Filters(dropped=True))]


def test_naming_a_dropped_status_shows_them_without_the_switch() -> None:
    assert [e.id for e in ep.arrange([*ROWS, DROPPED], ep.Filters(status="Afgevallen"))] == ["9"]


def test_status_counts_ignore_the_status_filter_and_include_dropped_epics() -> None:
    counts = ep.status_counts([*ROWS, DROPPED], ep.Filters(status="Done"))
    assert counts == [("Working on it", 1), ("Done", 1), ("On hold", 1), ("Afgevallen", 1)], "the board's order"


def test_status_counts_honour_every_other_filter() -> None:
    assert ep.status_counts([*ROWS, DROPPED], ep.Filters(owner="Agnes Dubbink")) == [
        ("Working on it", 1),
        ("Afgevallen", 1),
    ]


# --- being stuck ------------------------------------------------------------------------


def blocked_item(item_id: str, name: str, epic_id: str, board: Board = SPRINT_BOARD) -> dict[str, Any]:
    """A task on Impediment, as `queries.board_tasks` returns it — name included."""
    item = task_item(item_id, "3", "Impediment", epic_id, board=board)
    item["name"] = name
    return item


def test_a_blocked_task_is_found_named_and_addressed() -> None:
    found = ep.find_impediments([blocked_item("55", "Wacht op de leverancier", "e1")], SPRINT_BOARD)
    (blocker,) = found["e1"]
    assert (blocker.id, blocker.name, blocker.board) == ("55", "Wacht op de leverancier", SPRINT_BOARD.name)
    assert blocker.url == f"https://wdodelta.monday.com/boards/{SPRINT_BOARD.id}/pulses/55"


def test_only_impediment_counts_as_blocked() -> None:
    items = [task_item("1", "3", "On hold", "e1"), task_item("2", "3", "Wacht op Antwoord", "e1")]
    assert ep.find_impediments(items, SPRINT_BOARD) == {}, "waiting is not the same as blocked"


def test_a_blocker_in_the_dummy_group_or_on_no_epic_blocks_nothing() -> None:
    dummy = next(iter(DUMMY_GROUPS[SPRINT_BOARD.id]))
    items = [blocked_item("1", "Placeholder", "e1"), blocked_item("2", "Zwevend", "")]
    items[0]["group"] = {"id": dummy}
    assert ep.find_impediments(items, SPRINT_BOARD) == {}


def test_an_epic_is_stuck_from_either_side() -> None:
    blocker = ep.Impediment(id="1", name="Blokkade", board=SPRINT_BOARD.name, url="https://example.invalid")
    assert epic(status="Impediment").is_stuck, "the epic's own status"
    assert ep.Epic(id="1", name="E", impediments=(blocker,)).is_stuck, "or a task holding it up"
    assert not epic(status="Working on it").is_stuck


def test_is_blocked_is_the_epics_own_status_only() -> None:
    blocker = ep.Impediment(id="1", name="Blokkade", board=SPRINT_BOARD.name, url="https://example.invalid")
    held_up = ep.Epic(id="1", name="E", status="Working on it", impediments=(blocker,))
    assert held_up.is_stuck and not held_up.is_blocked


def test_only_stuck_narrows_to_the_blocked_epics() -> None:
    rows = [epic("Loopt", id="1"), epic("Vast", id="2", status="Impediment")]
    assert [e.name for e in ep.arrange(rows, ep.Filters(stuck=True))] == ["Vast"]


def test_sorting_on_stuck_leads_with_the_worst_blocked() -> None:
    blocker = ep.Impediment(id="1", name="Blokkade", board=SPRINT_BOARD.name, url="https://example.invalid")
    rows = [
        epic("Loopt", id="1"),
        epic("Eén blokkade", id="2", impediments=(blocker,)),
        epic("Twee blokkades", id="3", impediments=(blocker, blocker)),
    ]
    ordered = ep.arrange(rows, sort="stuck", desc=True)
    assert [e.name for e in ordered] == ["Twee blokkades", "Eén blokkade", "Loopt"]


def test_fetch_epics_hangs_the_blockers_on_the_epic_they_hold_up(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        EPIC_BOARD.id: [epic_item("e1", "Waterbalans"), epic_item("e2", "Droogte")],
        SPRINT_BOARD.id: [blocked_item("1", "Wacht op de leverancier", "e1")],
        DONE_BOARD.id: [],
    }

    class Fake:
        def all_board_items(self, build: Any) -> list[dict[str, Any]]:
            query = build(None)
            return next(items for bid, items in pages.items() if str(bid) in query)

    rows, _ = ep.fetch_epics(Fake())  # type: ignore[arg-type]
    by_id = {row.id: row for row in rows}
    assert [b.name for b in by_id["e1"].impediments] == ["Wacht op de leverancier"]
    assert by_id["e1"].is_stuck and not by_id["e2"].is_stuck
