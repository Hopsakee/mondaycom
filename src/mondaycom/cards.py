"""The cards view: the same rows as the tables, laid out as cards.

Every page can be read as a table or as cards (the switch in the page head, the
`weergave` cookie). The cards are a second *layout*, never a second calculation: each
card is built in `web.py` next to the table row it mirrors, from the same model and the
same helpers (`chart.battery`, `chart.status_tag`, the stuck marker), and this module
only supplies the pieces they are laid out with.

The look follows the Kwartaalplanbord design colleagues liked (`docs/tmp/`), in the
WDODelta huisstijl rather than its own teal: a surface card with a 4px top rule that
wears the card's state, a big figure top right, the meter full width, a quiet footer.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fasthtml.common import H3, Article, Button, Dialog, Div, Header, I, Small, Span

#: The view switch's two values. The cookie holds one of them; anything else is a table.
TABEL = "tabel"
KAARTEN = "kaarten"

CARDS_CSS = """
.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 19rem), 1fr)); gap: 1rem;
             margin-bottom: 1rem; }
.card-grid.wide { grid-template-columns: repeat(auto-fill, minmax(min(100%, 29rem), 1fr)); }
.card-grid.narrow { grid-template-columns: repeat(auto-fill, minmax(min(100%, 14rem), 1fr)); }
.kaart {
  background: var(--surface); border: 1px solid var(--line); border-top: 4px solid var(--tone, var(--series-actual));
  border-radius: 6px; padding: .95rem 1.05rem .8rem; display: flex; flex-direction: column; gap: .65rem;
  box-shadow: var(--shadow); min-width: 0;
  transition: border-color .15s ease, box-shadow .15s ease;
}
.kaart:hover { border-left-color: var(--accent); border-right-color: var(--accent);
               border-bottom-color: var(--accent); }
.kaart-head { display: flex; justify-content: space-between; gap: .75rem; align-items: flex-start; }
.kaart-head > div:first-child { min-width: 0; }
.kaart-head h3 { font-size: 1.05rem; margin: 0; line-height: 1.3; color: var(--ink); overflow-wrap: anywhere; }
.kaart-head h3 a { color: inherit; text-decoration: none; }
.kaart-head h3 a:hover { color: var(--heading); text-decoration: underline; text-underline-offset: 3px; }
.kaart-head .sub { display: block; font-size: .82rem; color: var(--muted); margin-top: .2rem; }
.kaart .big { font-size: 1.8rem; font-weight: 700; line-height: 1; color: var(--heading); text-align: right;
              white-space: nowrap; font-variant-numeric: tabular-nums; }
.kaart .big small { display: block; font-size: .78rem; font-weight: 600; color: var(--muted); margin-top: .3rem; }
.kaart .tags { display: flex; flex-wrap: wrap; gap: .35rem 1rem; align-items: center; font-size: .85rem; }
.kaart .battery { display: flex; }
.kaart .battery .track { flex: 1; width: auto; height: 10px; border-radius: 5px; }
.kaart .battery .fill { border-radius: 5px; }
.kaart-foot { display: flex; flex-wrap: wrap; justify-content: space-between; gap: .3rem 1rem; font-size: .8rem;
              color: var(--muted); border-top: 1px solid var(--line-2); padding-top: .55rem; margin-top: auto;
              font-variant-numeric: tabular-nums; }
.kaart-foot b { color: var(--ink); }
.kaart .stuck .blockers { max-width: none; }
.kaart details.stuck { margin: 0; }
.kaart .big.none { color: var(--muted); font-weight: 600; }
h4.layer { margin: 1rem 0 .6rem; font-size: 1rem; }
h4.layer small { color: var(--muted); font-weight: 600; margin-left: .3rem; }

/* A points or share token: monochrome, so the brand's two blues stay the only colours. */
.pill { display: inline-flex; align-items: center; gap: .25rem; font-weight: 700; font-size: .72rem;
        padding: .1rem .5rem; border-radius: 999px; white-space: nowrap; font-variant-numeric: tabular-nums;
        color: var(--heading); background: color-mix(in srgb, var(--series-actual) 11%, transparent); }

/* A short list inside a card: mark, name, figure. */
ul.elist { list-style: none; margin: 0; padding: 0; font-size: .87rem; }
ul.elist li { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: .6rem; align-items: center;
              padding: .32rem 0; border-bottom: 1px solid var(--line-2); list-style: none; margin: 0; }
