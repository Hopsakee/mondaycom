"""Aligning the kwartaalplanbord with monday.com — a temporary tool.

The team planned Q4 on the Kwartaalplanbord (`docs/tmp/Kwartaalplanbord.html`), whose
database dump is `kwartaalplanbord_database_compleet.json`: epics with a DPR number and
stories with points per discipline. monday.com holds the same epics with their own
STP-TODO and a split over the four disciplines on Epics-STP-distribution. This module
puts the two side by side, so the differences can be talked through and decided on.

- **Linked on the DPR number** — the board's `dpr`, the epic board's `prj_nr`. Nothing
  is matched by name. A link can be changed by hand (`State.links`), which is how a JSON
  epic with no or the wrong DPR gets a home.
- **The disciplines map** `mod`→DE, `vis`→DB, `ds`→DS, `ia`→PO/AT (`DISCIPLINE_KEYS`;
  the board's own legend calls `vis` "Vis", `mod` "DE" and `ia` "AT").
- **A split is the board's points per discipline**, as whole percentages that add up to
  exactly 100 (`split_from`, largest remainder): 1 DE + 2 DB is 33/67/0/0. A DPR on
  several JSON epics takes the points of all of them.
- **The comparison is against STP-TODO**, the number the Planning page plans with. A
  row is marked when the two differ by more than 10% of monday.com's figure
  (`DIFF_THRESHOLD`), or when monday.com has nothing and the board has something.
- **Decisions and actions live in one JSON file** next to the dump (`State`), never on
  monday.com: what total we want, where to change it, why, and who has to find out what.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime
from functools import cached_property
from pathlib import Path
from typing import Any

from mondaycom import burndown as bd
from mondaycom import epics, lookups, planning, queries
from mondaycom.client import MondayClient
from mondaycom.config import (
    DISCIPLINES,
    DISTRIBUTION_BOARD,
    as_date,
    keeps_dam,
)
from mondaycom.lookups import Choice

#: The kwartaalplanbord's discipline keys, as the distribution board names them.
DISCIPLINE_KEYS = {"mod": "DE", "vis": "DB", "ds": "DS", "ia": "PO/AT"}

#: The disciplines in a narrow column: the board's own "AT" for PO/AT.
SHORT = {d: d for d in DISCIPLINES} | {"PO/AT": "AT"}

#: More than this fraction of monday.com's STP apart, and a row is marked.
DIFF_THRESHOLD = 0.10

#: Where a decided total has to be made true — deduced from it by `where`, never chosen.
WHERE = {
    "monday": "monday.com aanpassen",
    "database": "database aanpassen",
    "beide": "beide aanpassen",
    "geen": "niets aanpassen",
}

#: An action's life: written down, sent to the person, done.
ACTION_STATES = ("open", "verstuurd", "klaar")

REPO = Path(__file__).resolve().parents[2]
DEFAULT_BOARD = REPO / "docs" / "tmp" / "kwartaalplanbord_database_compleet.json"


def board_path() -> Path:
    """The kwartaalplanbord dump. `ALIGN_BOARD` overrides it; `monday align-web --board` sets that."""
    return Path(os.environ.get("ALIGN_BOARD") or DEFAULT_BOARD)


def state_path() -> Path:
    """The decisions file, next to the dump unless `ALIGN_STATE` says otherwise."""
    return Path(os.environ.get("ALIGN_STATE") or board_path().with_name("afstemming.json"))


# --- the kwartaalplanbord ---------------------------------------------------------------


@dataclass(frozen=True)
class BoardEpic:
    """One epic on the kwartaalplanbord, with its stories' points per discipline."""

    id: str
    name: str
    dpr: str = ""
    portfolio: str = ""
    prio: int | None = None
    #: "Afhankelijkheid" — who or what the epic depends on, in the planners' words.
    afh: str = ""
    points: dict[str, float] = field(default_factory=dict)

    @property
    def total(self) -> float:
        return sum(self.points.values())

    @property
    def is_dam(self) -> bool:
        """The board's own word for it: a portfolio name is DAM, "Niet DAM" or none is not."""
        return self.portfolio.strip().lower() not in ("", NOT_DAM)


#: The kwartaalplanbord's portfolio for the epics outside the IV Portfolio, lowercased.
NOT_DAM = "niet dam"


