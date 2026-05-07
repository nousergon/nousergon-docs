# `append-changelog` composite action

Writes a JSON deploy-event to the system-wide changelog S3 prefix
(`s3://alpha-engine-research/changelog/`). Every alpha-engine* repo's
deploy workflow calls this on success so cross-repo deploy provenance
lives in one place. The companion `aggregate-changelog.yml` cron in
this repo materializes the entries into a Markdown view daily.

## Caller pattern

Add a final step to your existing deploy job:

```yaml
- name: Append to system changelog
  if: always()  # capture failures too — set deploy_status accordingly
  uses: cipher813/alpha-engine-docs/.github/actions/append-changelog@main
  with:
    deploy_status: ${{ job.status == 'success' && 'success' || 'failure' }}
    deploy_workflow: ${{ github.workflow }}
```

For repos without a CI deploy step (config / docs — where push-to-main
is the deploy itself), use a dedicated minimal workflow:

```yaml
on:
  push:
    branches: [main]

jobs:
  changelog:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - name: Configure AWS credentials via OIDC
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::711398986525:role/github-actions-lambda-deploy
          aws-region: us-east-1
      - uses: actions/checkout@v4
      - uses: cipher813/alpha-engine-docs/.github/actions/append-changelog@main
        with:
          deploy_status: merged
```

## What gets written

This action emits a single structured entry per deploy event to
`changelog/entries/{YYYY-MM-DD}/{event_id}.json` (schema 1.0.0).

Legacy dual-write to `changelog/deploys/{YYYY}/{MM}/{DD}T...` retired
2026-05-07 after the 1-week back-compat bake. Historical entries under
`changelog/deploys/` remain in S3 for retroactive queries.

### Structured entry (schema 1.0.0, `changelog/entries/...`)

```json
{
  "schema_version": "1.0.0",
  "event_id": "2026-05-01T15-23-44_alpha-engine-data_a1b2c3d",
  "ts_utc": "2026-05-01T15:23:44Z",
  "event_type": "change",
  "severity": null,
  "subsystem": "data_pipeline",
  "root_cause_category": null,
  "resolution_type": "code_fix",
  "started_at": null,
  "detected_at": "2026-05-01T15:23:44Z",
  "resolved_at": "2026-05-01T15:23:44Z",
  "verified_at": "2026-05-01T15:23:44Z",
  "summary": "feat(daily_append): producer-side universe-freshness scan + S3 receipt",
  "description": "<full PR body>",
  "resolution_notes": null,
  "actor": "cipher813",
  "machine": "github-actions",
  "source": "ci-deploy",
  "auto_emitted": true,
  "git_refs": [{"repo": "cipher813/alpha-engine-data", "sha": "febaccb...", "pr_number": 119}],
  "prompt_version": null,
  "run_id": null,
  "eval_run_ref": null,
  "deploy": {
    "status": "success",
    "workflow": "deploy.yml",
    "workflow_run_id": "1234567890",
    "sha7": "febaccb",
    "pr_url": "https://github.com/cipher813/alpha-engine-data/pull/119",
    "files_changed": 8
  }
}
```

`event_type` is `change` for `deploy_status ∈ {success, merged}` and
`incident` for `failure`. `subsystem` is derived from the repo name
(see the case-block in `action.yml`); pass `subsystem:` input to
override. `auto_emitted: true` flags this as written by CI rather
than by an operator — future aggregation can surface "needs review"
entries (e.g., incident entries needing a `root_cause_category`).

`pr_number` + `pr_title` are auto-derived from the merge-commit message
(`<title> (#<number>)` shape from squash/merge-commit/rebase strategies).
`pr_body` is auto-fetched via `gh api repos/{owner}/{repo}/pulls/{n}`
using the runner's `GITHUB_TOKEN` (no extra secret to wire). The full PR
body lands in `description` (untruncated) so retro mining queries have
the problem-statement + solution-rationale text to grep, not just the
title.

## Event types + sibling sources

The structured corpus uses the controlled-vocab `event_type` from
`alpha-engine-config/changelog/vocab.yaml` (incident, change, recovery,
investigation, regression_test_added, prompt_version_change,
infrastructure_change, eval_score_regression). This action emits
`change` for successful deploys and `incident` for failed ones.

Other event types come from sibling tooling:

| Source | event_type emitted | Surface |
|---|---|---|
| this composite action  | `change` / `incident` | CI on push-to-main |
| SNS-to-S3 mirror Lambda (alpha-engine-data) | `incident` | alpha-engine-alerts SNS subscriber |
| `changelog-log` CLI    | any                  | operator manual annotations |

Historical legacy event-typed sub-prefixes (`changelog/deploys/`,
`changelog/incidents/`, `changelog/manual/`, `changelog/recoveries/`)
remain in S3 for retroactive queries; new writes land at
`changelog/entries/` only since 2026-05-07.

## Reading the materialized changelog

Local pull:

```bash
aws s3 cp s3://alpha-engine-research/changelog/CHANGELOG.md \
  ~/Development/alpha-engine-docs/private/CHANGELOG.md
```

Or query S3 directly:

```bash
aws s3 ls s3://alpha-engine-research/changelog/2026/05/ --recursive
aws s3 cp s3://alpha-engine-research/changelog/2026/05/01T15-23-44_alpha-engine-data_febaccb.json -
```

## IAM grant

The OIDC role `github-actions-lambda-deploy` needs:

```json
{
  "Effect": "Allow",
  "Action": ["s3:PutObject", "s3:GetObject", "s3:ListBucket"],
  "Resource": [
    "arn:aws:s3:::alpha-engine-research",
    "arn:aws:s3:::alpha-engine-research/changelog/*"
  ]
}
```

(`ListBucket` is on the bucket itself, `PutObject` + `GetObject` on the
prefix. The aggregator needs ListBucket to enumerate; appenders only need
PutObject.)
