"""Column sorting for the tables, as one string.

Both overviews — the epics table and the portfolio table — sort on every column and
have to survive a round trip through a query string, so the whole state is a single
spec: ``"done"`` is done ascending, ``"-done"`` descending. That lets a sortable header
be a plain button carrying the *next* state and keeping no memory of its own.

A `Sorting` bundles the columns a table can sort on with its default and with the
columns that should start high-to-low; nobody opens a progress column wanting to see
the emptiest batteries first.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")


def label_key(labels: list[str], value: str) -> tuple[int, str]:
    """Sort a board's own labels in the board's order — a workflow, not an alphabet.

    A label the board no longer offers has no place in that order, so it sorts after
    every one it does, alphabetically among its kind.
    """
    return (labels.index(value), "") if value in labels else (len(labels), value.lower())


@dataclass(frozen=True)
class Sorting:
    """How one table sorts: its columns, its default, and which start descending."""

    keys: dict[str, Callable[[Any], Any]]
    default: str
    numeric: frozenset[str] = field(default_factory=frozenset)

    def parse(self, spec: str) -> tuple[str, bool]:
        """Split a spec into its column and direction.

        An unknown column falls back to the default rather than raising: it arrives
        from a query string, which anyone can type.
        """
        desc = spec.startswith("-")
        column = spec[1:] if desc else spec
        return (column, desc) if column in self.keys else (self.default, False)

    def next(self, column: str, spec: str) -> str:
        """The spec a click on `column`'s header should ask for, given the current one."""
        current, desc = self.parse(spec)
        if column == current:
            return column if desc else f"-{column}"
        return f"-{column}" if column in self.numeric else column

    def apply(self, rows: Iterable[T], sort: str, desc: bool = False) -> list[T]:
        """Sort `rows`. An unknown column falls back to the default rather than raising."""
        return sorted(rows, key=self.keys.get(sort, self.keys[self.default]), reverse=desc)
