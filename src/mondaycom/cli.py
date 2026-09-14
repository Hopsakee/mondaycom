"""Command-line entry point: `monday <subcommand>`.

Each subcommand writes plain text to stdout so it composes with pipes and the
wrappers in ``scripts/``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Sequence
from typing import Any

from mondaycom import burndown as bd
from mondaycom import epics as ep
from mondaycom import lookups, portfolio, project, queries, sprint
from mondaycom.client import MondayClient, MondayError
from mondaycom.config import ASSIGNED_TO_ME, BOARDS, DAM, ME, NON_DAM, OBSIDIAN_PROJECTS_DIR, OPEN_STATUSES
from mondaycom.lookups import Choice

# `--dam` / `--no-dam` on the command line; the two values `epics.Filters` speaks.
DAM_CHOICES = {"dam": DAM, "non-dam": NON_DAM, "all": ""}


def _person_name(client: MondayClient, person: str | None) -> str:
    """Resolve `--person` to a name, for the filters that match on owner/reviewer text.

    ``me`` is the token's own user and ``all`` drops the filter; anything else is an id
    or a name substring, resolved the same way `--epic` is.
    """
    if not person or person == "all":
        return ""
    if person == "me":
        return ME
    return lookups.resolve(lookups.fetch_people(client), person).name


def cmd_sprint_tasks(args: argparse.Namespace) -> int:
    """Print the sprint tasklist as Obsidian markdown."""
    end = args.end or sprint.default_sprint_end()
    statuses = OPEN_STATUSES if args.open_only else None
    with MondayClient() as client:
        person, reviewer = ASSIGNED_TO_ME, ME
        if args.person and args.person != "me":
            if args.person == "all":
                person = None
            else:
                match = lookups.resolve(lookups.fetch_people(client), args.person)
                person, reviewer = match.id, match.name

        epic_ids = None
        if args.epic:
            epic_ids = [lookups.resolve(lookups.fetch_epics(client), args.epic).id]

        tasks = sprint.fetch_tasks(
            client,
            end,
            statuses=statuses,
            person=person,
            epic_ids=epic_ids,
            me=reviewer,
        )
        dam = DAM_CHOICES[args.dam]
        if dam:
            # Applied here rather than in the query: "is this task's epic in the IV
            # Portfolio" is a fact about the epic board, not a rule items_page can take.
            dam_scope = ep.dam_epic_ids(client)
            want = dam == DAM
            tasks = [task for task in tasks if (task.epic_id in dam_scope) is want]
    print(sprint.tasklist_markdown(tasks, end))
    return 0


def cmd_people(_: argparse.Namespace) -> int:
    """List the people you can filter on, with the ids monday.com matches against."""
    with MondayClient() as client:
        for choice in lookups.fetch_people(client):
            print(f"{choice.id:<12} {choice.name}")
    return 0


def cmd_epics(_: argparse.Namespace) -> int:
    """List every epic with its id, for --epic."""
    with MondayClient() as client:
        for choice in lookups.fetch_epics(client):
            print(f"{choice.id:<12} {choice.name}")
    return 0


def cmd_burndown(args: argparse.Namespace) -> int:
    """Print the sprint burndown: committed, done, and the ideal line day by day."""
    dam = DAM_CHOICES[args.dam]
    with MondayClient() as client:
        items = bd.fetch_sprint_items(client)
        person = _person_name(client, args.person)
        dam_scope = frozenset(ep.dam_epic_ids(client)) if dam else frozenset()
    kept = bd.narrow(items, person=person, dam=dam, dam_epics=dam_scope)
    # A person's slice holds the work they review as well, but its points are the
    # Trekker's, so the numbers come from `owned`. The sprint window is guessed from the
    # due date most of the group shares, so it has to come from the whole group and not
    # from one person's slice of it.
    board = bd.build(bd.owned(kept, person), end=args.end or None, window_from=items)

    print(f"# Sprint {board.start} - {board.end}  (today {board.today})")
    if len(kept) != len(items):
        scope = " · ".join(filter(None, (person or "everyone", args.dam if dam else "")))
        line = f"# {scope} — {len(kept)} of {len(items)} tasks in the sprint group"
        print(f"{line} · points counted as Trekker only" if person else line)
    print(
        f"committed {bd.fmt(board.committed)} · done {bd.fmt(board.done)} · "
        f"remaining {bd.fmt(board.remaining)}" + (f" · cancelled {bd.fmt(board.cancelled)}" if board.cancelled else "")
    )
    print(f"ideal today {bd.fmt(round(board.ideal_today, 1))} — {board.verdict}")
    if args.quiet:
        return 0

    print()
    print(f"{'day':12} {'ideal':>7} {'left':>7} {'burned':>7}")
    for day in board.days:
        left = bd.fmt(day.remaining) if day.remaining is not None else "-"
        marker = "  <- today" if day.on == board.today else ""
        print(f"{day.on!s:12} {round(day.ideal, 1):>7g} {left:>7} {bd.fmt(day.burned):>7}{marker}")
    return 0


#: How wide the terminal battery is, in cells.
BATTERY_CELLS = 12


def battery_bar(done: float, remaining: float) -> str:
    """The web page's battery, in text: a filled bar and the percentage.

    Truncated rather than rounded, and never empty while any point is done, so a full
    bar means finished and an empty one means nothing started — 96% must not look done.
    """
    total = done + remaining
    if not total:
        return f"{'·' * BATTERY_CELLS}    - "
    fraction = done / total
    filled = BATTERY_CELLS if fraction == 1 else max(int(fraction * BATTERY_CELLS), 1 if done else 0)
    return f"{'█' * filled}{'·' * (BATTERY_CELLS - filled)} {fraction * 100:3.0f}%"


#: Row markers, two cells wide so every name still starts in the same column.
DAM_MARK = "\u25c6"  # linked to the IV Portfolio board
STUCK_MARK = "\u26d4"  # on Impediment, or with a task that is


def marks(dam: bool = False, stuck: bool = False) -> str:
    """The flags in front of a row's name. Fixed width, so the names stay in one column."""
    return f"{DAM_MARK if dam else ' '}{STUCK_MARK if stuck else ' '} "