@dataclass(frozen=True)
class Kwartaalbord:
    epics: list[BoardEpic]
    #: The planners' names for the team, for the action's person field.
    people: list[str]
    #: The last day of the board's last sprint.
    last_day: date | None = None

    @property
    def quarter_end(self) -> date:
        """The quarter the board plans — the one its last sprint ends in."""
        return planning.quarter_end(self.last_day or date.today())


def parse_board(data: dict[str, Any]) -> Kwartaalbord:
    """The dump's `config.main.epics` and `stories`, folded into points per epic."""
    main = data.get("config", {}).get("main", {})
    points: dict[str, dict[str, float]] = {}
    for story in (data.get("stories") or {}).values():
        tally = points.setdefault(story.get("epicId") or "", {})
        for key, value in (story.get("pts") or {}).items():
            discipline = DISCIPLINE_KEYS.get(key)
            if discipline is None:
                raise ValueError(f"The board has a discipline {key!r} this tool does not map: {story}")
            tally[discipline] = tally.get(discipline, 0.0) + float(value or 0)
    found = [
        BoardEpic(
            id=e["id"],
            name=(e.get("name") or "").strip(),
            dpr=(e.get("dpr") or "").strip().upper(),
            portfolio=e.get("portfolio") or "",
            prio=e.get("prio"),
            afh=e.get("afh") or "",
            points={d: v for d, v in points.get(e["id"], {}).items() if v},
        )
        for e in main.get("epics") or []
    ]
    ends = [d for s in main.get("sprints") or [] if (d := as_date(s.get("end") or ""))]
    people = sorted(p.get("name") or key for key, p in (data.get("people") or {}).items())
    return Kwartaalbord(epics=found, people=people, last_day=max(ends) if ends else None)


def load_board(path: Path | None = None) -> Kwartaalbord:
    return parse_board(json.loads((path or board_path()).read_text(encoding="utf-8")))


def split_from(points: dict[str, float]) -> dict[str, int]:
    """Points per discipline as whole percentages adding up to exactly 100.

    Largest remainder: everyone gets the floor of their share, and what is left goes to
    the biggest fractions. ``{"DE": 1, "DB": 2}`` is 33/67/0/0. No points, no split.
    """
    total = sum(points.get(d, 0.0) for d in DISCIPLINES)
    if total <= 0:
        return {}
    exact = {d: points.get(d, 0.0) * 100 / total for d in DISCIPLINES}
    split = {d: int(v) for d, v in exact.items()}
    left = 100 - sum(split.values())
    for d in sorted(DISCIPLINES, key=lambda d: (-(exact[d] - split[d]), DISCIPLINES.index(d)))[:left]:
        split[d] += 1
    return split


# --- monday.com -------------------------------------------------------------------------


@dataclass(frozen=True)
class MondayEpic:
    """An epic on monday.com: the Planning page's own `PlanEpic`, its planning row, its points."""

    plan: planning.PlanEpic
    split: planning.Split | None = None
    #: Done / open on the two sprint boards — context for why STP-TODO says what it says.
    points: epics.Points = field(default_factory=epics.Points)

    @property
    def id(self) -> str:
        return self.plan.id

    @property
    def name(self) -> str:
        return self.plan.name

    @property
    def prj_nr(self) -> str:
        return self.plan.prj_nr.upper()

    @property
    def group_title(self) -> str:
        return self.plan.group_title

    @property
    def url(self) -> str:
        return self.plan.url

    @property
    def todo(self) -> float:
        return self.split.todo if self.split else 0.0


@dataclass
class Monday:
    """Everything the alignment reads from monday.com."""

    epics: list[MondayEpic]
    people: list[Choice]
    #: The end of the sprint running now, as the Sprint and Planning pages guess it.
    current_end: date | None = None

    def by_prj_nr(self) -> dict[str, MondayEpic]:
        return {e.prj_nr: e for e in self.epics if e.prj_nr}

    def with_split(self, split: planning.Split) -> None:
        """Swap in a split just written, so the page shows it without a re-read."""
        self.epics = [replace(e, split=split) if e.split and e.split.id == split.id else e for e in self.epics]


