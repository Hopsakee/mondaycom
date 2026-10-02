"""The burndown chart, as server-rendered SVG.

An emphasis chart, not a two-series one: the **actual** line is the story and the
ideal line is context, so actual gets the one accent hue and ideal is a recessive
dashed gray. Colours are the validated defaults from the data-viz reference
palette, with their own dark-mode steps rather than an automatic flip.

No JavaScript: hover is a per-day transparent hit rect carrying an SVG `<title>`,
which browsers show as a tooltip, and the same numbers are in the table below the
chart for anyone the tooltip does not reach.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from fasthtml.common import Caption, Div, Footer, Header, Img, Small, Span, Strong, Table, Tbody, Td, Th, Thead, Tr
from fasthtml.svg import Circle, G, Line, Path, Rect, Svg, Text, Title

from mondaycom.burndown import Burndown, fmt
from mondaycom.epics import Points
from mondaycom.planning import LOAD_BAND, LOAD_WORDS, load_tone
from mondaycom.theme import BLAUW, DONKERBLAUW, GROEN, ORANJE, ROOD

# Geometry, in SVG user units. The viewBox scales to whatever width the page gives it.
W, H = 720, 300
PAD_L, PAD_R, PAD_T, PAD_B = 46, 18, 16, 34
PLOT_W = W - PAD_L - PAD_R
PLOT_H = H - PAD_T - PAD_B

# Roles, not raw hex, everywhere below. The values are the WDODelta huisstijl (see
# `theme.py`): donkerblauw carries the one series that matters, blauw is "being worked
# on", and groen / oranje / rood are kept for state. Dark mode is the huisstijl's
# blue-on-dark, chosen by the toggle rather than by the OS — light is the default.
# The tokens sit on :root so the tables outside the charts (a status tag in the task
# list, an avatar in a filter summary) speak the same palette as the charts do.
#
# Tones are the huisstijl's secondary palette, which is fixed across themes:
#   good #93c01f (groen) · warning #f29100 (oranje) · critical #d74116 (rood)
# `serious` has no colour of its own in the huisstijl, so it is the step between oranje
# and rood. `active` is blauw and `neutral` the ink-grey for "not started". Groen and
# oranje sit below 3:1 on white and close together for deuteranopes (validated), so
# every tone ships as mark + label, never as colour alone.
# The neutral inks and surfaces are the theme's own (`theme.THEME_CSS`) under the chart's
# role names, so a palette tweak lands in one place; only the chart's own steps — the
# series, the meter track, the tones — have values here, and dark steps where they differ.
CHART_CSS = f"""
:root {{
  --surface-1: var(--surface);
  --text-secondary: var(--ink-2);
  --text-muted: var(--muted);
  --grid: var(--line-2);
  --hairline: rgba(7, 88, 149, .12);
  --series-actual: {DONKERBLAUW};
  --series-ideal: #8a8a85;
  --meter-track: #d3e5f2;
  --tone-good: {GROEN};
  --tone-warning: {ORANJE};
  --tone-serious: #e2661a;
  --tone-critical: {ROOD};
  --tone-active: {BLAUW};
  --tone-neutral: #8a8a85;
  --tone-off: #c3c9ce;
  --tone-brand: var(--series-actual);
  --avatar-bg: #e3eef6;
  --avatar-ink: {DONKERBLAUW};
}}
:root[data-theme="dark"] {{
  --grid: var(--line);
  --hairline: rgba(255, 255, 255, .12);
  --series-actual: {BLAUW};
  --series-ideal: #8f9aa3;
  --meter-track: #1e4466;
  --tone-neutral: #8f9aa3;
  --tone-off: #3a5670;
  --avatar-bg: #1a3754;
  --avatar-ink: #c6d3de;
}}
.viz svg {{ width: 100%; height: auto; display: block; }}
.viz .tick {{ fill: var(--text-muted); font-size: 11px; }}
.viz .direct {{ font-size: 12px; font-weight: 600; }}
.viz figcaption {{ color: var(--text-secondary); font-size: .85rem; }}
.viz .hit:hover {{ fill: color-mix(in srgb, var(--series-actual) 8%, transparent); }}

/* Stat tiles: label, value, note, on a surface card whose top rule wears the tile's tone.
   The value is the point, so it is the one big thing on the row. */
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: .75rem;
        margin: .5rem 0 1.1rem; }}
.kpi {{
  padding: .8rem 1rem .85rem; border-radius: 6px; background: var(--surface);
  border: 1px solid var(--line); border-top: 4px solid var(--tone, var(--grid));
  box-shadow: var(--shadow); min-width: 0;
}}
.kpi small {{ color: var(--text-muted); display: block; font-size: .8rem; line-height: 1.35; }}
.kpi > small:first-child {{ font-weight: 700; }}
.kpi strong {{ font-size: 2rem; font-weight: 700; line-height: 1.1; display: block; margin: .25rem 0 .15rem;
              color: var(--ink); font-variant-numeric: tabular-nums; }}
