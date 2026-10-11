"""awc: AWS helper CLI (EC2, console login, IAM Identity Center)."""

from dataclasses import dataclass, field

import boto3
import click
from botocore.exceptions import BotoCoreError, ClientError

from tools.awc import ec2, s3, sso, web
from tools.ui import die


@dataclass
class Ctx:
    session: boto3.Session
    clients: dict = field(default_factory=dict)

    def client(self, service, region=None):
        region = region or self.session.region_name
        if (service, region) not in self.clients:
            self.clients[service, region] = self.session.client(service, region_name=region)
        return self.clients[service, region]


class AwsGroup(click.Group):
    """Turn AWS errors (expired SSO, access denied...) into one-line messages."""

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except (BotoCoreError, ClientError) as e:
            die(str(e))


@click.group(cls=AwsGroup)
@click.option("--profile", help="AWS profile (default: $AWS_PROFILE)")
@click.option("--region", help="AWS region (default: the profile's region)")
@click.pass_context
def cli(ctx, profile, region):
    """AWS helpers. Optional NAME arguments pre-filter the picker by name;
    a single match is used directly."""
    ctx.obj = Ctx(boto3.Session(profile_name=profile, region_name=region))


for command in (ec2.ls, ec2.ssh, ec2.console, ec2.create, ec2.terminate, s3.s3purge, web.web, sso.sso):
    cli.add_command(command)
