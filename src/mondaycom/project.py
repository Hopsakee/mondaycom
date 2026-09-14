"""One epic, turned into an Obsidian project note.

`monday project DPR-223` looks an epic up on the epic board and writes the vault's
project template with everything the board already knows filled in — codes, dates,
who is involved, and the epic's own metadata — so the note starts where monday.com
stops rather than as an empty form.

The template it renders is `docs/Project.md`, which is a Templater template: its
`<% tp.* %>` calls are evaluated by Obsidian when *it* creates a note. We create the
file ourselves, so the dynamic parts are resolved here instead — the creation stamp is
now, and the `tp.file.move` line is replaced by writing into the projects folder. The
`&=choice(...)` inline expressions are Dataview, evaluated when the note is *read*, and
are copied through untouched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
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


#: The template's opening callout, kept word for word. It is a constant rather than a
#: line of the rendered block only because it is longer than the repo's 120 columns.
CHASE_OR_SKIP = (
    "> [!todo] Eerst: chase of skip? Maak [[Besluit chase-of-skip]] — de drie poorten: "
    "wie vangt het op? / past het binnen het deel? / landt het?"
)


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


def _meta(key: str, value: str) -> str:
    """One frontmatter line. Empty values leave a bare `key:`, never a trailing space."""
    return f"{key}: {value}".rstrip()


def _line(label: str, value: str) -> str:
    """One `**Label:** value` line of the Betrokken block — the label stays when empty."""
    return f"**{label}:** {value}".rstrip()


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


def note_markdown(project: Project, created: datetime | None = None) -> str:
    """Render the vault's project template with this epic's values filled in.

    `created` is the note's creation stamp, in the `YYYY-MM-DD HH:mm` the vault's other
    project notes use; it defaults to now, which is what Templater would have written.
    """
    stamp = (created or datetime.now()).strftime("%Y-%m-%d %H:%M")
    # Quoted: a ten-digit item id is a number to YAML, and Dataview would render it in
    # scientific notation. The vault's existing notes quote it for the same reason.
    return f"""---
created: {stamp}
tags:
  - project
fileClass: project
hd:
MondayCom_nr: "{project.id}"
{_meta("Datalab_nr", project.prj_nr)}
alias:
{_meta("rol", project.role)}
{_meta("projectstatus", project.status)}
{_meta("start-project", project.start)}
{_meta("eind-project", project.end)}
tasks: true
---
[[!d5_Projecten WDOD-MOC]]

{CHASE_OR_SKIP}


> [!info] status, rol en datums
>  Status: `&=choice(this.projectstatus, this.projectstatus, "")`
> Rol: `&=choice(this.rol, this.rol, "")`
> Startdatum: `&=choice(this.start-project, this.start-project, "")`
> Einddatum: `&=choice(this.eind-project, this.eind-project, "")`

# Doel en toelichting

{_purpose(project)}

# Project meta data

## Betrokken

{_line("Opdrachtgever", project.get("client"))}
{_line("Gebruikers", "")}
{_line("PO/Projectleider", project.trekker)}
{_line("Specialisten", project.get("experts"))}
{_line("Adviseurs", "")}
{_line("Adviesbureaus", "")}

## Locaties bestanden

**Lokaal:**
**Netwerk:**
**Mail:**
**Scripts:**
**Modellen:**
**GIS:**
**Notities:**

## Relevante project codes

| Platform       | Code                                                |
| -------------- | --------------------------------------------------- |
| Datalab        | `&=choice(this.Datalab_nr, this.Datalab_nr, "")`     |
| Monday.com     | `&=choice(this.MondayCom_nr, this.MondayCom_nr, "")` |
| Jelle Deciamal | `&=choice(this.hd, this.hd, "")`                     |

## Epic op monday.com

{_meta_table(project)}

# Overleggen en afspraken


# Gerelateerde notities

```dataview
TABLE
WHERE hd = this.hd AND file.name != this.file.name
SORT file.name
LIMIT 25
```

# Tasks

> Import template 'Project afronding WDODelta' bij afsluiten project

- [ ] zet project id in tabel en onder 'jd' en 'alias'. 🆔 mqjpKx
- [ ] maak freefilesync aan van Obsidian note naar projectmap 🆔 pUFo5P
"""


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