.kpi .battery {{ margin-top: .6rem; }}
.kpi.wide {{ grid-column: span 2; }}
.swatch {{ display: inline-block; width: 22px; height: 0; vertical-align: middle;
          border-top-width: 2px; margin-right: .35rem; }}

/* A state as a tag: a coloured dot beside the label. The label carries the meaning
   and stays in ink; the dot is the glance channel. */
.tag {{ display: inline-flex; align-items: center; gap: .4rem; white-space: nowrap; line-height: 1.2; }}
.tag .dot {{
  flex: none; width: .6rem; height: .6rem; border-radius: 50%;
  background: var(--tone); box-shadow: 0 0 0 1px color-mix(in srgb, var(--tone) 35%, transparent);
}}
.tag.tone-off .dot {{ background: none; box-shadow: inset 0 0 0 2px var(--tone); }}
.tag.tone-off {{ color: var(--text-muted); }}
.tone-good {{ --tone: var(--tone-good); }}
.tone-warning {{ --tone: var(--tone-warning); }}
.tone-serious {{ --tone: var(--tone-serious); }}
.tone-critical {{ --tone: var(--tone-critical); }}
.tone-active {{ --tone: var(--tone-active); }}
.tone-neutral {{ --tone: var(--tone-neutral); }}
.tone-off {{ --tone: var(--tone-off); }}
.tone-brand {{ --tone: var(--tone-brand); }}
.tag.priority .dot {{ border-radius: 2px; }}

/* A person: a 24px round avatar and the name. The photo sits over the initials, so a
   picture that fails to load falls back to the letters instead of a broken image. */
.person {{ display: inline-flex; align-items: center; gap: .45rem; white-space: nowrap; }}
.people {{ display: flex; flex-wrap: wrap; gap: .25rem .9rem; }}
.avatar {{
  position: relative; flex: none; width: 24px; height: 24px; border-radius: 50%;
  background: var(--avatar-bg); color: var(--avatar-ink); overflow: hidden;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: .62rem; font-weight: 600; letter-spacing: .02em; text-transform: uppercase;
  box-shadow: inset 0 0 0 1px var(--hairline);
}}
.avatar img {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }}

/* The battery: a meter, so one fill on a track of a lighter step of the same blue
   ramp (light 100 / dark 650) rather than two peer series. Every track is the same
   fixed width so the fills compare across rows; the numbers beside it sit in a
   fixed-width slot for the same reason. They are always spelled out — the track is
   deliberately low-contrast, and a meter with no readable value is decoration. */
.battery {{ display: inline-flex; align-items: center; gap: .55rem; }}
.battery .track {{
  flex: none; width: 7rem; height: 8px; border-radius: 4px; overflow: hidden;
  background: var(--meter-track);
}}
.battery .fill {{ height: 100%; border-radius: 4px; background: var(--series-actual); }}
.battery .value {{ color: var(--text-secondary); font-size: .75rem; white-space: nowrap;
                  font-variant-numeric: tabular-nums; min-width: 2.6rem; }}
.battery.empty .track {{ background: none; box-shadow: inset 0 0 0 1px var(--grid); }}
.battery.empty .value {{ color: var(--text-muted); }}
.battery.wide .track {{ width: 14rem; }}
.battery.wide .value {{ min-width: 6rem; font-size: .85rem; }}

/* The load meter: the battery's track and fill, on a fixed 0–150% scale so rows compare,
   with a tick where capacity runs out. Work past the tick is the critical tone, after a
   2px surface gap — and always with "overbooked" in words beside it, never colour alone. */
.battery.load .track {{ display: flex; gap: 2px; position: relative; overflow: visible; }}
.battery.load .over {{ height: 100%; border-radius: 4px; background: var(--tone-critical); }}
.battery.load .over.ok {{ background: var(--tone-good); }}
.battery.load .mark {{ position: absolute; top: -3px; bottom: -3px; width: 2px; margin-left: -1px;
                      background: var(--text-secondary); border-radius: 1px; }}
.battery.load .value {{ min-width: 3rem; }}

/* Status chips: one tag per status with its count, the pressed one outlined. They are
   buttons, so they are keyboard-reachable, but they read as filter tokens. */
.chips {{ display: flex; flex-wrap: wrap; gap: .4rem; margin: .2rem 0 .9rem; }}
.chip {{
  all: unset; cursor: pointer; display: inline-flex; align-items: center; gap: .45rem;
  padding: .2rem .65rem; border-radius: 999px; font: inherit; font-size: .85rem;
  box-shadow: inset 0 0 0 1px var(--hairline);
}}
.chip:hover {{ background: color-mix(in srgb, var(--tone-active) 8%, transparent); }}
.chip:focus-visible {{ outline: 2px solid var(--tone-active); outline-offset: 2px; }}
.chip {{ background: var(--surface); transition: background-color .15s ease, box-shadow .15s ease; }}
.chip[aria-pressed="true"] {{ box-shadow: inset 0 0 0 2px var(--series-actual); font-weight: 600; }}
.chip .count {{ color: var(--text-muted); font-variant-numeric: tabular-nums; }}