def fetch_monday(client: MondayClient, with_points: bool = True) -> Monday:
    """The Planning page's read, plus the people and — for the web app — the sprint boards' points.

    The sprint boards are the slow part (~19s) and only feed the "open · klaar" context, so
    `align-splits` skips them. The three reads are independent and run side by side.
    """
    with ThreadPoolExecutor(max_workers=3) as pool:
        snapshot_read = pool.submit(planning.fetch, client)
        people_read = pool.submit(lookups.fetch_people, client)
        points_read = pool.submit(epics.fetch_epics, client) if with_points else None
        snapshot = snapshot_read.result()
        points = {e.id: e.points for e in points_read.result()[0]} if points_read else {}
        people = people_read.result()
    splits = {s.epic_id: s for s in snapshot.splits if s.epic_id}
    found = [MondayEpic(e, splits.get(e.id), points.get(e.id, epics.Points())) for e in snapshot.epics]
    return Monday(epics=found, people=people, current_end=snapshot.current_end)


def write_shares(client: MondayClient, item_id: str, shares: dict[str, str]) -> None:
    """Set a distribution row's percentages, as the text each column takes (`""` is blank)."""
    values = json.dumps({DISTRIBUTION_BOARD.column(d): v for d, v in shares.items()})
    client.execute(queries.CHANGE_COLUMNS, {"board": str(DISTRIBUTION_BOARD.id), "item": item_id, "values": values})


def write_split(client: MondayClient, split: planning.Split, shares: dict[str, int]) -> planning.Split:
    """Set one distribution row's four percentages, and return the row as it now is."""
    write_shares(client, split.id, {d: str(shares.get(d, 0)) for d in DISCIPLINES})
    return replace(split, shares={d: float(shares.get(d, 0)) for d in DISCIPLINES})


# --- decisions and actions --------------------------------------------------------------


@dataclass
class Decision:
    """What we agreed for one row: the total we want, and its definition of done."""

    wanted: float | None = None
    note: str = ""


@dataclass
class Action:
    """Something someone has to find out or do before a row can be decided."""

    id: str
    key: str
    text: str
    who: str = ""
    status: str = "open"
    created: str = ""
    sent: str = ""
    done: str = ""


ACTION_FIELDS = frozenset(Action.__dataclass_fields__)

#: The formats a copy can be saved in, with the extension each gets.
FORMATS = {"xlsx": "Excel (.xlsx)", "ods": "LibreOffice Calc (.ods)", "csv": "CSV (.csv)", "json": "JSON (.json)"}

#: How often autosave may write, in minutes. Five is the default: often enough that a
#: closed laptop loses little, rarely enough that the file is not rewritten per keystroke.
AUTOSAVE_MINUTES = (1, 5, 15, 30)


@dataclass
class Saving:
    """Where the user keeps their own copy, and how far it is behind.

    The decisions file itself sits in `docs/tmp`, which git ignores — right for a public
    repository, but it is backed up nowhere. This is the copy that is.
    """

    folder: str = ""
    format: str = "xlsx"
    autosave: bool = False
    minutes: int = 5
    #: When the copy was last written, where to, and the fingerprint it was written at.
    saved_at: str = ""
    saved_to: str = ""
    saved_print: str = ""
    error: str = ""


