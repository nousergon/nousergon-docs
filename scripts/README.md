# `scripts/` — operational helpers

Local + on-machine helpers for the system-wide changelog mining surface.
None of these are auto-invoked; they exist for the operator to drop
manual annotations into the changelog or pull aggregated views locally.

## `changelog-log` — structured manual annotations

Drops a JSON entry into `s3://alpha-engine-research/changelog/entries/{YYYY-MM-DD}/`
(structured corpus, source-of-truth) AND mirrors to the legacy
`changelog/{deploys,incidents,manual,recoveries}/` prefix during the
back-compat window so manual operator actions interleave with auto-emitted
deploys + incidents in the daily-aggregated `CHANGELOG.md`.

```bash
# Incident — all 4 timestamps + root cause + ≥ 200-char resolution narrative
changelog-log \
  --event-type incident --severity high --subsystem infrastructure \
  --root-cause infrastructure_failure \
  --started-at  2026-05-01T13:00:00Z \
  --detected-at 2026-05-01T13:01:00Z \
  --resolved-at 2026-05-01T14:30:00Z \
  --verified-at 2026-05-01T14:35:00Z \
  --summary "SF DeployDriftCheck timeout cascade" \
  --resolution-notes "yfinance VWAP=None silently coerced to NaN downstream → universe-wide signal degradation. Switched to Polygon as primary source + added explicit null-handling at ingest. Added regression test for null-VWAP handling."

# Manual operator action (event_type=change, resolution_type=manual_intervention)
changelog-log \
  --event-type change --subsystem executor \
  --resolution-type manual_intervention \
  --detected-at 2026-05-01T19:00:00Z \
  --resolved-at 2026-05-01T19:05:00Z \
  --verified-at 2026-05-01T19:06:00Z \
  --summary "Killed hung daemon pid 12345 on ae-trading"

# Investigation that produced no code change
changelog-log \
  --event-type investigation --subsystem predictor \
  --detected-at 2026-05-01T19:00:00Z \
  --summary "Triaged GBM IC drop — turned out to be expected post-retrain noise"
```

The legacy positional form (`changelog-log manual "summary"`) was removed
in PR 1 of the schema-discipline arc; the bash shim prints a migration
message + exits non-zero if invoked that way.

**Setup** — add to `~/.zshrc`:

```bash
alias changelog-log="$HOME/Development/alpha-engine-docs/scripts/changelog-log.sh"
```

**Vocab** — the CLI reads `~/Development/alpha-engine-config/changelog/vocab.yaml`
(override via `$ALPHA_ENGINE_CONFIG` or `$ALPHA_ENGINE_CHANGELOG_VOCAB`). Allowed
values for `--event-type`, `--severity`, `--subsystem`, `--root-cause`,
`--resolution-type` are listed there. Invalid values fail validation and the
entry is NOT written.

**Auth** — uses active AWS CLI creds. Needs `s3:PutObject` on
`arn:aws:s3:::alpha-engine-research/changelog/*`. The `cipher813` IAM user
already has it; for other operators, grant separately.

**Why structured** — freeform-text entries can't answer "show every retrieval
issue in Q3" or "every prompt regression linked to version X.Y.Z." The
controlled-vocab fields convert the changelog from a WIP narrative into a
queryable dataset. See ROADMAP > Observability > "System-wide changelog:
schema discipline + artifact linking + aggregation layer" (P1) for the full
arc; this is PR 1 (writer + vocab).

**Tests** — `python3 scripts/test_changelog_log.py` runs the smoke suite
(17 cases covering vocab loading, validation rules, S3 key derivation, the
legacy-shim error path, and an end-to-end --dry-run).

## `backfill_changelog.py` — one-shot migration of legacy entries

Converts every entry under the legacy event-typed prefixes
(`changelog/{deploys,incidents,manual,recoveries}/...`) to the
schema-1.0.0 structured corpus at
`changelog/entries/{YYYY-MM-DD}/{event_id}.json`. PR 3 of the
schema-discipline arc — operator runs once after the auto-emit PRs
land; PR 4 then flips the daily aggregator to read `entries/`
exclusively.