/* The stuck marker: a critical tag you can open, because "blocked" is only actionable
   if you can reach the thing doing the blocking. Closed it is one tag wide, so a table
   of running epics stays quiet; open it lists the blockers as links out to monday.com. */
.stuck {{ display: inline-block; }}
/* Three markers to suppress, not one: `display: inline-block` takes the summary off
   `list-item` (the UA triangle), `list-style` covers the browsers that ignore that, and
   `::after` is Pico's own chevron. The tag's dotted underline is what says "openable". */
.stuck > summary {{ display: inline-block; cursor: pointer; list-style: none; vertical-align: middle; }}
.stuck > summary::marker, .stuck > summary::-webkit-details-marker {{ content: ""; display: none; }}
.stuck > summary::after {{ display: none; }}
.stuck > summary:focus-visible {{ outline: 2px solid var(--tone-active); outline-offset: 2px; }}
.stuck > summary .tag {{ text-decoration: underline dotted; text-underline-offset: 3px; }}
/* Wide enough for a task title to be readable, capped so opening one does not push the
   Progress meter out of the scroll window. */
.blockers {{ list-style: none; margin: .4rem 0 .2rem; padding: 0; font-size: .82rem;
            min-width: 10rem; max-width: 13rem; }}
.blockers li {{ list-style: none; margin: 0 0 .25rem; white-space: normal; }}
.blockers li + li.epic {{ margin-top: .5rem; }}
.blockers .where {{ color: var(--text-muted); font-size: .9em; display: block; }}
.blockers ul {{ list-style: none; margin: .15rem 0 0; padding-left: .85rem;
               border-left: 2px solid var(--hairline); }}

/* The planning's horizontal bar charts: label, plot, value — one grid row per discipline,
   so the two charts side by side line up. Thin bars with rounded ends, recessive
   gridlines, the axis under the rows. */
.hbars {{ display: flex; flex-direction: column; gap: .35rem; min-width: 0; }}
.hrow {{ display: grid; grid-template-columns: minmax(6rem, 11rem) minmax(0, 1fr) 6.5rem; align-items: center;
        gap: .7rem; min-height: 1.9rem; font-size: .85rem; }}
.hlabel {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.hlabel small {{ color: var(--text-muted); }}
.hplot {{ position: relative; height: 14px; }}
.hbar {{ position: absolute; left: 0; top: 0; bottom: 0; border-radius: 0 4px 4px 0; }}
.hbar.ceiling {{ background: var(--meter-track); }}
.hbar.actual {{ background: var(--series-actual); top: 2px; bottom: 2px; }}
.hbar.booked {{ background: var(--tone); }}
.hgrid {{ position: absolute; top: -6px; bottom: -6px; width: 1px; background: var(--grid); }}
.hband {{ position: absolute; top: -6px; bottom: -6px;
         background: color-mix(in srgb, var(--tone-good) 22%, transparent); }}
/* The 100% line sits on top of the bars: it is the one reference every bar is read against. */
.htarget {{ position: absolute; top: -7px; bottom: -7px; width: 0; border-left: 2px dashed var(--text-secondary);
           z-index: 1; }}
.hvalue {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
.hvalue small {{ color: var(--text-muted); }}
.haxis {{ min-height: 1rem; }}
.hticks {{ position: relative; height: 1rem; }}
.hticks span {{ position: absolute; transform: translateX(-50%); color: var(--text-muted); font-size: .72rem; }}
.hticks span:first-child {{ transform: none; }}
.hlegend {{ display: flex; flex-wrap: wrap; gap: .2rem 1.1rem; font-size: .78rem; color: var(--text-secondary);
           margin-bottom: .2rem; }}
.hlegend > span {{ display: inline-flex; align-items: center; gap: .4rem; }}
.hlegend .key {{ width: 1.1rem; height: 10px; border-radius: 0 3px 3px 0; display: inline-block; }}
.hlegend .key.actual {{ background: var(--series-actual); }}
.hlegend .key.ceiling {{ background: var(--meter-track); }}

/* Small multiples: one burndown per person, each to its own scale, on the sprint's
   shared window. Each is a card with the person on top and the verdict as its tone. */
.multiples {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr)); gap: .75rem; }}
.multiple {{ border: 1px solid var(--line); border-radius: 6px; padding: .6rem .8rem .5rem;
            min-width: 0;
            background: var(--surface); box-shadow: var(--shadow); }}
.multiple header {{ display: flex; align-items: center; font-size: .85rem; margin-bottom: .3rem; min-width: 0; }}
.multiple header .person {{ min-width: 0; overflow: hidden; text-overflow: ellipsis; }}
.multiple footer {{ display: flex; justify-content: space-between; align-items: center; gap: .5rem;
                   margin-top: .25rem; font-size: .78rem; }}
