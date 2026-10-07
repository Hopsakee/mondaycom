"""Filter controls both web apps share: dates, the portfolio half, switches, the selection row.

`web.py` (the sprint board) and `align_web.py` (the temporary alignment app) both import
this, and neither imports the other. The Planning page's selection — window, DAM half,
layers, "Dit kwartaal" — is `selection_fields`, so the alignment app asks for epics in
exactly the controls the Planning page does.
"""

from __future__ import annotations

from typing import Any

from fasthtml.common import Button, Div, Fieldset, Input, Label, Legend, Option, Select, Span

from mondaycom import planning
from mondaycom.config import DAM, NON_DAM

# "Do not filter on the portfolio at all", alongside config.DAM / config.NON_DAM.
ANY_PORTFOLIO = ""
PORTFOLIO_LABELS = ((ANY_PORTFOLIO, "Beide"), (DAM, "Alleen DAM"), (NON_DAM, "Alleen niet-DAM"))

DAM_HELP = (
    "DAM: epics die gekoppeld zijn aan een item op het IV Portfolio-bord. Niet-DAM: epics zonder die koppeling. "
    "De bezetting, de prognose en de checks op de huidige en de volgende sprint volgen allemaal dit filter."
)

#: `this` is a date field's hidden native picker: write the picked date into the text
#: field as ISO. Its own `change` then bubbles to the form, which asks for the section.
DATE_PICKED_JS = "this.parentElement.querySelector('input[type=text]').value = this.value"

CSS = """
.htmx-request #spinner { display: inline; }
#spinner { display: none; color: var(--muted); }
/* One tight actions row rather than a full-width primary button. */
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; margin-top: .6rem; }
.actions button, .actions [role="button"] { width: auto; margin-bottom: 0; }
/* Filters in one block: a grid, so they stay compact and line up as the window changes,
   rather than rows of full-width Pico groups. */
.filters { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: .1rem .8rem;
           align-items: end; }
.filters label.switch { padding-bottom: .9rem; }
/* The selection row: narrower columns, and the layers as one line of checkboxes. */
.filters.selection { grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); }
.filters fieldset.layers { display: flex; flex-wrap: wrap; gap: .2rem 1rem; align-items: center;
                           margin: 0; padding-bottom: .9rem; border: 0; }
.filters fieldset.layers legend { font-size: .9rem; padding: 0; margin-bottom: .2rem; }
.filters fieldset.layers label.switch { padding-bottom: 0; margin: 0; width: auto; }
/* A date field: the ISO text and a calendar button in one control. The native picker is
   kept, invisible, under the button — only for the calendar it opens. */
.date-field { position: relative; display: flex; gap: .35rem; align-items: stretch;
              margin-bottom: var(--pico-spacing); }  /* the margin Pico gives every other input */
.date-field input[type=text] { flex: 1; margin-bottom: 0; font-variant-numeric: tabular-nums; }
.date-field input.date-picker { position: absolute; right: 0; bottom: 0; width: 1px; height: 1px; padding: 0;
                                margin: 0; border: 0; opacity: 0; pointer-events: none; }
.date-field button.date-button { width: auto; margin: 0; padding: 0 .65rem; background: var(--surface);
                                 border: 1px solid var(--line); color: var(--ink); }
.date-field button.date-button:hover { border-color: var(--accent); }
"""


def portfolio_select(selected: str = ANY_PORTFOLIO) -> Any:
    """DAM / non-DAM: whether the task's epic is linked to the IV Portfolio board."""
    return Select(
        *[Option(label, value=value, selected=value == selected) for value, label in PORTFOLIO_LABELS],
        name="dam",
    )


def dam_label(dam: str) -> str:
    """The filter's label ("Alleen DAM" / "Alleen niet-DAM"), or empty when it is off — or set
    to a value it does not know, which every DAM check treats as both (`config.keeps_dam`)."""
    return next((label for value, label in PORTFOLIO_LABELS if value == dam and value), "")


def date_field(name: str, value: str, id: str | None = None) -> Any:
    """A date as the page writes it everywhere, `2026-12-31`, with a calendar button.

    Not a bare `<input type="date">`: that one *shows* its value in the browser's locale
    (09/28/2026 on an English browser) whatever the page asks for. The text field is what
    is submitted and must read `JJJJ-MM-DD` (the browser blocks the request otherwise);
    the native picker sits hidden behind the button only for its calendar.
    """
    return Span(
        Input(
            type="text",
            name=name,
            value=value,
            inputmode="numeric",
            pattern=r"\d{4}-\d{2}-\d{2}",
            placeholder="JJJJ-MM-DD",
            title="Een datum als JJJJ-MM-DD, bijvoorbeeld 2026-12-31",
            autocomplete="off",
        ),
        Input(type="date", value=value, tabindex="-1", aria_hidden="true", cls="date-picker", onchange=DATE_PICKED_JS),
        Button(
            "📅",
            type="button",
            cls="date-button",
            aria_label="Kies een datum in de kalender",
            onclick="this.parentElement.querySelector('.date-picker').showPicker()",
        ),
        cls="date-field",
        id=id,
    )


def refresh_button(route: Any, form: str, target: str) -> Any:
    """Re-read the page's boards: `route` with `refresh` on it, sent with the `form`'s
    filters so the fresh read comes back in the same slice, swapped over `target`."""
    return Button(
        "Opnieuw ophalen van monday.com",
        type="button",
        cls="secondary outline",
        hx_get=route,
        hx_include=form,
        hx_target=target,
        hx_swap="outerHTML",
        hx_indicator=form,
    )


def switch(name: str, label: str, checked: bool, title: str) -> Any:
    """A filter that is on or off, with its rule in the hover."""
    return Label(Input(type="checkbox", name=name, role="switch", checked=checked), label, cls="switch", title=title)


def planning_date_fields(sprint_end: str, end: str) -> Any:
    """The window's two dates: the end of the current sprint (the plan starts the day after)
    and the end of the quarter. They show the window in use, so they come back out of band."""
    return Div(
        Label("Einde sprint", date_field("sprint_end", sprint_end)),
        Label("Einde kwartaal", date_field("end", end)),
        id="planning-dates",
        style="display: contents",
    )


def selection_fields(sprint_end: str, end: str, layers: tuple[str, ...], dam: str, this_quarter: bool) -> Any:
    """The Planning page's selection: the window, the DAM half, the layers and "Dit kwartaal"."""
    return Div(
        planning_date_fields(sprint_end, end),
        Label("Portfolio", portfolio_select(dam), title=DAM_HELP),
        Fieldset(
            Legend("Plannen"),
            *[
                Label(
                    Input(type="checkbox", name="layer", value=key, checked=key in layers),
                    label,
                    title=planning.LAYER_HELP_NL[key],
                )
                for key, label in planning.LAYERS_NL.items()
            ],
            Label(
                Input(type="checkbox", name="this_quarter", role="switch", checked=this_quarter),
                "Dit kwartaal",
                title=planning.THIS_QUARTER_HELP_NL,
            ),
            cls="layers",
        ),
        cls="filters selection",
    )