def cmd_epic_progress(args: argparse.Namespace) -> int:
    """Print every epic with its state and how far its story points have burnt down."""
    filters = ep.Filters(
        search=args.search or "",
        status=args.status or "",
        owner=args.owner or "",
        portfolio=args.portfolio or "",
        priority=args.priority or "",
        dam=DAM_CHOICES[args.dam],
        bucket=args.progress or "",
        stuck=args.stuck,
    )
    with MondayClient() as client:
        rows, orphans = ep.fetch_epics(client)
    shown = ep.arrange(rows, filters, sort=args.sort, desc=args.desc)

    _print_epic_rows(shown, label="item", show_dam=True)
    _print_totals(f"{len(shown)} of {len(rows)} epics", ep.totals(shown))
    print(f"{DAM_MARK} = linked to the IV Portfolio board (DAM)")
    print(f"{STUCK_MARK} = stuck: the epic is on Impediment, or a task of it is")
    _print_blockers(shown)
    if orphans.tasks:
        print(
            f"note: {orphans.tasks} sprint tasks ({bd.fmt(orphans.done + orphans.remaining)} points) "
            "link to no epic and are in none of the rows above."
        )
    return 0


def _print_epic_rows(epics: list[ep.Epic], *, label: str = "epic", show_dam: bool = False) -> None:
    """The epic lines, shared by `epic-progress` and `portfolio --item`.

    One format string, so the two commands' columns cannot drift apart. `epic-progress`
    is the only one that flags DAM: under a portfolio item every epic is DAM by
    definition, and a column with one value tells you nothing.
    """
    print(f"{'status':<15} {'trekker':<21} {'prio':<10} {'done':>6} {'left':>6}  {'progress':<18} {label}")
    for epic in epics:
        dam = {"dam": epic.is_dam} if show_dam else {}
        print(
            f"{epic.status[:14]:<15} {epic.owner[:20]:<21} {epic.priority[:9]:<10} "
            f"{bd.fmt(epic.done):>6} {bd.fmt(epic.remaining):>6}  "
            f"{battery_bar(epic.done, epic.remaining):<18} "
            f"{marks(stuck=epic.is_stuck, **dam)}{epic.name}"
        )


