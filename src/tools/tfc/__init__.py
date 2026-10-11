"""tfc: browse Terragrunt plans and Terraform state, apply reviewed plans."""

import json
import os
import subprocess
from pathlib import Path

import click
import yaml

from tools.tfc import mass
from tools.tfc import plan as tfplan
from tools.tfc import state as tfstate
from tools.tfc.browser import browse

class Passthrough(click.Command):
    """Match our options exactly and hand everything else to terragrunt plan
    (click would read -target=x as a cluster of short flags, -s included)."""

    def parse_args(self, ctx, args):
        options = [p for p in self.params if isinstance(p, click.Option)]
        valued = {o for p in options if not p.is_flag for o in p.opts}
        ours = {o for p in options for o in p.opts} | {"--help"}
        known, extra, it = [], [], iter(args)
        for arg in it:
            if arg in ours:
                known += [arg, next(it, "")] if arg in valued else [arg]
            elif arg.startswith("--") and arg.split("=", 1)[0] in valued:
                known.append(arg)
            else:
                extra.append(arg)
        return super().parse_args(ctx, [*known, "--", *extra])


def skip_option(f):
    return click.option("-s", "--skip-plan", is_flag=True, help="Reuse the last saved plan instead of planning.")(f)


def out_option(f):
    return click.option("-o", "--out", help="Plan file (default: ~/.cache/tfc/<dir>-<hash>.plan); "
                        "with --mass, a run folder to reuse.")(f)


def mass_option(f):
    return click.option("-m", "--mass", "mass_mode", is_flag=True,
                        help="Many directories: non-dash args are dirs/globs, dash args go to terragrunt plan.")(f)


def load_plan(skip_plan, out, extra):
    plan_file = out or tfplan.default_plan_file()
    if not skip_plan:
        tfplan.run_plan(plan_file, extra)
    return tfplan.extract_changes(tfplan.show_plan(plan_file)), plan_file


@click.group()
def cli():
    """Terragrunt plan/apply with a change browser, and a state browser."""


@cli.command("plan", cls=Passthrough)
@skip_option
@out_option
@mass_option
@click.option("-f", "--json-file", type=click.Path(exists=True, dir_okay=False), help="Browse a plan JSON file.")
@click.argument("extra", nargs=-1, type=click.UNPROCESSED)
def plan_cmd(skip_plan, out, mass_mode, json_file, extra):
    """Run terragrunt plan and browse the changes (EXTRA goes to terragrunt plan)."""
    if mass_mode:
        run, _, results = mass.prepare(extra, skip_plan, out)
        mass.show(run, results, "Plan")
        return
    if json_file:
        groups = tfplan.extract_changes(json.loads(Path(json_file).read_text()))
    else:
        groups, _ = load_plan(skip_plan, out, extra)
    if not groups:
        click.echo("No changes.")
        return
    browse(tfplan.build_change_tree(groups), f"Plan  {tfplan.summary(groups)}", grouped=True)


@cli.command("apply", cls=Passthrough)
@skip_option
@out_option
@mass_option
@click.argument("extra", nargs=-1, type=click.UNPROCESSED)
def apply_cmd(skip_plan, out, mass_mode, extra):
    """Plan (or reuse it with -s), browse it, then apply exactly that plan."""
    if mass_mode:
        run, base, results = mass.prepare(extra, skip_plan, out)
        mass.show(run, results, "Apply?")
        mass.apply(run, base, results)
        return
    groups, plan_file = load_plan(skip_plan, out, extra)
    if not groups:
        click.echo("No changes, nothing to apply.")
        return
    browse(tfplan.build_change_tree(groups), f"Apply?  {tfplan.summary(groups)}", grouped=True)
    if not click.confirm(f"Apply {tfplan.summary(groups)}?", default=False):
        raise click.ClickException("aborted")
    if subprocess.run(["terragrunt", "apply", plan_file]).returncode:
        raise click.ClickException("terragrunt apply failed")
    os.remove(plan_file)  # an applied plan can't be applied again


@cli.command("clean")
def clean_cmd():
    """Delete mass run folders (pick, all selected by default)."""
    mass.clean()


@cli.command("state")
@click.argument("state_file", required=False, type=click.Path(exists=True, dir_okay=False))
@click.option("-g", "--terragrunt", is_flag=True, help="Pull with terragrunt (default when terragrunt.hcl exists).")
@click.option("-C", "--dir", "workdir", default=".", type=click.Path(exists=True, file_okay=False),
              help="Directory to pull state from.")
@click.option("-y", "--yaml", "as_yaml", is_flag=True, help="Print resources as YAML instead of browsing.")
@click.option("-q", "--query", help="Print the result of a jq expression on the raw state.")
def state_cmd(state_file, terragrunt, workdir, as_yaml, query):
    """Browse state from STATE_FILE, terragrunt or terraform state pull."""
    if state_file:
        data, source = json.loads(Path(state_file).read_text()), state_file
    else:
        tool = "terragrunt" if terragrunt or Path(workdir, "terragrunt.hcl").exists() else "terraform"
        data, source = tfstate.pull(tool, workdir), f"{tool}:{Path(workdir).resolve()}"

    if query:
        result = subprocess.run(["jq", query], input=json.dumps(data), capture_output=True, text=True)
        if result.returncode:
            raise click.ClickException(f"jq: {result.stderr.strip()}")
        click.echo(result.stdout, nl=False)
        return

    resources = tfstate.extract_resources(data)
    if not resources:
        raise click.ClickException("no resources in state")
    if as_yaml:
        rows = [{"address": tfstate.address(r), **r} for r in resources]
        click.echo(yaml.safe_dump(rows, default_flow_style=False, sort_keys=False), nl=False)
        return
    browse(tfstate.build_tree(resources), f"State  {source}")
