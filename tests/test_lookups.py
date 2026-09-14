"""Offline tests for the person/epic choice lists and the name resolver. No network."""

from __future__ import annotations

from typing import Any

import pytest

from mondaycom import lookups
from mondaycom.lookups import Choice, NoMatch

PEOPLE = [
    Choice(id="23029337", name="Agnes Dubbink"),
    Choice(id="23028787", name="Jelle de Jong"),
    Choice(id="65571290", name="Joris Monster"),
]


class StubClient:
    """Returns a canned GraphQL payload instead of calling monday.com."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def execute(self, query: str, variables: Any = None) -> dict[str, Any]:
        return self.data


def test_people_come_back_sorted_by_name() -> None:
    client = StubClient(
        {
            "boards": [
                {
                    "subscribers": [
                        {"id": 65571290, "name": "Joris Monster"},
                        {"id": 23029337, "name": "Agnes Dubbink"},
                    ]
                }
            ]
        }
    )
    people = lookups.fetch_people(client)  # type: ignore[arg-type]
    assert [c.name for c in people] == ["Agnes Dubbink", "Joris Monster"]
    assert people[0].id == "23029337", "ids must be strings, monday.com returns them as numbers"
    assert people[0].photo == "", "no photo_url in the answer is not an error"


def test_people_carry_their_photo_when_monday_has_one() -> None:
    client = StubClient(
        {
            "boards": [
                {
                    "subscribers": [
                        {"id": 1, "name": "Agnes Dubbink", "photo_url": {"thumb_small": "https://f.monday.com/a.png"}},
                        {"id": 2, "name": "Joris Monster", "photo_url": None},
                    ]
                }
            ]
        }
    )
    people = lookups.fetch_people(client)  # type: ignore[arg-type]
    assert [c.photo for c in people] == ["https://f.monday.com/a.png", ""]


def test_epics_come_back_sorted_by_name() -> None:
    client = StubClient(
        {
            "boards": [
                {"items_page": {"cursor": None, "items": [{"id": 2, "name": "Zwemwater"}, {"id": 1, "name": "AHN"}]}}
            ]
        }
    )
    assert [c.name for c in lookups.fetch_epics(client)] == ["AHN", "Zwemwater"]  # type: ignore[arg-type]


def test_a_second_page_of_epics_is_refused_rather_than_silently_truncated() -> None:
    client = StubClient({"boards": [{"items_page": {"cursor": "abc", "items": [{"id": 1, "name": "AHN"}]}}]})
    with pytest.raises(NoMatch, match="cursor pagination"):
        lookups.fetch_epics(client)  # type: ignore[arg-type]


def test_a_board_that_returns_nothing_gives_an_empty_list() -> None:
    assert lookups.fetch_people(StubClient({"boards": []})) == []  # type: ignore[arg-type]


def test_resolve_matches_an_exact_id() -> None:
    assert lookups.resolve(PEOPLE, "23028787").name == "Jelle de Jong"


def test_resolve_matches_a_name_substring_case_insensitively() -> None:
    assert lookups.resolve(PEOPLE, "agnes").id == "23029337"


def test_an_id_wins_over_a_name_substring() -> None:
    choices = [Choice(id="Agnes", name="Joris Monster"), Choice(id="1", name="Agnes Dubbink")]
    assert lookups.resolve(choices, "Agnes").name == "Joris Monster"


def test_no_match_says_so() -> None:
    with pytest.raises(NoMatch, match="Nothing matches 'Willem'"):
        lookups.resolve(PEOPLE, "Willem")


def test_an_ambiguous_match_lists_the_candidates() -> None:
    with pytest.raises(NoMatch, match="ambiguous, it matches 2") as exc:
        lookups.resolve(PEOPLE, "J")
    assert "Jelle de Jong" in str(exc.value) and "Joris Monster" in str(exc.value)


def test_a_very_ambiguous_match_is_truncated() -> None:
    many = [Choice(id=str(i), name=f"Epic {i:02d} data") for i in range(30)]
    with pytest.raises(NoMatch) as exc:
        lookups.resolve(many, "data")
    message = str(exc.value)
    assert "it matches 30" in message
    assert f"and {30 - lookups.MAX_AMBIGUOUS} more" in message
    assert message.count(";") == lookups.MAX_AMBIGUOUS, "one separator per shown name, plus the tail"
