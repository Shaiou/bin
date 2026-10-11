# bin

Personal CLIs, packaged as one uv project (**tools**).

| Command | Purpose | Docs |
|---|---|---|
| **awc** | AWS: EC2 instances, S3 purge, console sign-in, IAM Identity Center audit | [docs/awc.md](docs/awc.md) |
| **gcp** | GCP: VMs, deleted principals in IAM, tag search | [docs/gcp.md](docs/gcp.md) |
| **tfc** | Terragrunt plan/apply (single or mass) with a change browser, state browser | [docs/tfc.md](docs/tfc.md) |

## Install

```bash
uv tool install --editable /Workspace/github/shaiou/bin   # awc, gcp, tfc in ~/.local/bin, edits are live
```

Run from the repo without installing:

```bash
uv run awc --help
```

## Layout

```
src/tools/ui.py      shared picker, table, confirm
src/tools/awc/       awc commands
src/tools/gcp/       gcp commands
src/tools/tfc/       tfc commands
docs/               one page per command
```

## License

[MIT](LICENSE)
