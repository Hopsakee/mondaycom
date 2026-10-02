"""The WDODelta huisstijl, as one stylesheet and the page chrome that wears it.

The rules come from the organisation's huisstijl (the `wdod-nicegui` skill's
HUISSTIJL.md): two blues carry every screen — donkerblauw `#075895` for headings,
primary buttons and the brand bar, blauw `#00b0ea` for accents, hover and focus — and
groen, oranje and rood are kept for state. The font stack starts with Vivala Sans
Rounded and falls straight through to Calibri, never to a look-alike web font. Corners
are 6px, shadows are soft, transitions are 150ms. Light is the default; dark is a
toggle, not the start.

Pico supplies the base; this file overrides its variables rather than its rules, so a
button or an input picks up the brand without a selector of its own. The chart and card
tokens (`chart.CHART_CSS`, `cards.CARDS_CSS`) build on the variables set here.
"""

from __future__ import annotations

from typing import Any

from fasthtml.common import A, Button, Div, Footer, Header, Script, Span

#: The brand's own colours. Nothing on a page should need a hex outside these and the
#: neutral inks below.
DONKERBLAUW = "#075895"
BLAUW = "#00b0ea"
GROEN = "#93c01f"
ORANJE = "#f29100"
ROOD = "#d74116"

FONT = '"Vivala Sans Rounded", Calibri, "Segoe UI", system-ui, sans-serif'

#: The page-wide tokens. Light is the huisstijl surface — white on a very light blue —
#: and dark is the brand's blue-on-dark, its own steps rather than an inverted light.
_LIGHT = f"""
  color-scheme: light;
  --bg: #f5fafd;
  --surface: #ffffff;
  --surface-2: #f0f6fa;
  --ink: #1a1a1a;
  --ink-2: #4a4a4a;
  --muted: #5f6b75;
  --line: #dbe5ec;
  --line-2: #e9f0f5;
  --heading: {DONKERBLAUW};
  --brand: {DONKERBLAUW};
  --brand-ink: #ffffff;
  --accent: {BLAUW};
  --link: {DONKERBLAUW};
  --hover-bg: rgba(0, 176, 234, .08);
  --shadow: 0 1px 3px rgba(7, 88, 149, .08), 0 2px 8px rgba(7, 88, 149, .04);
  --shadow-hover: 0 4px 14px rgba(7, 88, 149, .14);
  --pico-background-color: var(--bg);
  --pico-color: var(--ink);
  --pico-muted-color: var(--muted);
  --pico-muted-border-color: var(--line);
  --pico-h1-color: var(--heading);
  --pico-h2-color: var(--heading);
  --pico-h3-color: var(--heading);
  --pico-h4-color: var(--heading);
  --pico-primary: {DONKERBLAUW};
  --pico-primary-background: {DONKERBLAUW};
  --pico-primary-border: {DONKERBLAUW};
  --pico-primary-underline: rgba(7, 88, 149, .45);
  --pico-primary-hover: #04416f;
  --pico-primary-hover-background: #04416f;
  --pico-primary-hover-border: #04416f;
  --pico-primary-hover-underline: #04416f;
  --pico-primary-focus: rgba(0, 176, 234, .45);
  --pico-primary-inverse: #ffffff;
  --pico-secondary: #4a5a68;
  --pico-secondary-border: var(--line);
  --pico-secondary-hover: {DONKERBLAUW};
  --pico-secondary-hover-border: {BLAUW};
  --pico-form-element-background-color: var(--surface);
  --pico-form-element-border-color: var(--line);
  --pico-form-element-focus-color: {BLAUW};
  --pico-card-background-color: var(--surface);
  --pico-table-border-color: var(--line-2);
  --pico-code-background-color: var(--surface-2);
"""

