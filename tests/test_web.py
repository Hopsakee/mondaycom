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

from builders import epic
from mondaycom import burndown as bd
from mondaycom import epics as ep
from mondaycom import planning as pl
from mondaycom import portfolio as pf
from mondaycom import web
from mondaycom.client import MondayError
from mondaycom.config import ASSIGNED_TO_ME, DAM, EPIC_GROUP_ACTIVE, EPIC_GROUP_BACKLOG, ME, NON_DAM
from mondaycom.lookups import Choice

HTMX = {"HX-Request": "1"}

PEOPLE = [Choice(id="23029337", name="Agnes Dubbink"), Choice(id="23028787", name="Jelle de Jong")]

EPICS = [
    epic(
        "Waterbalans",
        id="e1",
        owner="Fransje van Oorschot",
        status="Working on it",
        priority="High",
        done=94,
        remaining=19,
        tasks=8,
    ),
    epic(
        "Kernregistratie",
        ("p1",),
        id="e2",
        owner="Rutger Feijen",
        status="Done",
        priority="Very High",
        portfolio="Kernregistratie",
        done=12,
        tasks=3,
    ),
    epic("Nog niks gepland", id="e3", owner="Agnes Dubbink", status="To Do", priority="Low"),
    epic("Oud plan", id="e4", owner="Agnes Dubbink", status="Afgevallen", priority="NNB", done=4),
]

BLOCKER = ep.Impediment(
    id="t7",
    name="Wachten op de leverancier",
    board="Sprint bord, actief",
    url="https://wdodelta.monday.com/boards/757790388/pulses/t7",
)

