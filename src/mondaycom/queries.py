"""GraphQL query builders.

monday.com's `items_page` filters compare against *ids*: a status is matched by
its index (see ``config.SPRINT_STATUS``) and a person by their user id or the
literal ``"assigned_to_me"``. See docs/monday-api/reference/items-page.md.
"""

from __future__ import annotations

import json
from datetime import datetime
from textwrap import dedent

from mondaycom.config import (
    ASSIGNED_TO_ME,
    CURRENT_SPRINT_GROUP,
    EPIC_BOARD,
    PORTFOLIO_BOARD,
    SPRINT_BOARD,
    SPRINT_STATUS,
    Board,
    person_filter_value,
)

# `items_page` will not hand back more than 500 items at a time, whatever you ask for.
PAGE_LIMIT = 500

#: The sprint group is one page of ~60 rows, so it asks for less than a board read does
#: — the limit is what a query's complexity is charged on. `fetch_sprint_items` raises
#: rather than truncating if the group ever outgrows it.
GROUP_LIMIT = 300


def _iso_date(value: str) -> str:
    """`value` as the ``YYYY-MM-DD`` a date filter compares against, or a `ValueError`.

    The date is the one filter value that is not a number and not a list monday.com
    hands us — it is typed by a human. Checking its shape here keeps anything that is
    not a date out of the query text, whichever caller supplied it.
    """
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"{value!r} is not a date: expected YYYY-MM-DD") from None
    return value


def _page_args(cursor: str | None, limit: int = PAGE_LIMIT) -> str:
    """The `items_page` arguments for one slice of a paginated read.

    `limit` has to be repeated on every page: a `cursor` on its own does *not* inherit
    the first call's page size, it silently falls back to the default 25. Getting this
    wrong turns five requests into sixty-three and costs about 40 seconds on the done board.
    """
    page = f"limit: {limit}"
    return f'{page}, cursor: "{cursor}"' if cursor else page


def sprint_tasks(
    due_on_or_before: str,
    statuses: list[str] | None = None,
    person: str | None = ASSIGNED_TO_ME,
    epic_ids: list[str] | None = None,
    board: Board = SPRINT_BOARD,
) -> str:
    """Tasks on `board` due by `due_on_or_before`, optionally narrowed by person and epic.

    Args:
        due_on_or_before: sprint end date as ``YYYY-MM-DD``.
        statuses: status labels to keep, e.g. ``config.OPEN_STATUSES``. ``None`` keeps every status.
        person: user id, or ``config.ASSIGNED_TO_ME``. Matches owner *or* reviewer.
            ``None`` drops the filter and returns everybody's tasks.
        epic_ids: item ids on the epic board. ``None`` or empty keeps every epic,
            including tasks with no epic linked at all.
        board: board to query.
    """
    # Every value interpolated into a query is escaped by the thing that shapes it:
    # `json.dumps` for text, `int` for ids. The date gets both — its shape is checked
    # and it is then written as JSON, so it cannot end the string literal it sits in.
    due = json.dumps(["EXACT", _iso_date(due_on_or_before)])
    rules = [
        f"""{{
                            column_id: "{board.column("due_date")}",
                            compare_value: {due},
                            operator: lower_than_or_equal
                        }}"""
    ]
    if statuses:
        indexes = json.dumps([SPRINT_STATUS[s] for s in statuses])
        rules.insert(
            0,
            f"""{{
                            column_id: "{board.column("status")}",
                            compare_value: {indexes},
                            operator: any_of
                        }}""",
        )
    if epic_ids:
        # A board_relation compares against linked item ids as *numbers*, not strings.
        linked = json.dumps([int(eid) for eid in epic_ids])
        rules.append(
            f"""{{
                            column_id: "{board.column("epic")}",
                            compare_value: {linked},
                            operator: any_of
                        }}"""
        )

    # "Assigned to someone" means owner or reviewer, so it is a nested OR group.
    groups = ""
    if person:
        who = json.dumps([person_filter_value(person)])
        groups = f""",
                        groups: {{
                            rules: [
                                {{
                                    column_id: "{board.column("owner")}",
                                    compare_value: {who},
                                    operator: any_of
                                }},
                                {{
                                    column_id: "{board.column("reviewer")}",
                                    compare_value: {who},
                                    operator: any_of
                                }}
                            ],
                            operator: or
                        }}"""

    columns = json.dumps(
        [board.column(a) for a in ("owner", "reviewer", "status", "story_points", "due_date", "story_syntax", "epic")]
    )

    return dedent(f"""
        query {{
            boards(ids: {board.id}) {{
                items_page(
                    query_params: {{
                        rules: [{",".join(rules)}],
                        operator: and{groups}
                    }}
                ) {{
                    cursor
                    items {{
                        id
                        name
                        column_values(ids: {columns}) {{
                            id
                            text
                            value
                            ... on BoardRelationValue {{
                                display_value
                                linked_item_ids
                            }}
                        }}
                    }}
                }}
            }}
        }}
    """).strip()