.multiple footer .figures {{ color: var(--text-muted); font-variant-numeric: tabular-nums; white-space: nowrap; }}
"""


# --- state as colour --------------------------------------------------------------------
# Which tone a status or a priority label wears. Labels come from the boards (see
# config.SPRINT_STATUS and config.EPIC_STATUSES); a label neither list knows about is
# neutral rather than an error, because it arrives from monday.com, not from us.

#: Status labels of both the sprint boards and the epic board, by what they mean.
STATUS_TONES: dict[str, str] = {
    "Done": "good",
    "Working on it": "active",
    "Ongoing": "active",
    "Onderhouden": "active",
    "Wacht op Antwoord": "warning",
    "Wacht op review": "warning",
    "Wacht op taak": "warning",
    "Wachten op Epic": "warning",
    "On hold": "warning",
    "Overleg": "warning",
    "Impediment": "critical",
    "To Do": "neutral",
    "To Refine": "neutral",
    "Gerefined": "neutral",
    "Making ready": "neutral",
    "User story": "neutral",
    "Opportunity": "neutral",
    "Vervallen": "off",
    "Afgevallen": "off",
    "Overgedragen": "off",
}

#: The epic board's priorities, as urgency: the top two wear the severity tones.
PRIORITY_TONES: dict[str, str] = {
    "Very High": "critical",
    "High": "serious",
    "Medium": "warning",
    "Low": "neutral",
    "Very Low": "off",
    "NNB": "off",
}

#: The IV Portfolio board's Urgentie, which is the same idea in Dutch and one step
#: shorter: "Hoog" is the board's top, so it reads as `serious` like "High" does.
URGENCY_TONES: dict[str, str] = {
    "Hoog": "serious",
    "Middel": "warning",
    "Laag": "neutral",
}


def _labelled(label: str, tones: dict[str, str], cls: str = "") -> Any:
    """A label wearing its board's tone. Empty stays empty — no mark for no state — and a
    label the board no longer offers is `neutral`, never an error."""
    if not label:
        return ""
    return tag(label, tones.get(label, "neutral"), cls=cls)


def status_tag(label: str) -> Any:
    """A status label with its tone dot."""
    return _labelled(label, STATUS_TONES)


def priority_tag(label: str) -> Any:
    """A priority label with its tone mark: a small square, so it never reads as a status."""
    return _labelled(label, PRIORITY_TONES, cls="priority")


def urgency_tag(label: str) -> Any:
    """An Urgentie label, marked like a priority — because that is what it is."""
    return _labelled(label, URGENCY_TONES, cls="priority")


def stuck_tag(label: str) -> Any:
    """The blocked marker. Always the critical tone, and always with a word beside it,
    so "stuck" is never carried by colour alone."""
    return tag(label, "critical")


def tag(label: str, tone: str, cls: str = "") -> Any:
    """A coloured mark beside a label. The label is the meaning; the mark is the glance."""
    return Span(Span(cls="dot", aria_hidden="true"), label, cls=f"tag tone-{tone} {cls}".strip())


def initials(name: str) -> str:
    """Two letters for the avatar: first and last word, so "Fransje van Oorschot" is FO."""
    words = [w for w in name.replace(",", " ").split() if w]
    if not words:
        return "?"
    return (words[0][0] + (words[-1][0] if len(words) > 1 else "")).upper()


def avatar(name: str, photo: str = "") -> Any:
    """A 24px round avatar: the profile photo when monday.com has one, initials otherwise.

    The initials are always rendered underneath, so a photo URL that stops resolving
    degrades to letters rather than to a broken-image glyph.
    """
    return Span(
        initials(name),
        Img(src=photo, alt="", loading="lazy", referrerpolicy="no-referrer", onerror="this.remove()")
        if photo
        else None,
        cls="avatar",
        aria_hidden="true",
    )


def person(name: str, photo: str = "") -> Any:
    """Avatar plus name. The name is the accessible content; the avatar is decoration."""
    return Span(avatar(name, photo), name, cls="person", title=name)


def people(names: str, photo_for: Callable[[str], str] = lambda _: "") -> Any:
    """A comma-joined people column ("Agnes Dubbink, Jelle de Jong") as a row of persons."""
    listed = [n.strip() for n in names.split(",") if n.strip()]
    if not listed:
        return ""
    if len(listed) == 1:
        return person(listed[0], photo_for(listed[0]))
    return Span(*[person(n, photo_for(n)) for n in listed], cls="people")


def verdict_text(b: Burndown) -> str:
    """`Burndown.verdict` in Dutch: the same `standing`, other words."""
    kind, points = b.standing
    return {
        "over": "sprint voorbij",
        "over-left": f"sprint voorbij, nog {fmt(points)} over",
        "on-track": "op schema",
        "ahead": f"{fmt(points)} punten voor",
        "behind": f"{fmt(points)} punten achter",
    }[kind]


def nice_ceiling(value: float) -> tuple[float, float]:
    """Round `value` up to a clean axis maximum, and pick a clean tick step."""
    if value <= 0:
        return 1.0, 1.0
    for step in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if value / step <= 6:
            return float(math.ceil(value / step) * step), float(step)
    return value, value / 5


def burndown_svg(b: Burndown) -> Any:
    """The chart itself."""
    span = max(len(b.days) - 1, 1)
    top, step = nice_ceiling(max([b.committed, *(d.ideal for d in b.days)]))

    def x(i: int) -> float:
        return PAD_L + PLOT_W * i / span

    def y(v: float) -> float:
        return PAD_T + PLOT_H * (1 - v / top)

    # Recessive grid, hairline and solid. Value labels sit outside the plot.
    ticks = []
    value = 0.0
    while value <= top + 1e-9:
        ticks.append(value)
        value += step
    grid = [
        G(
            Line(x1=PAD_L, y1=y(t), x2=W - PAD_R, y2=y(t), stroke="var(--grid)", stroke_width=1),
            Text(fmt(t), x=PAD_L - 8, y=y(t) + 4, text_anchor="end", cls="tick"),
        )
        for t in ticks
    ]

    # One date label roughly every three days, always including both ends.
    every = max(1, round(span / 6))
    x_labels = [
        Text(
            f"{d.on.day}/{d.on.month}",
            x=x(i),
            y=H - PAD_B + 18,
            text_anchor="middle" if 0 < i < span else ("start" if i == 0 else "end"),
            cls="tick",
        )
        for i, d in enumerate(b.days)
        if i % every == 0 or i == span
    ]

    ideal = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(d.ideal):.1f}" for i, d in enumerate(b.days))
    actual_pts = [(i, d.remaining) for i, d in enumerate(b.days) if d.remaining is not None]
    actual = " ".join(f"{'M' if n == 0 else 'L'}{x(i):.1f},{y(v):.1f}" for n, (i, v) in enumerate(actual_pts))

    lines = [
        # Dashing is the ideal line's secondary encoding, so it never rests on hue alone.
        Path(
            d=ideal,
            fill="none",
            stroke="var(--series-ideal)",
            stroke_width=2,
            stroke_dasharray="5 4",
            stroke_linecap="round",
        ),
        Path(
            d=actual,
            fill="none",
            stroke="var(--series-actual)",
            stroke_width=2,
            stroke_linejoin="round",
            stroke_linecap="round",
        ),
    ]

    # End marker on the line that matters, ringed in the surface colour so it stays
    # legible where it crosses the ideal line.
    marks = []
    if actual_pts:
        i, v = actual_pts[-1]
        marks.append(
            Circle(cx=x(i), cy=y(v), r=5, fill="var(--series-actual)", stroke="var(--surface-1)", stroke_width=2)
        )
        marks.append(
            Text(
                f"nog {fmt(v)}",
                x=x(i) - 10,
                y=y(v) - 10,
                text_anchor="end",
                fill="var(--text-secondary)",
                cls="direct",
            )
        )
    # Park the ideal label on an empty stretch of its own line rather than at the end,
    # where it would sit on top of the line it is naming.
    at = max(1, int(span * 0.72))
    labels = [
        Text(
            "ideaal",
            x=x(at),
            y=y(b.days[at].ideal) - 11,
            text_anchor="middle",
            fill="var(--text-muted)",
            cls="direct",
        )
    ]

    # Invisible per-day hit targets, wider than the marks, each carrying a tooltip.
    band = PLOT_W / span
    hits = [
        Rect(
            x=x(i) - band / 2,
            y=PAD_T,
            width=band,
            height=PLOT_H,
            fill="transparent",
            cls="hit",
        )(
            Title(
                f"{d.on} · "
                + (f"nog {fmt(d.remaining)}" if d.remaining is not None else "nog niet")
                + f" · ideaal {fmt(round(d.ideal))}"
                + (f" · {fmt(d.burned)} afgerond" if d.burned else "")
            )
        )
        for i, d in enumerate(b.days)
    ]

    today_line = []
    if b.start <= b.today <= b.end:
        tx = x((b.today - b.start).days)
        today_line = [Line(x1=tx, y1=PAD_T, x2=tx, y2=PAD_T + PLOT_H, stroke="var(--grid)", stroke_width=1)]

    return Svg(
        *grid,
        *today_line,
        *x_labels,
        *lines,
        *marks,
        *labels,
        *hits,
        viewBox=f"0 0 {W} {H}",
        role="img",
        aria_label=(
            f"Burndown van {b.committed:g} punten op {b.start} naar nog {fmt(b.remaining)} "
            f"op {b.today}; {verdict_text(b)}."
        ),
    )


# Small-multiple geometry: no axes, because the big chart above carries them and every
# multiple shares its window; a baseline and a today tick are enough to read the shape.
SW, SH, SPAD = 240, 80, 6


def burndown_small(b: Burndown) -> Any:
    """One person's burndown as a sparkline-sized chart: ideal, actual, end marker."""
    span = max(len(b.days) - 1, 1)
    top = max([b.committed, *(d.ideal for d in b.days), 1.0])

    def x(i: int) -> float:
        return SPAD + (SW - 2 * SPAD) * i / span

    def y(v: float) -> float:
        return SPAD + (SH - 2 * SPAD) * (1 - v / top)

    ideal = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(d.ideal):.1f}" for i, d in enumerate(b.days))
    pts = [(i, d.remaining) for i, d in enumerate(b.days) if d.remaining is not None]
    actual = " ".join(f"{'M' if n == 0 else 'L'}{x(i):.1f},{y(v):.1f}" for n, (i, v) in enumerate(pts))
    marks: list[Any] = []
    if pts:
        i, v = pts[-1]
        marks.append(
            Circle(cx=x(i), cy=y(v), r=4, fill="var(--series-actual)", stroke="var(--surface-1)", stroke_width=2)
        )
    today: list[Any] = []
    if b.start <= b.today <= b.end:
        tx = x((b.today - b.start).days)
        today = [Line(x1=tx, y1=SPAD, x2=tx, y2=SH - SPAD, stroke="var(--grid)", stroke_width=1)]
    return Svg(
        Line(x1=SPAD, y1=SH - SPAD, x2=SW - SPAD, y2=SH - SPAD, stroke="var(--grid)", stroke_width=1),
        *today,
        Path(d=ideal, fill="none", stroke="var(--series-ideal)", stroke_width=1.5, stroke_dasharray="4 3"),
        Path(d=actual, fill="none", stroke="var(--series-actual)", stroke_width=2, stroke_linejoin="round"),
        *marks,
        Title(f"{fmt(b.committed)} toegezegd, nog {fmt(b.remaining)} — {verdict_text(b)}"),
        viewBox=f"0 0 {SW} {SH}",
        role="img",
        aria_label=f"Nog {fmt(b.remaining)} van {fmt(b.committed)} punten; {verdict_text(b)}.",
    )


