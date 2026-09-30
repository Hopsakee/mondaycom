"""One epic, turned into an Obsidian project note.

`monday project DPR-223` looks an epic up on the epic board and writes the vault's
project template with everything the board already knows filled in — codes, dates,
who is involved, and the epic's own metadata — so the note starts where monday.com
stops rather than as an empty form.

The template it renders is `docs/Project.md`, read as it stands — it is the only copy,
so an edit there changes the next note without a Python edit. It is a Templater
template: its `<% tp.* %>` calls are evaluated by Obsidian when *it* creates a note. We
create the file ourselves, so they are resolved here instead — the creation stamp is
now, and the `tp.file.move` line is replaced by writing into the projects folder. The
`&=choice(...)` inline expressions are Dataview, evaluated when the note is *read*, and
are copied through untouched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any

from mondaycom import queries
from mondaycom.client import MondayClient
from mondaycom.config import (
    EPIC_BOARD,
    ME,
    OBSIDIAN_PROJECTS_DIR,
    PROJECT_NUMBER_MAX_DIGITS,
    PROJECT_NUMBER_PADDING,
    PROJECT_PREFIX,
    PROJECT_STATUSES,
    Board,
    item_url,
)

#: A reference typed as the project number, with or without its prefix: `DPR-223`,
#: `dpr223`, `223`. The digits are what gets looked up.
PROJECT_REF = re.compile(rf"^{PROJECT_PREFIX}[-\s_]?(\d+)$", re.IGNORECASE)

#: Characters Windows, Linux or Obsidian will not take in a file name. `#`, `^` and the
#: brackets are Obsidian's: they are link syntax, so a note carrying them cannot be
#: `[[linked]]` by name.
ILLEGAL_IN_FILENAME = re.compile(r'[<>:"/\\|?*\[\]#^]+')

#: One Templater tag, `<% … %>`.
TEMPLATER_TAG = re.compile(r"<%\s*(.*?)\s*%>")

#: A `**Label:** value` line — the Betrokken and Locaties blocks are made of them.
LABEL_LINE = re.compile(r"^\*\*(.+?):\*\*")

#: The template's headings the board's values go under.
PURPOSE_HEADING = "# Doel en toelichting"
META_HEADING = "# Project meta data"


class NotFound(ValueError):
    """No epic on the board carries the reference that was asked for."""


@dataclass(frozen=True)
class Reference:
    """What the user typed, resolved to the one column it addresses.

    `kind` is `"prj_nr"` for a project number and `"item_id"` for a monday.com item id;
    they take different queries, because only the first needs the board searched.
    """

    kind: str
    value: str

    def __str__(self) -> str:
        return self.value


def parse_reference(raw: str) -> Reference:
    """Read `DPR-223`, `223` or `2617136005` as the thing it identifies.

    Bare digits are ambiguous by shape alone, so length decides: `prj_nr` counts in the
    hundreds and a monday.com item id is ten digits, which is the gap
    `config.PROJECT_NUMBER_MAX_DIGITS` sits in. A number is padded back to the column's
    own width (`DPR-07`, not `DPR-7`), because the filter compares against the text the
    column displays.
    """
    text = raw.strip()
    if not text:
        raise ValueError("give a project number (DPR-223 or 223) or a monday.com item id")

    if match := PROJECT_REF.match(text):
        return Reference("prj_nr", project_number(match.group(1)))

    if not text.isdigit():
        raise ValueError(
            f"{raw!r} is not a reference: expected {PROJECT_PREFIX}-<number>, a bare number, or a monday.com item id"
        )

    if len(text) <= PROJECT_NUMBER_MAX_DIGITS:
        return Reference("prj_nr", project_number(text))
    return Reference("item_id", text)


def project_number(digits: str) -> str:
    """`7` → `DPR-07` — the number as the `prj_nr` column spells it."""
    return f"{PROJECT_PREFIX}-{digits.lstrip('0').zfill(PROJECT_NUMBER_PADDING)}"


@dataclass(frozen=True)
class Project:
    """An epic, with its columns keyed by the aliases in `config.EPIC_BOARD`."""

    id: str
    name: str
    fields: dict[str, str] = field(default_factory=dict)
    board: Board = EPIC_BOARD

    def get(self, alias: str) -> str:
        """The column's text, or `""` when it is empty — every field here is optional."""
        return self.fields.get(alias, "").strip()

    @property
    def prj_nr(self) -> str:
        return self.get("prj_nr")

    @property
    def url(self) -> str:
        return item_url(self.board, self.id)

    @property
    def trekker(self) -> str:
        """Whoever carries the epic. `Trekker_bup` is the text stand-in for the people column."""
        return self.get("owner") or self.get("owner_text")

    @property
    def status(self) -> str:
        """The vault's `projectstatus`, mapped from the board's own label.

        An unknown label maps to nothing rather than to a guess: `projectstatus` drives
        the note's status line, and a word the vault does not use reads as a typo.
        """
        return PROJECT_STATUSES.get(self.get("status"), "")

    @property
    def role(self) -> str:
        """`trekker` when the epic is Jelle's, blank otherwise.

        The board knows who pulls the epic; it does not know what Jelle's part in it is
        when that is somebody else, so the note asks rather than guesses.
        """
        return "trekker" if ME.lower() in self.trekker.lower() else ""

    @property
    def start(self) -> str:
        """The planned start, else when work actually began, else when it was submitted."""
        return self.get("planned_start") or self.get("started") or self.get("submitted")

    @property
    def end(self) -> str:
        """The planned delivery date, else the deadline, else when it finished."""
        return self.get("planned_end") or self.get("due_date") or self.get("finished")


