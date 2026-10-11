"""Mass mode: plan/apply many terragrunt directories, one cache folder per run."""

import glob
import json
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import click

from tools.tfc import plan as tfplan
from tools.tfc.browser import browse
from tools.tfc.tree import Node
from tools.ui import confirm, die, pick

WORKERS = 6
# terraform/tofu errors that ask for an init (backend, modules, providers, lock file)
NEEDS_INIT = re.compile(r"\b(terraform|tofu) init\b")


def mass_dir():
    return tfplan.cache_dir() / "mass"


def runs():
    """Run folders, oldest first (names start with a timestamp)."""
    return sorted(p for p in mass_dir().glob("*") if p.is_dir()) if mass_dir().is_dir() else []


def slug(patterns):
    return re.sub(r"[^A-Za-z0-9]+", "-", " ".join(patterns)).strip("-")[:60] or "run"


def unit_file(run, d, suffix):
    return run / f"{d.strip('/').replace('/', '__')}.{suffix}"


def expand(patterns):
    """Directories holding a terragrunt.hcl, globs expanded, order kept."""
    dirs = []
    for pattern in patterns:
        for match in sorted(glob.glob(pattern, recursive=True)) or [pattern]:
            d = str(Path(match))
            if not Path(d, "terragrunt.hcl").is_file():
                click.secho(f"  skip {d}: no terragrunt.hcl", fg="yellow", err=True)
            elif d not in dirs:
                dirs.append(d)
    return dirs


def _run(cmd, cwd, log):
    with open(log, "w") as f:
        return subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT).returncode == 0


def short(path):
    return str(path).replace(str(Path.home()), "~", 1)


def say(mark, verb, d, detail="", fg=None, dim=False):
    click.secho(f"  {mark} {verb:<10} {d}  {detail}".rstrip(), fg=fg, dim=dim, err=True)


def plan_unit(run, base, d, extra):
    """Plan one directory (init only when terraform asks for it), save the plan JSON.
    Returns the change groups, or None on failure."""
    cwd, log, plan_file = Path(base, d), unit_file(run, d, "plan.log"), unit_file(run, d, "plan")
    cmd = ["terragrunt", "plan", "--lock=false", "-out", str(plan_file), *extra]
    start = time.monotonic()
    say("▸", "plan", d, log.name, dim=True)
    ok = _run(cmd, cwd, log)
    if not ok and NEEDS_INIT.search(log.read_text(errors="replace")):
        init_log = unit_file(run, d, "init.log")
        say("↻", "init", d, f"requested by plan, {short(init_log)}", fg="yellow")
        ok = _run(["terragrunt", "init"], cwd, init_log) and _run(cmd, cwd, log)
    if ok:
        show = subprocess.run(["terragrunt", "show", "-json", str(plan_file)], cwd=cwd,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if show.returncode:
            with open(log, "a") as f:
                f.write(f"\nterragrunt show failed:\n{show.stderr}")
            ok = False
    took = f"({time.monotonic() - start:.0f}s)"
    if not ok:
        say("✗", "failed", d, f"{took} {short(log)}", fg="red")
        return None
    unit_file(run, d, "json").write_text(show.stdout)
    groups = tfplan.extract_changes(json.loads(show.stdout))
    if groups:
        say("✓", "planned", d, f"{tfplan.summary(groups)} {took}", fg="green")
    else:
        say("=", "no changes", d, took, dim=True)
    return groups


def run_all(fn, dirs):
    """{d: fn(d)}, WORKERS at a time."""
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return dict(zip(dirs, pool.map(fn, dirs)))


def recap(results):
    changed = sum(1 for g in results.values() if g)
    failed = sum(1 for g in results.values() if g is None)
    click.echo(f"{len(results)} directories: " + ", ".join([
        click.style(f"{changed} with changes", fg="green" if changed else None),
        click.style(f"{len(results) - changed - failed} unchanged", dim=True),
        click.style(f"{failed} failed", fg="red" if failed else None),
    ]), err=True)


def banner(run):
    click.secho(f"Run folder  {short(run)}", fg="cyan", bold=True, err=True)
    click.secho("Logs        <dir>.plan.log, <dir>.init.log, <dir>.apply.log in the run folder", dim=True, err=True)


def load(run):
    """{dir: change groups, or None when the plan failed}; applied dirs are left out."""
    manifest = json.loads((run / "manifest.json").read_text())
    results = {}
    for d in manifest["dirs"]:
        plan_json = unit_file(run, d, "json")
        if plan_json.exists():
            results[d] = tfplan.extract_changes(json.loads(plan_json.read_text()))
        elif not unit_file(run, d, "apply.log").exists():
            results[d] = None
    return manifest["base"], results


def prepare(extra, skip_plan, out):
    """Plan into a new run folder, or reuse one (-s: latest, -o: that folder)."""
    patterns = [a for a in extra if not a.startswith("-")]
    tg_args = [a for a in extra if a.startswith("-")]
    if skip_plan or out:
        if out:
            run = Path(out)
        elif runs():
            run = runs()[-1]
        else:
            die("no mass run to reuse, run without -s first")
        if not (run / "manifest.json").exists():
            die(f"{run} is not a mass run folder")
        banner(run)
        base, results = load(run)
        recap(results)
        return run, base, results

    if not patterns:
        die("--mass needs directories or globs")
    dirs = expand(patterns)
    if not dirs:
        die("no terragrunt directory matched")
    if len(dirs) > 1:
        dirs = pick(dirs, str, "Directories to plan", multi=True, preselect_all=True)

    run = mass_dir() / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug(patterns)}"
    run.mkdir(parents=True)
    base = str(Path.cwd())
    (run / "manifest.json").write_text(json.dumps({"base": base, "dirs": dirs, "args": tg_args}, indent=2))
    banner(run)
    click.secho(f"Planning {len(dirs)} directories, {min(WORKERS, len(dirs))} at a time", bold=True, err=True)
    results = run_all(lambda d: plan_unit(run, base, d, tg_args), dirs)
    recap(results)
    return run, base, results