def multiple(heading: Any, b: Burndown) -> Any:
    """One small-multiple card: who, how they stand, and the shape of their sprint."""
    return Div(
        Header(heading),
        burndown_small(b),
        Footer(
            tag(verdict_text(b), verdict_tone(b)),
            Span(f"nog {fmt(b.remaining)} van {fmt(b.committed)}", cls="figures"),
        ),
        cls="multiple",
    )


def legend() -> Any:
    """Always present for two series, so identity is never carried by colour alone."""
    return Div(
        Small(
            Span(cls="swatch", style="border-top: 2px solid var(--series-actual)"),
            "Werkelijk resterend",
            Span(cls="swatch", style="border-top: 2px dashed var(--series-ideal); margin-left: 1.25rem"),
            "Ideaal",
        ),
        style="color: var(--text-secondary)",
    )


def verdict_tone(b: Burndown) -> str:
    """The tone of the burndown's headline: green ahead, amber behind, red well behind."""
    if b.today > b.end:
        return "good" if b.remaining <= 0 else "neutral"
    if b.on_track or abs(b.ahead_by) < 0.5:
        return "good"
    return "critical" if b.committed and -b.ahead_by > 0.25 * b.committed else "warning"


def kpis(b: Burndown) -> Any:
    """The headline numbers. These are stat tiles, not a chart — the number is the point.

    Only the Remaining tile carries a tone, because only it holds a judgement; the
    others are counts, and a row of coloured tiles would say nothing.
    """
    tiles = [
        ("Toegezegd", fmt(b.committed), "punten in de sprintgroep", "tone-brand"),
        ("Klaar", fmt(b.done), f"{b.counts.get('Done', 0)} taken", ""),
        ("Resterend", fmt(b.remaining), tag(verdict_text(b), verdict_tone(b)), f"tone-{verdict_tone(b)}"),
    ]
    if b.cancelled:
        tiles.append(("Vervallen", fmt(b.cancelled), "geschrapt, niet afgerond", ""))
    return Div(*[tile(label, value, note, tone) for label, value, note, tone in tiles], cls="kpis")


