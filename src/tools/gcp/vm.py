"""VM commands: ls, ssh, create, terminate."""

import getpass
import os
import subprocess
from itertools import groupby

import click

from tools.gcp import basename, gcloud
from tools.ui import confirm, die, pick, table


def instances(project):
    return sorted(gcloud("compute", "instances", "list", project=project), key=lambda i: i["name"])


def ips(inst):
    nic = (inst.get("networkInterfaces") or [{}])[0]
    nat = (nic.get("accessConfigs") or [{}])[0].get("natIP", "")
    return nic.get("networkIP", ""), nat


def label(inst):
    internal, external = ips(inst)
    return f"{inst['name']:40} {basename(inst['zone']):18} {inst['status']:11} {internal:15} {external}"


def pick_instances(project, name, title, multi=False):
    return pick(instances(project), label, title, name=name, key=lambda i: i["name"], multi=multi)


@click.command("ls")
@click.argument("name", required=False)
@click.pass_obj
def ls(project, name):
    """List VMs of the project (NAME: substring filter)."""
    rows = [
        [i["name"], basename(i["zone"]), i["status"], basename(i["machineType"]), *ips(i)]
        for i in instances(project)
        if not name or name.lower() in i["name"].lower()
    ]
    table(rows, ["NAME", "ZONE", "STATUS", "TYPE", "INTERNAL IP", "EXTERNAL IP"])


@click.command()
@click.argument("name", required=False)
@click.option("--iap", is_flag=True, help="Tunnel through IAP.")
@click.option("--internal", is_flag=True, help="Connect to the internal IP.")
@click.pass_obj
def ssh(project, name, iap, internal):
    """SSH into a VM with gcloud compute ssh."""
    inst = pick_instances(project, name, "SSH into")
    cmd = ["gcloud", "compute", "ssh", inst["name"], f"--zone={basename(inst['zone'])}"]
    cmd += [f"--project={project}"] if project else []
    cmd += ["--tunnel-through-iap"] if iap else []
    cmd += ["--internal-ip"] if internal else []
    os.execvp("gcloud", cmd)


@click.command()
@click.argument("name", required=False)
@click.pass_obj
def terminate(project, name):
    """Delete VM(s) after confirmation."""
    chosen = pick_instances(project, name, "Delete", multi=True)
    for i in chosen:
        click.echo(f"  {label(i)}")
    if not confirm(f"Delete {len(chosen)} VM(s)? This cannot be undone"):
        die("aborted")
    by_zone = groupby(sorted(chosen, key=lambda i: i["zone"]), key=lambda i: basename(i["zone"]))
    for zone, group in by_zone:
        names = [i["name"] for i in group]
        gcloud("compute", "instances", "delete", *names, f"--zone={zone}", "--quiet",
               project=project, parse=False)
        click.echo(f"Deleted {', '.join(names)} ({zone})")


@click.command()
@click.option("--dry-run", is_flag=True, help="Print the gcloud command instead of running it.")
@click.pass_obj
def create(project, dry_run):
    """Create a VM: zone, machine type, image, subnet, external IP, name."""
    current = gcloud("config", "get-value", "project", parse=False)
    click.echo(f"Project: {project or current}")
    default_zone = gcloud("config", "get-value", "compute/zone", parse=False) or None
    zones = sorted(z["name"] for z in gcloud("compute", "zones", "list", project=project) if z["status"] == "UP")
    zone = pick(zones, str, "Zone", default=default_zone)
    region = zone.rsplit("-", 1)[0]

    machine_type = click.prompt("Machine type", default="e2-micro")
    images = gcloud("compute", "images", "list", project=project)
    families = sorted(
        {f"{i['selfLink'].split('/projects/')[1].split('/')[0]}/{i['family']}" for i in images if i.get("family")}
    )
    image = pick(families, str, "Image family", default="debian-cloud/debian-12")
    image_project, family = image.split("/")

    subnets = gcloud("compute", "networks", "subnets", "list", f"--filter=region:{region}", project=project)
    subnet = pick(
        sorted(subnets, key=lambda s: s["name"]),
        lambda s: f"{basename(s['network']):25} {s['name']:35} {s['ipCidrRange']}",
        "Subnet",
    )
    external = confirm("External IP?", default=False)
    name = click.prompt("Name", default=f"{getpass.getuser()}-test")

    cmd = [
        "gcloud", "compute", "instances", "create", name, f"--zone={zone}",
        f"--machine-type={machine_type}", f"--image-family={family}", f"--image-project={image_project}",
        f"--subnet={subnet['selfLink']}",
    ]
    cmd += [] if external else ["--no-address"]
    cmd += [f"--project={project}"] if project else []
    click.echo("\n" + " ".join(cmd))
    if dry_run:
        return
    if not confirm("Create it?", default=True):
        die("aborted")
    subprocess.run(cmd, check=True)
