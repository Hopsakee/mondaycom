"""Offline tests for the IV Portfolio overview: the link inversion, the totals, the filters."""

from __future__ import annotations

from typing import Any

import pytest

from mondaycom import epics as ep
from mondaycom import portfolio as pf
from mondaycom.config import PORTFOLIO_BOARD, SPRINT_BOARD


def portfolio_item(
    item_id: str,
    name: str,
    goal: str = "",
    urgency: str = "",
    type: str = "",
    lead: str = "",
    link: str = "",
    ref: str = "",
) -> dict[str, Any]:
    """An IV Portfolio item as `queries.portfolio_rows` returns it: plain text columns."""
    values = {"goal": goal, "urgency": urgency, "type": type, "lead": lead, "link": link, "ref": ref}
    return {
        "id": item_id,
        "name": name,
        "column_values": [{"id": PORTFOLIO_BOARD.column(alias), "text": text} for alias, text in values.items()],
    }


def epic(name: str, portfolio_ids: tuple[str, ...] = (), **kw: Any) -> ep.Epic:
    done = kw.pop("done", 0.0)
    remaining = kw.pop("remaining", 0.0)
    cancelled = kw.pop("cancelled", 0.0)
    return ep.Epic(
        id=kw.pop("id", name),
        name=name,
        portfolio_ids=portfolio_ids,
        points=ep.Points(done=done, remaining=remaining, cancelled=cancelled),
        **kw,
    )


BLOCKER = ep.Impediment(
    id="55",
    name="Wacht op de leverancier",
    board=SPRINT_BOARD.name,
    url="https://wdodelta.monday.com/boards/757790388/pulses/55",
)


# --- reading an item ---------------------------------------------------------------------


def test_an_item_reads_its_text_columns() -> None:
    row = pf.PortfolioItem.from_item(
        portfolio_item("p1", "Kernregistratie", "Run op orde", "Hoog", "Project", "Niek Kleine", "https://f", "169115")
    )
    assert (row.id, row.name, row.goal) == ("p1", "Kernregistratie", "Run op orde")
    assert (row.urgency, row.type, row.lead) == ("Hoog", "Project", "Niek Kleine")
    assert (row.link, row.ref) == ("https://f", "169115")


def test_an_item_knows_where_it_lives_on_monday() -> None:
    row = pf.PortfolioItem(id="p1", name="Kernregistratie")
    assert row.url == f"https://wdodelta.monday.com/boards/{PORTFOLIO_BOARD.id}/pulses/p1"


# --- inverting the link ------------------------------------------------------------------


def test_epics_are_grouped_under_the_item_they_link_to() -> None:
    """The IV Portfolio board carries no connect column back, so the epic side is the truth."""
    items = [pf.PortfolioItem(id="p1", name="Een"), pf.PortfolioItem(id="p2", name="Twee")]
    epics = [epic("A", ("p1",)), epic("B", ("p2",)), epic("C", ("p1",)), epic("D")]
    by_id = {item.id: item for item in pf.attach(items, epics)}
    assert sorted(e.name for e in by_id["p1"].epics) == ["A", "C"]
    assert [e.name for e in by_id["p2"].epics] == ["B"]


def test_attaching_leaves_the_originals_alone_so_it_can_be_redone_per_request() -> None:
    items = [pf.PortfolioItem(id="p1", name="Een")]
    pf.attach(items, [epic("A", ("p1",))])
    assert items[0].epics == (), "the cache holds bare rows; the join is made fresh"


def test_an_epic_pointing_at_a_missing_item_is_reported_not_dropped() -> None:
    items = [pf.PortfolioItem(id="p1", name="Een")]
    epics = [epic("A", ("p1",)), epic("Zwevend", ("weg",)), epic("Geen portfolio")]
    assert [e.name for e in pf.orphan_epics(items, epics)] == ["Zwevend"]