def sprint_group_tasks(board: Board = SPRINT_BOARD, group: str = CURRENT_SPRINT_GROUP, limit: int = GROUP_LIMIT) -> str:
    """Every task in the sprint group, with what the burndown needs: points, status, done date.

    The group is the sprint's true membership; the date filter used elsewhere is a
    proxy for it. No `query_params` here on purpose — we want the whole group.
    """
    columns = json.dumps(
        [board.column(a) for a in ("story_points", "status", "done_date", "due_date", "owner", "reviewer", "epic")]
    )
    return dedent(f"""
        query {{
            boards(ids: {board.id}) {{
                groups(ids: "{group}") {{
                    id
                    title
                    items_page({_page_args(None, limit)}) {{
                        cursor
                        items {{
                            id
                            name
                            column_values(ids: {columns}) {{
                                id
                                text
                                ... on BoardRelationValue {{
                                    display_value
                                    linked_item_ids
                                }}
                            }}
                        }}
                    }}
                }}
            }}
        }}
    """).strip()


def board_people(board: Board = SPRINT_BOARD) -> str:
    """Everyone subscribed to `board` — the people worth offering as an assignee filter.

    `photo_url` is the 2026-07 shape of the profile picture; the flat `photo_thumb_small`
    it replaces is gone in 2026-10. `thumb_small` is 50×50, plenty for a 24px avatar.
    """
    return dedent(f"""
        query {{
            boards(ids: [{board.id}]) {{
                subscribers {{
                    id
                    name
                    photo_url {{ thumb_small }}
                }}
            }}
        }}
    """).strip()


def epics(board: Board = EPIC_BOARD, limit: int = 500) -> str:
    """Every epic, as id and name, for the epic filter. One page covers the board today."""
    return dedent(f"""
        query {{
            boards(ids: [{board.id}]) {{
                items_page(limit: {limit}) {{
                    cursor
                    items {{
                        id
                        name
                    }}
                }}
            }}
        }}
    """).strip()


def epic_rows(board: Board = EPIC_BOARD, cursor: str | None = None) -> str:
    """Every epic with what the epics overview shows: owner, status, priority, portfolio.

    Paginated, because 275 epics fit in one page today but the board only grows.
    Portfolio is a board_relation, so its name is in `display_value` — `text` is null.
    """
    columns = json.dumps([board.column(a) for a in ("owner", "status", "priority", "portfolio")])
    return dedent(f"""
        query {{
            boards(ids: [{board.id}]) {{
                items_page({_page_args(cursor)}) {{
                    cursor
                    items {{
                        id
                        name
                        column_values(ids: {columns}) {{
                            id
                            text
                            ... on BoardRelationValue {{
                                display_value
                                linked_item_ids
                            }}
                        }}
                    }}
                }}
            }}
        }}
    """).strip()


