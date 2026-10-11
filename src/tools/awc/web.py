"""awc web: open the AWS web console with a profile's temporary credentials."""

import json
import urllib.parse
import urllib.request
import webbrowser

import boto3
import click

from tools.ui import die, pick

FEDERATION = "https://signin.aws.amazon.com/federation"


@click.command()
@click.argument("profile", required=False)
@click.option("--print", "print_url", is_flag=True, help="Print the sign-in URL instead of opening it.")
@click.pass_obj
def web(obj, profile, print_url):
    """Open the AWS console for a profile (SSO or assumed-role credentials).

    PROFILE pre-filters the profile picker. The browser comes from $BROWSER.
    """
    profiles = sorted(boto3.Session().available_profiles)
    if profile not in profiles:
        profile = pick(profiles, str, "Profile", name=profile, default=obj.session.profile_name)

    session = boto3.Session(profile_name=profile)
    creds = session.get_credentials()
    if creds is None:
        die(f"no credentials for {profile} (aws sso login?)")
    creds = creds.get_frozen_credentials()
    if not creds.token:
        die("long-term IAM user keys can't sign in to the console this way")

    session_json = json.dumps(
        {"sessionId": creds.access_key, "sessionKey": creds.secret_key, "sessionToken": creds.token}
    )
    query = urllib.parse.urlencode({"Action": "getSigninToken", "Session": session_json})
    with urllib.request.urlopen(f"{FEDERATION}?{query}", timeout=10) as resp:
        token = json.load(resp)["SigninToken"]

    region = session.region_name
    destination = (
        f"https://{region}.console.aws.amazon.com/console/home?region={region}"
        if region else "https://console.aws.amazon.com/"
    )
    url = f"{FEDERATION}?" + urllib.parse.urlencode(
        {"Action": "login", "Issuer": "awc", "Destination": destination, "SigninToken": token}
    )
    if print_url:
        click.echo(url)
    else:
        webbrowser.open(url)