ul.elist li:last-child { border-bottom: 0; }
ul.elist .n { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
ul.elist .n .tag { display: flex; min-width: 0; }
ul.elist .v { color: var(--muted); font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
ul.elist li.more { color: var(--muted); grid-template-columns: 1fr; }
ul.elist a { color: var(--ink); text-decoration: none; }
ul.elist a:hover { color: var(--heading); text-decoration: underline; text-underline-offset: 3px; }

/* The sort row the cards use instead of table headings: the same buttons, in a line. */
.sortbar { display: flex; flex-wrap: wrap; align-items: center; gap: .35rem .5rem; margin: 0 0 .9rem;
           font-size: .85rem; }
.sortbar > small { color: var(--muted); font-weight: 600; margin-right: .2rem; }
.sortbar button.sort { all: unset; cursor: pointer; padding: .2rem .6rem; border-radius: 999px;
                       border: 1px solid var(--line); background: var(--surface); white-space: nowrap;
                       transition: background-color .15s ease, border-color .15s ease; }
.sortbar button.sort:hover { border-color: var(--accent); }
.sortbar button.sort:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.sortbar button.sort[aria-sort] { background: var(--brand); border-color: var(--brand);
                                   color: var(--brand-ink); font-weight: 600; }
.sortbar button.sort .arrow { opacity: .6; font-size: .8em; }

/* The sprint as a board: one lane per state, a card per task. The card is the label of
   its checkbox, so clicking anywhere on it takes it in or out of the markdown. */
.kanban { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(13rem, 1fr); gap: .9rem;
          overflow-x: auto; padding-bottom: .4rem; margin-bottom: 1rem; align-items: start; }
.lane { background: var(--surface-2); border: 1px solid var(--line); border-radius: 6px; padding: .6rem;
        display: flex; flex-direction: column; gap: .5rem; min-width: 0; }
.lane > header { display: flex; justify-content: space-between; align-items: center; font-size: .9rem;
                 font-weight: 700; padding: .1rem .2rem .2rem; }
.lane > header small { color: var(--muted); font-weight: 600; font-variant-numeric: tabular-nums; }
label.taak {
  display: grid; grid-template-columns: auto minmax(0, 1fr); gap: .25rem .55rem; margin: 0; cursor: pointer;
  background: var(--surface); border: 1px solid var(--line); border-left: 3px solid var(--tone, var(--line));
  border-radius: 6px; padding: .55rem .65rem; box-shadow: var(--shadow);
  transition: border-color .15s ease, opacity .15s ease;
}
label.taak:hover { border-color: var(--accent); border-left-color: var(--tone, var(--accent)); }
label.taak input[type=checkbox] { margin: .15rem 0 0; }
label.taak .t { font-weight: 600; font-size: .9rem; line-height: 1.3; overflow-wrap: anywhere; }
label.taak .m { grid-column: 2; display: flex; flex-wrap: wrap; gap: .3rem .6rem; align-items: center;
                font-size: .78rem; color: var(--muted); }
label.taak .m .person { font-size: .8rem; color: var(--ink-2); min-width: 0; max-width: 100%; overflow: hidden;
                       text-overflow: ellipsis; }
label.taak.done .t { text-decoration: line-through; text-decoration-thickness: 1px; color: var(--muted); }
label.taak:has(input:not(:checked)) { opacity: .5; }
.kanban-tools { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem 1rem; margin-bottom: .6rem;
                font-size: .85rem; color: var(--muted); }
.kanban-tools label { margin: 0; display: inline-flex; gap: .4rem; align-items: center; }

/* The planning's two charts, side by side; stacked when the window is narrow. */
.chart-pair { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 30rem), 1fr)); gap: 1rem;
              margin-bottom: 1rem; }
.chart-half { padding: .8rem 1rem .7rem; }
.chart-half h4 { margin: 0 0 .5rem; font-size: 1rem; }
.chart-half h4 small { color: var(--muted); font-weight: 400; font-size: .8rem; margin-left: .5rem; }
.strip { display: inline-grid; grid-auto-flow: column; grid-auto-columns: .8rem; gap: 2px; }
.strip i { height: .65rem; border-radius: 2px; background: var(--line-2); }
.strip i.on { background: var(--series-actual); }
.strip i.past { background: var(--tone-critical); }
.strip-head { gap: 2px; }
.strip-head span { font-size: .68rem; font-weight: 700; color: var(--muted); text-align: center; }

/* A card that opens: the whole card is the target, its button the keyboard way in. */
.kaart.opens { cursor: pointer; }
.kaart.opens:hover { box-shadow: var(--shadow-hover); }
.kaart .open-list { width: auto; margin: 0; padding: .35rem .8rem; font-size: .85rem; }

/* The dialog: as wide as the list needs, never taller than the window; the rows scroll. */
dialog.kaart-dialog > article { width: min(60rem, 94vw); max-width: none; max-height: 86vh; display: flex;
                                flex-direction: column; padding: 1.1rem 1.2rem 1rem; border-radius: 6px; }
dialog.kaart-dialog > article > header { margin: -1.1rem -1.2rem .6rem; padding: 1rem 1.2rem .8rem;
                                         border-radius: 6px 6px 0 0; }