def portfolio_rows(board: Board = PORTFOLIO_BOARD, cursor: str | None = None) -> str:
    """Every IV Portfolio item with the fields the portfolio overview shows.

    Its epics are not here: the board carries no connect column back to the epic board,
    so the link is read from the epic side and inverted — see `portfolio.attach`.
    """
    columns = json.dumps([board.column(a) for a in ("goal", "urgency", "type", "lead", "start", "end", "link", "ref")])
    return dedent(f"""
        query {{
            boards(ids: [{board.id}]) {{
                items_page({_page_args(cursor)}) {{
                    cursor
                    items {{
                        id
                        name
                        column_values(ids: {columns}) {{
                            id
                            text
                        }}
                    }}
                }}
            }}
        }}
    """).strip()


def board_tasks(board: Board = SPRINT_BOARD, cursor: str | None = None) -> str:
    """Every task on `board`, reduced to what the per-epic point totals need.

    No dates and no people: this runs over the whole done board (2000+ items, five
    pages), so it asks for what gets summed and nothing else. The name comes along
    because a task on Impediment is named in the epic's stuck marker, and `group` so the
    dummy-story groups can be dropped — see `config.DUMMY_GROUPS`.
    """
    columns = json.dumps([board.column(a) for a in ("story_points", "status", "epic")])
    return dedent(f"""
        query {{
            boards(ids: [{board.id}]) {{
                items_page({_page_args(cursor)}) {{
                    cursor
                    items {{
                        id
                        name
                        group {{ id }}
                        column_values(ids: {columns}) {{
                            id
                            text
                            ... on BoardRelationValue {{
                                linked_item_ids
                            }}
                        }}
                    }}
                }}
            }}
        }}
    """).strip()


#: Everything an Obsidian project note fills in. One item, so the column budget is not
#: a concern here the way it is on the board-wide reads.
PROJECT_COLUMNS = (
    "prj_nr",
    "owner",
    "owner_text",
    "status",
    "priority",
    "portfolio",
    "funnel",
    "method",
    "type",
    "estimate",
    "client",
    "experts",
    "why",
    "product",
    "quality",
    "budget",
    "submitted",
    "planned_start",
    "started",
    "planned_end",
    "finished",
    "due_date",
)


def _project_fields(board: Board) -> str:
    """The `id`, `name` and column selection shared by both epic-item lookups."""
    columns = json.dumps([board.column(a) for a in PROJECT_COLUMNS])
    return f"""id
                    name
                    column_values(ids: {columns}) {{
                        id
                        text
                        ... on BoardRelationValue {{
                            display_value
                            linked_item_ids
                        }}
                    }}"""


def epic_by_id(item_id: str, board: Board = EPIC_BOARD) -> str:
    """One epic by its monday.com item id, with everything a project note needs.

    `items(ids:)` reaches the item directly — no board scan, no filter shape to get
    wrong. The board is still passed so the column ids come from one place.
    """
    return dedent(f"""
        query {{
            items(ids: [{int(item_id)}]) {{
                {_project_fields(board)}
            }}
        }}
    """).strip()


def epic_by_project_number(number: str, board: Board = EPIC_BOARD) -> str:
    """One epic by its `prj_nr` (`DPR-223`), with everything a project note needs.

    `prj_nr` is an `item_id`-type column with a custom key, and it compares against the
    text it displays — `any_of` with `"DPR-223"`, not the bare digits. It is the only
    operator the column configures: `contains_text` comes back as `no_operator_config`.
    """
    return dedent(f"""
        query {{
            boards(ids: [{board.id}]) {{
                items_page(
                    limit: 2,
                    query_params: {{
                        rules: [{{
                            column_id: "{board.column("prj_nr")}",
                            compare_value: {json.dumps([number])},
                            operator: any_of
                        }}]
                    }}
                ) {{
                    items {{
                        {_project_fields(board)}
                    }}
                }}
            }}
        }}
    """).strip()


def board_columns(board: Board = SPRINT_BOARD) -> str:
    """Every column on `board` with its id, title, and type — how you discover new column ids."""
    return dedent(f"""
        query {{
            boards(ids: [{board.id}]) {{
                name
                columns {{
                    id
                    title
                    type
                    settings_str
                }}
            }}
        }}
    """).strip()


def me() -> str:
    """The authenticated user — handy to confirm which token is loaded."""
    return dedent("""
        query {
            me {
                id
                name
                email
            }
        }
    """).strip()
