"""gcp iam-orphans: IAM bindings that still reference deleted principals."""

import json
import sys
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import click

from tools.gcp import GcloudError, basename, gcloud, pick_org
from tools.ui import confirm, table

# gcloud command group per resource kind (get-iam-policy / set-iam-policy)
KINDS = {
    "organization": ["organizations"],
    "folder": ["resource-manager", "folders"],
    "project": ["projects"],
    "billing": ["billing", "accounts"],
}


def folders(org):
    """Every folder under the org, any depth."""
    found, queue = [], [f"--organization={org}"]
    while queue:
        for f in gcloud("resource-manager", "folders", "list", queue.pop()):
            found.append(basename(f["name"]))
            queue.append(f"--folder={found[-1]}")
    return found


def resources(org, projects_filter):
    found = [("organization", org)] + [("folder", f) for f in folders(org)]
    args = [f"--filter=projectId:{projects_filter}"] if projects_filter else []
    found += [("project", p["projectId"]) for p in gcloud("projects", "list", *args)]
    try:
        found += [("billing", basename(b["name"])) for b in gcloud("billing", "accounts", "list")]
    except GcloudError as e:
        click.secho(f"skipping billing accounts: {e.message.splitlines()[-1]}", fg="yellow", err=True)
    return found


def scan(kind, rid, member):
    """(kind, rid, [(role, member, condition)], error)"""
    try:
        policy = gcloud(*KINDS[kind], "get-iam-policy", rid)
    except GcloudError as e:
        return kind, rid, [], e.message.splitlines()[-1]
    hits = [
        (b["role"], m, b.get("condition", {}).get("title", ""))
        for b in policy.get("bindings", [])
        for m in b["members"]
        if m.startswith("deleted:") and member in m
    ]
    return kind, rid, hits, None


def strip(kind, rid, members):
    """Read-modify-write; the policy etag makes a concurrent change fail instead of being lost."""
    policy = gcloud(*KINDS[kind], "get-iam-policy", rid)
    policy["version"] = 3
    bindings = [b | {"members": [m for m in b["members"] if m not in members]} for b in policy.get("bindings", [])]
    policy["bindings"] = [b for b in bindings if b["members"]]
    with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
        json.dump(policy, f)
        f.flush()
        gcloud(*KINDS[kind], "set-iam-policy", rid, f.name, "--quiet", parse=False)


@click.command("iam-orphans")
@click.argument("member", required=False, default="")
@click.option("--org", help="Organization ID (default: the only visible one, or picked).")
@click.option("--projects", "projects_filter", help="Only project IDs matching this pattern, e.g. 'blv-*'.")
@click.option("--delete", is_flag=True, help="Prompt to remove them, resource by resource.")
def iam_orphans(member, org, projects_filter, delete):
    """Deleted principals still bound on the org, folders, projects and
    billing accounts (MEMBER: substring filter)."""
    org = pick_org(org)
    targets = resources(org, projects_filter)
    found, skipped = [], []
    with ThreadPoolExecutor(8) as pool, click.progressbar(
        length=len(targets), label=f"Scanning {len(targets)} resources", file=sys.stderr
    ) as bar:
        for kind, rid, hits, error in pool.map(lambda t: scan(*t, member), targets):
            bar.update(1)
            if error:
                skipped.append(f"{kind} {rid}: {error}")
            found += [[kind, rid, role, m, cond] for role, m, cond in hits]
    for line in skipped:
        click.secho(f"skipped {line}", fg="yellow", err=True)
    if not found:
        click.secho("No deleted principals found.", fg="green")
        return
    table(found, ["KIND", "ID", "ROLE", "MEMBER", "CONDITION"])
    if not delete:
        return
    by_resource = defaultdict(set)
    for kind, rid, _, m, _ in found:
        by_resource[kind, rid].add(m)
    for (kind, rid), members in by_resource.items():
        if confirm(f"Remove {len(members)} deleted principal(s) from {kind} {rid}?"):
            strip(kind, rid, members)
            click.secho("  removed", fg="green")