def test_the_epics_under_an_item_lead_with_the_blocked_ones_then_the_most_work_left() -> None:
    items = [pf.PortfolioItem(id="p1", name="Een")]
    epics = [
        epic("Klein", ("p1",), remaining=1),
        epic("Groot", ("p1",), remaining=20),
        epic("Vast", ("p1",), remaining=2, impediments=(BLOCKER,)),
    ]
    (attached,) = pf.attach(items, epics)
    assert [e.name for e in attached.epics] == ["Vast", "Groot", "Klein"]


# --- the totals --------------------------------------------------------------------------


def test_an_items_points_are_its_epics_points() -> None:
    (item,) = pf.attach(
        [pf.PortfolioItem(id="p1", name="Een")],
        [epic("A", ("p1",), done=10, remaining=4), epic("B", ("p1",), done=2, cancelled=9)],
    )
    assert (item.done, item.remaining, item.total) == (12, 4, 16)
    assert item.points.cancelled == 9, "reported, and out of the total, exactly as in the burndown"
    assert item.fraction_done == 0.75


def test_an_item_with_no_points_sorts_after_a_full_one_rather_than_reading_as_zero() -> None:
    (empty,) = pf.attach([pf.PortfolioItem(id="p1", name="Een")], [epic("A", ("p1",))])
    assert empty.fraction_done == ep.NO_TASKS and empty.bucket == "no-tasks"


def test_the_buckets_are_the_epics_own_four() -> None:
    def bucket(**points: float) -> str:
        (item,) = pf.attach([pf.PortfolioItem(id="p1", name="Een")], [epic("A", ("p1",), **points)])
        return item.bucket

    assert bucket(remaining=5) == "not-started"
    assert bucket(done=2, remaining=5) == "in-progress"
    assert bucket(done=5) == "complete"


def test_an_item_with_no_epics_is_empty_but_an_item_with_pointless_epics_is_not() -> None:
    bare, linked = pf.attach(
        [pf.PortfolioItem(id="p1", name="Een"), pf.PortfolioItem(id="p2", name="Twee")], [epic("A", ("p2",))]
    )
    assert bare.is_empty and not linked.is_empty


def test_totals_add_the_selection_up() -> None:
    items = pf.attach(
        [pf.PortfolioItem(id="p1", name="Een"), pf.PortfolioItem(id="p2", name="Twee")],
        [epic("A", ("p1",), done=3, remaining=1), epic("B", ("p2",), done=4, cancelled=2)],
    )
    assert pf.totals(items) == ep.Points(done=7, remaining=1, cancelled=2)


# --- being stuck -------------------------------------------------------------------------


def test_an_item_is_stuck_when_any_of_its_epics_is() -> None:
    (item,) = pf.attach(
        [pf.PortfolioItem(id="p1", name="Een")],
        [epic("Loopt", ("p1",)), epic("Vast", ("p1",), status="Impediment")],
    )
    assert item.is_stuck and [e.name for e in item.stuck_epics] == ["Vast"]


def test_the_blocking_tasks_are_counted_across_every_epic() -> None:
    (item,) = pf.attach(
        [pf.PortfolioItem(id="p1", name="Een")],
        [epic("A", ("p1",), impediments=(BLOCKER,)), epic("B", ("p1",), impediments=(BLOCKER, BLOCKER))],
    )
    assert item.impediments == 3


def test_the_epics_own_impediment_leads_the_stuck_list() -> None:
    (item,) = pf.attach(
        [pf.PortfolioItem(id="p1", name="Een")],
        [epic("Taak vast", ("p1",), impediments=(BLOCKER,)), epic("Epic vast", ("p1",), status="Impediment")],
    )
    assert [e.name for e in item.stuck_epics] == ["Epic vast", "Taak vast"]


# --- filtering and sorting ---------------------------------------------------------------


