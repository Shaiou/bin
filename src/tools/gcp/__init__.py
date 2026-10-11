"""gcp: GCP helper CLI on top of gcloud (VMs, IAM orphans, tag search)."""

import json
import subprocess

import click

from tools.ui import pick


class GcloudError(click.ClickException):
    pass


def gcloud(*args, project=None, parse=True):
    """Run gcloud, return parsed JSON (or raw stdout with parse=False)."""
    cmd = ["gcloud", *args]
    if project:
        cmd.append(f"--project={project}")
    if parse:
        cmd.append("--format=json")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode:
        raise GcloudError(result.stderr.strip() or f"{' '.join(cmd)} failed")
    if not parse:
        return result.stdout.strip()
    return json.loads(result.stdout or "[]")


def basename(url):
    return url.rsplit("/", 1)[-1]


def pick_org(org=None):
    """Org ID: given, the only visible one, or picked."""
    if org:
        return org
    orgs = gcloud("organizations", "list")
    chosen = orgs[0] if len(orgs) == 1 else pick(
        orgs, lambda o: f"{basename(o['name']):15} {o['displayName']}", "Organization"
    )
    return basename(chosen["name"])


@click.group()
@click.option("--project", help="GCP project (default: gcloud config / $CLOUDSDK_CORE_PROJECT)")
@click.pass_context
def cli(ctx, project):
    """GCP helpers. Optional NAME arguments pre-filter the picker by name;
    a single match is used directly."""
    ctx.obj = project


from tools.gcp import iam, tags, vm  # noqa: E402

for command in (vm.ls, vm.ssh, vm.create, vm.terminate, iam.iam_orphans, tags.tagged):
    cli.add_command(command)
