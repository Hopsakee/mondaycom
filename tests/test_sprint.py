"""Offline tests for the sprint task rendering. No network."""

from __future__ import annotations

from datetime import date

import pytest

from mondaycom import queries
from mondaycom.config import OPEN_STATUSES, SPRINT_BOARD
from mondaycom.sprint import Task, default_sprint_end, sprint_start, tasklist_markdown


def item(name: str, **columns: str) -> dict[str, object]:
    return {
        "id": "1",
        "name": name,
        "column_values": [{"id": cid, "text": text} for cid, text in columns.items()],
    }


def test_sprint_start_is_three_weeks_inclusive() -> None:
    assert sprint_start("2026-09-06") == "2026-08-17"


def test_default_sprint_end_is_next_saturday() -> None:
    assert default_sprint_end(date(2026, 9, 3)) == "2026-09-05"
    assert default_sprint_end(date(2026, 9, 5)) == "2026-09-05"


def test_owner_task_renders_duration_and_dates() -> None:
    task = Task.from_item(item("Do the thing", person="Jelle de Jong", numbers5="2", date7="2026-09-06"))
    assert not task.is_reviewer
    assert task.duration_minutes == 240
    assert task.to_markdown("2026-08-17") == "- [ ] #sprint Do the thing [240m] ⏫ ➕ 2026-08-17 📅 2026-09-06"


def test_reviewer_task_gets_the_handshake() -> None:
    task = Task.from_item(item("Review the thing", people="Jelle de Jong", date7="2026-09-06"))
    assert task.is_reviewer
    assert task.to_markdown("2026-08-17") == "- [ ] #sprint Review the thing 🤝reviewer ⏫ ➕ 2026-08-17 📅 2026-09-06"


@pytest.mark.parametrize("points", ["", "not-a-number", None])
def test_missing_story_points_means_no_duration(points: str | None) -> None:
    task = Task.from_item(item("Vague task", numbers5=points))  # type: ignore[arg-type]
    assert task.duration_minutes == 0
    assert "m]" not in task.to_markdown("2026-08-17")


def test_task_without_due_date_omits_the_calendar() -> None:
    assert "📅" not in Task.from_item(item("Someday")).to_markdown("2026-08-17")


def test_tasklist_has_a_header_and_one_line_per_task() -> None:
    tasks = [Task(id="1", name="A"), Task(id="2", name="B")]
    lines = tasklist_markdown(tasks, "2026-09-06").splitlines()
    assert lines[0] == "# Sprint 2026-08-17 - 2026-09-06"
    assert lines[1] == ""
    assert len(lines) == 4


def test_query_filters_by_status_index_not_label() -> None:
    query = queries.sprint_tasks("2026-09-06", statuses=OPEN_STATUSES)
    assert "[16, 0, 6, 7]" in query
    assert "To Do" not in query
    assert str(SPRINT_BOARD.id) in query


def test_query_without_statuses_has_only_the_date_rule() -> None:
    query = queries.sprint_tasks("2026-09-06")
    assert "status_stories" not in query.split("groups:")[0]
    assert '"EXACT", "2026-09-06"' in query


def test_epic_name_comes_from_display_value_not_text() -> None:
    """A board_relation column returns `text: null`; the name lives in `display_value`."""
    raw = {
        "id": "1",
        "name": "Berekeningen fudura data",
        "column_values": [
            {"id": "person", "text": "Agnes Dubbink"},
            {"id": "link_to_stories__main2", "text": None, "display_value": "EBO-EIS 6.3"},
        ],
    }
    task = Task.from_item(raw)
    assert task.owner == "Agnes Dubbink"
    assert task.epic == "EBO-EIS 6.3"


def test_a_task_without_an_epic_has_an_empty_one() -> None:
    task = Task.from_item(item("Retrospect trigger", link_to_stories__main2=""))
    assert task.epic == ""


def test_the_handshake_marker_tracks_whoever_you_ask_about() -> None:
    raw = item("Review waterschapsmodel", people="Agnes Dubbink")
    assert Task.from_item(raw, me="Agnes Dubbink").is_reviewer
    assert not Task.from_item(raw, me="Jelle de Jong").is_reviewer


def test_owner_and_epic_stay_out_of_the_obsidian_line() -> None:
    """The vault format is fixed; the new columns are for the web table only."""
    task = Task(id="1", name="Doe het", story_points=1, owner="Agnes Dubbink", epic="EBO-EIS 6.3")
    assert task.to_markdown("2026-08-17") == "- [ ] #sprint Doe het [120m] ⏫ ➕ 2026-08-17"


def test_query_filters_on_a_person_as_owner_or_reviewer() -> None:
    q = queries.sprint_tasks("2026-09-19", person="23029337")
    assert '"person-23029337"' in q
    assert "operator: or" in q, "owner OR reviewer, so it must be a nested group"
    assert q.count('"person-23029337"') == 2


def test_query_defaults_to_assigned_to_me() -> None:
    assert '"assigned_to_me"' in queries.sprint_tasks("2026-09-19")


def test_query_without_a_person_has_no_people_group() -> None:
    q = queries.sprint_tasks("2026-09-19", person=None)
    assert "groups:" not in q
    assert "assigned_to_me" not in q


def test_query_filters_on_epics_by_numeric_item_id() -> None:
    q = queries.sprint_tasks("2026-09-19", epic_ids=["2645884097", "2970730154"])
    assert "compare_value: [2645884097, 2970730154]" in q, "board_relation compares numbers, not strings"
    assert SPRINT_BOARD.column("epic") in q


def test_query_without_epics_has_no_epic_rule() -> None:
    q = queries.sprint_tasks("2026-09-19", epic_ids=[])
    assert "any_of" not in q.split("groups:")[0], "only the date rule should remain"


def test_query_requests_the_epic_display_value() -> None:
    assert "display_value" in queries.sprint_tasks("2026-09-19")