def _shift(node, n):
    node.depth += n
    for c in node.children:
        _shift(c, n)


def build_tree(run, results):
    """dir -> action -> resource -> diff; then no changes, failed (with log paths)."""
    roots, unchanged, failed = [], [], []
    for d, groups in results.items():
        if groups is None:
            failed.append(Node(f"{d}  log: {unit_file(run, d, 'plan.log')}", kind="key", depth=1))
        elif not groups:
            unchanged.append(Node(d, kind="key", depth=1))
        else:
            node = Node(f"{d}  {tfplan.summary(groups)}", kind="resource")
            node.children = tfplan.build_change_tree(groups)
            for c in node.children:
                _shift(c, 1)
            node.expanded = True
            roots.append(node)
    for label, kind, children, expanded in (("no changes", "key", unchanged, False),
                                            ("failed", "delete", failed, True)):
        if children:
            node = Node(f"{label} ({len(children)})", kind=kind)
            node.children, node.expanded = children, expanded
            roots.append(node)
    return roots


def show(run, results, verb):
    browse(build_tree(run, results), f"{verb}  {run}")
    failed = [d for d, g in results.items() if g is None]
    for d in failed:
        say("✗", "failed", d, short(unit_file(run, d, "plan.log")), fg="red")
    click.secho(f"Run folder  {short(run)}", fg="cyan", bold=True, err=True)


def apply(run, base, results):
    """Pick the directories to apply (all selected), confirm, apply their saved plans."""
    changed = [d for d, g in results.items() if g]
    if not changed:
        click.echo("No changes, nothing to apply.")
        return
    dirs = pick(changed, lambda d: f"{d}  {tfplan.summary(results[d])}", "Directories to apply",
                key=str, multi=True, preselect_all=True)
    if not confirm(f"Apply {len(dirs)} directories?"):
        raise click.ClickException("aborted")

    def apply_unit(d):
        plan_file, log = unit_file(run, d, "plan"), unit_file(run, d, "apply.log")
        start = time.monotonic()
        say("▸", "apply", d, log.name, dim=True)
        ok = _run(["terragrunt", "apply", str(plan_file)], Path(base, d), log)
        took = f"({time.monotonic() - start:.0f}s)"
        if not ok:
            say("✗", "failed", d, f"{took} {short(log)}", fg="red")
            return False
        plan_file.unlink()  # an applied plan can't be applied again
        unit_file(run, d, "json").unlink()
        say("✓", "applied", d, f"{tfplan.summary(results[d])} {took}", fg="green")
        return True

    click.secho(f"Applying {len(dirs)} directories, {min(WORKERS, len(dirs))} at a time", bold=True, err=True)
    failed = [d for d, ok in run_all(apply_unit, dirs).items() if not ok]
    click.secho(f"Applied {len(dirs) - len(failed)}/{len(dirs)}", fg="red" if failed else "green", bold=True, err=True)
    click.secho(f"Run folder  {short(run)}", fg="cyan", bold=True, err=True)
    if failed:
        raise click.ClickException(f"{len(failed)} failed, retry with: tfc apply -m -o {short(run)}")


def clean():
    """Delete mass run folders (all selected by default)."""
    found = runs()
    if not found:
        click.echo("No mass runs.")
        return
    for run in pick(found, lambda p: p.name, "Mass runs to delete", multi=True, preselect_all=True):
        shutil.rmtree(run)
        say("✗", "deleted", short(run), dim=True)