@dataclass
class State:
    """The decisions file. Saved whole on every change — it is one person's handful of rows."""

    decisions: dict[str, Decision] = field(default_factory=dict)
    #: A JSON epic's DPR, by its board id, where it differs from the dump. `""` is "no link".
    links: dict[str, str] = field(default_factory=dict)
    actions: list[Action] = field(default_factory=list)
    saving: Saving = field(default_factory=Saving)
    path: Path | None = None

    def content(self) -> dict[str, Any]:
        """What the user decided — everything but where their copy goes."""
        return {
            "decisions": {k: asdict(v) for k, v in sorted(self.decisions.items()) if v != Decision()},
            "links": dict(sorted(self.links.items())),
            "actions": [asdict(a) for a in self.actions],
        }

    @property
    def fingerprint(self) -> str:
        """A hash of `content`: two states with the same decisions have the same one."""
        text = json.dumps(self.content(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    @property
    def unsaved(self) -> bool:
        """Changed since the last copy was saved — or never saved, once there is anything to save."""
        if not self.saving.saved_print:
            return self.content() != State().content()
        return self.saving.saved_print != self.fingerprint

    @classmethod
    def load(cls, path: Path | None = None) -> State:
        path = path or state_path()
        if not path.exists():
            return cls(path=path)
        data = json.loads(path.read_text(encoding="utf-8"))
        state = cls.from_content(data)
        state.saving = Saving(**(data.get("saving") or {}))
        state.path = path
        return state

    @classmethod
    def from_content(cls, data: dict[str, Any]) -> State:
        """The decisions, links and actions of a state file — or of a JSON copy, which holds them too."""
        return cls(
            # `where` was once chosen by hand; it is deduced now, so an old file's is dropped.
            decisions={
                k: Decision(wanted=v.get("wanted"), note=v.get("note", ""))
                for k, v in (data.get("decisions") or {}).items()
            },
            links={str(k): str(v) for k, v in (data.get("links") or {}).items()},
            actions=[Action(**{k: v for k, v in a.items() if k in ACTION_FIELDS}) for a in data.get("actions") or []],
        )

    def backup(self) -> Path | None:
        """Write what the user decided to a file of its own, next to the state file, before it is replaced."""
        if self.path is None:
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.path.with_name(f"{self.path.stem}_voor-laden_{stamp}.json")
        target.write_text(json.dumps(self.content(), indent=2, ensure_ascii=False), encoding="utf-8")
        return target

    def save(self) -> None:
        if self.path is None:
            return
        data = {**self.content(), "saving": asdict(self.saving)}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def decision(self, key: str) -> Decision:
        return self.decisions.get(key) or Decision()

    def link(self, epic: BoardEpic) -> str:
        return self.links.get(epic.id, epic.dpr)

    def add_action(self, key: str, text: str, who: str = "") -> Action:
        action = Action(id=uuid.uuid4().hex[:10], key=key, text=text.strip(), who=who.strip(), created=_now())
        self.actions.append(action)
        return action

    def set_status(self, action_id: str, status: str) -> Action | None:
        if status not in ACTION_STATES:
            raise ValueError(f"Unknown action status {status!r}")
        for action in self.actions:
            if action.id == action_id:
                action.status = status
                if status == "verstuurd" and not action.sent:
                    action.sent = _now()
                if status == "klaar":
                    action.done = _now()
                return action
        return None

    def actions_for(self, key: str) -> list[Action]:
        return [a for a in self.actions if a.key == key]


def _now() -> str:
    return datetime.now().isoformat(timespec="minutes")


#: One lock for every read-modify-write of the state file: the web app's handlers run
#: on worker threads.
STATE_LOCK = threading.Lock()


@contextmanager
def editing(path: Path | None = None) -> Iterator[State]:
    """Load the state, let the caller change it, save it — all under `STATE_LOCK`."""
    with STATE_LOCK:
        state = State.load(path)
        yield state
        state.save()


# --- the comparison ---------------------------------------------------------------------

BOTH = "beide"
BOARD_ONLY = "database"
MONDAY_ONLY = "monday"

#: The three kinds of row, in the page's and the copy's words.
KINDS_NL = {BOTH: "Op beide", BOARD_ONLY: "Alleen in de database", MONDAY_ONLY: "Alleen op monday.com"}


@dataclass(frozen=True)
class Row:
    """One line of the comparison: an epic as monday.com and the board each see it.

    Frozen, so the derived figures are worked out once per row (`cached_property`) however
    many cells and checks read them.
    """

    key: str
    dpr: str
    monday: MondayEpic | None = None
    board: tuple[BoardEpic, ...] = ()
    #: The monday.com epic's planning layer for the quarter; empty when it is not planned.
    layer: str = ""
    #: Whether the selection (layers, DAM, "Dit kwartaal") takes this row in.
    selected: bool = True

    @property
    def kind(self) -> str:
        if self.monday and self.board:
            return BOTH
        return BOARD_ONLY if self.board else MONDAY_ONLY

    @property
    def name(self) -> str:
        return self.monday.name if self.monday else " + ".join(e.name for e in self.board)

    @property
    def title(self) -> str:
        """`DPR-227 FIR 1a. …` — the row as a message or a list names it."""
        return f"{self.dpr} {self.name}".strip()

    @cached_property
    def board_points(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for e in self.board:
            for d, v in e.points.items():
                out[d] = out.get(d, 0.0) + v
        return out

    @cached_property
    def board_total(self) -> float:
        return sum(e.total for e in self.board)

    @property
    def monday_total(self) -> float | None:
        return self.monday.todo if self.monday else None

    @cached_property
    def diff(self) -> float | None:
        """Board minus monday.com; `None` when one side is missing."""
        if self.monday is None or not self.board:
            return None
        return self.board_total - self.monday.todo

    @cached_property
    def ratio(self) -> float | None:
        """The difference as a fraction of monday.com's STP; infinite when that is 0."""
        if self.diff is None or self.monday is None:
            return None
        if self.monday.todo == 0:
            return 0.0 if self.diff == 0 else float("inf")
        return self.diff / self.monday.todo

    @property
    def flagged(self) -> bool:
        """More than 10% apart, measured against monday.com."""
        return self.ratio is not None and abs(self.ratio) > DIFF_THRESHOLD

    @cached_property
    def board_split(self) -> dict[str, int]:
        return split_from(self.board_points)

    @cached_property
    def monday_split(self) -> dict[str, float | None]:
        split = self.monday.split if self.monday else None
        return dict(split.shares) if split else {}

    def monday_share(self, discipline: str) -> float:
        """monday.com's STP for one discipline: STP-TODO × its percentage."""
        split = self.monday.split if self.monday else None
        return split.share(discipline) if split else 0.0

    @property
    def split_differs(self) -> bool:
        """The board has a split, monday.com has a row for it, and they do not agree."""
        target, current = self.board_split, self.monday_split
        if not target or not self.monday or not self.monday.split:
            return False
        return any(abs((current.get(d) or 0.0) - target[d]) > planning.SPLIT_TOLERANCE for d in DISCIPLINES)

    @property
    def warnings(self) -> list[str]:
        """What is odd about the link itself, in Dutch — shown under the name."""
        out = []
        if len(self.board) > 1:
            out.append(f"{self.dpr} staat op {len(self.board)} epics in de database; hun punten zijn opgeteld.")
        if self.kind == BOARD_ONLY:
            out.append(
                f"{self.dpr} staat in de database maar niet op monday.com."
                if self.dpr
                else "Geen DPR-nummer in de database: koppel deze epic aan een DPR."
            )
        if self.monday and self.board and not self.monday.split:
            out.append("Geen rij op Epics-STP-distribution voor deze epic.")
        return out


@dataclass(frozen=True)
class Selection:
    """The Planning page's selection: the quarter end, the layers, the DAM half, "Dit kwartaal".

    A monday.com epic is in it exactly when the Planning page would plan it
    (`PlanEpic.selected`). A board epic linked to nothing has no layer and no due date —
    the board *is* the quarter's plan — so only the DAM filter applies to it, on the
    board's own portfolio name.
    """

    quarter_end: date
    layers: tuple[str, ...] = (planning.PROMISED,)
    dam: str = ""
    this_quarter: bool = False

    def takes(self, epic: MondayEpic) -> bool:
        return bool(epic.plan.selected(self.quarter_end, self.layers, self.dam, self.this_quarter))

    def takes_board(self, epic: BoardEpic) -> bool:
        return keeps_dam(self.dam, epic.is_dam)


def compare(board: Kwartaalbord, monday: Monday, state: State, selection: Selection | None = None) -> list[Row]:
    """Every row: linked epics first, then the board's unlinked ones, then monday.com's own.

    Linked rows are always returned, marked `selected` or not, so a row the board plans and
    the selection leaves out can still be shown. monday.com's own are the selected epics
    with STP-TODO left that no board epic links to — the work only one side planned. The
    default selection is the Planning page's default: Promised, for the board's quarter.
    """
    selection = selection or Selection(board.quarter_end)
    end = selection.quarter_end
    by_nr = monday.by_prj_nr()
    linked: dict[str, list[BoardEpic]] = {}
    loose: list[Row] = []
    for e in board.epics:
        dpr = state.link(e).strip().upper()
        if dpr in by_nr:
            linked.setdefault(dpr, []).append(e)
        else:
            loose.append(Row(key=f"db:{e.id}", dpr=dpr, board=(e,), selected=selection.takes_board(e)))
    rows = []
    for dpr, found in sorted(linked.items()):
        m = by_nr[dpr]
        rows.append(
            Row(key=dpr, dpr=dpr, monday=m, board=tuple(found), layer=m.plan.layer(end), selected=selection.takes(m))
        )
    own = [
        Row(key=e.prj_nr or f"mon:{e.id}", dpr=e.prj_nr, monday=e, layer=e.plan.layer(end))
        for e in monday.epics
        if e.todo > 0 and e.prj_nr not in linked and selection.takes(e)
    ]
    return rows + loose + sorted(own, key=lambda r: r.dpr)


def split_changes(rows: list[Row]) -> list[Row]:
    """Every row whose distribution split differs from the board's."""
    return [r for r in rows if r.split_differs]


def apply_splits(client: MondayClient, rows: list[Row], backup: Path) -> list[planning.Split]:
    """Write the board's splits to monday.com, after saving the old ones to `backup`.

    The backup is written first and in full, so an interrupted run can still be undone
    with `restore_splits`.
    """
    targets = [(r, r.monday.split) for r in rows if r.monday and r.monday.split]
    old = {split.id: {"dpr": r.dpr, "name": r.name, "shares": r.monday_split} for r, split in targets}
    backup.write_text(json.dumps(old, indent=2, ensure_ascii=False), encoding="utf-8")
    return [write_split(client, split, r.board_split) for r, split in targets]


def restore_splits(client: MondayClient, backup: Path) -> int:
    """Put back the percentages a backup holds. A blank share goes back as blank."""
    old = json.loads(backup.read_text(encoding="utf-8"))
    for item_id, row in old.items():
        write_shares(client, item_id, {d: "" if v is None else f"{v:g}" for d, v in row["shares"].items()})
    return len(old)


def backup_file() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return board_path().parent / f"verdeling_backup_{stamp}.json"


# --- words ------------------------------------------------------------------------------


def fmt(points: float | None) -> str:
    """`burndown.fmt` to one decimal, and `—` for a side that has no figure."""
    return "—" if points is None else bd.fmt(round(points, 1))


def split_text(split: dict[str, Any]) -> str:
    """``35/30/25/10`` in DE/DB/DS/PO-AT order; `—` for a blank share."""
    if not split:
        return "—"
    return "/".join("—" if split.get(d) is None else fmt(float(split[d])) for d in DISCIPLINES)


def where(row: Row, decision: Decision) -> str:
    """Where the wanted total has to be made true: whichever side does not hold it yet.
    A side the row does not have needs no change. `""` while nothing is decided."""
    wanted = decision.wanted
    if wanted is None:
        return ""
    monday = row.monday is not None and abs(wanted - row.monday.todo) > 1e-9
    board = bool(row.board) and abs(wanted - row.board_total) > 1e-9
    if monday and board:
        return "beide"
    return "monday" if monday else "database" if board else "geen"


def message(who: str, actions: list[Action], rows: dict[str, Row], state: State, sender: str) -> str:
    """The note to send someone their open actions, with each row's figures and explanation."""
    first = who.split()[0] if who.strip() else ""
    lines = [
        f"Hoi {first}," if first else "Hoi,",
        "",
        "We leggen de kwartaalplanning (het kwartaalplanbord) naast monday.com en hebben daarbij iets van je nodig:",
        "",
    ]
    for a in actions:
        row = rows.get(a.key)
        lines.append(f"• {row.title if row else a.key}")
        lines.append(f"  Actie: {a.text}")
        if row:
            lines.append(f"  Kwartaalplanbord {fmt(row.board_total)} STP · monday.com {fmt(row.monday_total)} STP")
            if row.monday:
                lines.append(f"  {row.monday.url}")
        note = state.decision(a.key).note
        if note:
            lines.append(f"  Definition of Done: {note}")
        lines.append("")
    lines += ["Alvast bedankt!", sender.split()[0] if sender else ""]
    return "\n".join(lines).rstrip() + "\n"


def export_markdown(rows: list[Row], state: State) -> str:
    """Every decided or discussed row and every action, as a markdown note."""
    out = [f"# Afstemming kwartaalplanbord ↔ monday.com ({date.today().isoformat()})", ""]
    out += [
        "| DPR | Epic | Database | monday.com | Gewenst | Waar | Definition of Done |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        d = state.decision(r.key)
        if d == Decision() and not state.actions_for(r.key):
            continue
        note = d.note.replace("\n", " ").replace("|", "\\|")
        out.append(
            f"| {r.dpr} | {r.name} | {fmt(r.board_total if r.board else None)} | {fmt(r.monday_total)} "
            f"| {fmt(d.wanted)} | {WHERE.get(where(r, d), '')} | {note} |"
        )
    out += ["", "## Acties", ""]
    names = {r.key: r.title for r in rows}
    for a in sorted(state.actions, key=lambda a: (a.status == "klaar", a.who, a.created)):
        box = "x" if a.status == "klaar" else " "
        out.append(f"- [{box}] **{a.who or 'niemand'}** — {a.text} ({names.get(a.key, a.key)}; {a.status})")
    return "\n".join(out) + "\n"
