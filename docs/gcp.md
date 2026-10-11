# gcp

GCP helpers on top of the **gcloud** CLI: they use its login and current project. **--project** overrides the project.

```bash
gcloud auth login   # if the session expired
```

## VMs

```bash
gcp ls [NAME]
gcp ssh [NAME] [--iap] [--internal]
gcp create [--dry-run]
gcp terminate [NAME]
```

- **ssh** runs **gcloud compute ssh**; **--iap** tunnels through IAP, **--internal** uses the internal IP
- **create** is a wizard:
  1. zone (gcloud default zone preselected)
  2. machine type (default **e2-micro**)
  3. image family (default **debian-cloud/debian-12**)
  4. subnet of the zone's region
  5. external IP or not
  6. name

  It prints the full gcloud command and asks before running it; **--dry-run** only prints it.
- **terminate**: multi-select, confirmation, deletes zone by zone

## Deleted principals in IAM

```bash
gcp iam-orphans [MEMBER] [--org ID] [--projects 'blv-*'] [--delete]
```

- Scans the organization, every folder (any depth), all visible projects and billing accounts for **deleted:** members
- **MEMBER** filters on the member string, **--projects** restricts project IDs
- **--delete** prompts resource by resource. Each removal reads the policy, drops the deleted members (and bindings left empty) and writes it back with its etag, so a concurrent change fails instead of being overwritten
- Resources it can't read are listed as skipped

## Tag search

```bash
gcp tagged [VALUE] [--org ID] [--scope S] [--direct] [--type T]
```

- Picker over every tag value of the organization (**VALUE** pre-filters), then lists the resources carrying it through Cloud Asset Inventory
- Inherited tags are included unless **--direct**
- **--scope**: **projects/ID**, **folders/ID** or **organizations/ID** (default: the organization)
- **--type**: asset types, e.g. **compute.googleapis.com/Instance**
- Needs the Cloud Asset API and **roles/cloudasset.viewer** on the scope

When only one organization is visible, **--org** is not needed.
