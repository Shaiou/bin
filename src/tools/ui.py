"""Shared terminal UI: picker, table, confirm."""

import sys

import click
from simple_term_menu import TerminalMenu
from tabulate import tabulate


def die(msg):
    click.secho(f"ERROR: {msg}", fg="red", err=True)
    sys.exit(1)


def pick(items, label, title, name=None, key=None, multi=False, default=None, preselect_all=False):
    """Pick one item (or a list with multi=True) from items.

    name: optional case-insensitive substring pre-filter on key(item)
    (defaults to label); a single match is returned without prompting.
    default: item to put the cursor on.
    preselect_all: multi only, start with every item selected.
    """
    key = key or label
    if name:
        items = [i for i in items if name.lower() in key(i).lower()]
    if not items:
        die(f"nothing matches '{name}'" if name else "nothing to pick from")
    if len(items) == 1 and name:
        return items if multi else items[0]

    labels = [label(i) for i in items]
    cursor = items.index(default) if default in items else None
    menu = TerminalMenu(
        labels,
        title=f"{title}  (/ search{', space select' if multi else ''}, q quit)",
        multi_select=multi,
        show_multi_select_hint=multi,
        cursor_index=cursor,
        preselected_entries=range(len(labels)) if multi and preselect_all else None,
    )
    chosen = menu.show()
    if chosen is None:
        die("cancelled")
    if multi:
        return [items[i] for i in chosen]
    return items[chosen]


def table(rows, headers):
    click.echo(tabulate(rows, headers=headers, tablefmt="simple"))


def confirm(msg, default=False):
    return click.confirm(msg, default=default)
