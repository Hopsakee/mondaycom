"""Offline tests for the FastHTML web interface. No network: every fetch is stubbed."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from typing import Any

import pytest
from fasthtml.common import to_xml
from starlette.testclient import TestClient

from mondaycom import burndown as bd
from mondaycom import epics as ep
from mondaycom import portfolio as pf
from mondaycom import web
from mondaycom.client import MondayError
from mondaycom.config import ASSIGNED_TO_ME, DAM, ME, NON_DAM
from mondaycom.lookups import Choice

HTMX = {"HX-Request": "1"}

PEOPLE = [Choice(id="23029337", name="Agnes Dubbink"), Choice(id="23028787", name="Jelle de Jong")]

EPICS = [
    ep.Epic(
        id="e1",
        name="Waterbalans",
        owner="Fransje van Oorschot",
        status="Working on it",
        priority="High",
        points=ep.Points(done=94, remaining=19, tasks=8),
    ),
    ep.Epic(
        id="e2",
        name="Kernregistratie",
        owner="Rutger Feijen",
        status="Done",
        priority="Very High",
        portfolio="Kernregistratie",
        portfolio_ids=("p1",),
        points=ep.Points(done=12, tasks=3),
    ),
    ep.Epic(id="e3", name="Nog niks gepland", owner="Agnes Dubbink", status="To Do", priority="Low"),
    ep.Epic(
        id="e4", name="Oud plan", owner="Agnes Dubbink", status="Afgevallen", priority="NNB", points=ep.Points(done=4)
    ),
]

BLOCKER = ep.Impediment(
    id="t7",
    name="Wachten op de leverancier",
    board="Sprint bord, actief",
    url="https://wdodelta.monday.com/boards/757790388/pulses/t7",
)

#: An epic held up by a task, and one the epic board itself put on Impediment. Kept out
#: of `EPICS` so the counts every other test asserts on stay where they are.
HELD_UP = ep.Epic(
    id="e5",
    name="Vastgelopen koppeling",
    owner="Rutger Feijen",
    status="Working on it",
    priority="Medium",
    portfolio="Kernregistratie",
    portfolio_ids=("p1",),
    points=ep.Points(done=2, remaining=8, tasks=3),
    impediments=(BLOCKER,),
)
ON_IMPEDIMENT = ep.Epic(id="e6", name="Zit muurvast", status="Impediment", portfolio_ids=("p1",))

PORTFOLIO = [
    pf.PortfolioItem(
        id="p1",
        name="Kernregistratie",
        goal="Run op orde",
        urgency="Hoog",
        type="Project",
        lead="Niek Kleine",
        start="2026-04-01",
        link="https://wdodelta.fortes-online.com/project-portfolio/Portfolio/169813/funnel?open=169115",
        ref="169115",
    ),
    pf.PortfolioItem(id="p2", name="Datavalidatie BWK", goal="Watersysteem", type="Initiatief"),
    pf.PortfolioItem(id="p3", name="Nog niets aan gekoppeld", goal="Werkplek", urgency="Laag", type="Initiatief"),
]


class FakeClient:
    """Stands in for MondayClient so no request ever leaves the process."""

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        pass


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A test client with the dropdown caches pre-filled, so nothing goes looking online."""
    monkeypatch.setattr(web, "MondayClient", FakeClient)
    web._TASKS.clear()
    web._PEOPLE[:] = PEOPLE
    # Pre-filled, so no route goes looking for the epic board either.
    web._EPICS[:] = EPICS
    web._PORTFOLIO[:] = PORTFOLIO
    yield TestClient(web.app)
    web._TASKS.clear()
    web._PEOPLE.clear()
    web._EPICS.clear()
    web._PORTFOLIO.clear()
    web._DAM_EPICS.clear()


@pytest.fixture
def sprint_group(monkeypatch: pytest.MonkeyPatch) -> list[bd.SprintItem]:
    """A three-task sprint group, so the sprint routes never touch the network.

    Agnes owns two tasks and Jelle reviews one of them and owns the third, which is
    Done. One task is on a DAM epic, one on a non-DAM epic, one on none.
    """
    items = [
        bd.SprintItem(
            id="1",
            name="Bouw het dashboard",
            points=2,
            owner="Agnes Dubbink",
            status="To Do",
            due_date="2026-09-06",
            epic="Waterbalans",
            epic_id="1999099384",
        ),
        bd.SprintItem(
            id="2",
            name="Review waterschapsmodel",
            points=5,
            owner="Agnes Dubbink",
            reviewer=ME,
            status="Wacht op review",
            due_date="2026-09-06",
        ),
        bd.SprintItem(
            id="3",
            name="Klaar hiermee",
            points=3,
            owner=ME,
            status="Done",
            done_on=date(2026, 8, 20),
            due_date="2026-09-06",
            epic="Kernregistratie",
            epic_id="e2",
        ),
    ]
    monkeypatch.setattr(bd, "fetch_sprint_items", lambda client: items)
    return items


def epic_options(body: str) -> list[str]:
    """The labels in the epic dropdown. `EVERYONE` and `ALL_EPICS` are both "all",
    so the person select would match a naive search."""
    match = re.search(r'<select[^>]*name="epic".*?</select>', body, re.S)
    return re.findall(r"<option[^>]*>([^<]*)</option>", match.group(0)) if match else []


def task_names(body: str) -> list[str]:
    return re.findall(r'aria-label="Include ([^"]*) in the markdown"', body)


def tiles(body: str) -> dict[str, str]:
    return dict(re.findall(r'<div class="kpi[^"]*">\s*<small>([^<]*)</small><strong>([^<]*)</strong>', body))


# --- the sprint page: filters -----------------------------------------------------------


