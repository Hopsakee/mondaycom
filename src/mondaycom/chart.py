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

# Geometry, in SVG user units. The viewBox scales to whatever width the page gives it.
W, H = 720, 300
PAD_L, PAD_R, PAD_T, PAD_B = 46, 18, 16, 34
PLOT_W = W - PAD_L - PAD_R
PLOT_H = H - PAD_T - PAD_B

# Roles, not raw hex, everywhere below. Dark steps are chosen for the dark surface and
# validated as a set; the toggle scope must beat the OS media query in both directions.
# The tokens sit on :root so the tables outside the charts (a status tag in the task
# list, an avatar in a filter summary) speak the same palette as the charts do.
#
# Tones are the reference status palette, which is fixed across themes and deliberately
# distinct from the categorical slots so a state never impersonates a series:
#   good #0ca30c · warning #fab219 · serious #ec835a · critical #d03b3b
# `active` is the one accent hue (the burndown's actual line, the battery fill) and
# `neutral` is the ink-grey for "not started". Warning and serious sit below 3:1 on the
# light surface by design, so every tone ships as dot + label, never as colour alone.
#: The dark steps, written once: the media query and the explicit `data-theme` scope
#: both need them, and a palette tweak that lands in only one of the two is invisible
#: until somebody switches themes by hand.
_DARK = """
  --surface-1: #1a1a19;
  --text-secondary: #c3c2b7;
  --text-muted: #a3a299;
  --grid: #33332f;
  --hairline: rgba(255, 255, 255, .10);
  --series-actual: #3987e5;
  --series-ideal: #8f8f88;
  --meter-track: #104281;
  --tone-active: #3987e5;
  --tone-neutral: #8f8f88;
  --tone-off: #52514e;
  --avatar-bg: #33332f;
  --avatar-ink: #c3c2b7;
"""

