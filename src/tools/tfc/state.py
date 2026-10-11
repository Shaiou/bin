"""Terraform state: load (file, terraform or terragrunt) and build the resource tree."""

import json
import subprocess

import click

from tools.tfc.tree import Node, value_children


def pull(tool, cwd):
    click.echo(f"  -> {tool} state pull in {cwd}", err=True)
    result = subprocess.run([tool, "state", "pull"], capture_output=True, text=True, cwd=cwd)
    if result.returncode:
        raise click.ClickException(f"{tool} state pull failed:\n{result.stderr}")
    return json.loads(result.stdout)


def extract_resources(state):
    """Flat resource list from a raw .tfstate or a `show -json` document."""
    resources = []
    if "resources" in state:
        for res in state["resources"]:
            instances = res.get("instances", [])
            for idx, inst in enumerate(instances):
                resources.append({
                    "type": res.get("type"), "name": res.get("name"), "provider": res.get("provider"),
                    "mode": res.get("mode"), "module": res.get("module"),
                    "index_key": inst.get("index_key", idx if len(instances) > 1 else None),
                    "attributes": inst.get("attributes", {}),
                })
        return resources

    def walk(module):
        for res in module.get("resources", []):
            addr = res.get("address", "")
            resources.append({
                "type": res.get("type"), "name": res.get("name"), "provider": res.get("provider_name"),
                "mode": res.get("mode"), "module": addr.rsplit(".", 2)[0] if "module." in addr else None,
                "index_key": res.get("index"), "attributes": res.get("values", {}),
            })
        for child in module.get("child_modules", []):
            walk(child)

    root = state.get("values", {}).get("root_module")
    if root:
        walk(root)
    return resources


def address(res):
    parts = [res["module"]] if res.get("module") else []
    parts += ["data"] if res.get("mode") == "data" else []
    parts.append(f"{res['type']}.{res['name']}")
    addr = ".".join(parts)
    key = res.get("index_key")
    if key is not None:
        addr += f"[{key}]" if isinstance(key, int) else f'["{key}"]'
    return addr


def build_tree(resources):
    roots = []
    for res in resources:
        node = Node(address(res), kind="resource", depth=0)
        node.children = value_children(res.get("attributes", {}), 1)
        roots.append(node)
    return roots