def _print_totals(lead: str, total: ep.Points) -> None:
    """The points line under a table. Cancelled work is named only when there is some."""
    print()
    print(
        f"{lead} · {bd.fmt(total.done)} done · {bd.fmt(total.remaining)} left"
        + (f" · {bd.fmt(total.cancelled)} cancelled" if total.cancelled else "")
    )


def _print_blockers(epics: Iterable[ep.Epic]) -> None:
    """The blocking tasks by name and address, because "stuck" is only useful if you can
    get to what is doing it — the same reason the web marker opens into links."""
    for epic in epics:
        for blocker in epic.impediments:
            print(f"   {STUCK_MARK} {epic.name}: {blocker.name} — {blocker.url}")


def cmd_portfolio(args: argparse.Namespace) -> int:
    """Print the IV Portfolio board with the epics linked to each item summed up.

    Without `--item` this is the overview; with it, the one item and its epics.
    """
    with MondayClient() as client:
        items, epic_rows = portfolio.fetch_portfolio(client)

    if args.item:
        choice = lookups.resolve([Choice(id=i.id, name=i.name) for i in items], args.item)
        found = next(i for i in items if i.id == choice.id)
        print(f"# {found.name}")
        facts = [
            ("doelstelling", found.goal),
            ("type", found.type),
            ("urgentie", found.urgency),
            ("projectleider", found.lead),
            ("start", found.start),
            ("einddatum", found.end),
        ]
        print(" · ".join(f"{label}: {value}" for label, value in facts if value))
        print(f"monday: {found.url}")
        if found.link:
            print(f"fortes: {found.link}")
        print()
        if not found.epics:
            print("No epics are linked to this portfolio item.")
            return 0
        _print_epic_rows(list(found.epics))
        _print_totals(f"{len(found.epics)} epics", found.points)
        print(f"{STUCK_MARK} = stuck: the epic is on Impediment, or a task of it is")
        _print_blockers(found.epics)
        return 0

    filters = portfolio.Filters(
        search=args.search or "",
        goal=args.goal or "",
        type=args.type or "",
        urgency=args.urgency or "",
        lead=args.lead or "",
        bucket=args.progress or "",
        stuck=args.stuck,
        empty=args.empty,
    )
    shown = portfolio.arrange(items, filters, sort=args.sort, desc=args.desc)

    print(f"{'urgentie':<10} {'type':<11} {'epics':>5} {'done':>6} {'left':>6}  {'progress':<18} item")
    for item in shown:
        print(
            f"{item.urgency[:9]:<10} {item.type[:10]:<11} {len(item.epics):>5} "
            f"{bd.fmt(item.done):>6} {bd.fmt(item.remaining):>6}  "
            f"{battery_bar(item.done, item.remaining):<18} "
            f"{marks(stuck=item.is_stuck)}{item.name}"
        )

    _print_totals(f"{len(shown)} of {len(items)} portfolio items", portfolio.totals(shown))
    if not filters.empty:
        hidden = sum(1 for item in items if item.is_empty)
        print(f"note: {hidden} items have no epic linked and are hidden; --empty shows them.")
    print(f"{STUCK_MARK} = stuck: one of its epics is on Impediment, or has a task that is")
    orphans = portfolio.orphan_epics(items, epic_rows)
    if orphans:
        points = bd.fmt(sum(e.total for e in orphans))
        print(
            f"note: {len(orphans)} epics ({points} points) name a portfolio item this board "
            "did not return and are in none of the rows above."
        )
    return 0