CHART_CSS = """
:root {
  --surface-1: #fcfcfb;
  --text-secondary: #52514e;
  --text-muted: #78766f;
  --grid: #e6e5e1;
  --hairline: rgba(11, 11, 11, .10);
  --series-actual: #2a78d6;
  --series-ideal: #8a8a85;
  --meter-track: #cde2fb;
  --tone-good: #0ca30c;
  --tone-warning: #fab219;
  --tone-serious: #ec835a;
  --tone-critical: #d03b3b;
  --tone-active: #2a78d6;
  --tone-neutral: #8a8a85;
  --tone-off: #c3c2b7;
  --avatar-bg: #e6e5e1;
  --avatar-ink: #52514e;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {__DARK__}
}
:root[data-theme="dark"] {__DARK__}
.viz svg { width: 100%; height: auto; display: block; }
.viz .tick { fill: var(--text-muted); font-size: 11px; }
.viz .direct { font-size: 12px; font-weight: 600; }
.viz figcaption { color: var(--text-secondary); font-size: .85rem; }
.viz .hit:hover { fill: color-mix(in srgb, var(--series-actual) 8%, transparent); }

/* Stat tiles: label, value, note. The value is the point, so it is the one big thing on
   the row; proportional figures, because nothing here has to align vertically. */
.kpis { display: flex; flex-wrap: wrap; gap: .75rem 1.25rem; margin: .5rem 0 1rem; }
.kpi {
  flex: 1 1 9rem; padding: .55rem .8rem .6rem; border-radius: .5rem;
  border: 1px solid var(--hairline); border-top: 3px solid var(--grid);
}
.kpi small { color: var(--text-muted); display: block; font-size: .8rem; line-height: 1.3; }
.kpi strong { font-size: 1.75rem; font-weight: 600; line-height: 1.15; display: block; margin: .1rem 0; }
.kpi .battery { margin-top: .45rem; }
.kpi.tone-good { border-top-color: var(--tone-good); }
.kpi.tone-warning { border-top-color: var(--tone-warning); }
.kpi.tone-serious { border-top-color: var(--tone-serious); }
.kpi.tone-critical { border-top-color: var(--tone-critical); }
.kpi.tone-active { border-top-color: var(--tone-active); }
.swatch { display: inline-block; width: 22px; height: 0; vertical-align: middle;
          border-top-width: 2px; margin-right: .35rem; }

/* A state as a tag: a coloured dot beside the label. The label carries the meaning
   and stays in ink; the dot is the glance channel. */
.tag { display: inline-flex; align-items: center; gap: .4rem; white-space: nowrap; line-height: 1.2; }
.tag .dot {
  flex: none; width: .6rem; height: .6rem; border-radius: 50%;
  background: var(--tone); box-shadow: 0 0 0 1px color-mix(in srgb, var(--tone) 35%, transparent);
}
.tag.tone-off .dot { background: none; box-shadow: inset 0 0 0 2px var(--tone); }
.tag.tone-off { color: var(--text-muted); }
.tone-good { --tone: var(--tone-good); }
.tone-warning { --tone: var(--tone-warning); }
.tone-serious { --tone: var(--tone-serious); }
.tone-critical { --tone: var(--tone-critical); }
.tone-active { --tone: var(--tone-active); }
.tone-neutral { --tone: var(--tone-neutral); }
.tone-off { --tone: var(--tone-off); }
.tag.priority .dot { border-radius: 2px; }

/* A person: a 24px round avatar and the name. The photo sits over the initials, so a
   picture that fails to load falls back to the letters instead of a broken image. */
.person { display: inline-flex; align-items: center; gap: .45rem; white-space: nowrap; }
.people { display: flex; flex-wrap: wrap; gap: .25rem .9rem; }
.avatar {
  position: relative; flex: none; width: 24px; height: 24px; border-radius: 50%;
  background: var(--avatar-bg); color: var(--avatar-ink); overflow: hidden;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: .62rem; font-weight: 600; letter-spacing: .02em; text-transform: uppercase;
  box-shadow: inset 0 0 0 1px var(--hairline);
}
.avatar img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }

/* The battery: a meter, so one fill on a track of a lighter step of the same blue
   ramp (light 100 / dark 650) rather than two peer series. Every track is the same
   fixed width so the fills compare across rows; the numbers beside it sit in a
   fixed-width slot for the same reason. They are always spelled out — the track is
   deliberately low-contrast, and a meter with no readable value is decoration. */
.battery { display: inline-flex; align-items: center; gap: .55rem; }
.battery .track {
  flex: none; width: 7rem; height: 8px; border-radius: 4px; overflow: hidden;
  background: var(--meter-track);
}
.battery .fill { height: 100%; border-radius: 4px; background: var(--series-actual); }
.battery .value { color: var(--text-secondary); font-size: .75rem; white-space: nowrap;
                  font-variant-numeric: tabular-nums; min-width: 2.6rem; }
.battery.empty .track { background: none; box-shadow: inset 0 0 0 1px var(--grid); }
.battery.empty .value { color: var(--text-muted); }
.battery.wide .track { width: 14rem; }
.battery.wide .value { min-width: 6rem; font-size: .85rem; }

/* Status chips: one tag per status with its count, the pressed one outlined. They are
   buttons, so they are keyboard-reachable, but they read as filter tokens. */
.chips { display: flex; flex-wrap: wrap; gap: .4rem; margin: .2rem 0 .9rem; }
.chip {
  all: unset; cursor: pointer; display: inline-flex; align-items: center; gap: .45rem;
  padding: .2rem .65rem; border-radius: 999px; font: inherit; font-size: .85rem;
  box-shadow: inset 0 0 0 1px var(--hairline);
}
.chip:hover { background: color-mix(in srgb, var(--tone-active) 8%, transparent); }
.chip:focus-visible { outline: 2px solid var(--pico-primary-focus, #0172ad); outline-offset: 2px; }
.chip[aria-pressed="true"] { box-shadow: inset 0 0 0 2px var(--tone-active); }
.chip .count { color: var(--text-muted); font-variant-numeric: tabular-nums; }

/* The stuck marker: a critical tag you can open, because "blocked" is only actionable
   if you can reach the thing doing the blocking. Closed it is one tag wide, so a table
   of running epics stays quiet; open it lists the blockers as links out to monday.com. */
.stuck { display: inline-block; }
/* Three markers to suppress, not one: `display: inline-block` takes the summary off
   `list-item` (the UA triangle), `list-style` covers the browsers that ignore that, and
   `::after` is Pico's own chevron. The tag's dotted underline is what says "openable". */
.stuck > summary { display: inline-block; cursor: pointer; list-style: none; }
.stuck > summary::marker, .stuck > summary::-webkit-details-marker { content: ""; display: none; }
.stuck > summary::after { display: none; }
.stuck > summary:focus-visible { outline: 2px solid var(--pico-primary-focus, #0172ad); outline-offset: 2px; }
.stuck > summary .tag { text-decoration: underline dotted; text-underline-offset: 3px; }
/* Wide enough for a task title to be readable, capped so opening one does not push the
   Progress meter out of the scroll window. */
.blockers { list-style: none; margin: .4rem 0 .2rem; padding: 0; font-size: .82rem;
            min-width: 10rem; max-width: 13rem; }
.blockers li { list-style: none; margin: 0 0 .25rem; white-space: normal; }
.blockers li + li.epic { margin-top: .5rem; }
.blockers .where { color: var(--text-muted); font-size: .9em; display: block; }
.blockers ul { list-style: none; margin: .15rem 0 0; padding-left: .85rem;
               border-left: 2px solid var(--hairline); }

/* Small multiples: one burndown per person, each to its own scale, on the sprint's
   shared window. Each is a card with the person on top and the verdict as its tone. */
.multiples { display: grid; grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr)); gap: .75rem; }
.multiple { border: 1px solid var(--hairline); border-radius: .5rem; padding: .5rem .7rem .45rem; min-width: 0; }
.multiple header { display: flex; align-items: center; font-size: .85rem; margin-bottom: .3rem; min-width: 0; }
.multiple header .person { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.multiple footer { display: flex; justify-content: space-between; align-items: center; gap: .5rem;
                   margin-top: .25rem; font-size: .78rem; }
.multiple footer .figures { color: var(--text-muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
""".replace("__DARK__", _DARK)


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
                f"{fmt(v)} left",
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
            "ideal",
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
                f"{d.on:%a %d %b} · "
                + (f"{fmt(d.remaining)} left" if d.remaining is not None else "not yet")
                + f" · ideal {fmt(round(d.ideal))}"
                + (f" · burned {fmt(d.burned)}" if d.burned else "")
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
            f"Burndown from {b.committed:g} points on {b.start} to {fmt(b.remaining)} left on {b.today}; {b.verdict}."
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
        Title(f"{fmt(b.committed)} committed, {fmt(b.remaining)} left — {b.verdict}"),
        viewBox=f"0 0 {SW} {SH}",
        role="img",
        aria_label=f"{fmt(b.remaining)} of {fmt(b.committed)} points left; {b.verdict}.",
    )


