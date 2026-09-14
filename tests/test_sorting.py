"""Offline tests for the one-string sort spec both overviews share."""

from __future__ import annotations

from dataclasses import dataclass

from mondaycom.sorting import Sorting, label_key


@dataclass
class Row:
    name: str
    size: int = 0


SORTING = Sorting(
    keys={"name": lambda r: r.name.lower(), "size": lambda r: r.size},
    default="name",
    numeric=frozenset({"size"}),
)


def test_a_spec_carries_its_direction() -> None:
    assert SORTING.parse("size") == ("size", False)
    assert SORTING.parse("-size") == ("size", True)


def test_an_unknown_column_falls_back_rather_than_raising() -> None:
    """It arrives from a query string, which anyone can type."""
    assert SORTING.parse("verzonnen") == ("name", False)
    assert SORTING.parse("-verzonnen") == ("name", False), "the direction goes with the column"


def test_clicking_the_sorted_column_flips_it() -> None:
    assert SORTING.next("name", "name") == "-name"
    assert SORTING.next("name", "-name") == "name"


def test_a_fresh_column_starts_the_way_it_is_useful() -> None:
    assert SORTING.next("size", "name") == "-size", "nobody opens a number column at its smallest"
    assert SORTING.next("name", "-size") == "name"


def test_apply_sorts_and_an_unknown_column_falls_back_there_too() -> None:
    rows = [Row("b", 3), Row("a", 1), Row("c", 2)]
    assert [r.name for r in SORTING.apply(rows, "size", desc=True)] == ["b", "c", "a"]
    assert [r.name for r in SORTING.apply(rows, "verzonnen")] == ["a", "b", "c"]


def test_labels_sort_in_the_boards_order_not_the_alphabet() -> None:
    """A workflow, not a word list: To Do comes before Done because the board says so."""
    board = ["To Do", "Working on it", "Done"]
    assert sorted(["Done", "To Do", "Working on it"], key=lambda v: label_key(board, v)) == board


def test_a_label_the_board_no_longer_offers_sorts_after_every_one_it_does() -> None:
    board = ["To Do", "Done"]
    assert sorted(["Afgeschaft", "Done", "To Do"], key=lambda v: label_key(board, v)) == [
        "To Do",
        "Done",
        "Afgeschaft",
    ]
