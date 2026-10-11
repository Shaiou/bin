"""Curses browser for plan / state trees.

Keys: j/k or arrows move, Enter/Space toggle, +/- or Right/Left expand/collapse,
e/c expand/collapse current subtree, E/C everything, PgUp/PgDn, Home/End,
/ filter resources, q or Esc quit.
"""

import curses

from tools.tfc.tree import Node, flatten, node_line, set_expanded

FOOTER = " j/k move  +/- expand  e/c subtree  E/C all  / filter  q quit "

# kind -> (foreground, bold)
COLORS = {
    "resource": (curses.COLOR_CYAN, True),
    "key": (curses.COLOR_YELLOW, False),
    "leaf": (curses.COLOR_WHITE, False),
    "added": (curses.COLOR_GREEN, False),
    "removed": (curses.COLOR_RED, False),
    "changed": (curses.COLOR_MAGENTA, True),
    "create": (curses.COLOR_GREEN, True),
    "change": (curses.COLOR_YELLOW, True),
    "delete": (curses.COLOR_RED, True),
    "replace": (curses.COLOR_MAGENTA, True),
}
SELECTED = len(COLORS) + 1


class Browser:
    """grouped=True: roots are action groups whose children are resources (plan);
    otherwise roots are the resources (state)."""

    def __init__(self, roots, title, grouped=False):
        self.all_roots = self.roots = roots
        self.title = title
        self.grouped = grouped
        self.selected = self.top = 0
        self.filter_text = ""
        self.attrs = {}

    def resources(self, roots):
        return [c for r in roots for c in r.children] if self.grouped else roots

    def apply_filter(self, text):
        self.filter_text = text
        lw = text.lower()
        if not text:
            self.roots = self.all_roots
        elif not self.grouped:
            self.roots = [r for r in self.all_roots if lw in r.label.lower()]
        else:
            self.roots = []
            for group in self.all_roots:
                matching = [c for c in group.children if lw in c.label.lower()]
                if matching:
                    clone = Node(f"{group.label.split(' (')[0]} ({len(matching)})", kind=group.kind)
                    clone.expanded = group.expanded
                    clone.children = matching
                    self.roots.append(clone)
        self.selected = self.top = 0

    def _cur(self, visible):
        return visible[self.selected] if 0 <= self.selected < len(visible) else None

    def _prompt_filter(self, stdscr):
        curses.curs_set(1)
        curses.echo()
        h, w = stdscr.getmaxyx()
        stdscr.move(h - 1, 0)
        stdscr.clrtoeol()
        stdscr.addstr(h - 1, 0, "/")
        try:
            text = stdscr.getstr(h - 1, 1, w - 2).decode("utf-8", "replace")
        except curses.error:
            text = ""
        curses.noecho()
        curses.curs_set(0)
        self.apply_filter(text.strip())

    def _draw(self, stdscr, visible):
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        shown, total = len(self.resources(self.roots)), len(self.resources(self.all_roots))
        hdr = f" {self.title}  {shown}/{total}"
        if self.filter_text:
            hdr += f'  filter:"{self.filter_text}"'
        stdscr.addstr(0, 0, hdr[:w - 1].ljust(w - 1), curses.A_REVERSE)
        for row in range(h - 2):
            idx = self.top + row
            if idx >= len(visible):
                break
            node = visible[idx]
            line = node_line(node)[:w - 1]
            if idx == self.selected:
                stdscr.addstr(row + 1, 0, line.ljust(w - 1), self.attrs.get("selected", curses.A_REVERSE))
            else:
                stdscr.addstr(row + 1, 0, line, self.attrs.get(node.kind, 0))
        stdscr.addstr(h - 1, 0, FOOTER[:w - 1].ljust(w - 1), curses.A_REVERSE)
        stdscr.refresh()

    def _init_colors(self):
        curses.use_default_colors()
        if not curses.has_colors():
            return
        for pair, (kind, (fg, bold)) in enumerate(COLORS.items(), start=1):
            curses.init_pair(pair, fg, -1)
            self.attrs[kind] = curses.color_pair(pair) | (curses.A_BOLD if bold else 0)
        curses.init_pair(SELECTED, curses.COLOR_BLACK, curses.COLOR_WHITE)
        self.attrs["selected"] = curses.color_pair(SELECTED)

    def run(self, stdscr):
        curses.curs_set(0)
        stdscr.keypad(True)
        self._init_colors()
        while True:
            visible = flatten(self.roots)
            self._draw(stdscr, visible)
            ch = stdscr.getch()
            cur = self._cur(visible)
            page = max(1, stdscr.getmaxyx()[0] - 3)
            last = max(len(visible) - 1, 0)

            if ch in (ord("q"), 27):
                break
            elif ch in (curses.KEY_DOWN, ord("j")):
                self.selected = min(self.selected + 1, last)
            elif ch in (curses.KEY_UP, ord("k")):
                self.selected = max(self.selected - 1, 0)
            elif ch == curses.KEY_NPAGE:
                self.selected = min(self.selected + page, last)
            elif ch == curses.KEY_PPAGE:
                self.selected = max(self.selected - page, 0)
            elif ch == curses.KEY_HOME:
                self.selected = 0
            elif ch == curses.KEY_END:
                self.selected = last
            elif ch in (curses.KEY_ENTER, 10, 13, ord(" ")) and cur and cur.expandable:
                cur.expanded = not cur.expanded
            elif ch in (ord("+"), ord("="), curses.KEY_RIGHT) and cur and cur.expandable:
                cur.expanded = True
            elif ch in (ord("-"), ord("_"), curses.KEY_LEFT) and cur and cur.expandable:
                cur.expanded = False
            elif ch in (ord("E"), ord("C")):
                for r in self.roots:
                    set_expanded(r, ch == ord("E"))
            elif ch in (ord("e"), ord("c")) and cur:
                set_expanded(cur, ch == ord("e"))
            elif ch == ord("/"):
                self._prompt_filter(stdscr)

            vh = stdscr.getmaxyx()[0] - 2
            if self.selected < self.top:
                self.top = self.selected
            elif self.selected >= self.top + vh:
                self.top = self.selected - vh + 1
            self.top = max(0, min(self.top, max(0, len(visible) - vh)))


def browse(roots, title, grouped=False):
    curses.wrapper(Browser(roots, title, grouped).run)