def multiple(heading: Any, b: Burndown) -> Any:
    """One small-multiple card: who, how they stand, and the shape of their sprint."""
    return Div(
        Header(heading),
        burndown_small(b),
        Footer(tag(b.verdict, verdict_tone(b)), Span(f"{fmt(b.remaining)} of {fmt(b.committed)} left", cls="figures")),
        cls="multiple",
    )


def legend() -> Any:
    """Always present for two series, so identity is never carried by colour alone."""
    return Div(
        Small(
            Span(cls="swatch", style="border-top: 2px solid var(--series-actual)"),
            "Actual remaining",
            Span(cls="swatch", style="border-top: 2px dashed var(--series-ideal); margin-left: 1.25rem"),
            "Ideal",
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
        ("Committed", fmt(b.committed), "points in the sprint group", ""),
        ("Done", fmt(b.done), f"{b.counts.get('Done', 0)} tasks", ""),
        ("Remaining", fmt(b.remaining), tag(b.verdict, verdict_tone(b)), f"tone-{verdict_tone(b)}"),
    ]
    if b.cancelled:
        tiles.append(("Cancelled", fmt(b.cancelled), "dropped, not burned", ""))
    return Div(*[tile(label, value, note, tone) for label, value, note, tone in tiles], cls="kpis")


def tile(label: str, value: Any, note: Any = None, tone: str = "", **attrs: Any) -> Any:
    """One stat tile: a label, the figure it is about, and a line of context under it."""
    return Div(Small(label), Strong(value), Small(note), cls=f"kpi {tone}".strip(), **attrs)


def points_tiles(total: Points) -> list[Any]:
    """The Done / Left / Cancelled tiles every points summary shows, in that order.

    Cancelled appears only when there is some: a zero tile for dropped work says nothing.
    """
    tiles = [
        tile("Done", fmt(total.done), "story points", "tone-good"),
        tile("Left", fmt(total.remaining), "story points", "tone-active"),
    ]
    if total.cancelled:
        tiles.append(tile("Cancelled", fmt(total.cancelled), "dropped, not counted"))
    return tiles


def progress_tile(total: Points) -> Any:
    """The selection's own battery: the same meter as every row, at double length."""
    return Div(
        Small("Progress"),
        battery(total.done, total.remaining, wide=True),
        cls="kpi",
        style="flex-grow: 2",
    )


def burndown_table(b: Burndown) -> Any:
    """The same numbers as a table — the accessible view of the chart."""
    rows = [
        Tr(
            Td(f"{d.on:%a %d %b}"),
            Td(fmt(round(d.ideal)), style="text-align:right"),
            Td(fmt(d.remaining) if d.remaining is not None else "—", style="text-align:right"),
            Td(fmt(d.burned) if d.burned else "", style="text-align:right"),
        )
        for d in b.days
    ]
    return Div(
        Table(
            Caption(Small("Every day of the sprint, in points.")),
            Thead(
                Tr(
                    Th("Day"),
                    Th("Ideal", style="text-align:right"),
                    Th("Remaining", style="text-align:right"),
                    Th("Burned", style="text-align:right"),
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
            Span("no tasks", cls="value"),
            cls=f"{cls} empty",
            title="No sprint tasks are linked to this epic yet",
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
            aria_label=f"{fmt(done)} of {fmt(total)} story points done",
        ),
        Span(f"{fmt(done)}/{fmt(total)} · {percent:.0f}%" if wide else f"{percent:.0f}%", cls="value"),
        cls=cls,
        title=f"{fmt(done)} done, {fmt(remaining)} still open, {fmt(total)} committed",
    )