def cmd_project(args: argparse.Namespace) -> int:
    """Write an Obsidian project note for one epic, or print it."""
    ref = project.parse_reference(args.reference)
    with MondayClient() as client:
        epic = project.fetch(client, ref)

    if args.stdout:
        print(project.note_markdown(epic), end="")
        return 0

    path = project.write_note(epic, directory=args.out, force=args.force)
    print(path)
    return 0


def cmd_columns(args: argparse.Namespace) -> int:
    """List every column on a board with its id and type."""
    with MondayClient() as client:
        data = client.execute(queries.board_columns(BOARDS[args.board]))
    board = data["boards"][0]
    print(f"# {board['name']}")
    for col in board["columns"]:
        print(f"{col['id']:<24} {col['type']:<16} {col['title']}")
    return 0


def cmd_whoami(_: argparse.Namespace) -> int:
    """Show which monday.com user the loaded token belongs to."""
    with MondayClient() as client:
        me = client.execute(queries.me())["me"]
    print(f"{me['name']} <{me['email']}>  id={me['id']}")
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    """Serve the FastHTML web interface."""
    # Read at import time by web.py, so it has to be set before the import. Without the
    # reloader there is nothing to live-refresh *from*, and the socket only adds noise.
    os.environ["MONDAY_WEB_LIVE"] = "1" if args.reload else "0"

    from mondaycom import web  # imported lazily: the other subcommands should not pay for it

    print(f"serving on http://{args.host}:{args.port}  (ctrl-c to stop)", file=sys.stderr)
    web.run(host=args.host, port=args.port, reload=args.reload)
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    """Run a raw GraphQL query from a file or stdin and pretty-print the JSON."""
    if args.file == "-":
        query = sys.stdin.read()
    else:
        with open(args.file) as handle:
            query = handle.read()
    with MondayClient() as client:
        data = client.execute(query)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def _add_dam(p: argparse.ArgumentParser) -> None:
    """The DAM half-of-the-board filter, which three commands offer on the same terms."""
    p.add_argument(
        "--dam",
        default="all",
        choices=sorted(DAM_CHOICES),
        help="only epics linked to the IV Portfolio board ('dam'), only those not linked ('non-dam'), or both",
    )


