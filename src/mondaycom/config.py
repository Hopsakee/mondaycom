"""Environment and workspace configuration.

Everything account-specific lives here: the API token, the board ids, and the
column ids of the boards we query. monday.com filters on *ids*, never on the
labels you see in the UI, so this module is the translation table.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api.monday.com/v2"

# Date-named API version. Current as of 2026-09-03; see docs/monday-api/guides/api-versioning.md.
API_VERSION = "2026-07"

# The workspace behind every board id below, and the only place its name is spelled out.
# An item's web address is derivable from it, so `item_url` costs no `url` field on the
# big board reads — which run over 2400 items.
ACCOUNT_SLUG = "wdodelta"

# Whose account this is, by the name the boards spell out: owner and reviewer columns
# arrive as text, so the 🤝 marker, the burndown's person filter and a project note's
# `rol` all match on it. `MONDAY_ME` overrides it for anyone else running this.
ME = os.environ.get("MONDAY_ME", "Jelle de Jong")


def api_key() -> str:
    """Return the monday.com personal API token, or explain how to set it."""
    key = os.environ.get("API_KEY_MONDAY")
    if not key:
        raise RuntimeError(
            "API_KEY_MONDAY is not set. Copy .env.example to .env and paste your "
            "monday.com personal API token (Avatar > Developers > My access tokens)."
        )
    return key


@dataclass(frozen=True)
class Board:
    """A board we work with, plus the column ids we care about on it."""

    name: str
    id: int
    columns: dict[str, str] = field(default_factory=dict)

    def column(self, alias: str) -> str:
        """Resolve a human alias to the column id monday.com expects."""
        try:
            return self.columns[alias]
        except KeyError:
            raise KeyError(
                f"Board {self.name!r} has no column alias {alias!r}. Known: {sorted(self.columns)}"
            ) from None

    def cells(self, item: dict[str, Any]) -> Cells:
        """One item's column values, ready to be read by alias."""
        return Cells(self, {col["id"]: col for col in item.get("column_values") or []})


def as_number(text: str) -> float:
    """A column's text as a number. An estimate nobody filled in, or filled in with a
    word, is worth nothing — never an error, on boards this size."""
    try:
        return float(text) if text else 0.0
    except ValueError:
        return 0.0


@dataclass(frozen=True)
class Cells:
    """One item's `column_values`, addressed by the board's own aliases.

    Reading a column is never just `text`: a board_relation answers in `display_value`
    and leaves `text` null, and a formula does the same. That fallback lives here rather
    than in each of the five `from_item`s that would otherwise spell it out.
    """

    board: Board
    #: The raw column dicts, by column id — for the fields that are not text.
    raw: dict[str, dict[str, Any]]

    def text(self, alias: str) -> str:
        """One column as the string the board displays. Missing columns read as empty."""
        col = self.raw.get(self.board.column(alias), {})
        return str(col.get("text") or col.get("display_value") or "").strip()

    def number(self, alias: str) -> float:
        """One column as a number. Anything unparseable is worth nothing, never an error."""
        return as_number(self.text(alias))

    def linked(self, alias: str) -> tuple[str, ...]:
        """The ids a board_relation column points at — `display_value` holds their names."""
        ids = self.raw.get(self.board.column(alias), {}).get("linked_item_ids") or []
        return tuple(str(i) for i in ids)


SPRINT_BOARD = Board(
    name="Sprint bord, actief",
    id=757790388,
    columns={
        "status": "status_stories",
        "due_date": "date7",
        "owner": "person",  # "Trekker"
        "reviewer": "people",  # "Reviewer"
        "story_points": "numbers5",
        "story_syntax": "story_syntax",
        "epic": "link_to_stories__main2",  # board_relation to EPIC_BOARD
        "done_date": "date",  # when it actually moved to Done — the burndown x-axis
    },
)

# The archive the active board's tasks move to when a sprint closes. Same data,
# different column ids — do not reuse the active board's aliases against it.
DONE_BOARD = Board(
    name="Sprint bord, done",
    id=757790418,
    columns={
        "status": "status_stories1",
        "due_date": "date8",
        "owner": "person",  # "Trekker"
        "reviewer": "people",  # "Reviewer"
        "story_points": "numbers5",
        "story_syntax": "story_syntax",
        "epic": "link_to_stories__main",  # note: no trailing 2, unlike the active board
        "done_date": "date",
    },
)