dialog.kaart-dialog h3 { margin: 0; }
dialog.kaart-dialog header small { color: var(--muted); }
.dialog-scroll { overflow: auto; min-height: 0; }
.dialog-scroll table { margin-bottom: .6rem; font-size: .88rem; }
.dialog-scroll thead th { position: sticky; top: 0; background: var(--surface); z-index: 1; }
.dialog-scroll td.num { text-align: right; font-variant-numeric: tabular-nums; }
.dialog-scroll .strip { grid-auto-columns: 1.6rem; }
.dialog-scroll .strip i { height: .8rem; }
.strip-help { color: var(--muted); font-size: .82rem; max-width: 46rem; }
.strip-help .strip { vertical-align: middle; margin: 0 .2rem; }
.overflow { font-size: .82rem; }
"""


def grid(cards: Iterable[Any], size: str = "") -> Any:
    """Cards in a responsive grid: as many columns as the window holds. `size` is ``wide``
    for cards that carry a list of their own, ``narrow`` for small figure cards."""
    return Div(*cards, cls=f"card-grid {size}".strip())


def card(*children: Any, tone: str = "", cls: str = "", **attrs: Any) -> Any:
    """One card. `tone` is a chart tone (`good`, `critical`, `off`, …) and colours the top rule."""
    classes = " ".join(filter(None, ["kaart", f"tone-{tone}" if tone else "", cls]))
    return Div(*children, cls=classes, **attrs)


def percent(part: float, whole: float) -> str | None:
    """`part` of `whole` as the figure a card shows, or `None` when there is no whole."""
    return f"{part / whole:.0%}" if whole else None


def head(title: Any, sub: Any = None, big: str | None = None, big_note: Any = None) -> Any:
    """A card's head: the title (and a line under it) on the left, the figure on the right.
    A `big` of `None` is "nothing to measure": a muted dash, never a 0."""
    figure = Div(big or "—", Small(big_note) if big_note else None, cls="big" if big else "big none")
    return Div(Div(H3(title), Span(sub, cls="sub") if sub else None), figure, cls="kaart-head")


def _row(cls: str, items: tuple[Any, ...]) -> Any:
    """A row of `items`, empty ones dropped so no gap is left for them; nothing at all when
    every item is empty."""
    kept = [item for item in items if item not in ("", None)]
    return Div(*kept, cls=cls) if kept else None


def tags(*items: Any) -> Any:
    """A row of tags and people."""
    return _row("tags", items)


def foot(*items: Any) -> Any:
    """The quiet line at the bottom of a card."""
    return _row("kaart-foot", items)


def pill(text: str, **attrs: Any) -> Any:
    return Span(text, cls="pill", **attrs)


def strip(sprints: int, first: int | None, last: int | None) -> Any:
    """Which of the window's sprints a share lands in, as a row of cells, one per sprint.

    Dark: a sprint the forecast works on it. Light: a sprint it does not. The last cell in
    the critical tone: the share runs on past the window. The strip says the same in
    words, as its label and its hover, so it is never read from colour alone.
    """
    cells = []
    for n in range(1, sprints + 1):
        on = first is not None and last is not None and first <= n <= last
        past = n == sprints and last is not None and last > sprints
        cells.append(I(cls="past" if past else "on" if on else None))
    if first is None:
        label = "niemand om het te doen"
    elif last is not None and last > sprints:
        label = f"vanaf S{first}, loopt door na de periode"
    else:
        label = f"S{first}" if first == last else f"S{first}–S{last}"
    words = f"Sprints volgens de prognose: {label}"
    return Span(*cells, cls="strip", role="img", aria_label=words, title=words)


def strip_head(sprints: int) -> Any:
    """The sprint labels over a column of strips: S1, S2, … one per cell."""
    return Span(*[Span(f"S{n}") for n in range(1, sprints + 1)], cls="strip strip-head", aria_hidden="true")


#: `this` is a folded card: open its dialog, unless the click was a link or inside the
#: dialog. Its "Bekijk" button has no handler of its own: its click bubbles up to here.
OPEN_JS = "if (!event.target.closest('dialog, a')) this.querySelector('dialog').showModal()"

#: `this` is a dialog: a click on the backdrop (the dialog itself, not its content) closes it.
BACKDROP_JS = "if (event.target === this) this.close()"


def dialog(title: Any, sub: Any, *content: Any) -> Any:
    """A modal over the page, in Pico's dialog > article form: a header with the title and
    a close button, then `content` in a block that scrolls on its own. Escape, the close
    button and a click beside it all close it."""
    return Dialog(
        Article(
            Header(
                Button(aria_label="Sluiten", rel="prev", type="button", onclick="this.closest('dialog').close()"),
                H3(title),
                Small(sub) if sub else None,
            ),
            Div(*content, cls="dialog-scroll"),
        ),
        cls="kaart-dialog",
        onclick=BACKDROP_JS,
    )