def tile(label: str, value: Any, note: Any = None, tone: str = "", **attrs: Any) -> Any:
    """One stat tile: a label, the figure it is about, and a line of context under it."""
    return Div(Small(label), Strong(value), Small(note), cls=f"kpi {tone}".strip(), **attrs)


def points_tiles(total: Points) -> list[Any]:
    """The Done / Left / Cancelled tiles every points summary shows, in that order.

    Cancelled appears only when there is some: a zero tile for dropped work says nothing.
    """
    tiles = [
        tile("Klaar", fmt(total.done), "story points", "tone-good"),
        tile("Te gaan", fmt(total.remaining), "story points", "tone-active"),
    ]
    if total.cancelled:
        tiles.append(tile("Vervallen", fmt(total.cancelled), "geschrapt, telt niet mee"))
    return tiles


def progress_tile(total: Points) -> Any:
    """The selection's own battery: the same meter as every row, at double length."""
    return Div(
        Small("Voortgang"),
        battery(total.done, total.remaining, wide=True),
        cls="kpi wide",
    )


def burndown_table(b: Burndown) -> Any:
    """The same numbers as a table — the accessible view of the chart."""
    rows = [
        Tr(
            Td(str(d.on)),
            Td(fmt(round(d.ideal)), style="text-align:right"),
            Td(fmt(d.remaining) if d.remaining is not None else "—", style="text-align:right"),
            Td(fmt(d.burned) if d.burned else "", style="text-align:right"),
        )
        for d in b.days
    ]
    return Div(
        Table(
            Caption(Small("Elke dag van de sprint, in punten.")),
            Thead(
                Tr(
                    Th("Dag"),
                    Th("Ideaal", style="text-align:right"),
                    Th("Resterend", style="text-align:right"),
                    Th("Afgerond", style="text-align:right"),
                )
            ),
            Tbody(*rows),
        ),
    )