EPIC_BOARD = Board(
    name="Epic",
    id=757753649,
    columns={
        "owner": "person",  # "Trekker"
        "owner_text": "text4",  # "Trekker_bup" — a plain-text stand-in, filled when `owner` is not
        "status": "status_stories_2",  # "Status epic"
        "priority": "color_mksqcf7n",  # "Priority"
        "portfolio": "board_relation_mm41w9ng",  # board_relation to PORTFOLIO_BOARD
        # Everything below is read by `project.py` only: the fields that fill an Obsidian
        # project note. The overview pages do not ask for them — see "Only request the
        # columns you need" in CLAUDE.md.
        "prj_nr": "pulse_id_mkrbpetp",  # "prj_nr" — auto-numbered `DPR-<n>`, see PROJECT_PREFIX
        "funnel": "color_mm1g9tq6",  # "Funnel" — Verkennen ... Beheren
        "method": "status4",  # "Methode" — Zelf / Uitbesteed / Cocreatie / ...
        "type": "status6",  # "Type" — Innovatie / Optimalisatie / Corvee / ...
        "estimate": "dropdown",  # "T-Estimation" — a T-shirt size
        "client": "dropdown_mkwcht3k",  # "Opdrachtgever"
        "experts": "opdrachtgever",  # "Domein experts" — note the id: it is *not* the client
        "why": "long_text",  # "Waarom willen we dit gebruiken?" — the user story
        "product": "long_text0",  # "Omschrijving product"
        "quality": "kwaliteits_impuls",  # "Kwaliteits impuls"
        "budget": "numbers9",  # "Geschat Budget"
        "submitted": "date3",  # "Date ingebracht"
        "planned_start": "date_mkqf44cs",  # "Geplande start datum"
        "started": "date40",  # "Date started working on it"
        "planned_end": "date4",  # "Geplande oplever datum"
        "finished": "date5",  # "Date finished"
        "due_date": "date",  # "Due date"
    },
)

# The IV portfolio. An epic linked to an item here is portfolio ("DAM") work; see DAM_* below.
# Its own "Portfolio" column says "IV portfolio" on all 177 items, so it is not read: the
# link from the epic board is the whole signal. The link *back* does not exist either —
# the board carries no connect column to the epics, so an item's epics are found by
# inverting `EPIC_BOARD`'s portfolio column.
PORTFOLIO_BOARD = Board(
    name="IV Portfolio",
    id=5097962810,
    columns={
        "goal": "text_mm5rpj62",  # "Doelstelling" — the programme it belongs to
        "urgency": "text_mm5rjvsf",  # "Urgentie" — Hoog / Middel / Laag, see PORTFOLIO_URGENCIES
        "type": "text_mm5rjs8m",  # "Type" — Initiatief or Project
        "lead": "text_mm5rdssg",  # "Projectleider"
        "start": "date_mm41tpw3",  # "Start Date"
        "end": "date_mm41mp1s",  # "Einddatum" — empty on every item today, shown when filled
        "link": "link_mm5r9d80",  # the item's page in Fortes, the portfolio tool of record
        "ref": "text_mm5rpjaw",  # its Fortes id
    },
)

BOARDS = {
    "sprint": SPRINT_BOARD,
    "done": DONE_BOARD,
    "epic": EPIC_BOARD,
    "portfolio": PORTFOLIO_BOARD,
}

# The two boards a sprint task can live on: still open, or archived as finished.
TASK_BOARDS = (SPRINT_BOARD, DONE_BOARD)

# Placeholder rows, not work: one group per board holds "Dummy User stories", whose
# estimates are epic-level guesses (1705 points on the active board alone). Counting
# them would swamp every real total, so every aggregate skips these groups.
DUMMY_GROUPS = {
    SPRINT_BOARD.id: {"new_group__1"},
    DONE_BOARD.id: {"group_mm3ypcwm"},
}

# Status column indexes on the sprint board. Filters compare against these, not the label text.
SPRINT_STATUS = {
    "Working on it": 0,
    "Done": 1,
    "Impediment": 2,
    "On hold": 3,
    "User story": 4,
    "Wacht op Antwoord": 6,
    "Wacht op review": 7,
    "Overleg": 8,
    "Gerefined": 9,
    "Vervallen": 10,
    "To Do": 16,
    "Wacht op taak": 19,
    "To Refine": 154,
}

# The statuses that mean "still on my plate".
OPEN_STATUSES = ["To Do", "Working on it", "Wacht op Antwoord", "Wacht op review"]

