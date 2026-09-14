"""Offline tests for the Obsidian project note: reference parsing, fetch, rendering."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from mondaycom import project
from mondaycom.config import EPIC_BOARD

# The epic behind the example in docs/Project.md, as the board really answers it.
DPR_223 = {
    "id": "2617136005",
    "name": "Data validatie hydrologisch modelleren het vervolg",
    "column_values": [
        {"id": EPIC_BOARD.column("prj_nr"), "text": "DPR-223"},
        {"id": EPIC_BOARD.column("owner"), "text": "Rutger Feijen"},
        {"id": EPIC_BOARD.column("owner_text"), "text": "Rutger Feijen"},
        {"id": EPIC_BOARD.column("status"), "text": "Working on it"},
        {"id": EPIC_BOARD.column("priority"), "text": "Medium"},
        # A board_relation answers in display_value; `text` is null.
        {
            "id": EPIC_BOARD.column("portfolio"),
            "text": None,
            "display_value": "Kernregistratie",
            "linked_item_ids": ["3125996105"],
        },
        {"id": EPIC_BOARD.column("funnel"), "text": "PoC"},
        {"id": EPIC_BOARD.column("method"), "text": "Cocreatie"},
        {"id": EPIC_BOARD.column("type"), "text": "Optimalisatie"},
        {"id": EPIC_BOARD.column("estimate"), "text": "S"},
        {"id": EPIC_BOARD.column("client"), "text": None},
        {"id": EPIC_BOARD.column("experts"), "text": "Stefan de Vries"},
        {"id": EPIC_BOARD.column("why"), "text": "Als hydroloog wil ik gevalideerde data gebruiken"},
        {"id": EPIC_BOARD.column("product"), "text": ""},
        {"id": EPIC_BOARD.column("quality"), "text": "verbeterde data en verbeterd beheerregister"},
        {"id": EPIC_BOARD.column("budget"), "text": ""},
        {"id": EPIC_BOARD.column("submitted"), "text": "2026-01-08"},
        {"id": EPIC_BOARD.column("planned_start"), "text": "2026-01-01"},
        {"id": EPIC_BOARD.column("started"), "text": "2026-01-08"},
        {"id": EPIC_BOARD.column("planned_end"), "text": "2026-07-01"},
        {"id": EPIC_BOARD.column("finished"), "text": ""},
        {"id": EPIC_BOARD.column("due_date"), "text": ""},
    ],
}


class FakeClient:
    """Answers one canned payload and records the query it was asked."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.queries: list[str] = []

    def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        self.queries.append(query)
        return self.payload


def sample() -> project.Project:
    return project.fetch(FakeClient({"items": [DPR_223]}), project.Reference("item_id", "2617136005"))  # type: ignore[arg-type]


# --- parse_reference ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "kind", "value"),
    [
        ("DPR-223", "prj_nr", "DPR-223"),
        ("dpr-223", "prj_nr", "DPR-223"),
        ("DPR223", "prj_nr", "DPR-223"),
        ("DPR 223", "prj_nr", "DPR-223"),
        ("  DPR-223  ", "prj_nr", "DPR-223"),
        ("223", "prj_nr", "DPR-223"),
        ("7", "prj_nr", "DPR-07"),  # padded to the column's own width
        ("DPR-7", "prj_nr", "DPR-07"),
        ("007", "prj_nr", "DPR-07"),
        ("2617136005", "item_id", "2617136005"),
    ],
)
def test_parse_reference(raw: str, kind: str, value: str) -> None:
    ref = project.parse_reference(raw)
    assert (ref.kind, ref.value) == (kind, value)


@pytest.mark.parametrize("raw", ["", "   ", "EBO-EIS", "DPR-", "223a", "12.5"])
def test_parse_reference_rejects_nonsense(raw: str) -> None:
    with pytest.raises(ValueError):
        project.parse_reference(raw)


def test_five_digits_is_an_item_id_not_a_project_number() -> None:
    """The boundary: `prj_nr` counts in the hundreds, an item id is long."""
    assert project.parse_reference("9999").kind == "prj_nr"
    assert project.parse_reference("10000").kind == "item_id"


# --- fetch -------------------------------------------------------------------------


def test_fetch_by_item_id_reads_the_item_directly() -> None:
    client = FakeClient({"items": [DPR_223]})
    epic = project.fetch(client, project.Reference("item_id", "2617136005"))  # type: ignore[arg-type]
    assert "items(ids: [2617136005])" in client.queries[0]
    assert epic.name == "Data validatie hydrologisch modelleren het vervolg"
    assert epic.prj_nr == "DPR-223"


def test_fetch_by_project_number_filters_on_the_displayed_text() -> None:
    """`prj_nr` compares against `"DPR-223"`, not against the bare digits."""
    client = FakeClient({"boards": [{"items_page": {"items": [DPR_223]}}]})
    epic = project.fetch(client, project.Reference("prj_nr", "DPR-223"))  # type: ignore[arg-type]
    assert '"DPR-223"' in client.queries[0]
    assert EPIC_BOARD.column("prj_nr") in client.queries[0]
    assert epic.id == "2617136005"


def test_fetch_raises_when_nothing_matches() -> None:
    client = FakeClient({"boards": [{"items_page": {"items": []}}]})
    with pytest.raises(project.NotFound):
        project.fetch(client, project.Reference("prj_nr", "DPR-999"))  # type: ignore[arg-type]