def battery(done: float, remaining: float, wide: bool = False) -> Any:
    """Story points done against points still open, as a meter.

    One measure, so no legend: the fill is how much of the epic is burnt down and the
    value beside it says so in words. Every track is the same width, so two rows
    compare by fill alone. In a table row the value is the percentage — the two
    columns to its left already hold the absolute points — while `wide`, the headline
    variant at double length, spells out done/total as well. An epic with no tasks yet
    gets an outlined empty track rather than a 0% fill: there is nothing to be 0% of.
    """
    total = done + remaining
    cls = "battery wide" if wide else "battery"
    if not total:
        return Div(
            Div(cls="track"),
            Span("geen taken", cls="value"),
            cls=f"{cls} empty",
            title="Er zijn nog geen sprinttaken aan gekoppeld",
        )
    percent = done / total * 100
    return Div(
        Div(
            Div(cls="fill", style=f"width: {percent:.1f}%"),
            cls="track",
            role="meter",
            aria_valuenow=f"{done:g}",
            aria_valuemin="0",
            aria_valuemax=f"{total:g}",
            aria_label=f"{fmt(done)} van {fmt(total)} story points klaar",
        ),
        Span(f"{fmt(done)}/{fmt(total)} · {percent:.0f}%" if wide else f"{percent:.0f}%", cls="value"),
        cls=cls,
        title=f"{fmt(done)} klaar, {fmt(remaining)} nog open, {fmt(total)} in totaal",
    )


#: The load meter's full width, as a fraction of capacity: room to show a discipline half
#: again as overbooked before the fill runs off the end. Fixed, so every row compares.
LOAD_SCALE = 1.5


def load_meter(points: float, capacity: float) -> Any:
    """Work queued against capacity, as a meter with a tick where capacity runs out.

    The same track as the battery, so the page reads as one system, but the question is
    the other way round: a full battery is good news, a meter past its tick is not. What
    lies beyond the tick wears the critical tone and says "overbooked" beside it.
    """
    if not capacity:
        return Div(
            Div(cls="track"),
            Span("niemand" if points else "—", cls="value"),
            cls="battery load empty",
            title="Niemand op Capaciteit heeft deze rol" if points else "Niets ingepland, niemand om het te doen",
        )
    load = points / capacity
    within = min(load, 1) / LOAD_SCALE * 100
    over = max(min(load, LOAD_SCALE) - 1, 0) / LOAD_SCALE * 100
    overbooked = load > LOAD_BAND[1]
    value: Any = tag(f"{load:.0%} · overboekt", "critical") if overbooked else f"{load:.0%}"
    return Div(
        Div(
            Div(cls="fill", style=f"width: {within:.1f}%") if within else None,
            # Past 100% but inside the target band is still on target: green, not red.
            Div(cls="over" if overbooked else "over ok", style=f"width: {over:.1f}%") if over else None,
            Span(cls="mark", style=f"left: {100 / LOAD_SCALE:.1f}%", aria_hidden="true"),
            cls="track",
            role="meter",
            aria_valuenow=f"{points:.1f}",
            aria_valuemin="0",
            aria_valuemax=f"{capacity:.1f}",
            aria_label=f"{fmt(round(points, 1))} van {fmt(round(capacity, 1))} story points capaciteit",
        ),
        Span(value, cls="value"),
        cls="battery load",
        title=f"{fmt(round(points, 1))} ingepland, {fmt(round(capacity, 1))} capaciteit",
    )


# --- the planning's two horizontal bar charts -----------------------------------------
# One row per discipline, side by side, in the same order: what each discipline *can* do
# this quarter, and how much of that the selection books. HTML rather than SVG, because
# the rows share the page's grid and wrap with it; every value is spelled out at the end
# of its bar, and the bar itself carries the tooltip.


def booked_scale(loads: list[float]) -> tuple[float, float]:
    """The booked chart's axis: up to the highest load (never below the load meter's
    `LOAD_SCALE`, so the band and the 100% line always have room), rounded up to a clean
    step — 50% steps up to 300%, whole hundreds above that, so 360% reads on a 0–400% axis
    and the bars keep their real proportions to each other."""
    top = max([LOAD_SCALE, *loads])
    step = 0.5 if top <= 3 else 1.0 if top <= 6 else 2.0
    return math.ceil(top / step - 1e-9) * step, step