_DARK = f"""
  color-scheme: dark;
  --bg: #0a1f33;
  --surface: #102a44;
  --surface-2: #0d2439;
  --ink: #f1f5f9;
  --ink-2: #c6d3de;
  --muted: #9fb3c4;
  --line: #24476a;
  --line-2: #1a3754;
  --heading: #ffffff;
  --brand: #0b69ad;
  --brand-ink: #ffffff;
  --accent: {BLAUW};
  --link: #5cd0f5;
  --hover-bg: rgba(0, 176, 234, .12);
  --shadow: 0 1px 3px rgba(0, 0, 0, .3);
  --shadow-hover: 0 4px 14px rgba(0, 0, 0, .45);
  --pico-background-color: var(--bg);
  --pico-color: var(--ink);
  --pico-muted-color: var(--muted);
  --pico-muted-border-color: var(--line);
  --pico-h1-color: var(--heading);
  --pico-h2-color: var(--heading);
  --pico-h3-color: var(--heading);
  --pico-h4-color: var(--heading);
  --pico-primary: #5cd0f5;
  --pico-primary-background: #0b69ad;
  --pico-primary-border: #0b69ad;
  --pico-primary-underline: rgba(92, 208, 245, .5);
  --pico-primary-hover: #8fdef8;
  --pico-primary-hover-background: {DONKERBLAUW};
  --pico-primary-hover-border: {BLAUW};
  --pico-primary-hover-underline: #8fdef8;
  --pico-primary-focus: rgba(0, 176, 234, .5);
  --pico-primary-inverse: #ffffff;
  --pico-secondary: #c6d3de;
  --pico-secondary-border: var(--line);
  --pico-secondary-hover: #ffffff;
  --pico-secondary-hover-border: {BLAUW};
  --pico-form-element-background-color: var(--surface-2);
  --pico-form-element-border-color: var(--line);
  --pico-form-element-focus-color: {BLAUW};
  --pico-card-background-color: var(--surface);
  --pico-table-border-color: var(--line-2);
  --pico-code-background-color: var(--surface-2);
"""

THEME_CSS = f"""
:root[data-theme="light"], :root:not([data-theme]) {{{_LIGHT}}}
:root[data-theme="dark"] {{{_DARK}}}
:root {{
  --pico-font-family: {FONT};
  --pico-font-family-sans-serif: {FONT};
  --pico-border-radius: 6px;
  --pico-transition: .15s ease;
  --pico-line-height: 1.5;
  --pico-font-weight: 400;
}}
body {{ background: var(--bg); color: var(--ink); font-family: {FONT}; line-height: 1.5; min-height: 100vh;
        display: flex; flex-direction: column; }}
h1, h2, h3, h4 {{ color: var(--heading); font-weight: 700; letter-spacing: normal; }}
h1 {{ font-size: 1.9rem; line-height: 1.1; margin-bottom: .3rem; }}
h2 {{ font-size: 1.35rem; margin: 1.2rem 0 .4rem; }}
h3 {{ font-size: 1.1rem; }}
a {{ color: var(--link); }}
a:hover {{ color: var(--accent); }}
:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
button, [role="button"], input, select, textarea {{ border-radius: 6px; }}
button, [role="button"] {{ font-weight: 600; }}
code, pre {{ border-radius: 6px; }}

/* The brand bar: the word mark, the app's name, the pay-off, and the theme switch. The
   official logo replaces the word mark once Afdeling Communicatie supplies the SVG. */
.brandbar {{ background: {DONKERBLAUW}; color: #ffffff; }}
.brandbar .in {{ display: flex; align-items: center; gap: .75rem; padding: .7rem 0; }}
.brandbar a.wm {{ color: var(--brand-ink); font-weight: 700; font-size: 1.2rem; text-decoration: none;
                  letter-spacing: .02em; }}
.brandbar .sep {{ opacity: .6; }}
.brandbar .app {{ font-weight: 600; }}
.brandbar .payoff {{ opacity: .85; font-size: .9rem; margin-left: .25rem; }}
.brandbar .grow {{ flex: 1; }}
.brandbar button.theme {{
  all: unset; cursor: pointer; display: inline-grid; place-items: center; width: 2rem; height: 2rem;
  border-radius: 6px; color: var(--brand-ink); font-size: 1rem; transition: background-color .15s ease;
}}
.brandbar button.theme:hover {{ background: rgba(255, 255, 255, .15); }}
.brandbar button.theme:focus-visible {{ outline: 2px solid #ffffff; outline-offset: 2px; }}

main.page {{ flex: 1; padding-top: 1.5rem; padding-bottom: 2.5rem; }}

/* The page head: one dominant H1 with its lede, the view switch on the right. */
.page-head {{ display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between;
              gap: .75rem 1.5rem; margin-bottom: .6rem; }}
.page-head h1 {{ margin: 0; }}
.page-head p.lede {{ margin: .3rem 0 0; color: var(--muted); }}

/* The pages as tabs: the current one carries the accent underline, not a link colour. */
nav.tabs {{ display: flex; gap: .25rem; border-bottom: 1px solid var(--line); margin-bottom: 1.25rem;
            overflow-x: auto; }}
nav.tabs ul {{ margin: 0; padding: 0; gap: .25rem; }}
nav.tabs li {{ padding: 0; }}
nav.tabs a {{ display: block; padding: .6rem .9rem; margin: 0; border-radius: 6px 6px 0 0;
              color: var(--muted); font-weight: 600; text-decoration: none; border-bottom: 3px solid transparent;
              transition: color .15s ease, border-color .15s ease, background-color .15s ease; }}
nav.tabs a:hover {{ color: var(--heading); background: var(--hover-bg); }}
nav.tabs a[aria-current="page"] {{ color: var(--heading); border-bottom-color: var(--accent); }}

/* A segmented switch: the table/cards view. The pressed half is the brand blue.
   `role="group"` is Pico's full-width input group; the switch is a small control. */
.seg, .seg[role="group"] {{ display: inline-flex; width: auto; margin: 0; flex: none; border: 1px solid var(--line);
                            border-radius: 6px; overflow: hidden; background: var(--surface);
                            box-shadow: var(--shadow); }}
.seg button {{
  all: unset; cursor: pointer; display: inline-flex; align-items: center; gap: .4rem;
  padding: .4rem .85rem; font-weight: 600; font-size: .9rem; color: var(--muted);
  transition: background-color .15s ease, color .15s ease;
}}
.seg button + button {{ border-left: 1px solid var(--line); }}
.seg button:hover {{ background: var(--hover-bg); color: var(--heading); }}
.seg button[aria-pressed="true"] {{ background: var(--brand); color: var(--brand-ink); }}
.seg button:focus-visible {{ outline: 2px solid var(--accent); outline-offset: -2px; }}
.seg svg {{ width: 1rem; height: 1rem; }}

/* The footer: who to ask. An internal tool keeps the contact block and drops the socials. */
footer.site {{ border-top: 1px solid var(--line); color: var(--muted); font-size: .82rem; padding: 1rem 0 1.5rem; }}
footer.site .in {{ display: flex; flex-wrap: wrap; gap: .3rem 1.5rem; }}

/* Panels: the filter form and every table sit on a surface, the page on the tint. */
form.panel, .table-wrap, details.how, .panel {{
  background: var(--surface); border: 1px solid var(--line); border-radius: 6px; box-shadow: var(--shadow);
}}
form.panel {{ padding: 1rem 1.1rem .6rem; margin-bottom: 1.25rem; font-size: .92rem;
               --pico-form-element-spacing-vertical: .45rem; --pico-form-element-spacing-horizontal: .75rem; }}
form.panel label {{ font-weight: 600; color: var(--ink-2); }}
form.panel label.switch, form.panel fieldset label {{ font-weight: 400; }}
form.panel button, form.panel [role="button"] {{ font-size: .9rem; padding: .45rem .9rem; }}
.chart-panel {{ padding: .7rem 1rem .5rem; margin-bottom: .6rem; }}
.table-wrap {{ padding: 0 .25rem; }}
.table-wrap table {{ margin-bottom: 0; }}
table th {{ color: var(--muted); font-size: .8rem; font-weight: 700; }}
table tbody tr {{ transition: background-color .15s ease; }}
table tbody tr:hover {{ background: var(--hover-bg); }}
details.how {{ padding: .6rem 1rem; }}
"""

