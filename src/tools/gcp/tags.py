"""gcp tagged: resources carrying a tag value (Cloud Asset Inventory)."""

import click

from tools.gcp import gcloud, pick_org
from tools.ui import pick, table


@click.command()
@click.argument("value", required=False)
@click.option("--org", help="Organization ID (default: the only visible one, or picked).")
@click.option("--scope", help="projects/ID, folders/ID or organizations/ID (default: the organization).")
@click.option("--direct", is_flag=True, help="Only directly attached tags (default includes inherited).")
@click.option("--type", "asset_types", help="Asset types, e.g. compute.googleapis.com/Instance.")
def tagged(value, org, scope, direct, asset_types):
    """Resources carrying a tag value (VALUE: substring filter on key/value).

    Needs the Cloud Asset API and roles/cloudasset.viewer on the scope.
    """
    org = pick_org(org)
    keys = gcloud("resource-manager", "tags", "keys", "list", f"--parent=organizations/{org}")
    values = [
        v for k in keys
        for v in gcloud("resource-manager", "tags", "values", "list", f"--parent={k['name']}")
    ]
    tag = pick(values, lambda v: v["namespacedName"], "Tag value", name=value)

    field = "tagValues" if direct else "effectiveTagValues"
    args = [
        "asset", "search-all-resources", f"--scope={scope or f'organizations/{org}'}",
        f"--query={field}:{tag['namespacedName']}",
    ]
    args += [f"--asset-types={asset_types}"] if asset_types else []
    found = gcloud(*args)
    if not found:
        click.echo(f"Nothing tagged {tag['namespacedName']}.")
        return
    table(
        [[r.get("assetType", ""), r.get("displayName", ""), r.get("location", ""), r["name"]] for r in found],
        ["TYPE", "NAME", "LOCATION", "RESOURCE"],
    )
