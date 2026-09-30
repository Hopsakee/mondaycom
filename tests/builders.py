"""Builders the test modules share. No network, no fixtures — plain functions.

Every column value is keyed by the board's *alias*, never by a raw monday.com column
id, so renaming a column in `config.py` breaks these tests instead of leaving them
green against ids the code no longer asks for.
"""

from __future__ import annotations

from typing import Any

from mondaycom import epics as ep
from mondaycom.config import SPRINT_BOARD, Board

#: A column value: plain text, or the whole cell for a column that answers elsewhere.
Cell = str | None | dict[str, Any]


def link(name: str = "", *ids: str) -> dict[str, Any]:
    """A board_relation cell: `text` is null, the name is in `display_value`. An empty
    id links nothing, so ``link("", epic_id)`` reads the same with or without one."""
    return {"text": None, "display_value": name, "linked_item_ids": [i for i in ids if i]}


def board_item(
    board: Board = SPRINT_BOARD,
    name: str = "t",
    id: str = "1",
    group: str | dict[str, str] | None = None,
    **cells: Cell,
) -> dict[str, Any]:
    """An item as ``items_page`` returns it, its column values keyed by alias. `group` is
    the group's id, or the whole group when the title matters too."""
    item: dict[str, Any] = {
        "id": id,
        "name": name,
        "column_values": [
            {"id": board.column(alias), **(cell if isinstance(cell, dict) else {"text": cell})}
            for alias, cell in cells.items()
        ],
    }
    if group is not None:
        item["group"] = group if isinstance(group, dict) else {"id": group}
    return item


def epic(
    name: str = "E",
    portfolio_ids: tuple[str, ...] = (),
    *,
    id: str | None = None,
    done: float = 0,
    remaining: float = 0,
    cancelled: float = 0,
    tasks: int = 0,
    **kw: Any,
) -> ep.Epic:
    """An `Epic` with its points spelled out flat: ``epic("A", done=3, remaining=1)``."""
    points = ep.Points(done=done, remaining=remaining, cancelled=cancelled, tasks=tasks)
    return ep.Epic(id=id or name, name=name, portfolio_ids=portfolio_ids, points=points, **kw)