def _columns(item: dict[str, Any], board: Board) -> dict[str, str]:
    """Turn the item's `column_values` into `{alias: text}`.

    A board_relation answers in `display_value` and leaves `text` null — the epic
    board's Portfolio column is one, so reading `text` alone loses it.
    """
    cells = board.cells(item)
    return {alias: cells.text(alias) for alias in board.columns}


def fetch(client: MondayClient, ref: Reference, board: Board = EPIC_BOARD) -> Project:
    """Read the one epic `ref` names. Raises `NotFound` when the board has no such item."""
    if ref.kind == "item_id":
        items = client.execute(queries.epic_by_id(ref.value, board)).get("items") or []
    else:
        data = client.execute(queries.epic_by_project_number(ref.value, board))
        boards = data.get("boards") or []
        items = boards[0]["items_page"]["items"] if boards else []

    if not items:
        raise NotFound(f"no epic on the {board.name} board has {ref.kind} {ref.value}")
    item = items[0]
    return Project(id=str(item["id"]), name=item["name"], fields=_columns(item, board), board=board)


def note_filename(project: Project) -> str:
    """`<Item>_<prj_nr>.md`, with what a file system or Obsidian would choke on removed.

    An epic with no project number falls back to its item id — the name still has to end
    in something that tells two notes apart.
    """
    suffix = project.prj_nr or project.id
    stem = f"{_safe(project.name)}_{_safe(suffix)}"
    return f"{stem}.md"


def _safe(text: str) -> str:
    """A file-name-safe version of `text`: illegal characters out, whitespace collapsed."""
    cleaned = ILLEGAL_IN_FILENAME.sub(" ", text)
    return re.sub(r"\s+", " ", cleaned).strip(" .")


def template_text() -> str:
    """The vault's project template, `docs/Project.md`.

    A wheel carries it as package data (pyproject's `force-include`); a checkout, where
    `uv sync` installs the package in place, reads it straight out of `docs/`.
    """
    packaged = resources.files("mondaycom") / "Project.md"
    if packaged.is_file():
        return packaged.read_text(encoding="utf-8")
    return (Path(__file__).resolve().parents[2] / "docs" / "Project.md").read_text(encoding="utf-8")


def _resolve_templater(template: str, stamp: str) -> list[str]:
    """The template's lines with every `<% … %>` resolved the way Templater would.

    A quoted literal is itself, `tp.file.creation_date()` is `stamp`, and a line that
    only moved the file disappears — we write into the projects folder instead. Any
    other call raises: a `<%` left in the note would be written out as text.
    """

    def resolve(match: re.Match[str]) -> str:
        expr = match.group(1)
        if literal := re.fullmatch(r'"([^"]*)"|\'([^\']*)\'', expr):
            return literal.group(1) or literal.group(2) or ""
        if expr.startswith("tp.file.creation_date("):
            return stamp
        if re.match(r"(await\s+)?tp\.file\.move\(", expr):
            return ""
        raise ValueError(f"the project template uses a Templater call project.py cannot resolve: <% {expr} %>")

    lines = []
    for line in template.splitlines():
        resolved, tags = TEMPLATER_TAG.subn(resolve, line)
        if resolved.strip() or not tags:
            lines.append(resolved)
    return lines


