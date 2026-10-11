"""Terragrunt plan: run, read as JSON, build the change tree."""

import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path

import click

from tools.tfc.tree import Node, compact, fmt_value, value_children, value_node

ACTIONS = {
    ("create",): "create",
    ("update",): "change",
    ("delete",): "delete",
    ("delete", "create"): "replace",
    ("create", "delete"): "replace",
    ("read",): "read",
}
ACTION_ORDER = ["create", "change", "delete", "replace", "read"]
# Fields that only show an update timestamp
NOISE = re.compile(".*modified_on|updated_at|last_updated|modified_date|update_time|last_modified")


def cache_dir():
    """Plans live outside the repo (plan files can hold secrets)."""
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "tfc"


def default_plan_file():
    """Per-directory plan file."""
    key = hashlib.sha1(os.getcwd().encode()).hexdigest()[:12]
    cache_dir().mkdir(parents=True, exist_ok=True)
    return str(cache_dir() / f"{Path.cwd().name}-{key}.plan")


def run_plan(plan_file, extra_args):
    cmd = ["terragrunt", "plan", "--lock=false", "-out", plan_file, *extra_args]
    click.echo(f"  -> {' '.join(cmd)}", err=True)
    if subprocess.run(cmd).returncode:
        raise click.ClickException("terragrunt plan failed")


