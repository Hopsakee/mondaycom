"""Sprint tasks: from a monday.com item to an Obsidian Tasks line."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from mondaycom import queries
from mondaycom.client import MondayClient
from mondaycom.config import (
    ASSIGNED_TO_ME,
    ME,
    MINUTES_PER_STORY_POINT,
    SPRINT_BOARD,
    SPRINT_LENGTH_WEEKS,
    TASK_TAG,
    Board,
)


def sprint_start(end_date: str) -> str:
    """The first day of the sprint that ends on `end_date` (``YYYY-MM-DD``)."""
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    return (end - timedelta(weeks=SPRINT_LENGTH_WEEKS) + timedelta(days=1)).isoformat()


@dataclass
class Task:
    """One sprint item, flattened out of the monday.com column-value soup."""

    id: str
    name: str
    status: str = ""
    due_date: str = ""
    story_points: int = 0
    is_reviewer: bool = False
    owner: str = ""
    epic: str = ""
    epic_id: str = ""

    @property
    def duration_minutes(self) -> int:
        return self.story_points * MINUTES_PER_STORY_POINT

    @classmethod
    def from_item(cls, item: dict[str, Any], board: Board = SPRINT_BOARD, me: str = ME) -> Task:
        """Build a Task from an ``items_page`` item.

        The `people` column holds the reviewer and `person` the owner; an item is
        review work for `me` when that name shows up in `people`. A board_relation
        column (the epic) carries its name in `display_value`, not in `text`.
        """
        cells = board.cells(item)
        linked = cells.linked("epic")
        return cls(
            id=item["id"],
            name=item["name"],
            status=cells.text("status"),
            due_date=cells.text("due_date"),
            # A checkbox carries whole minutes, so a half-point estimate rounds down here.
            story_points=int(cells.number("story_points")),
            is_reviewer=me in cells.text("reviewer"),
            owner=cells.text("owner"),
            epic=cells.text("epic"),
            epic_id=linked[0] if linked else "",
        )

    def to_markdown(self, created: str) -> str:
        """Render as an Obsidian Tasks checkbox line."""
        parts = [f"- [ ] {TASK_TAG} {self.name}"]
        if self.is_reviewer:
            parts.append("🤝reviewer")
        if self.duration_minutes:
            parts.append(f"[{self.duration_minutes}m]")
        parts.append("⏫")
        parts.append(f"➕ {created}")
        if self.due_date:
            parts.append(f"📅 {self.due_date}")
        return " ".join(parts)


def fetch_tasks(
    client: MondayClient,
    sprint_end: str,
    statuses: list[str] | None = None,
    person: str | None = ASSIGNED_TO_ME,
    epic_ids: list[str] | None = None,
    board: Board = SPRINT_BOARD,
    me: str = ME,
) -> list[Task]:
    """Fetch sprint tasks as `Task` objects.

    `person` and `epic_ids` narrow the query server-side; see `queries.sprint_tasks`.
    `me` is the name whose reviewer assignments earn the 🤝 marker — pass the person
    being filtered on, so the marker tracks whoever you are looking at.
    """
    items = client.board_items(
        queries.sprint_tasks(sprint_end, statuses=statuses, person=person, epic_ids=epic_ids, board=board)
    )
    return [Task.from_item(item, board=board, me=me) for item in items]


def tasklist_markdown(tasks: list[Task], sprint_end: str) -> str:
    """Render a full sprint tasklist, ready to paste into the vault."""
    start = sprint_start(sprint_end)
    lines = [f"# Sprint {start} - {sprint_end}", ""]
    lines.extend(task.to_markdown(created=start) for task in tasks)
    return "\n".join(lines)


def default_sprint_end(today: date | None = None) -> str:
    """Next Saturday on or after today — the usual sprint boundary.

    Only a convenience default so the CLI can run without arguments; pass an
    explicit date whenever the sprint does not end on a Saturday.
    """
    today = today or date.today()
    return (today + timedelta(days=(5 - today.weekday()) % 7)).isoformat()
