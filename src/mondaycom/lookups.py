"""The id/name lists behind the person and epic filters.

monday.com filters on ids, so both the CLI and the web UI need to turn something
a human typed or picked ("Agnes", "all", an epic name) into an id. Fetching is
kept separate from resolving so the web UI can cache the lists and the CLI can
resolve straight off a fresh fetch.
"""

from __future__ import annotations

from dataclasses import dataclass

from mondaycom import queries
from mondaycom.client import MondayClient
from mondaycom.config import EPIC_BOARD, SPRINT_BOARD, Board

# How many candidate names an ambiguous match is allowed to print before it truncates.
MAX_AMBIGUOUS = 8


class NoMatch(ValueError):
    """What the user typed matched no choice, or more than one."""


@dataclass(frozen=True)
class Choice:
    """One option in a filter: the id monday.com wants, and the name a human reads."""

    id: str
    name: str
    #: Profile picture URL, when monday.com has one. Only people carry it; epics never do.
    photo: str = ""


def fetch_people(client: MondayClient, board: Board = SPRINT_BOARD) -> list[Choice]:
    """Everyone subscribed to the board, alphabetically."""
    data = client.execute(queries.board_people(board))
    boards = data.get("boards") or []
    if not boards:
        return []
    people = [
        Choice(id=str(u["id"]), name=u["name"], photo=(u.get("photo_url") or {}).get("thumb_small") or "")
        for u in boards[0]["subscribers"]
    ]
    return sorted(people, key=lambda c: c.name.lower())


def fetch_epics(client: MondayClient, board: Board = EPIC_BOARD) -> list[Choice]:
    """Every epic, alphabetically. The board fits in one page today; warn if that changes."""
    data = client.execute(queries.epics(board))
    boards = data.get("boards") or []
    if not boards:
        return []
    page = boards[0]["items_page"]
    epics = [Choice(id=str(i["id"]), name=i["name"]) for i in page["items"]]
    if page.get("cursor"):
        # Rather than silently filtering against a partial list, say so.
        raise NoMatch(
            f"The epic board no longer fits in one page ({len(epics)} fetched). queries.epics needs cursor pagination."
        )
    return sorted(epics, key=lambda c: c.name.lower())


def resolve(choices: list[Choice], needle: str) -> Choice:
    """Find the one choice matching `needle`: an exact id, or a case-insensitive name substring."""
    for choice in choices:
        if choice.id == needle:
            return choice

    wanted = needle.casefold()
    hits = [c for c in choices if wanted in c.name.casefold()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise NoMatch(f"Nothing matches {needle!r}.")

    # 47 epic names on one line helps nobody; show a few and say how many were hidden.
    shown = sorted(c.name for c in hits)[:MAX_AMBIGUOUS]
    listed = "; ".join(shown)
    if len(hits) > MAX_AMBIGUOUS:
        listed += f"; … and {len(hits) - MAX_AMBIGUOUS} more"
    raise NoMatch(f"{needle!r} is ambiguous, it matches {len(hits)}: {listed}")