#: An epic held up by a task, and one the epic board itself put on Impediment. Kept out
#: of `EPICS` so the counts every other test asserts on stay where they are.
HELD_UP = epic(
    "Vastgelopen koppeling",
    ("p1",),
    id="e5",
    owner="Rutger Feijen",
    status="Working on it",
    priority="Medium",
    portfolio="Kernregistratie",
    done=2,
    remaining=8,
    tasks=3,
    impediments=(BLOCKER,),
)
ON_IMPEDIMENT = epic("Zit muurvast", ("p1",), id="e6", status="Impediment")

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

    made = 0

    def __init__(self) -> None:
        FakeClient.made += 1
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A test client with the dropdown caches pre-filled, so nothing goes looking online."""
    monkeypatch.setattr(web, "MondayClient", FakeClient)
    web._CLIENT.clear()  # so the shared client is made from the fake
    web._TASKS.clear()
    web._SPRINT.clear()
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
    web._SPRINT.clear()
    web._CLIENT.clear()


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
    return re.findall(r'aria-label="Neem ([^"]*) op in de markdown"', body)


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
    assert f'<option value="{ASSIGNED_TO_ME}" selected>Ik</option>' in body
    assert f'<option value="{web.EVERYONE}">Iedereen</option>' in body
    assert '<option value="23029337">Agnes Dubbink</option>' in body


def test_the_default_slice_is_mine_and_says_so(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/").text
    assert f"{ME} — 2 van 3 taken in de sprintgroep" in body, "one owned, one reviewed"
    assert "punten tellen alleen voor de Trekker" in body
    assert tiles(body)["Toegezegd"] == "3", "the reviewed task's 5 points are Agnes's"


def test_everyone_is_the_whole_group_and_says_nothing(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/", params={"person": web.EVERYONE}).text
    assert "taken in de sprintgroep" not in body, "nothing was filtered, so say nothing"
    assert tiles(body)["Toegezegd"] == "10"
    assert task_names(body) == ["Bouw het dashboard", "Review waterschapsmodel", "Klaar hiermee"]


def test_a_specific_person_is_matched_by_name(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/sprint_view", params={"person": "23029337"}, headers=HTMX).text
    assert "Agnes Dubbink — 2 van 3 taken in de sprintgroep" in body
    assert task_names(body) == ["Bouw het dashboard", "Review waterschapsmodel"]


def test_an_unknown_person_is_an_error_in_place_not_a_500(client: TestClient, sprint_group: Any) -> None:
    response = client.get("/sprint_view", params={"person": "999"}, headers=HTMX)
    assert response.status_code == 200 and "Onbekende persoon" in response.text and 'id="sprint"' in response.text


def test_the_epic_dropdown_only_offers_epics_in_the_scope(client: TestClient, sprint_group: Any) -> None:
    mine = client.get("/").text
    assert epic_options(mine) == ["Alle epics", "Kernregistratie"]
    everyone = client.get("/", params={"person": web.EVERYONE}).text
    assert epic_options(everyone) == ["Alle epics", "Kernregistratie", "Waterbalans"]


def test_picking_an_epic_narrows_the_chart_and_the_table(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/sprint_view", params={"person": web.EVERYONE, "epic": "1999099384"}, headers=HTMX).text
    assert task_names(body) == ["Bouw het dashboard"]
    assert tiles(body)["Toegezegd"] == "2"
    assert "iedereen · Waterbalans — 1 van 3 taken in de sprintgroep" in body


def test_an_epic_that_left_the_scope_falls_back_to_all(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/", params={"epic": "1999099384"}).text  # mine, and Waterbalans is not mine
    assert task_names(body) == ["Review waterschapsmodel", "Klaar hiermee"]
    assert f'<option value="{web.ALL_EPICS}" selected>Alle epics</option>' in body


def test_the_partial_refreshes_the_epic_list_and_the_date_field_out_of_band(
    client: TestClient, sprint_group: Any
) -> None:
    body = client.get("/sprint_view", params={"person": web.EVERYONE}, headers=HTMX).text
    select = re.search(r'<select[^>]*name="epic"[^>]*>', body)
    assert select is not None and 'hx-swap-oob="true"' in select.group(0)
    field = re.search(r'<span id="sprint-end" class="date-field"[^>]*>.*?</span>', body, re.S)
    assert field is not None and 'hx-swap-oob="true"' in field.group(0) and 'value="2026-09-06"' in field.group(0)


def test_the_page_shows_the_window_it_settled_on_in_the_date_field(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/").text
    field = re.search(r'id="sprint-end" class="date-field">\s*<input type="text" name="end" value="2026-09-06"', body)
    assert field, "the window in use, as ISO text — a native date input would show it in the browser's locale"
    assert 'name="end" value="2026-09-06"' in body and 'type="date" name=' not in body, "the picker is not submitted"
    assert "Sprint 2026-08-17 – 2026-09-06" in body


def test_an_explicit_end_moves_the_window(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/", params={"end": "2026-09-13"}).text
    assert "Sprint 2026-08-24 – 2026-09-13" in body


def test_dam_keeps_only_tasks_on_a_portfolio_epic(client: TestClient, sprint_group: Any) -> None:
    web._DAM_EPICS.update({"e2"})
    body = client.get("/sprint_view", params={"person": web.EVERYONE, "dam": DAM}, headers=HTMX).text
    assert task_names(body) == ["Klaar hiermee"]
    assert "iedereen · alleen dam — 1 van 3 taken" in body


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
    assert tiles(body)["Klaar"] == "3", "a burndown without its done tasks is not a burndown"


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


# --- the sprint page: the cached read ----------------------------------------------------


def counting_reads(monkeypatch: pytest.MonkeyPatch, items: list[bd.SprintItem]) -> list[int]:
    reads: list[int] = []
    monkeypatch.setattr(bd, "fetch_sprint_items", lambda client: reads.append(1) or items)
    return reads


def test_a_filter_change_narrows_the_cached_group_instead_of_reading_it_again(
    client: TestClient, sprint_group: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No filter changes the read, so re-reading would fetch identical bytes."""
    reads = counting_reads(monkeypatch, sprint_group)
    client.get("/")
    client.get("/sprint_view", params={"person": web.EVERYONE}, headers=HTMX)
    body = client.get("/sprint_view", params={"person": web.EVERYONE, "open_only": "on"}, headers=HTMX).text
    assert len(reads) == 1
    assert task_names(body) == ["Bouw het dashboard", "Review waterschapsmodel"], "still narrowed"


