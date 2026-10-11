"""Collapsible tree model shared by the plan and state views."""


class Node:
    __slots__ = ("label", "value", "kind", "children", "expanded", "depth")

    def __init__(self, label, value=None, kind="leaf", depth=0):
        self.label = label
        self.value = value
        self.kind = kind
        self.children = []
        self.expanded = False
        self.depth = depth

    @property
    def expandable(self):
        return bool(self.children)


def fmt_value(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return "{}" if isinstance(v, dict) else "[]"
    return str(v)


def compact(v, limit=80):
    """One-line summary of a value for a collapsed node label."""
    if isinstance(v, dict):
        s = "{" + ", ".join(f"{k}={fmt_value(val)}" for k, val in v.items()) + "}"
    elif isinstance(v, list):
        s = "[" + ", ".join(fmt_value(x) for x in v) + "]"
    else:
        return fmt_value(v)
    return s if len(s) <= limit else s[:limit - 1] + "…"


def value_children(value, depth):
    if isinstance(value, dict):
        return [value_node(str(k), v, depth) for k, v in value.items()]
    if isinstance(value, list):
        return [value_node(f"[{i}]", v, depth) for i, v in enumerate(value)]
    return []


def value_node(label, value, depth):
    if isinstance(value, (dict, list)) and value:
        node = Node(label, kind="key", depth=depth)
        node.children = value_children(value, depth + 1)
        return node
    return Node(label, value=value, kind="leaf", depth=depth)


def flatten(roots):
    out = []

    def visit(n):
        out.append(n)
        if n.expanded:
            for c in n.children:
                visit(c)

    for r in roots:
        visit(r)
    return out


def set_expanded(node, state):
    """Expand or collapse a node and its whole subtree."""
    if node.expandable:
        node.expanded = state
        for c in node.children:
            set_expanded(c, state)


def node_line(node):
    indent = "  " * node.depth
    if node.expandable:
        return f"{indent}{'[-] ' if node.expanded else '[+] '}{node.label}"
    if node.kind == "leaf":
        return f"{indent}    {node.label} = {fmt_value(node.value)}"
    return f"{indent}    {node.label}"