def test_index_renders_the_filter_form(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/").text
    for field in ("end", "person", "epic", "dam", "open_only"):
        assert f'name="{field}"' in body, field
    assert 'id="sprint-filters"' in body


def test_the_nav_has_three_pages_and_marks_the_current_one(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/").text
    assert re.search(r'<a href="/"[^>]*aria-current="page"[^>]*>Sprint</a>', body)
    assert re.search(r'<a href="/epics"[^>]*>Epics</a>', body) and "Burndown</a>" not in body
    assert re.search(r'<a href="/portfolio"[^>]*>Portfolio</a>', body)
    assert 'aria-current="page">Epics' not in body


def test_person_dropdown_offers_me_everyone_and_each_person(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/").text
    assert f'<option value="{ASSIGNED_TO_ME}" selected>Me</option>' in body
    assert f'<option value="{web.EVERYONE}">Everyone</option>' in body
    assert '<option value="23029337">Agnes Dubbink</option>' in body


def test_the_default_slice_is_mine_and_says_so(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/").text
    assert f"{ME} — 2 of 3 tasks in the sprint group" in body, "one owned, one reviewed"
    assert "points counted as Trekker only" in body
    assert tiles(body)["Committed"] == "3", "the reviewed task's 5 points are Agnes's"


def test_everyone_is_the_whole_group_and_says_nothing(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/", params={"person": web.EVERYONE}).text
    assert "tasks in the sprint group" not in body, "nothing was filtered, so say nothing"
    assert tiles(body)["Committed"] == "10"
    assert task_names(body) == ["Bouw het dashboard", "Review waterschapsmodel", "Klaar hiermee"]


def test_a_specific_person_is_matched_by_name(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/sprint_view", params={"person": "23029337"}, headers=HTMX).text
    assert "Agnes Dubbink — 2 of 3 tasks in the sprint group" in body
    assert task_names(body) == ["Bouw het dashboard", "Review waterschapsmodel"]


def test_an_unknown_person_is_an_error_in_place_not_a_500(client: TestClient, sprint_group: Any) -> None:
    response = client.get("/sprint_view", params={"person": "999"}, headers=HTMX)
    assert response.status_code == 200 and "Unknown person" in response.text and 'id="sprint"' in response.text


def test_the_epic_dropdown_only_offers_epics_in_the_scope(client: TestClient, sprint_group: Any) -> None:
    mine = client.get("/").text
    assert epic_options(mine) == ["All epics", "Kernregistratie"]
    everyone = client.get("/", params={"person": web.EVERYONE}).text
    assert epic_options(everyone) == ["All epics", "Kernregistratie", "Waterbalans"]


def test_picking_an_epic_narrows_the_chart_and_the_table(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/sprint_view", params={"person": web.EVERYONE, "epic": "1999099384"}, headers=HTMX).text
    assert task_names(body) == ["Bouw het dashboard"]
    assert tiles(body)["Committed"] == "2"
    assert "everyone · Waterbalans — 1 of 3 tasks in the sprint group" in body


def test_an_epic_that_left_the_scope_falls_back_to_all(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/", params={"epic": "1999099384"}).text  # mine, and Waterbalans is not mine
    assert task_names(body) == ["Review waterschapsmodel", "Klaar hiermee"]
    assert f'<option value="{web.ALL_EPICS}" selected>All epics</option>' in body


def test_the_partial_refreshes_the_epic_list_and_the_date_field_out_of_band(
    client: TestClient, sprint_group: Any
) -> None:
    body = client.get("/sprint_view", params={"person": web.EVERYONE}, headers=HTMX).text
    select = re.search(r'<select[^>]*name="epic"[^>]*>', body)
    assert select is not None and 'hx-swap-oob="true"' in select.group(0)
    field = re.search(r'<input type="date" name="end"[^>]*>', body)
    assert field is not None and 'hx-swap-oob="true"' in field.group(0) and 'value="2026-09-06"' in field.group(0)


def test_the_page_shows_the_window_it_settled_on_in_the_date_field(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/").text
    assert re.search(r'<input type="date" name="end" value="2026-09-06"[^>]*id="sprint-end"', body)
    assert "Sprint 2026-08-17 – 2026-09-06" in body


def test_an_explicit_end_moves_the_window(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/", params={"end": "2026-09-13"}).text
    assert "Sprint 2026-08-24 – 2026-09-13" in body


def test_dam_keeps_only_tasks_on_a_portfolio_epic(client: TestClient, sprint_group: Any) -> None:
    web._DAM_EPICS.update({"e2"})
    body = client.get("/sprint_view", params={"person": web.EVERYONE, "dam": DAM}, headers=HTMX).text
    assert task_names(body) == ["Klaar hiermee"]
    assert "everyone · dam only — 1 of 3 tasks" in body


def test_non_dam_keeps_everything_else_including_tasks_with_no_epic(client: TestClient, sprint_group: Any) -> None:
    web._DAM_EPICS.update({"e2"})
    body = client.get("/sprint_view", params={"person": web.EVERYONE, "dam": NON_DAM}, headers=HTMX).text
    assert task_names(body) == ["Bouw het dashboard", "Review waterschapsmodel"]


def test_no_portfolio_filter_never_reads_the_epic_board(
    client: TestClient, sprint_group: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(client: Any) -> set[str]:
        raise AssertionError("the epic board was read without a DAM filter")

    monkeypatch.setattr(ep, "dam_epic_ids", boom)
    assert client.get("/sprint_view", headers=HTMX).status_code == 200


def test_open_only_drops_done_from_the_table_but_not_from_the_burndown(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/sprint_view", params={"open_only": "on"}, headers=HTMX).text
    assert task_names(body) == ["Review waterschapsmodel"]
    assert tiles(body)["Done"] == "3", "a burndown without its done tasks is not a burndown"


def test_a_fetch_failure_is_shown_in_place_not_raised(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(client: Any) -> list[bd.SprintItem]:
        raise MondayError("monday.com rejected the query: complexity budget exhausted")

    monkeypatch.setattr(bd, "fetch_sprint_items", boom)
    response = client.get("/sprint_view", headers=HTMX)
    assert response.status_code == 200 and "budget exhausted" in response.text and 'id="sprint"' in response.text


def test_an_empty_group_is_an_error_message_not_a_crash(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bd, "fetch_sprint_items", lambda client: [])
    response = client.get("/")
    assert response.status_code == 200 and "No due dates in the sprint group" in response.text


# --- the sprint page: the views ---------------------------------------------------------


def test_the_person_filter_lists_review_work_but_does_not_count_its_points(
    client: TestClient, sprint_group: Any
) -> None:
    body = client.get("/sprint_view", params={"person": ASSIGNED_TO_ME}, headers=HTMX).text
    assert task_names(body) == ["Review waterschapsmodel", "Klaar hiermee"], "the one he reviews is in the list"
    assert tiles(body)["Committed"] == "3", "3 owned; the 5 he only reviews are Agnes's points"
    assert "8 points · 3 as Trekker" in body, "the list's own total says which share counts for him"


def test_a_done_task_is_struck_through_but_still_ticked(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/sprint_view", headers=HTMX).text
    row = re.search(r'<tr class="done">.*?</tr>', body, re.S)
    assert row is not None
    assert "<del>Klaar hiermee</del>" in row.group(0) and "checked" in row.group(0)


def row_of(body: str, name: str) -> str:
    """The one table row naming `name`."""
    return next(row for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S) if name in row)


def test_the_handshake_marker_follows_the_selected_person(client: TestClient, sprint_group: Any) -> None:
    mine = client.get("/sprint_view", headers=HTMX).text
    assert "🤝" in row_of(mine, "Review waterschapsmodel"), "Jelle reviews it"
    agnes = client.get("/sprint_view", params={"person": "23029337"}, headers=HTMX).text
    assert "🤝" not in row_of(agnes, "Review waterschapsmodel"), "Agnes owns it, she does not review it"


def test_task_status_wears_a_tone_and_the_owner_an_avatar(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/sprint_view", params={"person": web.EVERYONE}, headers=HTMX).text
    assert 'class="tag tone-neutral"' in body, "To Do"
    assert 'class="tag tone-warning"' in body, "Wacht op review"
    assert 'class="tag tone-good"' in body, "Done"
    assert re.search(r'<span class="person" title="Agnes Dubbink"><span[^>]*class="avatar">AD</span>', body)


def test_a_known_person_gets_their_photo_over_the_initials(client: TestClient, sprint_group: Any) -> None:
    web._PEOPLE[:] = [Choice(id="23029337", name="Agnes Dubbink", photo="https://files.monday.com/a.png")]
    body = client.get("/sprint_view", params={"person": web.EVERYONE}, headers=HTMX).text
    avatar = re.search(r'<span[^>]*class="avatar">AD<img[^>]*></span>', body)
    assert avatar is not None and 'src="https://files.monday.com/a.png"' in avatar.group(0)
    assert 'onerror="this.remove()"' in avatar.group(0), "a dead photo URL falls back to the initials"


def test_the_per_person_row_has_the_whole_slice_first_then_everyone_with_a_task(
    client: TestClient, sprint_group: Any
) -> None:
    body = client.get("/sprint_view", params={"person": web.EVERYONE}, headers=HTMX).text
    cards = body.split('<div class="multiple">')[1:]
    assert len(cards) == 3
    assert "<strong>Everyone</strong>" in cards[0]
    assert 'title="Agnes Dubbink"' in cards[1] and f'title="{ME}"' in cards[2]
    assert all("<footer" in card and 'class="tag tone-' in card.split("<footer")[1] for card in cards), (
        "each card carries its verdict"
    )


def test_the_per_person_row_has_no_card_for_someone_who_only_reviews(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/sprint_view", params={"person": web.EVERYONE}, headers=HTMX).text
    cards = body.split('<div class="multiple">')[1:]
    assert len(cards) == 3, "Everyone, Agnes and Jelle — the reviewer of Agnes's task is Jelle, who owns one too"
    jelle = next(card for card in cards if f'title="{ME}"' in card)
    assert "0 of 3 left" in jelle, "his card holds the 3 points he is Trekker of, not the 5 he reviews"


def test_the_per_person_row_ignores_the_person_filter_but_not_the_others(client: TestClient, sprint_group: Any) -> None:
    web._DAM_EPICS.update({"e2"})
    body = client.get("/sprint_view", params={"person": "23029337", "dam": DAM}, headers=HTMX).text
    cards = re.findall(r'<div class="multiple">', body)
    assert len(cards) == 2, "the whole DAM slice, and Jelle, who owns the one DAM task"


def test_the_burndown_tiles_carry_the_verdict_tone(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/sprint_view", headers=HTMX).text
    assert re.search(r'<div class="kpi tone-(good|warning|critical|neutral)">\s*<small>Remaining</small>', body)


# --- the markdown --------------------------------------------------------------------


def test_fetch_fills_the_cache_for_the_markdown_route(client: TestClient, sprint_group: Any) -> None:
    client.get("/sprint_view", params={"person": web.EVERYONE}, headers=HTMX)
    assert set(web._TASKS) == {"1", "2", "3"}


def test_markdown_renders_only_the_checked_tasks(client: TestClient, sprint_group: Any) -> None:
    client.get("/sprint_view", params={"person": web.EVERYONE}, headers=HTMX)
    body = client.get("/markdown", params={"end": "2026-09-06", "task_id": ["1"]}, headers=HTMX).text
    assert "Bouw het dashboard" in body and "Review waterschapsmodel" not in body
    assert "# Sprint 2026-08-17 - 2026-09-06" in body


def test_markdown_with_nothing_checked_is_just_the_heading(client: TestClient, sprint_group: Any) -> None:
    client.get("/sprint_view", headers=HTMX)
    body = client.get("/markdown", params={"end": "2026-09-06"}, headers=HTMX).text
    assert "# Sprint 2026-08-17 - 2026-09-06" in body and "- [ ]" not in body


def test_unknown_task_ids_are_ignored(client: TestClient, sprint_group: Any) -> None:
    client.get("/sprint_view", headers=HTMX)
    assert client.get("/markdown", params={"end": "2026-09-06", "task_id": ["nope"]}, headers=HTMX).status_code == 200


def test_the_markdown_uses_the_settled_sprint_window(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/sprint_view", params={"person": web.EVERYONE}, headers=HTMX).text
    assert "➕ 2026-08-17 📅 2026-09-06" in body


# --- state as colour, the pieces on their own -----------------------------------------


def test_an_unknown_status_label_is_neutral_not_an_error() -> None:
    assert "tone-neutral" in to_xml(web.chart.status_tag("Iets nieuws"))
    assert web.chart.status_tag("") == "", "no state, no dot"


def test_initials_take_the_first_and_last_word() -> None:
    assert web.chart.initials("Fransje van Oorschot") == "FO"
    assert web.chart.initials("Cher") == "C"
    assert web.chart.initials("") == "?"


# --- the epics page ---------------------------------------------------------------------


def test_the_epics_page_defers_the_fetch_to_a_second_request(client: TestClient) -> None:
    body = client.get("/epics").text
    loader = re.search(r'<div[^>]*id="epic-table"[^>]*>', body)
    assert loader is not None and 'hx-trigger="load"' in loader.group(0)
    assert "Waterbalans" not in body, "the rows come with the second request"


def test_the_epics_page_offers_the_remaining_filters_and_the_status_chips(client: TestClient) -> None:
    body = client.get("/epics").text
    for field in ("search", "owner", "dam", "bucket", "stuck", "dropped", "status"):
        assert f'name="{field}"' in body, field
    for gone in ("portfolio", "priority"):
        assert f'name="{gone}"' not in body, gone
    assert 'id="status-chips"' in body


def test_the_epics_table_shows_every_asked_for_column(client: TestClient) -> None:
    body = client.get("/epic_table_rows", headers=HTMX).text
    headings = ("Item", "Status epic", "Stuck", "Trekker", "Portfolio", "Priority", "STP done", "STP left", "Progress")
    for heading in headings:
        assert f">{heading}" in body, heading


def test_a_row_carries_its_status_trekker_portfolio_priority_and_battery(client: TestClient) -> None:
    body = client.get("/epic_table_rows", headers=HTMX).text
    assert "Waterbalans" in body and "Fransje van Oorschot" in body and ">High<" in body
    assert "Kernregistratie" in body, "the linked IV Portfolio item's name"
    assert 'class="battery"' in body and ">83%<" in body, "the row battery says the percentage"
    assert "94 done, 19 still open, 113 committed" in body, "and its tooltip the points"


def test_epic_status_and_priority_wear_a_tone_dot_beside_the_label(client: TestClient) -> None:
    body = client.get("/epic_table_rows", headers=HTMX).text
    assert re.search(r'<span class="tag tone-good"><span[^>]*class="dot"></span>Done</span>', body)
    assert re.search(r'<span class="tag tone-active"><span[^>]*class="dot"></span>Working on it</span>', body)
    assert re.search(r'<span class="tag tone-critical priority"><span[^>]*class="dot"></span>Very High</span>', body)
    assert re.search(r'<span class="tag tone-serious priority"><span[^>]*class="dot"></span>High</span>', body)


def test_a_trekker_gets_an_avatar_with_initials(client: TestClient) -> None:
    body = client.get("/epic_table_rows", headers=HTMX).text
    assert re.search(r'<span class="person" title="Fransje van Oorschot"><span[^>]*class="avatar">FO</span>', body)


def test_several_trekkers_become_several_persons(client: TestClient) -> None:
    web._EPICS[:] = [ep.Epic(id="e9", name="Samen", owner="Agnes Dubbink, Jelle de Jong", status="To Do")]
    body = client.get("/epic_table_rows", headers=HTMX).text
    assert body.count('class="person"') == 2 and 'class="people"' in body


def test_an_epic_with_no_tasks_gets_an_empty_battery_not_a_zero_one(client: TestClient) -> None:
    body = client.get("/epic_table_rows", headers=HTMX).text
    assert 'class="battery empty"' in body and "no tasks" in body


def test_every_column_has_a_sortable_header(client: TestClient) -> None:
    body = client.get("/epic_table_rows", headers=HTMX).text
    for column in ("name", "status", "stuck", "owner", "portfolio", "priority", "done", "remaining", "progress"):
        assert f"resort={column}" in body or f"resort=-{column}" in body, column


def test_the_default_sort_is_priority_highest_first(client: TestClient) -> None:
    body = client.get("/epic_table_rows", headers=HTMX).text
    assert body.index("Kernregistratie") < body.index("Waterbalans") < body.index("Nog niks gepland")


def test_a_header_click_re_sorts_and_the_form_remembers_it(client: TestClient) -> None:
    body = client.get("/epic_table_rows", params={"resort": "-done", "sort": "priority"}, headers=HTMX).text
    assert body.index("Waterbalans") < body.index("Kernregistratie"), "resort wins over the form's sort"
    remembered = re.search(r'<input[^>]*name="sort"[^>]*>', body)
    assert remembered is not None
    for attribute in ('value="-done"', 'id="epic-sort"', 'hx-swap-oob="true"'):
        assert attribute in remembered.group(0), attribute


def test_the_sorted_column_says_which_way_it_is_sorted(client: TestClient) -> None:
    body = client.get("/epic_table_rows", params={"resort": "-done"}, headers=HTMX).text
    assert 'aria-sort="descending"' in body


def test_filtering_keeps_the_current_sort(client: TestClient) -> None:
    body = client.get("/epic_table_rows", params={"sort": "-done", "status": "Done"}, headers=HTMX).text
    assert 'value="-done"' in body and "Kernregistratie" in body and "Waterbalans" not in body


def test_each_filter_narrows_the_table(client: TestClient) -> None:
    def names(**params: str) -> str:
        return client.get("/epic_table_rows", params=params, headers=HTMX).text

    assert "Kernregistratie" not in names(search="water")
    assert "Waterbalans" not in names(owner="Rutger Feijen")
    assert "Waterbalans" not in names(status="Done")
    assert "Waterbalans" not in names(bucket="no-tasks")
    assert "Waterbalans" not in names(dam=DAM) and "Kernregistratie" in names(dam=DAM)
    assert "Kernregistratie" not in names(dam=NON_DAM)


def test_dropped_epics_are_hidden_until_asked_for(client: TestClient) -> None:
    assert "Oud plan" not in client.get("/epic_table_rows", headers=HTMX).text
    assert "Oud plan" in client.get("/epic_table_rows", params={"dropped": "on"}, headers=HTMX).text


def test_the_dropped_status_chip_shows_them_without_the_switch(client: TestClient) -> None:
    body = client.get("/epic_table_rows", params={"status": "Afgevallen"}, headers=HTMX).text
    assert "Oud plan" in body and "Waterbalans" not in body


def test_the_status_chips_carry_counts_under_the_other_filters(client: TestClient) -> None:
    body = client.get("/epic_table_rows", headers=HTMX).text
    opening = re.search(r'<div[^>]*id="status-chips"[^>]*>', body)
    assert opening is not None and 'hx-swap-oob="true"' in opening.group(0), "the counts move with every filter"
    assert chips(body) == [("", "3"), ("To Do", "1"), ("Working on it", "1"), ("Done", "1"), ("Afgevallen", "1")]
    narrowed = client.get("/epic_table_rows", params={"owner": "Agnes Dubbink"}, headers=HTMX).text
    assert chips(narrowed) == [("", "1"), ("To Do", "1"), ("Afgevallen", "1")], (
        "no chip for a status with nothing behind it"
    )
    shown = client.get("/epic_table_rows", params={"dropped": "on"}, headers=HTMX).text
    assert chips(shown)[0] == ("", "4"), '"All" counts what clearing the status shows: dropped only with the switch'


def chips(body: str) -> list[tuple[str, str]]:
    """(status, count) per chip, in page order."""
    buttons = re.findall(r"<button[^>]*class=\"chip\"[^>]*>(?:(?!</button>).)*</button>", body, re.S)
    return [
        (re.search(r'data-status="([^"]*)"', b).group(1), re.search(r'<span class="count">(\d+)</span>', b).group(1))  # type: ignore[union-attr]
        for b in buttons
    ]


def test_the_pressed_chip_is_the_current_status(client: TestClient) -> None:
    body = client.get("/epic_table_rows", params={"status": "Done"}, headers=HTMX).text
    assert re.search(r'data-status="Done"[^>]*aria-pressed="true"', body) or re.search(
        r'aria-pressed="true"[^>]*data-status="Done"', body
    )
    assert re.search(r'<input type="hidden" name="status" value="Done"', body)


def test_filtering_everything_out_says_so_instead_of_showing_an_empty_table(client: TestClient) -> None:
    body = client.get("/epic_table_rows", params={"search": "bestaat niet"}, headers=HTMX).text
    assert "No epics match these filters." in body


def test_the_summary_counts_the_selection_and_the_whole_board(client: TestClient) -> None:
    body = client.get("/epic_table_rows", params={"status": "Done"}, headers=HTMX).text
    assert tiles(body) == {"Epics": "1", "Done": "12", "Left": "0"}
    assert "of 4 on the epic board" in body


def test_the_summary_battery_is_the_wide_one_and_covers_the_selection(client: TestClient) -> None:
    body = client.get("/epic_table_rows", headers=HTMX).text
    wide = re.search(r'<div class="battery wide"[^>]*>.*?</div>\s*<span class="value">([^<]*)</span>', body, re.S)
    assert wide is not None and wide.group(1) == "106/125 · 85%", "94 + 12 done of 94 + 19 + 12 committed"


def test_points_on_no_epic_are_reported_rather_than_quietly_dropped(client: TestClient) -> None:
    web._ORPHANS = ep.Points(done=181, remaining=12, tasks=150)
    try:
        body = client.get("/epic_table_rows", headers=HTMX).text
        assert "150 sprint tasks (193 points)" in body and "linked to no epic" in body
    finally:
        web._ORPHANS = ep.Points()


def test_the_dropdown_options_arrive_with_the_first_table(client: TestClient) -> None:
    """A cold page load has no rows yet, so the filters have nothing to offer until then."""
    web._EPICS.clear()
    assert "Fransje van Oorschot" not in client.get("/epics").text
    web._EPICS[:] = EPICS
    body = client.get("/epic_table_rows", params={"fields": "1"}, headers=HTMX).text
    oob = re.search(r'<div[^>]*id="epic-filter-fields"[^>]*>', body)
    assert oob is not None and 'hx-swap-oob="true"' in oob.group(0)
    assert "Fransje van Oorschot" in body


def test_a_sort_click_does_not_re_render_the_filters_under_the_cursor(client: TestClient) -> None:
    body = client.get("/epic_table_rows", params={"resort": "name"}, headers=HTMX).text
    assert 'id="epic-filter-fields"' not in body, "that would take the caret out of the search box"


def test_everything_that_swaps_the_epic_table_replaces_the_wrapper(client: TestClient) -> None:
    """Every response carries `#epic-table`, so an innerHTML swap would nest two of them."""
    page = client.get("/epics").text
    form = re.search(r'<form[^>]*id="epic-filters"[^>]*>', page)
    assert form is not None and 'hx-swap="outerHTML"' in form.group(0)
    table = client.get("/epic_table_rows", headers=HTMX).text
    for button in re.findall(r'<button[^>]*hx-target="#epic-table"[^>]*>', table + page):
        assert 'hx-swap="outerHTML"' in button, button


def test_refresh_re_reads_the_board(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    reads = []

    def fake_fetch(client: Any) -> tuple[list[ep.Epic], ep.Points]:
        reads.append(1)
        return EPICS, ep.Points()

    monkeypatch.setattr(ep, "fetch_epics", fake_fetch)
    client.get("/epic_table_rows", headers=HTMX)
    assert reads == [], "the cache is warm, so nothing is read"
    client.get("/epic_table_rows", params={"refresh": "1"}, headers=HTMX)
    assert reads == [1]


def test_the_epic_board_is_read_once_and_then_cached(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    reads = []
    monkeypatch.setattr(ep, "fetch_epics", lambda client: (reads.append(1), (EPICS, ep.Points()))[1])
    web._EPICS.clear()
    client.get("/epic_table_rows", headers=HTMX)
    client.get("/epic_table_rows", params={"sort": "name"}, headers=HTMX)
    assert reads == [1], "sorting and filtering must not re-hit monday.com"


def test_an_epic_fetch_failure_is_shown_in_place(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(client: Any) -> tuple[list[ep.Epic], ep.Points]:
        raise MondayError("monday.com rejected the query: complexity budget exhausted")

    monkeypatch.setattr(ep, "fetch_epics", boom)
    web._EPICS.clear()
    response = client.get("/epic_table_rows", headers=HTMX)
    assert response.status_code == 200 and "complexity budget exhausted" in response.text
    assert 'id="epic-table"' in response.text


def test_an_empty_epic_board_says_so(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ep, "fetch_epics", lambda client: ([], ep.Points()))
    web._EPICS.clear()
    body = client.get("/epic_table_rows", headers=HTMX).text
    assert "The epic board came back empty." in body


# --- the stuck marker ---------------------------------------------------------------------


def test_an_epic_that_runs_gets_no_marker_at_all(client: TestClient) -> None:
    body = client.get("/epic_table_rows", headers=HTMX).text
    assert 'class="stuck"' not in body, "a quiet table is the whole point of an empty cell"


def test_an_epic_on_impediment_is_marked_and_links_to_itself(client: TestClient) -> None:
    web._EPICS[:] = [ON_IMPEDIMENT]
    body = client.get("/epic_table_rows", headers=HTMX).text
    assert re.search(r'<summary><span class="tag tone-critical"><span[^>]*></span>epic</span></summary>', body)
    assert "boards/757753649/pulses/e6" in body, "the epic itself is always a way in"


def test_a_blocking_task_is_named_counted_and_linked(client: TestClient) -> None:
    web._EPICS[:] = [HELD_UP]
    body = client.get("/epic_table_rows", headers=HTMX).text
    assert ">1 task</span>" in body, "one task, singular"
    assert f'href="{BLOCKER.url}"' in body and "Wachten op de leverancier" in body
    assert "Sprint bord, actief" in body, "which board it is parked on"


def test_an_epic_blocked_from_both_sides_says_both(client: TestClient) -> None:
    web._EPICS[:] = [ep.Epic(id="e7", name="Dubbel", status="Impediment", impediments=(BLOCKER, BLOCKER))]
    body = client.get("/epic_table_rows", headers=HTMX).text
    assert ">epic + 2 tasks</span>" in body


def test_only_stuck_narrows_to_the_blocked_epics(client: TestClient) -> None:
    web._EPICS[:] = [*EPICS, HELD_UP]
    assert "Waterbalans" in client.get("/epic_table_rows", headers=HTMX).text
    body = client.get("/epic_table_rows", params={"stuck": "on"}, headers=HTMX).text
    assert "Vastgelopen koppeling" in body and "Waterbalans" not in body


def test_sorting_on_stuck_puts_the_blocked_epics_first(client: TestClient) -> None:
    web._EPICS[:] = [*EPICS, HELD_UP]
    body = client.get("/epic_table_rows", params={"resort": "-stuck"}, headers=HTMX).text
    assert body.index("Vastgelopen koppeling") < body.index("Waterbalans")


def test_an_epics_portfolio_is_a_way_into_the_portfolio_page(client: TestClient) -> None:
    body = client.get("/epic_table_rows", headers=HTMX).text
    assert '<a href="/portfolio_item?item=p1">Kernregistratie</a>' in body


# --- the portfolio page -------------------------------------------------------------------


def portfolio_names(body: str) -> list[str]:
    """The item names in the portfolio table, in page order."""
    return re.findall(r'<a href="/portfolio_item\?item=[^"]*">([^<]*)</a>', body)


def test_the_portfolio_page_defers_the_fetch_to_a_second_request(client: TestClient) -> None:
    body = client.get("/portfolio").text
    loader = re.search(r'<div[^>]*id="portfolio-table"[^>]*>', body)
    assert loader is not None and 'hx-trigger="load"' in loader.group(0)
    assert "Datavalidatie BWK" not in body, "the rows come with the second request"


def test_the_portfolio_table_shows_every_asked_for_column(client: TestClient) -> None:
    body = client.get("/portfolio_table_rows", headers=HTMX).text
    for heading in ("Item", "Stuck", "Doelstelling", "Type", "Urgentie", "Projectleider", "Epics"):
        assert f">{heading}" in body, heading
    for heading in ("STP done", "STP left", "Progress"):
        assert f">{heading}" in body, heading


def test_a_row_sums_the_epics_under_it_and_links_to_them(client: TestClient) -> None:
    body = client.get("/portfolio_table_rows", headers=HTMX).text
    assert portfolio_names(body) == ["Kernregistratie"], "the other two have no epics"
    assert '<a href="/portfolio_item?item=p1">Kernregistratie</a>' in body
    assert ">Run op orde<" in body and ">Niek Kleine<" in body
    assert "12 done, 0 still open, 12 committed" in body, "e2's points, from the epic board"


def test_urgentie_wears_a_priority_mark_not_a_status_dot(client: TestClient) -> None:
    body = client.get("/portfolio_table_rows", headers=HTMX).text
    assert re.search(r'<span class="tag tone-serious priority"><span[^>]*class="dot"></span>Hoog</span>', body)


def test_items_with_no_epics_are_hidden_until_asked_for(client: TestClient) -> None:
    """166 of the board's 177 items are like that; they would drown the eleven real ones."""
    assert "Datavalidatie BWK" not in client.get("/portfolio_table_rows", headers=HTMX).text
    body = client.get("/portfolio_table_rows", params={"empty": "on"}, headers=HTMX).text
    assert portfolio_names(body) == ["Kernregistratie", "Datavalidatie BWK", "Nog niets aan gekoppeld"]


def test_each_portfolio_filter_narrows_the_table(client: TestClient) -> None:
    def names(**params: str) -> list[str]:
        return portfolio_names(client.get("/portfolio_table_rows", params={"empty": "on", **params}, headers=HTMX).text)

    assert names(search="valid") == ["Datavalidatie BWK"]
    assert names(goal="Werkplek") == ["Nog niets aan gekoppeld"]
    assert names(type="Project") == ["Kernregistratie"]
    assert names(urgency="Hoog") == ["Kernregistratie"]
    assert names(lead="Niek") == ["Kernregistratie"]
    assert names(bucket="complete") == ["Kernregistratie"]


def test_the_default_sort_is_least_complete_first(client: TestClient) -> None:
    """p1 is 14 of 22 points done; p2 gets Waterbalans, which is 94 of 113. p1 leads."""
    web._EPICS[:] = [
        *EPICS,
        HELD_UP,
        ep.Epic(id="e8", name="Waterbalans II", portfolio_ids=("p2",), points=ep.Points(done=94, remaining=19)),
    ]
    body = client.get("/portfolio_table_rows", headers=HTMX).text
    assert portfolio_names(body) == ["Kernregistratie", "Datavalidatie BWK"]


def test_a_portfolio_header_click_re_sorts_and_the_form_remembers_it(client: TestClient) -> None:
    body = client.get("/portfolio_table_rows", params={"empty": "on", "resort": "-name"}, headers=HTMX).text
    assert portfolio_names(body) == ["Nog niets aan gekoppeld", "Kernregistratie", "Datavalidatie BWK"]
    remembered = re.search(r'<input[^>]*id="portfolio-sort"[^>]*>', body)
    assert remembered is not None and 'value="-name"' in remembered.group(0)
    assert 'hx-swap-oob="true"' in remembered.group(0)


def test_a_stuck_epic_makes_its_portfolio_item_stuck(client: TestClient) -> None:
    web._EPICS[:] = [*EPICS, HELD_UP, ON_IMPEDIMENT]
    body = client.get("/portfolio_table_rows", headers=HTMX).text
    assert ">2 epics</span>" in body, "both of p1's blocked epics, rolled up"
    assert "Vastgelopen koppeling" in body and "Zit muurvast" in body
    assert f'href="{BLOCKER.url}"' in body, "and the blocking task is still one click away"
    assert tiles(body)["Stuck"] == "1"


def test_only_stuck_narrows_the_portfolio_too(client: TestClient) -> None:
    web._EPICS[:] = [*EPICS, HELD_UP]
    body = client.get("/portfolio_table_rows", params={"empty": "on", "stuck": "on"}, headers=HTMX).text
    assert portfolio_names(body) == ["Kernregistratie"]


def test_the_portfolio_summary_counts_the_selection_and_the_whole_board(client: TestClient) -> None:
    body = client.get("/portfolio_table_rows", headers=HTMX).text
    assert tiles(body) == {"Portfolio items": "1", "Done": "12", "Left": "0"}
    assert "of 3 on the board · 1 epics" in body


def test_epics_pointing_at_a_missing_portfolio_item_are_reported(client: TestClient) -> None:
    web._EPICS[:] = [ep.Epic(id="e9", name="Zwevend", portfolio_ids=("weg",), points=ep.Points(remaining=7))]
    body = client.get("/portfolio_table_rows", headers=HTMX).text
    assert "1 epics (7 points) name a portfolio item" in body


def test_filtering_the_portfolio_out_says_so_instead_of_showing_an_empty_table(client: TestClient) -> None:
    body = client.get("/portfolio_table_rows", params={"search": "bestaat niet"}, headers=HTMX).text
    assert "No portfolio items match these filters." in body


def test_the_portfolio_dropdowns_arrive_with_the_first_table(client: TestClient) -> None:
    body = client.get("/portfolio_table_rows", params={"fields": "1"}, headers=HTMX).text
    oob = re.search(r'<div[^>]*id="portfolio-filter-fields"[^>]*>', body)
    assert oob is not None and 'hx-swap-oob="true"' in oob.group(0)
    assert ">Run op orde</option>" in body and ">Niek Kleine</option>" in body


def test_a_sort_click_does_not_re_render_the_portfolio_filters(client: TestClient) -> None:
    body = client.get("/portfolio_table_rows", params={"resort": "name"}, headers=HTMX).text
    assert 'id="portfolio-filter-fields"' not in body


def test_everything_that_swaps_the_portfolio_table_replaces_the_wrapper(client: TestClient) -> None:
    page = client.get("/portfolio").text
    form = re.search(r'<form[^>]*id="portfolio-filters"[^>]*>', page)
    assert form is not None and 'hx-swap="outerHTML"' in form.group(0)
    table = client.get("/portfolio_table_rows", headers=HTMX).text
    for button in re.findall(r'<button[^>]*hx-target="#portfolio-table"[^>]*>', table + page):
        assert 'hx-swap="outerHTML"' in button, button


def test_the_portfolio_board_is_read_once_and_then_cached(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    reads: list[str] = []
    monkeypatch.setattr(pf, "fetch_items", lambda client: (reads.append("portfolio"), PORTFOLIO)[1])
    monkeypatch.setattr(ep, "fetch_epics", lambda client: (reads.append("epics"), (EPICS, ep.Points()))[1])
    web._PORTFOLIO.clear()
    client.get("/portfolio_table_rows", headers=HTMX)
    client.get("/portfolio_table_rows", params={"sort": "name"}, headers=HTMX)
    assert reads == ["portfolio"], "sorting and filtering must not re-hit monday.com"
    client.get("/portfolio_table_rows", params={"refresh": "1"}, headers=HTMX)
    assert reads == ["portfolio", "epics", "portfolio"], "refresh re-reads both halves"


def test_a_portfolio_fetch_failure_is_shown_in_place(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(client: Any) -> list[pf.PortfolioItem]:
        raise MondayError("monday.com rejected the query: complexity budget exhausted")

    monkeypatch.setattr(pf, "fetch_items", boom)
    web._PORTFOLIO.clear()
    response = client.get("/portfolio_table_rows", headers=HTMX)
    assert response.status_code == 200 and "complexity budget exhausted" in response.text
    assert 'id="portfolio-table"' in response.text


def test_an_empty_portfolio_board_says_so(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pf, "fetch_items", lambda client: [])
    web._PORTFOLIO.clear()
    body = client.get("/portfolio_table_rows", headers=HTMX).text
    assert "The IV Portfolio board came back empty." in body


# --- one portfolio item -------------------------------------------------------------------


def test_the_item_page_defers_the_fetch_and_stays_on_the_portfolio_nav(client: TestClient) -> None:
    body = client.get("/portfolio_item", params={"item": "p1"}).text
    loader = re.search(r'<div[^>]*id="portfolio-item"[^>]*>', body)
    assert loader is not None and 'hx-trigger="load"' in loader.group(0)
    assert 'hx-get="/portfolio_item_view?item=p1"' in loader.group(0)
    assert re.search(r'<a href="/portfolio"[^>]*aria-current="page"[^>]*>Portfolio</a>', body)


def test_the_item_page_shows_its_fields_its_totals_and_its_epics(client: TestClient) -> None:
    web._EPICS[:] = [*EPICS, HELD_UP]
    body = client.get("/portfolio_item_view", params={"item": "p1"}, headers=HTMX).text
    assert "<h2>Kernregistratie</h2>" in body
    assert ">Run op orde<" in body and ">Project<" in body and ">Niek Kleine<" in body
    assert f'href="{PORTFOLIO[0].link}"' in body and ">169115</a>" in body, "the Fortes link, by its id"
    assert "boards/5097962810/pulses/p1" in body, "and the item on monday.com"
    assert tiles(body) == {"Epics": "2", "Done": "14", "Left": "8", "Stuck": "1"}
    assert "Vastgelopen koppeling" in body and "Kernregistratie" in body


def test_a_fortes_link_that_is_not_a_web_address_is_not_a_link(client: TestClient) -> None:
    """The Fortes column is free text on the board, and a `javascript:` href would run
    in this page's own origin — so an address we do not recognise stays text."""
    web._PORTFOLIO[:] = [replace(PORTFOLIO[0], link="javascript:alert(1)"), *PORTFOLIO[1:]]
    web._EPICS[:] = [*EPICS, HELD_UP]
    body = client.get("/portfolio_item_view", params={"item": "p1"}, headers=HTMX).text
    assert "javascript:" not in body
    assert ">169115<" in body, "the id is still shown, just not as a link"


def test_the_item_page_puts_the_blocked_epics_first(client: TestClient) -> None:
    web._EPICS[:] = [*EPICS, HELD_UP]
    body = client.get("/portfolio_item_view", params={"item": "p1"}, headers=HTMX).text
    rows = re.findall(r'<td class="item">\s*<a [^>]*>([^<]*)</a>', body)
    assert rows == ["Vastgelopen koppeling", "Kernregistratie"]


def test_an_item_with_no_epics_says_so_rather_than_showing_an_empty_table(client: TestClient) -> None:
    body = client.get("/portfolio_item_view", params={"item": "p2"}, headers=HTMX).text
    assert "No epics are linked to this portfolio item." in body


def test_an_unknown_item_is_a_message_not_a_500(client: TestClient) -> None:
    response = client.get("/portfolio_item_view", params={"item": "bestaat-niet"}, headers=HTMX)
    assert response.status_code == 200 and "No portfolio item with that id" in response.text


def test_closing_the_live_reload_socket_is_not_an_asgi_error(client: TestClient) -> None:
    """fasthtml's own handler receives once past the disconnect and raises RuntimeError."""
    with client.websocket_connect("/live-reload"):
        pass