def test_a_page_load_and_the_refresh_button_read_the_group_afresh(
    client: TestClient, sprint_group: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reloading is how you see a task you just moved on monday.com."""
    reads = counting_reads(monkeypatch, sprint_group)
    client.get("/")
    client.get("/")
    assert len(reads) == 2
    client.get("/sprint_view", params={"refresh": "1"}, headers=HTMX)
    assert len(reads) == 3


def test_the_refresh_button_keeps_the_filters(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/").text
    button = re.search(r"<button[^>]*>Opnieuw ophalen van monday.com</button>", body)
    assert button and 'hx-include="#sprint-filters"' in button.group(0)
    assert "refresh=1" in button.group(0)


# --- the sprint page: the views ---------------------------------------------------------


def test_the_person_filter_lists_review_work_but_does_not_count_its_points(
    client: TestClient, sprint_group: Any
) -> None:
    body = client.get("/sprint_view", params={"person": ASSIGNED_TO_ME}, headers=HTMX).text
    assert task_names(body) == ["Review waterschapsmodel", "Klaar hiermee"], "the one he reviews is in the list"
    assert tiles(body)["Toegezegd"] == "3", "3 owned; the 5 he only reviews are Agnes's points"
    assert "8 punten · 3 als Trekker" in body, "the list's own total says which share counts for him"


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
    assert "<strong>Iedereen</strong>" in cards[0]
    assert 'title="Agnes Dubbink"' in cards[1] and f'title="{ME}"' in cards[2]
    assert all("<footer" in card and 'class="tag tone-' in card.split("<footer")[1] for card in cards), (
        "each card carries its verdict"
    )


def test_the_per_person_row_has_no_card_for_someone_who_only_reviews(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/sprint_view", params={"person": web.EVERYONE}, headers=HTMX).text
    cards = body.split('<div class="multiple">')[1:]
    assert len(cards) == 3, "Everyone, Agnes and Jelle — the reviewer of Agnes's task is Jelle, who owns one too"
    jelle = next(card for card in cards if f'title="{ME}"' in card)
    assert "nog 0 van 3" in jelle, "his card holds the 3 points he is Trekker of, not the 5 he reviews"


def test_the_per_person_row_ignores_the_person_filter_but_not_the_others(client: TestClient, sprint_group: Any) -> None:
    web._DAM_EPICS.update({"e2"})
    body = client.get("/sprint_view", params={"person": "23029337", "dam": DAM}, headers=HTMX).text
    cards = re.findall(r'<div class="multiple">', body)
    assert len(cards) == 2, "the whole DAM slice, and Jelle, who owns the one DAM task"


def test_the_burndown_tiles_carry_the_verdict_tone(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/sprint_view", headers=HTMX).text
    assert re.search(r'<div class="kpi tone-(good|warning|critical|neutral)">\s*<small>Resterend</small>', body)


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
    headings = (
        "Epic",
        "Status epic",
        "Vast",
        "Trekker",
        "Portfolio",
        "Prioriteit",
        "STP klaar",
        "STP te gaan",
        "Voortgang",
    )
    for heading in headings:
        assert f">{heading}" in body, heading


def test_a_row_carries_its_status_trekker_portfolio_priority_and_battery(client: TestClient) -> None:
    body = client.get("/epic_table_rows", headers=HTMX).text
    assert "Waterbalans" in body and "Fransje van Oorschot" in body and ">High<" in body
    assert "Kernregistratie" in body, "the linked IV Portfolio item's name"
    assert 'class="battery"' in body and ">83%<" in body, "the row battery says the percentage"
    assert "94 klaar, 19 nog open, 113 in totaal" in body, "and its tooltip the points"


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
    web._EPICS[:] = [epic("Samen", id="e9", owner="Agnes Dubbink, Jelle de Jong", status="To Do")]
    body = client.get("/epic_table_rows", headers=HTMX).text
    assert body.count('class="person"') == 2 and 'class="people"' in body


def test_an_epic_with_no_tasks_gets_an_empty_battery_not_a_zero_one(client: TestClient) -> None:
    body = client.get("/epic_table_rows", headers=HTMX).text
    assert 'class="battery empty"' in body and "geen taken" in body


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
    assert "Geen epics die aan deze filters voldoen." in body


def test_the_summary_counts_the_selection_and_the_whole_board(client: TestClient) -> None:
    body = client.get("/epic_table_rows", params={"status": "Done"}, headers=HTMX).text
    assert tiles(body) == {"Epics": "1", "Klaar": "12", "Te gaan": "0"}
    assert "van de 4 op het epic-bord" in body


def test_the_summary_battery_is_the_wide_one_and_covers_the_selection(client: TestClient) -> None:
    body = client.get("/epic_table_rows", headers=HTMX).text
    wide = re.search(r'<div class="battery wide"[^>]*>.*?</div>\s*<span class="value">([^<]*)</span>', body, re.S)
    assert wide is not None and wide.group(1) == "106/125 · 85%", "94 + 12 done of 94 + 19 + 12 committed"


def test_points_on_no_epic_are_reported_rather_than_quietly_dropped(client: TestClient) -> None:
    web._ORPHANS = ep.Points(done=181, remaining=12, tasks=150)
    try:
        body = client.get("/epic_table_rows", headers=HTMX).text
        assert "150 sprinttaken (193 punten)" in body and "hangen aan geen enkele epic" in body
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
    assert "Het epic-bord kwam leeg terug." in body


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
    assert ">1 taak</span>" in body, "one task, singular"
    assert f'href="{BLOCKER.url}"' in body and "Wachten op de leverancier" in body
    assert "Sprint bord, actief" in body, "which board it is parked on"


def test_an_epic_blocked_from_both_sides_says_both(client: TestClient) -> None:
    web._EPICS[:] = [epic("Dubbel", id="e7", status="Impediment", impediments=(BLOCKER, BLOCKER))]
    body = client.get("/epic_table_rows", headers=HTMX).text
    assert ">epic + 2 taken</span>" in body


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
    for heading in ("Portfolio-item", "Vast", "Doelstelling", "Type", "Urgentie", "Projectleider", "Epics"):
        assert f">{heading}" in body, heading
    for heading in ("STP klaar", "STP te gaan", "Voortgang"):
        assert f">{heading}" in body, heading


def test_a_row_sums_the_epics_under_it_and_links_to_them(client: TestClient) -> None:
    body = client.get("/portfolio_table_rows", headers=HTMX).text
    assert portfolio_names(body) == ["Kernregistratie"], "the other two have no epics"
    assert '<a href="/portfolio_item?item=p1">Kernregistratie</a>' in body
    assert ">Run op orde<" in body and ">Niek Kleine<" in body
    assert "12 klaar, 0 nog open, 12 in totaal" in body, "e2's points, from the epic board"


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
        epic("Waterbalans II", ("p2",), id="e8", done=94, remaining=19),
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
    assert ">2 epics vast</span>" in body, "both of p1's blocked epics, rolled up"
    assert "Vastgelopen koppeling" in body and "Zit muurvast" in body
    assert f'href="{BLOCKER.url}"' in body, "and the blocking task is still one click away"
    assert tiles(body)["Vastgelopen"] == "1"


def test_only_stuck_narrows_the_portfolio_too(client: TestClient) -> None:
    web._EPICS[:] = [*EPICS, HELD_UP]
    body = client.get("/portfolio_table_rows", params={"empty": "on", "stuck": "on"}, headers=HTMX).text
    assert portfolio_names(body) == ["Kernregistratie"]


def test_the_portfolio_summary_counts_the_selection_and_the_whole_board(client: TestClient) -> None:
    body = client.get("/portfolio_table_rows", headers=HTMX).text
    assert tiles(body) == {"Portfolio-items": "1", "Klaar": "12", "Te gaan": "0"}
    assert "van de 3 op het bord · 1 epics" in body


def test_epics_pointing_at_a_missing_portfolio_item_are_reported(client: TestClient) -> None:
    web._EPICS[:] = [epic("Zwevend", ("weg",), id="e9", remaining=7)]
    body = client.get("/portfolio_table_rows", headers=HTMX).text
    assert "1 epics (7 punten) noemen een portfolio-item" in body


def test_filtering_the_portfolio_out_says_so_instead_of_showing_an_empty_table(client: TestClient) -> None:
    body = client.get("/portfolio_table_rows", params={"search": "bestaat niet"}, headers=HTMX).text
    assert "Geen portfolio-items die aan deze filters voldoen." in body


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
    assert "Het IV Portfolio-bord kwam leeg terug." in body


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
    assert tiles(body) == {"Epics": "2", "Klaar": "14", "Te gaan": "8", "Vastgelopen": "1"}
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
    assert "Er zijn geen epics aan dit portfolio-item gekoppeld." in body


def test_an_unknown_item_is_a_message_not_a_500(client: TestClient) -> None:
    response = client.get("/portfolio_item_view", params={"item": "bestaat-niet"}, headers=HTMX)
    assert response.status_code == 200 and "Er is geen portfolio-item met dat id" in response.text


def test_closing_the_live_reload_socket_is_not_an_asgi_error(client: TestClient) -> None:
    """fasthtml's own handler receives once past the disconnect and raises RuntimeError."""
    with client.websocket_connect("/live-reload"):
        pass


# --- the planning page ------------------------------------------------------------------

PLAN = pl.Snapshot(
    splits=[
        pl.Split(
            id="s1",
            name="Waterbalans",
            epic_id="e1",
            todo=40,
            has_todo=True,
            shares={"DE": 100.0, "DB": None, "DS": None, "PO/AT": None},
        ),
        pl.Split(
            id="s2",
            name="Backlogding",
            epic_id="e2",
            todo=10,
            has_todo=True,
            shares={"DE": 50.0, "DB": 50.0, "DS": None, "PO/AT": None},
        ),
    ],
    epics=[
        pl.PlanEpic(
            id="e1",
            name="Waterbalans",
            group=EPIC_GROUP_ACTIVE,
            status="Working on it",
            priority="High",
            portfolio_ids=("p1",),
        ),
        pl.PlanEpic(id="e2", name="Backlogding", group=EPIC_GROUP_BACKLOG, priority="Low"),
        pl.PlanEpic(id="e3", name="Nog niet gekoppeld", group=EPIC_GROUP_ACTIVE, priority="High"),
    ],
    people=[
        pl.Person(name="Agnes", role="DE", stp=10, sprint_available=100, quarter_available=100),
        pl.Person(name="Andor", role="DB", stp=10, sprint_available=100, quarter_available=100),
    ],
    current_end=date(2026, 10, 4),
)


@pytest.fixture
def planned(client: TestClient) -> Iterator[TestClient]:
    web._PLANNING[:] = [PLAN]
    yield client
    web._PLANNING.clear()


def test_planning_page_defers_its_numbers_to_a_load_request(planned: TestClient) -> None:
    html = planned.get("/planning").text
    assert 'aria-current="page"' in html and ">Planning<" in html
    assert 'hx-trigger="load"' in html
    assert "/planning_view" in html


def test_planning_view_shows_disciplines_queue_and_what_is_left_out(planned: TestClient) -> None:
    html = planned.get("/planning_view", params={"start": "2026-10-05", "end": "2026-11-18"}, headers=HTMX).text
    assert 'id="planning"' in html
    # 40 DE points against 10 per sprint over two sprints: 200%, overbooked, said in words.
    assert "200% · overboekt" in html
    assert "Waterbalans" in html
    # Backlog is not shown by default, and the unlinked epic is reported with its fix.
    assert "Backlogding" not in html
    assert "Nog niet gekoppeld" in html and "niet gekoppeld op Epics-STP-distribution" in html
    # The dates come back out of band, so the fields show the window in use.
    assert 'id="planning-dates"' in html and 'hx-swap-oob="true"' in html


def test_planning_view_layers_are_checkboxes(planned: TestClient) -> None:
    html = planned.get(
        "/planning_view", params={"start": "2026-10-05", "end": "2026-11-18", "layer": ["backlog"]}, headers=HTMX
    ).text
    assert "Backlogding" in html
    assert "Waterbalans" not in html.split("Epics</h3>")[1].split("Volgende sprint")[0]


def test_planning_view_defaults_the_window_from_the_current_sprint(planned: TestClient) -> None:
    html = planned.get("/planning_view", headers=HTMX).text
    assert 'value="2026-10-05"' in html and 'value="2026-12-31"' in html


def test_planning_view_reports_a_bad_date(planned: TestClient) -> None:
    html = planned.get("/planning_view", params={"end": "2026-01-01", "start": "2026-10-05"}, headers=HTMX).text
    assert "before the start" in html


def test_planning_view_reports_a_failed_fetch(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(client: Any) -> pl.Snapshot:
        raise MondayError("complexity budget exhausted")

    monkeypatch.setattr(pl, "fetch", boom)
    web._PLANNING.clear()
    html = client.get("/planning_view", headers=HTMX).text
    assert "complexity budget exhausted" in html


def test_planning_dam_filter_scopes_the_queue_and_the_load(planned: TestClient) -> None:
    window = {"start": "2026-10-05", "end": "2026-11-18", "layer": ["promised", "backlog"]}
    dam = planned.get("/planning_view", params={**window, "dam": DAM}, headers=HTMX).text
    assert "Waterbalans" in dam and "Backlogding" not in dam
    assert "Alleen DAM" in dam
    non_dam = planned.get("/planning_view", params={**window, "dam": NON_DAM}, headers=HTMX).text
    epics_part = non_dam.split("Epics</h3>")[1].split("Volgende sprint")[0]
    assert "Backlogding" in epics_part and "Waterbalans" not in epics_part
    # Only the selection takes capacity: 5 DE points of 20, not the 45 of both halves.
    assert "25%" in non_dam and "% · overboekt" not in non_dam


def test_planning_explains_itself_with_the_selections_own_numbers(planned: TestClient) -> None:
    html = planned.get("/planning_view", params={"start": "2026-10-05", "end": "2026-11-18"}, headers=HTMX).text
    assert "Hoe wordt dit berekend?" in html
    assert "Uitgerekend voor DE: 40.0 STP ÷ (10.0 STP per sprint × 2 sprints = 20.0) = 200%." in html
    for help_text in pl.LAYER_HELP_NL.values():
        assert help_text in html


def test_planning_layer_checkboxes_carry_their_definition_on_hover(planned: TestClient) -> None:
    html = planned.get("/planning").text
    assert f'title="{pl.LAYER_HELP_NL[pl.PROMISED]}"' in html
    assert 'name="dam"' in html


def test_planning_treats_an_unknown_dam_value_as_both(planned: TestClient) -> None:
    params = {"start": "2026-10-05", "end": "2026-11-18", "layer": ["promised", "backlog"], "dam": "DAM"}
    response = planned.get("/planning_view", params=params, headers=HTMX)
    assert response.status_code == 200
    assert "Waterbalans" in response.text and "Backlogding" in response.text
    assert "Alleen" not in response.text.split('class="lede-scope"')[1].split("</p>")[0]
    assert planned.get("/planning", params={"dam": "DAM"}).status_code == 200


def test_planning_this_quarter_switch_narrows_to_epics_due_by_the_quarter_end(planned: TestClient) -> None:
    params = {"start": "2026-10-05", "end": "2026-11-18", "layer": ["promised", "backlog"]}
    html = planned.get("/planning_view", params={**params, "this_quarter": "1"}, headers=HTMX).text
    # Neither fixture epic has a due date, so nothing is due by the quarter end.
    assert "Geen epic in deze selectie" in html
    assert "due uiterlijk 2026-11-18" in html
    page_html = planned.get("/planning", params={"this_quarter": "1"}).text
    assert 'name="this_quarter"' in page_html and "checked" in page_html.split('name="this_quarter"')[1][:40]
    assert f'title="{pl.THIS_QUARTER_HELP_NL}"' in page_html
    assert "this_quarter=1" in page_html


# --- the shared client ------------------------------------------------------------------


def test_every_route_shares_one_client_rather_than_a_session_each(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A client per route was a fresh TLS handshake per page render and filter change."""
    monkeypatch.setattr(bd, "fetch_sprint_items", lambda client: [])
    before = FakeClient.made
    client.get("/sprint_view", params={"person": web.EVERYONE}, headers=HTMX)
    client.get("/sprint_view", params={"person": web.EVERYONE, "open_only": "1"}, headers=HTMX)
    assert FakeClient.made - before == 1


def test_the_shared_client_is_closed_when_the_server_shuts_down(client: TestClient) -> None:
    shared = web.monday_client()
    with TestClient(web.app):
        pass  # entering and leaving runs the app's startup and shutdown
    assert shared.closed


# --- the page shells build no filter block ------------------------------------------------


@pytest.mark.parametrize(("path", "module", "fn"), [("/epics", ep, "status_counts"), ("/portfolio", pf, "attach")])
def test_a_page_shell_leaves_the_filter_options_to_the_first_table(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str, module: Any, fn: str
) -> None:
    """The deferred table brings the options and counts (`fields=1`); computing them in
    the shell as well was a second full pass over the rows on every page load."""
    calls: list[int] = []
    real = getattr(module, fn)
    monkeypatch.setattr(module, fn, lambda *a, **kw: calls.append(1) or real(*a, **kw))
    body = client.get(path).text
    assert calls == []
    assert 'hx-trigger="load"' in body and "fields=1" in body


def test_a_page_shell_keeps_every_filter_it_was_given(client: TestClient) -> None:
    """Its dropdowns have no options yet, but the chosen value is one of them, so touching
    another control before the table arrives does not quietly drop it."""
    body = client.get("/epics", params={"owner": "Agnes Dubbink", "status": "Done", "search": "water"}).text
    assert re.search(r'<option value="Agnes Dubbink" selected>', body)
    assert '<input type="hidden" name="status" value="Done">' in body
    assert 'value="water"' in body
    assert 'class="chip"' not in body, "no chips counted from no rows"


# --- the huisstijl shell and the cards view -----------------------------------------------


def test_every_page_is_dutch_light_by_default_and_carries_the_brand_bar(client: TestClient, sprint_group: Any) -> None:
    body = client.get("/").text
    assert '<html lang="nl" data-theme="light">' in body
    assert ">WDODelta</a>" in body and "jouw waterschap" in body, "the internal pay-off"
    assert "Waterschap Drents Overijsselse Delta (WDODelta)" in body, "the footer names the organisation once in full"
    assert "Vivala Sans Rounded" in body and "#075895" in body


@pytest.mark.parametrize("path", ["/", "/epics", "/portfolio", "/portfolio_item?item=p1", "/planning"])
def test_every_page_has_the_view_switch_with_the_table_pressed_by_default(
    client: TestClient, sprint_group: Any, path: str
) -> None:
    web._PLANNING[:] = [PLAN]
    body = client.get(path).text
    assert re.search(r'data-weergave="tabel" aria-pressed="true"', body), path
    assert re.search(r'data-weergave="kaarten" aria-pressed="false"', body), path
    client.cookies.set("weergave", "kaarten")
    body = client.get(path).text
    assert re.search(r'data-weergave="kaarten" aria-pressed="true"', body), "the cookie is the choice"
    web._PLANNING.clear()


def test_every_filter_form_is_marked_so_the_switch_can_re_ask_for_its_section(
    client: TestClient, sprint_group: Any
) -> None:
    web._PLANNING[:] = [PLAN]
    for path, form in (("/", "sprint"), ("/epics", "epic"), ("/portfolio", "portfolio"), ("/planning", "planning")):
        assert re.search(rf'<form(?=[^>]*id="{form}-filters")(?=[^>]*data-refilter)', client.get(path).text), path
    web._PLANNING.clear()


def test_the_sprint_cards_are_a_board_of_lanes_with_the_same_selection(client: TestClient, sprint_group: Any) -> None:
    client.cookies.set("weergave", "kaarten")
    body = client.get("/sprint_view", params={"person": web.EVERYONE}, headers=HTMX).text
    assert 'class="kanban"' in body and "<table" not in body.split('id="markdown-block"')[0].split("Taken")[-1]
    assert task_names(body) == ["Bouw het dashboard", "Review waterschapsmodel", "Klaar hiermee"]
    lanes = re.findall(r'<div aria-label="([^"]*)" class="lane">', body)
    assert lanes == ["Te doen", "Wacht", "Klaar"], "only the lanes that hold a task, in workflow order"
    assert re.search(r'<label class="taak tone-good done"', body), "a Done task is struck through, still ticked"


def test_an_unknown_view_is_the_table(client: TestClient, sprint_group: Any) -> None:
    client.cookies.set("weergave", "iets")
    assert 'class="tasks"' in client.get("/sprint_view", params={"person": web.EVERYONE}, headers=HTMX).text


def test_the_epic_cards_hold_the_rows_figures_and_sort_like_the_headers(client: TestClient) -> None:
    client.cookies.set("weergave", "kaarten")
    body = client.get("/epic_table_rows", headers=HTMX).text
    assert "<table" not in body and body.count('class="kaart ') == 3, "dropped epics stay hidden"
    assert 'class="sortbar"' in body and "resort=" in body
    assert ">83%" in body and "94 van 113 STP" in body, "Waterbalans: 94 of 113 done"
    assert "94 klaar, 19 nog open, 113 in totaal" in body, "the same battery as the row"
    order = [name for name in ("Kernregistratie", "Waterbalans", "Nog niks gepland") if name in body]
    assert sorted(order, key=body.index) == order, "the default sort, as in the table"


def test_a_stuck_epic_card_wears_the_critical_rule_and_names_its_blockers(client: TestClient) -> None:
    web._EPICS[:] = [*EPICS, HELD_UP]
    client.cookies.set("weergave", "kaarten")
    body = client.get("/epic_table_rows", headers=HTMX).text
    card = re.search(r'<div class="kaart tone-critical[^"]*">.*?Vastgelopen koppeling.*?</details>', body, re.S)
    assert card is not None and "Wachten op de leverancier" in card.group(0)


def test_the_portfolio_cards_list_their_epics_and_link_to_the_item(client: TestClient) -> None:
    client.cookies.set("weergave", "kaarten")
    body = client.get("/portfolio_table_rows", headers=HTMX).text
    assert 'class="card-grid wide"' in body
    assert 'href="/portfolio_item?item=p1"' in body and 'class="elist"' in body
    assert "Kernregistratie" in body and "12/12" in body, "e2's points under its item"


def test_one_portfolio_items_cards_leave_out_the_shared_portfolio(client: TestClient) -> None:
    web._EPICS[:] = [*EPICS, HELD_UP, ON_IMPEDIMENT]
    client.cookies.set("weergave", "kaarten")
    body = client.get("/portfolio_item_view", params={"item": "p1"}, headers=HTMX).text
    assert "<h2>Kernregistratie</h2>" in body and body.count('class="kaart ') == 3
    assert "Geen portfolio" not in body and 'href="/portfolio_item' not in body


def test_the_planning_cards_open_with_capacity_and_booked_charts_side_by_side(planned: TestClient) -> None:
    planned.cookies.set("weergave", "kaarten")
    params = {"start": "2026-10-05", "end": "2026-11-18", "layer": ["promised", "backlog"]}
    html = planned.get("/planning_view", params=params, headers=HTMX).text
    pair = html.split('class="chart-pair"')[1].split('class="card-grid wide"')[0]
    assert pair.count('class="hbars"') == 2, "capacity on the left, booked on the right"
    assert pair.count('class="hrow"') == 2 * 4, "every discipline in both, in the same order"
    # DE: Agnes, 10 STP a sprint at 100%, so 20 over the two sprints, both actual and ceiling.
    assert "DE: 20.0 STP beschikbaar, 20.0 bij 100% beschikbaarheid" in pair
    # DE: 40 promised + 5 backlog = 45 booked against 20: 225%, so the axis runs to 250%.
    assert "DE: 225% geboekt, 45.0 van 20.0 STP" in pair
    assert 'class="hbar booked tone-critical" style="width: 90.0%"' in pair, "225 of 250"
    assert 'style="width: 10.0%"' in pair, "DB's 25%, on the same axis"
    assert ">250%</span>" in pair
    assert 'class="hbar booked tone-critical"' in pair
    assert "DB: 25% geboekt, 5.0 van 20.0 STP" in pair and 'class="hbar booked tone-active"' in pair
    assert "PO/AT: — geboekt" in pair and "PO/AT: 0%" not in pair, "nobody, and nothing to book: no 0%"
    assert 'class="spbar"' not in html, "the per-sprint bars are gone"
    assert "<h3>DE · Data engineering</h3>" in html and ">225%" in html and "overboekt" in html
    assert "25.0 STP past niet in de periode" in html
    assert "<h4" in html and "Toegezegd" in html
    outside = re.sub(
        r"<dialog.*?</dialog>", "", html.split("Per discipline")[1].split("Volgende sprint")[0], flags=re.S
    )
    assert "<table" not in outside, "the cards view holds no table, only the dialogs do"


def test_a_discipline_card_is_folded_and_opens_every_epic_in_a_dialog(planned: TestClient) -> None:
    planned.cookies.set("weergave", "kaarten")
    params = {"start": "2026-10-05", "end": "2026-11-18", "layer": ["promised", "backlog"]}
    html = planned.get("/planning_view", params=params, headers=HTMX).text
    de = re.search(r'<div [^>]*class="kaart tone-critical opens".*?</dialog>', html, re.S)
    assert de is not None and "showModal()" in de.group(0)
    folded = de.group(0).split("<dialog")[0]
    assert "<strong>2 epics</strong> in de rij" in folded and "Bekijk de epics" in folded
    assert "Waterbalans" not in folded, "the list is in the dialog, not on the card"
    dialog = de.group(0).split("<dialog")[1]
    assert "Waterbalans" in dialog and "Backlogding" in dialog and ">S1</span><span>S2</span>" in dialog
    # Waterbalans: 40 STP at 10 a sprint is four sprints, and the window holds two.
    assert 'aria-label="Sprints volgens de prognose: vanaf S1, loopt door na de periode"' in dialog
    assert "Donkerblauw: een sprint waarin DE volgens de prognose aan deze epic werkt" in dialog
    assert 'aria-label="Sluiten"' in dialog
    assert 'class="kaart tone-neutral"' in html, "a discipline with nothing to do has no dialog to open"


def test_the_booked_axis_runs_to_the_highest_load_and_never_below_150_percent() -> None:
    assert web.chart.booked_scale([0.4, 0.8]) == (1.5, 0.5), "room for the band and the 100% line"
    assert web.chart.booked_scale([1.2, 1.9]) == (2.0, 0.5)
    assert web.chart.booked_scale([3.6, 2.53, 2.15, 1.2]) == (4.0, 1.0), "360% on a 0–400% axis"
    assert web.chart.booked_scale([]) == (1.5, 0.5)


def test_every_date_field_is_iso_text_with_a_calendar(planned: TestClient) -> None:
    html = planned.get("/planning").text
    for name in ("start", "end"):
        assert re.search(rf'<input type="text" name="{name}"[^>]*pattern="\\d\{{4\}}-\\d\{{2\}}-\\d\{{2\}}"', html), (
            name
        )
    assert html.count('class="date-picker"') == 2 and html.count('aria-label="Kies een datum in de kalender"') == 2