def _fill_frontmatter(lines: list[str], values: dict[str, str | list[str]]) -> list[str]:
    """Set each key of `values` in the frontmatter; keys the template lacks go last.

    A list becomes a YAML list under its key, and a filled key replaces whatever the
    template had nested under it.
    """

    def entry(key: str, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return [f"{key}:", *(f"  - {v}" for v in value)]
        return [f"{key}: {value}"]

    if lines[:1] != ["---"] or "---" not in lines[1:]:
        raise ValueError("the project template has no frontmatter to fill")
    close = lines.index("---", 1)
    head: list[str] = []
    missing, filled = dict(values), False
    for line in lines[1:close]:
        key = line.split(":", 1)[0]
        if ":" in line and key in missing:
            head.extend(entry(key, missing.pop(key)))
            filled = True
        elif not (filled and line[:1].isspace()):
            # An indented line belongs to the key above it; a filled key replaces it too.
            head.append(line)
            filled = False
    for key, value in missing.items():
        head.extend(entry(key, value))
    return ["---", *head, *lines[close:]]


def _section_end(lines: list[str], heading: str) -> int:
    """Where the section under `heading` ends: before the next heading of its level,
    and before the blank lines leading up to it. The end of the note if it is missing."""
    level = heading.split(" ", 1)[0] + " "
    try:
        start = lines.index(heading) + 1
    except ValueError:
        return len(lines)
    end = next((i for i in range(start, len(lines)) if lines[i].startswith(level)), len(lines))
    while end > start and not lines[end - 1].strip():
        end -= 1
    return end


def _fill_labels(lines: list[str], values: dict[str, str]) -> list[str]:
    """Fill every `**Label:**` line `values` has an answer for; the label stays when empty."""

    def fill(line: str) -> str:
        match = LABEL_LINE.match(line)
        if match and match.group(1) in values:
            return f"{match.group(0)} {values[match.group(1)]}"
        return line

    return [fill(line) for line in lines]


def _row(label: str, value: str) -> str:
    return f"| {label} | {value} |"


def _meta_table(project: Project) -> str:
    """The epic's own metadata, as a table. Only the fields the board actually filled.

    This is the one block the template does not have: everything else on the page is a
    field the vault already knows about, and this is what monday.com knows instead.
    """
    budget = project.get("budget")
    rows = [
        ("Epic", f"[{project.name}]({project.url})"),
        ("Status epic", project.get("status")),
        ("Funnel", project.get("funnel")),
        ("Type", project.get("type")),
        ("Methode", project.get("method")),
        ("Prioriteit", project.get("priority")),
        ("Portfolio", project.get("portfolio")),
        ("T-shirt schatting", project.get("estimate")),
        ("Geschat budget", f"€ {budget}" if budget else ""),
        ("Ingebracht", project.get("submitted")),
        ("Geplande start", project.get("planned_start")),
        ("Gestart", project.get("started")),
        ("Geplande oplevering", project.get("planned_end")),
        ("Deadline", project.get("due_date")),
        ("Afgerond", project.get("finished")),
    ]
    filled = [_row(label, value) for label, value in rows if value]
    return "\n".join([_row("Veld", "Waarde"), _row("---", "---"), *filled])


def _purpose(project: Project) -> str:
    """The Doel en toelichting body: the user story, then what it delivers and improves."""
    blocks = []
    if why := project.get("why"):
        blocks.append(why)
    if product := project.get("product"):
        blocks.append(f"**Omschrijving product:** {product}")
    if quality := project.get("quality"):
        blocks.append(f"**Kwaliteits impuls:** {quality}")
    return "\n\n".join(blocks)


def note_markdown(project: Project, created: datetime | None = None, template: str | None = None) -> str:
    """Render the vault's project template with this epic's values filled in.

    `created` is the note's creation stamp, in the `YYYY-MM-DD HH:mm` the vault's other
    project notes use; it defaults to now, which is what Templater would have written.
    `template` defaults to `docs/Project.md`.
    """
    stamp = (created or datetime.now()).strftime("%Y-%m-%d %H:%M")
    lines = _resolve_templater(template_text() if template is None else template, stamp)
    lines = _fill_frontmatter(
        lines,
        {
            "tags": ["project"],
            # Quoted: a ten-digit item id is a number to YAML, and Dataview would render
            # it in scientific notation. The vault's existing notes quote it too.
            "MondayCom_nr": f'"{project.id}"',
            "Datalab_nr": project.prj_nr,
            "rol": project.role,
            "projectstatus": project.status,
            "start-project": project.start,
            "eind-project": project.end,
        },
    )
    lines = _fill_labels(
        lines,
        {
            "Opdrachtgever": project.get("client"),
            "PO/Projectleider": project.trekker,
            "Specialisten": project.get("experts"),
        },
    )
    at = _section_end(lines, META_HEADING)
    lines[at:at] = ["", "## Epic op monday.com", "", _meta_table(project)]
    if purpose := _purpose(project):
        at = _section_end(lines, PURPOSE_HEADING)
        lines[at:at] = ["", purpose]
    return "\n".join(line.rstrip() for line in lines).rstrip() + "\n"


def projects_dir(directory: str | None = None) -> Path:
    """Where notes are written: `--out`, else the vault's projects folder, else here.

    The vault lives on the Windows side of WSL, so it is not there on every machine the
    repo is checked out on. Falling back to the working directory keeps the command
    usable — and printable — rather than failing on a path the user never asked about.
    """
    if directory:
        return Path(directory).expanduser()
    vault = Path(OBSIDIAN_PROJECTS_DIR).expanduser()
    return vault if vault.is_dir() else Path.cwd()


def write_note(project: Project, directory: str | None = None, force: bool = False) -> Path:
    """Write the note and return its path. Refuses to overwrite unless `force`.

    An existing note is the user's own work — this command only ever creates the
    starting point, so clobbering it silently would be the one unrecoverable thing here.
    """
    path = projects_dir(directory) / note_filename(project)
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; pass --force to overwrite it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note_markdown(project), encoding="utf-8")
    return path