def _ticks(top: float, step: float, label: Callable[[float], str]) -> Any:
    """The value axis under a bar chart: recessive labels at every step."""
    marks = []
    value = 0.0
    while value <= top + 1e-9:
        marks.append(Span(label(value), style=f"left: {value / top * 100:.1f}%"))
        value += step
    return Div(Span(cls="hlabel"), Div(*marks, cls="hticks"), Span(cls="hvalue"), cls="hrow haxis", aria_hidden="true")


def _gridlines(top: float, step: float) -> list[Any]:
    lines = []
    value = step
    while value < top - 1e-9:
        lines.append(Span(cls="hgrid", style=f"left: {value / top * 100:.1f}%"))
        value += step
    return lines


def _hchart(legend: list[Any], rows: list[Any], top: float, step: float, label: Callable[[float], str]) -> Any:
    """A horizontal bar chart: its legend, its rows, the axis under them."""
    return Div(Div(*legend, cls="hlegend"), *rows, _ticks(top, step, label), cls="hbars")


def _hrow(key: str, name: str, marks: list[Any], top: float, step: float, aria: str, title: str, value: Any) -> Any:
    """One discipline's row: its label, its marks over the gridlines, its value spelled out."""
    return Div(
        Span(Strong(key), " ", Small(name), cls="hlabel"),
        Div(*_gridlines(top, step), *marks, cls="hplot", role="img", aria_label=aria, title=title),
        Span(*value, cls="hvalue"),
        cls="hrow",
    )


def _at(value: float, top: float) -> str:
    return f"{value / top * 100:.1f}%"


def capacity_chart(rows: list[tuple[str, str, float, float]]) -> Any:
    """STP per discipline in the quarter: what Capaciteit gives, against the ceiling.

    `rows` are (key, name, actual, at 100% availability). An emphasis chart, not two peer
    series: the actual capacity is the solid accent bar, the 100% ceiling the lighter
    step of the same blue behind it, so the gap between them is the availability given
    away. Both numbers are written out at the end of the row.
    """
    top, step = nice_ceiling(max([full for *_, full in rows] + [1.0]))
    body = [
        _hrow(
            key,
            name,
            [
                Span(cls="hbar ceiling", style=f"width: {_at(full, top)}"),
                Span(cls="hbar actual", style=f"width: {_at(actual, top)}"),
            ],
            top,
            step,
            f"{key}: {actual:.1f} STP beschikbaar, {full:.1f} bij 100% beschikbaarheid",
            f"{key} · {name}: {actual:.1f} STP beschikbaar van {full:.1f} bij 100% beschikbaarheid",
            [Strong(f"{actual:.1f}"), Small(f" / {full:.1f}")],
        )
        for key, name, actual, full in rows
    ]
    legend = [
        Span(Span(cls="key actual"), "Beschikbaar volgens Capaciteit"),
        Span(Span(cls="key ceiling"), "Bij 100% beschikbaarheid"),
    ]
    return _hchart(legend, body, top, step, fmt)


def booked_chart(rows: list[tuple[str, str, float | None, float, float]]) -> Any:
    """The selection's STP per discipline as a share of its actual capacity.

    `rows` are (key, name, load, booked STP, capacity STP); a load of `None` is work with
    nobody to do it. One scale for every row, up to the highest load (`booked_scale`), so
    360% is visibly longer than 253%; the target band shaded, 100% as a line, and each bar
    in its band's tone — with the percentage in words, so the tone is never the only signal.
    """
    top, step = booked_scale([load for _, _, load, *_ in rows if load is not None])
    low, high = LOAD_BAND
    body = []
    for key, name, load, booked, capacity in rows:
        tone = load_tone(load) if booked else "neutral"
        # Nothing booked and nobody to do it is not "0%": there is nothing to measure.
        text = "—" if not capacity and not booked else "niemand" if load is None else f"{load:.0%}"
        marks = [
            Span(cls="hband", style=f"left: {_at(low, top)}; width: {_at(high - low, top)}"),
            Span(cls=f"hbar booked tone-{tone}", style=f"width: {_at(load, top)}") if load else None,
            Span(cls="htarget", style=f"left: {_at(1, top)}"),
        ]
        body.append(
            _hrow(
                key,
                name,
                marks,
                top,
                step,
                f"{key}: {text} geboekt, {booked:.1f} van {capacity:.1f} STP",
                f"{key} · {name}: {booked:.1f} STP geboekt van {capacity:.1f} STP capaciteit",
                [tag(text, tone), Small(f" {booked:.0f}/{capacity:.0f}")],
            )
        )
    legend = [
        tag(f"onder {low:.0%}: {LOAD_WORDS['active']}", "active"),
        tag(f"{low:.0%}–{high:.0%}: {LOAD_WORDS['good']}", "good"),
        tag(f"boven {high:.0%}: {LOAD_WORDS['critical']}", "critical"),
    ]
    return _hchart(legend, body, top, step, lambda v: f"{v:.0%}")
