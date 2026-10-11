# tfc

Terragrunt plan and apply with an interactive change browser, plus a Terraform state browser.

## Plan and apply

```bash
tfc plan [-s] [-o FILE] [-m] [-f plan.json] [terragrunt args]
tfc apply [-s] [-o FILE] [-m] [terragrunt args]
```

- **plan** runs **terragrunt plan --lock=false**, then opens the browser grouped by action: create, change, delete, replace, read
- **apply** plans, opens the same browser, then asks for confirmation and runs **terragrunt apply** on that saved plan: exactly what was reviewed gets applied, and Terraform refuses if the state changed meanwhile. The plan file is removed after a successful apply
- Unknown arguments go to **terragrunt plan**, e.g. **tfc plan -target=aws_vpc.main -var env=dev**

| Option | Meaning |
|---|---|
| **-s**, **--skip-plan** | Reuse the directory's last saved plan instead of planning |
| **-o**, **--out FILE** | Plan file location (default: **~/.cache/tfc/<dir>-<hash>.plan**, outside the repo since plans can hold secrets) |
| **-m**, **--mass** | Many directories at once, see below |
| **-f**, **--json-file FILE** | **plan** only: browse a **terraform show -json** output without running terragrunt (e.g. a CI artifact) |

Change view details:
- list attributes are diffed by content: pure reorders are flagged, edited elements are paired field by field
- timestamp-only fields (modified_on, updated_at...) are hidden

## Mass plan and apply

```bash
tfc plan  -m 'aws/*/global/datadog' hybrid/shd/eu-west-1/vault   # plan and browse
tfc apply -m 'aws/*/global/datadog' -var=env=prd                 # plan, browse, pick, apply
tfc apply -m -s                                                  # apply the latest run, no new plan
tfc apply -m -o ~/.cache/tfc/mass/<run>                          # apply an older run (retry failures)
tfc clean                                                        # delete run folders
```

- Arguments starting with **-** go to **terragrunt plan**, the others are directories or globs (only directories with a **terragrunt.hcl** are kept). Use the **-var=x=y** form, since **-var x=y** would read **x=y** as a directory
- Quote globs (**\*\*** included) so tfc expands them and the run folder gets a readable name
- Before planning, a picker lists the matched directories, all selected: unselect the ones to skip
- Up to 6 plans run in parallel. **terragrunt init** runs only when a plan fails asking for it, then the plan is retried
- Each run gets its own folder, **~/.cache/tfc/mass/<timestamp>-<slugified args>/**: manifest, plan files, plan JSON, init/plan/apply logs. Its path is printed before and after the browser and shown in the browser header
- Browser: one node per directory with changes (expanded down to resources), then **no changes** and **failed** (with log paths)
- **apply**: after the browser, a picker lists the directories with changes, all selected, then one confirmation and up to 6 parallel **terragrunt apply** on the saved plans. Applied plans are removed; failed ones stay, so the same run can be retried with **-o**
- **clean**: pick the run folders to delete, all selected by default

## State

```bash
tfc state [FILE] [-g] [-C DIR] [-y] [-q JQ]
```

- Source: **FILE** (raw .tfstate or **show -json**), otherwise **terragrunt state pull** when **terragrunt.hcl** exists (or **-g**), otherwise **terraform state pull**
- **-C DIR**: directory to pull from
- **-y**: print resources as YAML
- **-q JQ**: print the result of a jq expression on the raw state

## Browser keys

| Key | Action |
|---|---|
| **j/k**, arrows | move |
| **Enter**, **Space** | toggle node |
| **+** / **-**, Right / Left | expand / collapse node |
| **e** / **c** | expand / collapse the current subtree |
| **E** / **C** | expand / collapse everything |
| **PgUp/PgDn**, **Home/End** | scroll |
| **/** | filter resources |
| **q**, **Esc** | quit |
