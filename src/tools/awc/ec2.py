"""EC2 commands: ls, ssh, console, create, terminate."""

import getpass
import os
import re
import time
from pathlib import Path

import click
from botocore.exceptions import ClientError

from tools.ui import confirm, die, pick, table

LIVE = ["pending", "running", "stopping", "stopped"]
TEST_NAME = "infra-core-test-network"
AMI_PARAM = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-{arch}"


def tag(resource, key, default=""):
    return next((t["Value"] for t in resource.get("Tags", []) if t["Key"] == key), default)


def name_of(inst):
    return tag(inst, "Name") or inst["InstanceId"]


def instances(ec2, states=LIVE):
    pages = ec2.get_paginator("describe_instances").paginate(
        Filters=[{"Name": "instance-state-name", "Values": states}]
    )
    found = [i for p in pages for r in p["Reservations"] for i in r["Instances"]]
    return sorted(found, key=lambda i: (name_of(i), i["LaunchTime"]))


def label(inst):
    return (
        f"{name_of(inst):40} {inst['InstanceId']:20} {inst['State']['Name']:9} "
        f"{inst.get('PrivateIpAddress', '-'):15} {inst.get('PublicIpAddress', '-')}"
    )


def pick_instances(ec2, name, title, multi=False, states=LIVE):
    return pick(instances(ec2, states), label, title, name=name, key=name_of, multi=multi)


def dry_run_ok(call, **kwargs):
    """Run an EC2 call with DryRun=True; True when permissions are fine."""
    try:
        call(DryRun=True, **kwargs)
    except ClientError as e:
        if e.response["Error"]["Code"] != "DryRunOperation":
            raise
    return True


# --- ls / ssh / console / terminate

@click.command("ls")
@click.argument("name", required=False)
@click.option("-a", "--all", "show_all", is_flag=True, help="Include terminated instances.")
@click.pass_obj
def ls(obj, name, show_all):
    """List instances (NAME: substring filter on the Name tag)."""
    states = LIVE + ["shutting-down", "terminated"] if show_all else LIVE
    rows = [
        [
            name_of(i), i["InstanceId"], i["State"]["Name"], i["InstanceType"],
            i.get("PrivateIpAddress", ""), i.get("PublicIpAddress", ""),
            i["Placement"]["AvailabilityZone"], f"{i['LaunchTime']:%Y-%m-%d %H:%M}",
        ]
        for i in instances(obj.client("ec2"), states)
        if not name or name.lower() in name_of(i).lower()
    ]
    table(rows, ["NAME", "ID", "STATE", "TYPE", "PRIVATE IP", "PUBLIC IP", "AZ", "LAUNCHED"])


@click.command()
@click.argument("name", required=False)
@click.option("-u", "--user", default="ec2-user", show_default=True, help="SSH user.")
@click.option("--private", is_flag=True, help="Use private IPs even when a public one exists.")
@click.pass_obj
def ssh(obj, name, user, private):
    """SSH into running instance(s); several picked -> tmux-cssh."""
    chosen = pick_instances(obj.client("ec2"), name, "SSH into", multi=True, states=["running"])
    if private:
        ips = [i.get("PrivateIpAddress") for i in chosen]
    else:
        ips = [i.get("PublicIpAddress") or i.get("PrivateIpAddress") for i in chosen]
    ips = [ip for ip in ips if ip]
    if not ips:
        die("selected instance(s) have no IP")
    if len(ips) == 1:
        os.execvp("ssh", ["ssh", f"{user}@{ips[0]}"])
    os.execvp("tmux-cssh", ["tmux-cssh", "-set", "-u", user, *ips])


@click.command()
@click.argument("name", required=False)
@click.option("-f", "--follow", is_flag=True, help="Poll every 20s until cloud-init finishes.")
@click.pass_obj
def console(obj, name, follow):
    """Show an instance's console (serial) output."""
    ec2 = obj.client("ec2")
    inst = pick_instances(ec2, name, "Console output of")
    shown = ""
    while True:
        out = ec2.get_console_output(InstanceId=inst["InstanceId"]).get("Output", "")
        click.echo(out[len(shown):] if out.startswith(shown) else out, nl=False)
        shown = out
        if re.search(r"cloud-init.*finished", out):
            return
        if not follow:
            if not out:
                click.echo("No console output yet (try --follow).")
            return
        time.sleep(20)


@click.command()
@click.argument("name", required=False)
@click.option("--dry-run", is_flag=True, help="Only check permissions.")
@click.pass_obj
def terminate(obj, name, dry_run):
    """Terminate instance(s) after confirmation."""
    ec2 = obj.client("ec2")
    chosen = pick_instances(ec2, name, "Terminate", multi=True)
    for i in chosen:
        click.echo(f"  {label(i)}")
    ids = [i["InstanceId"] for i in chosen]
    if dry_run:
        dry_run_ok(ec2.terminate_instances, InstanceIds=ids)
        click.echo("Dry run OK.")
        return
    if not confirm(f"Terminate {len(ids)} instance(s)? This cannot be undone"):
        die("aborted")
    ec2.terminate_instances(InstanceIds=ids)
    click.echo(f"Terminating: {', '.join(ids)}")


# --- create wizard

