"""awc sso: IAM Identity Center audit (list, orphans, unused)."""

import csv
import sys
import time

import click

from tools.ui import confirm, table


def paginate(client, method, key, **kwargs):
    for page in client.get_paginator(method).paginate(**kwargs):
        yield from page[key]


class Sso:
    """Identity Center clients plus the lookups shared by every command."""

    def __init__(self, obj, region):
        self.admin = obj.client("sso-admin", region)
        self.ids = obj.client("identitystore", region)
        self.org = obj.client("organizations", region)
        instances = self.admin.list_instances()["Instances"]
        if not instances:
            raise click.ClickException(
                f"no IAM Identity Center instance for profile {obj.session.profile_name} in {region}; "
                "use the management account's profile (awc --profile ...) or sso --region"
            )
        self.arn = instances[0]["InstanceArn"]
        self.store = instances[0]["IdentityStoreId"]

    def permission_sets(self):
        """{arn: name}"""
        arns = paginate(self.admin, "list_permission_sets", "PermissionSets", InstanceArn=self.arn)
        return {
            arn: self.admin.describe_permission_set(InstanceArn=self.arn, PermissionSetArn=arn)[
                "PermissionSet"
            ].get("Name", arn)
            for arn in arns
        }

    def accounts(self):
        return {a["Id"]: a["Name"] for a in paginate(self.org, "list_accounts", "Accounts")}

    def assignments(self, ps_arn):
        """Yield (account_id, assignment) over the accounts the set is provisioned to."""
        account_ids = paginate(
            self.admin, "list_accounts_for_provisioned_permission_set", "AccountIds",
            InstanceArn=self.arn, PermissionSetArn=ps_arn,
        )
        for account_id in account_ids:
            for a in paginate(
                self.admin, "list_account_assignments", "AccountAssignments",
                InstanceArn=self.arn, AccountId=account_id, PermissionSetArn=ps_arn,
            ):
                yield account_id, a

    def group_name(self, group_id):
        """Display name, or None when the group no longer exists."""
        try:
            return self.ids.describe_group(IdentityStoreId=self.store, GroupId=group_id)["DisplayName"]
        except self.ids.exceptions.ResourceNotFoundException:
            return None

    def delete_assignment(self, account_id, ps_arn, principal_type, principal_id):
        """Delete and wait: the deletion is asynchronous."""
        status = self.admin.delete_account_assignment(
            InstanceArn=self.arn, TargetId=account_id, TargetType="AWS_ACCOUNT",
            PermissionSetArn=ps_arn, PrincipalType=principal_type, PrincipalId=principal_id,
        )["AccountAssignmentDeletionStatus"]
        for _ in range(30):
            if status["Status"] == "SUCCEEDED":
                return
            if status["Status"] == "FAILED":
                raise click.ClickException(status.get("FailureReason", "assignment deletion failed"))
            time.sleep(2)
            status = self.admin.describe_account_assignment_deletion_status(
                InstanceArn=self.arn, AccountAssignmentDeletionRequestId=status["RequestId"]
            )["AccountAssignmentDeletionStatus"]
        raise click.ClickException("assignment deletion timed out")


@click.group()
@click.option("--region", default="eu-west-1", show_default=True, help="Identity Center region.")
@click.pass_context
def sso(ctx, region):
    """IAM Identity Center audit."""
    ctx.obj = Sso(ctx.obj, region)


@sso.command("list")
@click.option("--csv", "as_csv", is_flag=True, help="CSV output.")
@click.pass_obj
def list_(s, as_csv):
    """Permission sets with their accounts and groups."""
    accounts = s.accounts()
    rows = []
    with click.progressbar(s.permission_sets().items(), label="Permission sets", file=sys.stderr) as items:
        for ps_arn, ps_name in items:
            groups = {}
            for account_id, a in s.assignments(ps_arn):
                groups.setdefault(account_id, [])
                if a["PrincipalType"] == "GROUP":
                    groups[account_id].append(s.group_name(a["PrincipalId"]) or a["PrincipalId"])
            rows += [[ps_name, acc, accounts.get(acc, acc), ", ".join(g)] for acc, g in groups.items()]
            if not groups:
                rows.append([ps_name, "", "", ""])
    headers = ["PERMISSION SET", "ACCOUNT ID", "ACCOUNT", "GROUPS"]
    if as_csv:
        writer = csv.writer(sys.stdout)
        writer.writerows([headers, *rows])
    else:
        table(rows, headers)


@sso.command()
@click.option("--delete", is_flag=True, help="Prompt to delete each orphan.")
@click.pass_obj
def orphans(s, delete):
    """Assignments that point to deleted groups."""
    accounts = s.accounts()
    found = []
    with click.progressbar(s.permission_sets().items(), label="Permission sets", file=sys.stderr) as items:
        for ps_arn, ps_name in items:
            for account_id, a in s.assignments(ps_arn):
                if a["PrincipalType"] == "GROUP" and s.group_name(a["PrincipalId"]) is None:
                    found.append((ps_name, ps_arn, account_id, a["PrincipalId"]))
    if not found:
        click.secho("No orphaned assignments.", fg="green")
        return
    table([[n, acc, accounts.get(acc, acc), g] for n, _, acc, g in found],
          ["PERMISSION SET", "ACCOUNT ID", "ACCOUNT", "DELETED GROUP ID"])
    if not delete:
        return
    for ps_name, ps_arn, account_id, group_id in found:
        if confirm(f"Delete {ps_name} on {accounts.get(account_id, account_id)} for group {group_id}?"):
            s.delete_assignment(account_id, ps_arn, "GROUP", group_id)
            click.secho("  deleted", fg="green")


@sso.command()
@click.option("--delete", is_flag=True, help="Prompt to delete each unused permission set.")
@click.pass_obj
def unused(s, delete):
    """Permission sets with no group assignment."""
    found = []
    with click.progressbar(s.permission_sets().items(), label="Permission sets", file=sys.stderr) as items:
        for ps_arn, ps_name in items:
            if not any(a["PrincipalType"] == "GROUP" for _, a in s.assignments(ps_arn)):
                found.append((ps_name, ps_arn))
    if not found:
        click.secho("Every permission set has a group assignment.", fg="green")
        return
    table(found, ["PERMISSION SET", "ARN"])
    if not delete:
        return
    for ps_name, ps_arn in found:
        if not confirm(f"Delete permission set {ps_name} (and its user assignments)?"):
            continue
        for account_id, a in s.assignments(ps_arn):
            s.delete_assignment(account_id, ps_arn, a["PrincipalType"], a["PrincipalId"])
        s.admin.delete_permission_set(InstanceArn=s.arn, PermissionSetArn=ps_arn)
        click.secho("  deleted", fg="green")