def three() -> list[pf.PortfolioItem]:
    """Three items: one with epics, one empty, one stuck."""
    items = [
        pf.PortfolioItem(id="p1", name="Kernregistratie", goal="Run op orde", urgency="Hoog", type="Project"),
        pf.PortfolioItem(id="p2", name="Leeg", goal="Werkplek", type="Initiatief"),
        pf.PortfolioItem(id="p3", name="Vastgelopen", goal="Werkplek", urgency="Laag", type="Initiatief"),
    ]
    epics = [
        epic("A", ("p1",), done=6, remaining=2),
        epic("B", ("p3",), remaining=5, status="Impediment"),
    ]
    return pf.attach(items, epics)


def test_items_with_no_epics_are_hidden_unless_asked_for() -> None:
    assert [i.name for i in pf.arrange(three())] == ["Vastgelopen", "Kernregistratie"]
    assert "Leeg" in [i.name for i in pf.arrange(three(), pf.Filters(empty=True))]


def test_every_filter_narrows() -> None:
    def names(**kw: Any) -> list[str]:
        return [i.name for i in pf.arrange(three(), pf.Filters(empty=True, **kw))]

    assert names(search="kern") == ["Kernregistratie"]
    assert sorted(names(goal="Werkplek")) == ["Leeg", "Vastgelopen"]
    assert names(type="Project") == ["Kernregistratie"]
    assert names(urgency="Hoog") == ["Kernregistratie"]
    assert names(bucket="in-progress") == ["Kernregistratie"]
    assert names(stuck=True) == ["Vastgelopen"]


def test_a_lead_is_matched_as_a_substring_like_a_trekker_is() -> None:
    items = [pf.PortfolioItem(id="p1", name="Een", lead="Niek Kleine", epics=(epic("A"),))]
    assert pf.matches(items[0], pf.Filters(lead="Niek"))
    assert not pf.matches(items[0], pf.Filters(lead="Evert"))


def test_the_default_sort_leads_with_the_least_complete() -> None:
    assert [i.name for i in pf.arrange(three())] == ["Vastgelopen", "Kernregistratie"], "0% before 75%"


def test_urgentie_sorts_in_the_boards_order_not_the_alphabet() -> None:
    items = [
        pf.PortfolioItem(id="p1", name="A", urgency="Laag", epics=(epic("x"),)),
        pf.PortfolioItem(id="p2", name="B", urgency="Hoog", epics=(epic("y"),)),
        pf.PortfolioItem(id="p3", name="C", urgency="Middel", epics=(epic("z"),)),
    ]
    assert [i.urgency for i in pf.arrange(items, sort="urgency")] == ["Hoog", "Middel", "Laag"]


def test_a_sort_spec_carries_its_direction_and_an_unknown_one_falls_back() -> None:
    assert pf.parse_sort("-done") == ("done", True)
    assert pf.parse_sort("verzonnen") == (pf.DEFAULT_SORT, False)


def test_a_header_offers_the_next_state_and_the_counts_start_high_to_low() -> None:
    assert pf.next_sort("name", "name") == "-name", "clicking the sorted column flips it"
    assert pf.next_sort("remaining", "name") == "-remaining", "a fresh numeric column starts descending"
    assert pf.next_sort("name", "-name") == "name"


def test_the_dropdowns_offer_only_values_the_board_actually_has() -> None:
    assert pf.options(three(), "goal") == ["Run op orde", "Werkplek"]
    assert pf.options(three(), "urgency") == ["Hoog", "Laag"], "in the board's order, and no blank"


# --- fetching ----------------------------------------------------------------------------


def test_fetch_portfolio_joins_the_board_to_the_epics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pf, "fetch_epics", lambda client: ([epic("A", ("p1",), done=3), epic("B", ("p9",))], ep.Points())
    )

    class Fake:
        def all_board_items(self, build: Any) -> list[dict[str, Any]]:
            return [portfolio_item("p1", "Kernregistratie")]

    items, epics = pf.fetch_portfolio(Fake())  # type: ignore[arg-type]
    assert [i.name for i in items] == ["Kernregistratie"] and items[0].done == 3
    assert [e.name for e in pf.orphan_epics(items, epics)] == ["B"]