def _add_sort(p: argparse.ArgumentParser, *, default: str, columns: Any, noun: str) -> None:
    """The sort and search flags the two table commands share, each with its own columns."""
    p.add_argument("--sort", default=default, choices=sorted(columns), help="column to sort on")
    p.add_argument("--desc", action="store_true", help="sort high to low / Z to A")
    p.add_argument("--search", help=f"keep {noun} whose title contains this (case-insensitive)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="monday", description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)

    p = subs.add_parser("sprint-tasks", help="print the current sprint's tasks as Obsidian markdown")
    p.add_argument("--end", help="sprint end date, YYYY-MM-DD (default: next Saturday)")
    p.add_argument("--open-only", action="store_true", help="drop tasks that are already Done")
    p.add_argument(
        "--person",
        help="whose tasks: 'me' (default), 'all', or a user id or name substring (see `monday people`)",
    )
    p.add_argument("--epic", help="only this epic: an item id or name substring (see `monday epics`)")
    _add_dam(p)
    p.set_defaults(func=cmd_sprint_tasks)

    p = subs.add_parser("burndown", help="sprint burndown: points done vs the ideal line")
    p.add_argument("--end", help="sprint end date, YYYY-MM-DD (default: the group's usual due date)")
    p.add_argument("--quiet", action="store_true", help="just the totals, no day-by-day table")
    p.add_argument(
        "--person",
        help="whose tasks to burn down: 'all' (default), 'me', or a user id or name substring; "
        "matches owner or reviewer, but only counts points where they are the Trekker",
    )
    _add_dam(p)
    p.set_defaults(func=cmd_burndown)

    p = subs.add_parser("epic-progress", help="every epic with its status, trekker, portfolio and points")
    _add_sort(p, default=ep.DEFAULT_SORT, columns=ep.SORTS, noun="epics")
    p.add_argument("--status", help="keep only this Status epic label, exactly")
    p.add_argument("--owner", help="keep only epics whose Trekker contains this name")
    p.add_argument("--portfolio", help="keep only epics linked to this IV Portfolio item, exactly")
    p.add_argument("--priority", help="keep only this Priority label, exactly")
    _add_dam(p)
    p.add_argument("--progress", choices=sorted(ep.BUCKETS), help="keep only epics at this stage")
    p.add_argument(
        "--stuck",
        action="store_true",
        help="keep only stuck epics: on Impediment themselves, or with a task that is",
    )
    p.set_defaults(func=cmd_epic_progress)

    p = subs.add_parser("portfolio", help="the IV Portfolio board with the epics linked to each item")
    p.add_argument("--item", help="one portfolio item and its epics: an item id or a name substring")
    _add_sort(p, default=portfolio.DEFAULT_SORT, columns=portfolio.SORTS, noun="items")
    p.add_argument("--goal", help="keep only this Doelstelling, exactly")
    p.add_argument("--type", help="keep only this Type ('Project' or 'Initiatief'), exactly")
    p.add_argument("--urgency", help="keep only this Urgentie ('Hoog', 'Middel', 'Laag'), exactly")
    p.add_argument("--lead", help="keep only items whose Projectleider contains this name")
    p.add_argument("--progress", choices=sorted(portfolio.BUCKETS), help="keep only items at this stage")
    p.add_argument("--stuck", action="store_true", help="keep only items with a stuck epic under them")
    p.add_argument(
        "--empty",
        action="store_true",
        help="also show items with no epic linked (166 of 177 today, so hidden by default)",
    )
    p.set_defaults(func=cmd_portfolio)

    p = subs.add_parser("project", help="write an Obsidian project note for one epic")
    p.add_argument(
        "reference",
        help="project number (DPR-223 or 223) or the epic's monday.com item id (2617136005)",
    )
    p.add_argument(
        "--out",
        help=f"directory to write into (default: {OBSIDIAN_PROJECTS_DIR}, "
        "or the working directory when that is not there)",
    )
    p.add_argument("--stdout", action="store_true", help="print the note instead of writing it")
    p.add_argument("--force", action="store_true", help="overwrite an existing note")
    p.set_defaults(func=cmd_project)

    p = subs.add_parser("columns", help="list a board's columns with their ids and types")
    p.add_argument("--board", default="sprint", choices=sorted(BOARDS))
    p.set_defaults(func=cmd_columns)

    p = subs.add_parser("people", help="list the board's people with their ids, for --person")
    p.set_defaults(func=cmd_people)

    p = subs.add_parser("epics", help="list the epics with their ids, for --epic")
    p.set_defaults(func=cmd_epics)

    p = subs.add_parser("whoami", help="show the user behind the configured API token")
    p.set_defaults(func=cmd_whoami)

    p = subs.add_parser("web", help="serve the sprint tasklist as a local web page")
    p.add_argument("--host", default="127.0.0.1", help="bind address (default: localhost only)")
    p.add_argument("--port", type=int, default=5001, help="port to listen on")
    p.add_argument(
        "--no-reload",
        dest="reload",
        action="store_false",
        help="do not restart or live-refresh the browser on code changes",
    )
    p.set_defaults(func=cmd_web, reload=True)

    p = subs.add_parser("query", help="run a raw GraphQL query")
    p.add_argument("file", help="path to a .graphql file, or - for stdin")
    p.set_defaults(func=cmd_query)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        code = int(args.func(args))
        # Flush in here, so a closed pipe raises where we can still catch it rather
        # than during interpreter shutdown, where it only prints "Exception ignored".
        sys.stdout.flush()
        return code
    except BrokenPipeError:
        # `monday epics | head` closes the pipe early; that is not an error. Send the
        # remaining buffer to /dev/null so the exit-time flush cannot fail again.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except (MondayError, ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