def pick_region(obj):
    current = obj.session.region_name
    regions = obj.client("ec2", current or "us-east-1").describe_regions()["Regions"]
    return pick(sorted(r["RegionName"] for r in regions), str, "Region", default=current)


def pick_key(ec2):
    new = "+ import a public key"
    keys = sorted(k["KeyName"] for k in ec2.describe_key_pairs()["KeyPairs"])
    choice = pick(keys + [new], str, "Key pair")
    if choice != new:
        return choice
    path = Path(click.prompt("Public key file", default="~/.ssh/id_ecdsa.pub")).expanduser()
    name = click.prompt("Key pair name", default=f"{TEST_NAME}-{getpass.getuser()}")
    ec2.import_key_pair(KeyName=name, PublicKeyMaterial=path.read_bytes())
    return name


def pick_security_groups(ec2, vpc_id):
    new = {"GroupId": None, "GroupName": f"+ create {TEST_NAME} (SSH from anywhere)"}
    sgs = ec2.describe_security_groups(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
    sgs = sorted(sgs["SecurityGroups"], key=lambda g: g["GroupName"])
    if not any(g["GroupName"] == TEST_NAME for g in sgs):
        sgs.append(new)
    chosen = pick(sgs, lambda g: f"{g['GroupId'] or '':22} {g['GroupName']}", "Security group(s)", multi=True)
    ids = [g["GroupId"] for g in chosen if g["GroupId"]]
    if new in chosen:
        sg_id = ec2.create_security_group(
            GroupName=TEST_NAME, Description=f"{TEST_NAME} (awc)", VpcId=vpc_id
        )["GroupId"]
        ec2.authorize_security_group_ingress(
            GroupId=sg_id, IpProtocol="tcp", FromPort=22, ToPort=22, CidrIp="0.0.0.0/0"
        )
        click.echo(f"Created {sg_id} with inbound SSH from 0.0.0.0/0")
        ids.append(sg_id)
    return ids


@click.command()
@click.option("--dry-run", is_flag=True, help="Validate the launch without creating instances.")
@click.pass_obj
def create(obj, dry_run):
    """Launch Amazon Linux 2023 instance(s), one per picked subnet."""
    region = pick_region(obj)
    ec2 = obj.client("ec2", region)
    click.echo(f"Profile: {obj.session.profile_name}   Region: {region}")

    vpcs = ec2.describe_vpcs()["Vpcs"]
    vpc = pick(vpcs, lambda v: f"{v['VpcId']:23} {tag(v, 'Name') or '-':30} {v['CidrBlock']}", "VPC")
    subnets = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc["VpcId"]]}])["Subnets"]
    subnets = pick(
        sorted(subnets, key=lambda s: (tag(s, "Name"), s["AvailabilityZone"])),
        lambda s: f"{s['SubnetId']:25} {s['AvailabilityZone']:12} {tag(s, 'Name') or '-':35} {s['CidrBlock']}",
        "Subnet(s), one instance each",
        multi=True,
    )

    itype = click.prompt("Instance type", default="t4g.micro")
    archs = ec2.describe_instance_types(InstanceTypes=[itype])["InstanceTypes"][0]["ProcessorInfo"]
    arch = "arm64" if "arm64" in archs["SupportedArchitectures"] else "x86_64"
    ami = obj.client("ssm", region).get_parameter(Name=AMI_PARAM.format(arch=arch))["Parameter"]["Value"]
    key = pick_key(ec2)
    sg_ids = pick_security_groups(ec2, vpc["VpcId"])
    base = click.prompt("Name tag", default=f"{TEST_NAME}-{getpass.getuser()}")
    plan = [(s, f"{base}-{tag(s, 'Name') or s['SubnetId']}" if len(subnets) > 1 else base) for s in subnets]

    click.echo(f"\nAMI {ami} (AL2023 {arch})  type {itype}  key {key}  SG {', '.join(sg_ids)}")
    for s, inst_name in plan:
        click.echo(f"  {inst_name}  ->  {s['SubnetId']} ({s['AvailabilityZone']})")

    def launch(subnet, inst_name, **extra):
        return ec2.run_instances(
            ImageId=ami, InstanceType=itype, MinCount=1, MaxCount=1, KeyName=key,
            SubnetId=subnet["SubnetId"], SecurityGroupIds=sg_ids,
            TagSpecifications=[{"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": inst_name}]}],
            **extra,
        )

    if dry_run:
        dry_run_ok(lambda **kw: launch(*plan[0], **kw))
        click.echo("Dry run OK.")
        return
    if not confirm(f"Launch {len(plan)} instance(s)?", default=True):
        die("aborted")

    ids = [launch(s, n)["Instances"][0]["InstanceId"] for s, n in plan]
    click.echo(f"Launched {', '.join(ids)}, waiting for running state...")
    ec2.get_waiter("instance_running").wait(InstanceIds=ids)
    done = [i for r in ec2.describe_instances(InstanceIds=ids)["Reservations"] for i in r["Instances"]]
    table(
        [[name_of(i), i["InstanceId"], i.get("PrivateIpAddress", ""), i.get("PublicIpAddress", "")] for i in done],
        ["NAME", "ID", "PRIVATE IP", "PUBLIC IP"],
    )
