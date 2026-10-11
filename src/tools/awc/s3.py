"""awc s3purge: delete every object version and delete marker of a bucket."""

import click

from tools.ui import die, pick


@click.command()
@click.argument("bucket", required=False)
@click.pass_obj
def s3purge(obj, bucket):
    """Empty a bucket, versions included (BUCKET: substring filter)."""
    s3 = obj.session.resource("s3")
    names = sorted(b.name for b in s3.buckets.all())
    if bucket not in names:
        bucket = pick(names, str, "Bucket to purge", name=bucket)
    if click.prompt(f"Type the bucket name to purge {bucket}") != bucket:
        die("aborted")
    s3.Bucket(bucket).object_versions.all().delete()
    click.echo(f"Purged {bucket}")