def test_board_relation_is_read_from_display_value() -> None:
    assert sample().get("portfolio") == "Kernregistratie"


# --- the project's derived fields --------------------------------------------------


def test_status_maps_onto_the_vaults_own_vocabulary() -> None:
    assert sample().status == "loopt"


def test_unknown_status_maps_to_nothing_rather_than_a_guess() -> None:
    epic = project.Project(id="1", name="x", fields={"status": "Iets nieuws"})
    assert epic.status == ""


def test_role_is_trekker_only_when_the_epic_is_jelles() -> None:
    assert sample().role == ""
    assert project.Project(id="1", name="x", fields={"owner": "Jelle de Jong"}).role == "trekker"


def test_trekker_falls_back_to_the_text_column() -> None:
    epic = project.Project(id="1", name="x", fields={"owner": "", "owner_text": "Rutger Feijen"})
    assert epic.trekker == "Rutger Feijen"


def test_dates_fall_back_in_order() -> None:
    assert sample().start == "2026-01-01"  # planned start wins
    assert sample().end == "2026-07-01"
    later = project.Project(id="1", name="x", fields={"started": "2026-02-02", "finished": "2026-03-03"})
    assert (later.start, later.end) == ("2026-02-02", "2026-03-03")


# --- the file name -----------------------------------------------------------------


def test_note_filename_is_name_then_project_number() -> None:
    assert project.note_filename(sample()) == "Data validatie hydrologisch modelleren het vervolg_DPR-223.md"


def test_note_filename_strips_what_a_path_or_obsidian_cannot_take() -> None:
    epic = project.Project(id="1", name="GGOR/GxG: [tool] #2?", fields={"prj_nr": "DPR-09"})
    assert project.note_filename(epic) == "GGOR GxG tool 2_DPR-09.md"


def test_note_filename_falls_back_to_the_item_id() -> None:
    epic = project.Project(id="2617136005", name="Naamloos", fields={})
    assert project.note_filename(epic) == "Naamloos_2617136005.md"


# --- the note ----------------------------------------------------------------------


def test_note_markdown_fills_the_frontmatter() -> None:
    note = project.note_markdown(sample(), created=datetime(2026, 9, 14, 10, 30))
    head = note.split("---")[1]
    assert "created: 2026-09-14 10:30" in head
    assert 'MondayCom_nr: "2617136005"' in head  # quoted: YAML would read it as a number
    assert "Datalab_nr: DPR-223" in head
    assert "projectstatus: loopt" in head
    assert "start-project: 2026-01-01" in head
    assert "eind-project: 2026-07-01" in head
    assert "fileClass: project" in head


def test_note_markdown_fills_the_body() -> None:
    note = project.note_markdown(sample())
    assert "Als hydroloog wil ik gevalideerde data gebruiken" in note
    assert "**Kwaliteits impuls:** verbeterde data en verbeterd beheerregister" in note
    assert "**PO/Projectleider:** Rutger Feijen" in note
    assert "**Specialisten:** Stefan de Vries" in note
    # Empty ones keep their label and lose the trailing space.
    assert "**Adviseurs:**\n" in note


def test_note_markdown_keeps_the_templates_dataview_expressions() -> None:
    """`&=choice(...)` and the dataview block are read-time, not creation-time."""
    note = project.note_markdown(sample())
    assert '`&=choice(this.Datalab_nr, this.Datalab_nr, "")`' in note
    assert "```dataview" in note
    assert "[[!d5_Projecten WDOD-MOC]]" in note
    assert "🆔 mqjpKx" in note


def test_note_markdown_resolves_the_templater_calls() -> None:
    """We create the file, so no `<% tp.* %>` may survive into it."""
    note = project.note_markdown(sample())
    assert "<%" not in note
    assert "tp.file" not in note


def test_meta_table_holds_the_epic_and_skips_empty_fields() -> None:
    note = project.note_markdown(sample())
    assert "| Epic | [Data validatie hydrologisch modelleren het vervolg]" in note
    assert "boards/757753649/pulses/2617136005" in note
    assert "| Portfolio | Kernregistratie |" in note
    assert "| Funnel | PoC |" in note
    assert "| Geschat budget |" not in note  # empty on this epic
    assert "| Afgerond |" not in note


def test_an_empty_epic_still_renders() -> None:
    """Every column is optional; a bare epic must not raise."""
    note = project.note_markdown(project.Project(id="1", name="Nieuw idee", fields={}))
    assert "Datalab_nr:" in note
    assert "| Epic | [Nieuw idee]" in note


# --- writing -------------------------------------------------------------------------


def test_write_note_writes_and_refuses_to_clobber(tmp_path: Any) -> None:
    epic = sample()
    path = project.write_note(epic, directory=str(tmp_path))
    assert path.name == "Data validatie hydrologisch modelleren het vervolg_DPR-223.md"
    assert "Datalab_nr: DPR-223" in path.read_text(encoding="utf-8")

    with pytest.raises(FileExistsError):
        project.write_note(epic, directory=str(tmp_path))
    assert project.write_note(epic, directory=str(tmp_path), force=True) == path


def test_projects_dir_falls_back_to_the_working_directory(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(project, "OBSIDIAN_PROJECTS_DIR", str(tmp_path / "no-vault-here"))
    monkeypatch.chdir(tmp_path)
    assert project.projects_dir() == tmp_path
    assert project.projects_dir(str(tmp_path / "elsewhere")) == tmp_path / "elsewhere"