def show_plan(plan_file):
    if not os.path.exists(plan_file):
        raise click.ClickException(f"{plan_file} not found, run without -s first")
    cmd = ["terragrunt", "show", "-json", plan_file]
    click.echo(f"  -> {' '.join(cmd)}", err=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode:
        raise click.ClickException(f"terragrunt show failed: {result.stderr}")
    return json.loads(result.stdout)


def extract_changes(plan):
    """{action: [resource_change, ...]}, no-ops dropped."""
    groups = {}
    for rc in plan.get("resource_changes", []):
        actions = rc.get("change", {}).get("actions", [])
        if actions != ["no-op"]:
            groups.setdefault(ACTIONS.get(tuple(actions), "+".join(actions)), []).append(rc)
    return groups


def summary(groups):
    order = sorted(groups, key=lambda a: ACTION_ORDER.index(a) if a in ACTION_ORDER else 99)
    return ", ".join(f"{a}: {len(groups[a])}" for a in order)


# --- attribute diff

def diff_values(before, after, after_unknown):
    """[(key, added|removed|changed, detail)]"""
    before, after, after_unknown = before or {}, after or {}, after_unknown or {}
    diffs = []
    for key in sorted(set(before) | set(after)):
        # after_unknown is exactly True only when the whole value is unknown
        if after_unknown.get(key) is True:
            diffs.append((key, "changed", {"before": before.get(key), "after": "(known after apply)"}))
        elif key in before and key not in after:
            diffs.append((key, "removed", {"before": before[key]}))
        elif key not in before:
            diffs.append((key, "added", {"after": after[key]}))
        elif before[key] != after[key]:
            diffs.append((key, "changed", {"before": before[key], "after": after[key]}))
    return diffs


def _canon(v):
    return json.dumps(v, sort_keys=True, default=str)


def diff_list_by_content(before, after):
    """(removed, added, kept) ignoring element order (multiset diff)."""
    bkeys, akeys = [_canon(x) for x in before], [_canon(x) for x in after]
    bc, ac = Counter(bkeys), Counter(akeys)
    removed, added = [], []
    seen = Counter()
    for x, k in zip(before, bkeys):
        if seen[k] < max(0, bc[k] - ac[k]):
            removed.append(x)
        seen[k] += 1
    seen = Counter()
    for x, k in zip(after, akeys):
        if seen[k] < max(0, ac[k] - bc[k]):
            added.append(x)
        seen[k] += 1
    return removed, added, len(before) - len(removed)


def _similarity(a, b):
    if not (isinstance(a, dict) and isinstance(b, dict)):
        return 0.0
    keys = set(a) | set(b)
    return sum(1 for k in keys if k in a and k in b and a[k] == b[k]) / len(keys) if keys else 0.0


def pair_changes(removed, added, threshold=0.5):
    """Pair removed/added dicts sharing > threshold of fields (edited elements)."""
    available = list(range(len(added)))
    pairs, rem_left = [], []
    for r in removed:
        best_j, best_s = None, threshold
        for j in available:
            s = _similarity(r, added[j])
            if s > best_s:
                best_s, best_j = s, j
        if best_j is None:
            rem_left.append(r)
        else:
            pairs.append((r, added[best_j]))
            available.remove(best_j)
    return pairs, rem_left, [added[j] for j in available]


# --- tree

def _content_node(prefix, value, kind, depth=3):
    if isinstance(value, (dict, list)) and value:
        node = Node(f"{prefix} {compact(value)}", kind=kind, depth=depth)
        node.children = value_children(value, depth + 1)
        return node
    return Node(f"{prefix} {fmt_value(value)}", kind=kind, depth=depth)


def _pair_node(removed, added, depth=3):
    """Edited list element: identity in the label, changed fields below."""
    keys = sorted(set(removed) | set(added))
    changed = [k for k in keys if removed.get(k) != added.get(k)]
    node = Node(f"~ {compact({k: added.get(k) for k in keys if k not in changed})}", kind="changed", depth=depth)
    node.children = [
        Node(f"{k} = {fmt_value(removed.get(k))} -> {fmt_value(added.get(k))}", kind="changed", depth=depth + 1)
        for k in changed
    ]
    return node


def _changed_children(bv, av):
    if isinstance(bv, list) and isinstance(av, list):
        removed, added, kept = diff_list_by_content(bv, av)
        if not removed and not added:
            return [Node(f"↻ reordered — {kept} items, no content change", kind="changed", depth=3)]
        pairs, rem_left, add_left = pair_changes(removed, added)
        children = [_content_node("+", el, "added") for el in add_left]
        children += [_pair_node(r, a) for r, a in pairs]
        children += [_content_node("-", el, "removed") for el in rem_left]
        if kept:
            children.append(Node(f"= {kept} unchanged (kept)", kind="key", depth=3))
        return children
    if isinstance(bv, (dict, list)) or isinstance(av, (dict, list)):
        return [value_node("before", bv, 3), value_node("after", av, 3)]
    return [
        Node(f"before = {fmt_value(bv)}", kind="removed", depth=3),
        Node(f"after  = {fmt_value(av)}", kind="added", depth=3),
    ]


def build_change_tree(groups):
    """action -> resource -> attributes (create/delete) or diff (others)."""
    roots = []
    for action in ACTION_ORDER:
        resources = groups.get(action)
        if not resources:
            continue
        action_node = Node(f"{action} ({len(resources)})", kind=action, depth=0)
        action_node.expanded = True
        for rc in resources:
            res_node = Node(rc.get("address", "?"), kind="resource", depth=1)
            change = rc.get("change", {})
            if action == "create":
                res_node.children = value_children(change.get("after") or {}, 2)
            elif action == "delete":
                res_node.children = value_children(change.get("before") or {}, 2)
            else:
                for key, kind, detail in diff_values(change.get("before"), change.get("after"), change.get("after_unknown")):
                    if NOISE.match(key):
                        continue
                    if kind == "added":
                        child = Node(f"+ {key} = {fmt_value(detail['after'])}", kind="added", depth=2)
                    elif kind == "removed":
                        child = Node(f"- {key} = {fmt_value(detail['before'])}", kind="removed", depth=2)
                    else:
                        child = Node(f"~ {key}", kind="changed", depth=2)
                        child.children = _changed_children(detail.get("before"), detail.get("after"))
                    res_node.children.append(child)
            action_node.children.append(res_node)
        roots.append(action_node)
    return roots
