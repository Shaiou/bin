# awc

AWS helpers on top of **boto3**. Uses **$AWS_PROFILE** and the profile's region unless **--profile** / **--region** are given. Expired SSO sessions and AWS errors are reported on one line.

```bash
aws sso login --profile <profile>   # if the session expired
```

## EC2

```bash
awc ls [NAME] [-a]              # table of instances, -a includes terminated ones
awc ssh [NAME] [-u USER] [--private]
awc console [NAME] [-f]         # serial console output
awc create [--dry-run]
awc terminate [NAME] [--dry-run]
```

- **ssh**: multi-select; one instance runs **ssh**, several run **tmux-cssh**. Uses the public IP when there is one (**--private** forces private IPs). Default user **ec2-user**
- **console -f**: polls every 20s until cloud-init finishes
- **create** is a wizard:
  1. region (current one preselected)
  2. VPC
  3. subnets, one instance per subnet
  4. instance type (default **t4g.micro**)
  5. key pair: existing one or import a public key
  6. security groups: existing ones or create **infra-core-test-network** with SSH open
  7. Name tag

  The AMI is the latest Amazon Linux 2023 for the instance type's architecture. **--dry-run** checks permissions without launching.
- **terminate**: multi-select, confirmation defaults to No

## S3

```bash
awc s3purge [BUCKET]
```

Deletes every object version and delete marker. Confirm by typing the bucket name.

## Console sign-in

```bash
awc web [PROFILE] [--print]
BROWSER=brave-adm awc web prod
```

Builds an AWS console sign-in URL from the profile's temporary credentials (SSO or assumed role) and opens it in **$BROWSER**. **--print** prints the URL instead. Long-term IAM user keys are not supported.

## IAM Identity Center

```bash
awc --profile <management-profile> sso list [--csv]
awc --profile <management-profile> sso orphans [--delete]
awc --profile <management-profile> sso unused [--delete]
```

- Needs a profile in the account that hosts Identity Center
- Default region **eu-west-1**, override with **awc sso --region R ...**
- **list**: permission sets with their accounts and groups
- **orphans**: assignments that point to deleted groups
- **unused**: permission sets without any group assignment
- **--delete** prompts item by item; **unused --delete** also removes the set's user assignments first