#: Runs in <head>, before the body paints, so a dark choice never flashes white first.
THEME_JS = """
(function () {
  var t = localStorage.getItem('theme');
  if (t === 'dark' || t === 'light') document.documentElement.dataset.theme = t;
  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.querySelector('.brandbar button.theme');
    if (btn && document.documentElement.dataset.theme === 'dark') {
      btn.textContent = '☀';
      btn.setAttribute('aria-label', 'Licht thema');
    }
  });
})();
function toggleTheme(btn) {
  var root = document.documentElement;
  var next = root.dataset.theme === 'dark' ? 'light' : 'dark';
  root.dataset.theme = next;
  localStorage.setItem('theme', next);
  btn.setAttribute('aria-label', next === 'dark' ? 'Licht thema' : 'Donker thema');
  btn.textContent = next === 'dark' ? '☀' : '☾';
}
"""


def brandbar(app_name: str) -> Any:
    """The blue bar across the top: the word mark (home), the app, the internal pay-off."""
    return Header(
        Div(
            A("WDODelta", href="/", cls="wm", aria_label="WDODelta — naar de startpagina"),
            Span("·", cls="sep", aria_hidden="true"),
            Span(app_name, cls="app"),
            Span("jouw waterschap", cls="payoff"),
            Span(cls="grow"),
            Button(
                "☾",
                type="button",
                cls="theme",
                aria_label="Donker thema",
                title="Wissel tussen licht en donker",
                onclick="toggleTheme(this)",
            ),
            cls="container in",
        ),
        cls="brandbar",
    )


def site_footer() -> Any:
    """Who runs this and who to ask — the huisstijl's contact block, for an internal tool."""
    return Footer(
        Div(
            Span("Datalab · Waterschap Drents Overijsselse Delta (WDODelta)"),
            Span("Vragen of ideeën? Neem contact op met het Datalab."),
            cls="container in",
        ),
        cls="site",
    )


def theme_script() -> Any:
    return Script(THEME_JS)