```bash
# Sample-test with 5 entries per prefix, no S3 writes
python3 scripts/backfill_changelog.py --dry-run --limit 5 --verbose

# Full backfill across all legacy prefixes (idempotent — HEAD probe skips
# entries already in structured form)
python3 scripts/backfill_changelog.py

# Re-process a single prefix only
python3 scripts/backfill_changelog.py --prefix incidents

# Force overwrite (rare — use only if you've changed the transform logic
# and want to re-run against an already-backfilled corpus)
python3 scripts/backfill_changelog.py --reprocess
```

Backfilled entries carry `backfilled: true` so future aggregation can
flag them as reconstructed-from-legacy + needing operator review for
the controlled-vocab fields that defaulted (subsystem,
`root_cause_category`, etc.). No external Python deps; runs against
the `aws` CLI via subprocess.

**Tests** — `python3 scripts/test_backfill_changelog.py` runs the
12-case transform suite (deploy → change/incident, incident, manual
→ change, recovery, subsystem inference, deterministic event_id).

## `aggregate_periodic.py` — weekly + monthly rollups

Generates structured rollup aggregates of the structured changelog
corpus over weekly + monthly windows. Invoked by the
`aggregate-changelog-weekly.yml` (Mondays 07:00 UTC) and
`aggregate-changelog-monthly.yml` (1st of month 08:00 UTC) cron
workflows in this repo. Each run reads
`s3://alpha-engine-research/changelog/entries/` and writes:

- `s3://alpha-engine-research/changelog/aggregates/{period_type}/{period_id}.json`
- `s3://alpha-engine-research/changelog/aggregates/{period_type}/{period_id}.md`

PR 5 of the schema-discipline arc — sub-item 4 of the ROADMAP item.
Daily rollup lives in `aggregate-changelog.yml`.

```bash
# Local dry-run against the live corpus (downloads to a temp dir)
python3 scripts/aggregate_periodic.py --period weekly --dry-run
python3 scripts/aggregate_periodic.py --period monthly --dry-run

# Anchor the rollup to a specific date — useful for backfilling old periods
python3 scripts/aggregate_periodic.py --period weekly --reference-date 2026-04-20

# Use a local corpus dir (skips the S3 sync)
python3 scripts/aggregate_periodic.py --period weekly --corpus-dir /tmp/entries
```

Each rollup contains entry counts by `event_type` / `subsystem` /
`severity` / `root_cause_category` / `resolution_type`, incident
metrics (count, MTTD + MTTR with mean / p50 / p95), longest-lived
open issues (entries with `started_at` populated but `resolved_at`
null), and deltas vs the prior period (entry count, incident count,
MTTR mean).

**Tests** — `python3 scripts/test_aggregate_periodic.py` runs the
14-case suite (period boundary math, rollup counts, incident metric
computation, open-issue selection, delta computation, markdown
render, second-formatting helpers).

## `ae-changelog` — pull aggregated CHANGELOG.md as a versioned snapshot

```bash
ae-changelog              # pull latest, save to private/CHANGELOG_<ver>.md
ae-changelog --force      # re-download even if a snapshot for this version exists
ae-changelog --latest     # also write/update private/CHANGELOG.md (always-latest pointer)
```

Each pull is a discrete snapshot named with the S3 object's
`Last-Modified` timestamp (the aggregator's last-run time). Multiple
pulls of the same aggregator-version are idempotent — same filename,
no re-download unless `--force`.

**Setup** — add to `~/.zshrc`:

```bash
alias ae-changelog="$HOME/Development/alpha-engine-docs/scripts/ae-changelog.sh"
```

**Auth** — uses active AWS CLI creds. Needs `s3:GetObject` on
`arn:aws:s3:::alpha-engine-research/changelog/CHANGELOG.md`. Personal
IAM user already has it.

**Aggregator cadence** — runs daily at 06:00 UTC. To force a refresh
between scheduled runs:

```bash
gh workflow run aggregate-changelog.yml -R nousergon/nousergon-docs
```