# Finished, and dropped. Dropped work is not burned down — it leaves the sprint total.
DONE_STATUS = "Done"
CANCELLED_STATUSES = ["Vervallen"]

# The board group holding this sprint's work. The id really is "backlog"; the title is not.
CURRENT_SPRINT_GROUP = "backlog"

# Status and Priority labels of the *epic* board, in the board's own display order, so
# sorting a column of them reads as a workflow rather than as an alphabet.
EPIC_STATUSES = [
    "To Refine",
    "Making ready",
    "To Do",
    "Working on it",
    "Done",
    "Onderhouden",
    "Ongoing",
    "On hold",
    "Impediment",
    "Opportunity",
    "Afgevallen",
    "Overgedragen",
    "Wachten op Epic",
]

# Epics that left the board's workflow without finishing. Hidden by default on the epics
# page — their batteries read as 100% because every open task was cancelled — behind a
# "show dropped" switch.
EPIC_DROPPED_STATUSES = ["Afgevallen", "Overgedragen"]

EPIC_PRIORITIES = ["Very High", "High", "Medium", "Low", "Very Low", "NNB"]

# The one label that means "blocked" on both the sprint boards and the epic board. An
# epic is stuck when it wears it, or when any of its tasks does; a portfolio item is
# stuck when any of its epics is.
IMPEDIMENT_STATUS = "Impediment"

# The IV Portfolio board's Urgentie labels, most urgent first — a free-text column, so
# this is the display order, not something the board enforces.
PORTFOLIO_URGENCIES = ["Hoog", "Middel", "Laag"]

# "DAM" is not a label anywhere: on the epic board it is the formula
# `IF({Portfolio#Count} > 0, TRUE(), FALSE())`, i.e. "is this epic linked to an item on
# the IV Portfolio board". We read the link itself rather than the formula, so the two
# filter values below mean exactly "has a portfolio link" and "has none".
DAM = "dam"
NON_DAM = "non-dam"

# People filters compare against "person-<user id>"; this is the one literal monday.com
# also accepts, and it resolves to whoever owns the API token.
ASSIGNED_TO_ME = "assigned_to_me"


def person_filter_value(person: str) -> str:
    """Turn a user id into the `person-<id>` form that `any_of` expects."""
    return person if person == ASSIGNED_TO_ME else f"person-{person}"


def item_url(board: Board, item_id: str) -> str:
    """Where an item lives in the monday.com UI, so a table row can link out to it.

    Built rather than read: `ItemType.url` exists, but asking for it on the board-wide
    task reads would carry the field over thousands of rows to serve a handful of links.
    """
    return f"https://{ACCOUNT_SLUG}.monday.com/boards/{board.id}/pulses/{item_id}"


# A sprint runs three weeks, inclusive of both endpoints.
SPRINT_LENGTH_WEEKS = 3

# Obsidian task rendering.
MINUTES_PER_STORY_POINT = 120
TASK_TAG = "#sprint"

# --- Obsidian project notes (`monday project`) ------------------------------------

# The epic board's `prj_nr` column is an auto-numbered custom key: prefix "DPR",
# minimum two digits. Its text is what a filter compares against, so a reference typed
# as bare digits is padded back into this shape before it is looked up.
PROJECT_PREFIX = "DPR"
PROJECT_NUMBER_PADDING = 2

# How many digits a bare number may have before it is read as an item id rather than a
# project number. `prj_nr` counts in the hundreds; a monday.com item id is ten digits.
PROJECT_NUMBER_MAX_DIGITS = 4

# Where the notes live. The vault's own folder, overridable for a different machine.
OBSIDIAN_PROJECTS_DIR = os.environ.get(
    "OBSIDIAN_PROJECTS_DIR",
    "~/Braincave/d5 WDODelta/40-49 Taken en ideeën/43 Projecten 2023-2026",
)

# The epic board's 13 statuses mapped onto the six the vault's `projectstatus` field
# actually uses. The two vocabularies are not the same size and never will be: the board
# tracks a sprint workflow, the note tracks whether a project is running.
PROJECT_STATUSES = {
    "To Refine": "verkenning",
    "Making ready": "verkenning",
    "Opportunity": "verkenning",
    "To Do": "backlog",
    "Working on it": "loopt",
    "Ongoing": "loopt",
    "Onderhouden": "loopt",
    "On hold": "pauze",
    "Impediment": "pauze",
    "Wachten op Epic": "pauze",
    "Done": "afgerond",
    "Afgevallen": "afgevallen",
    "Overgedragen": "afgevallen",
}
