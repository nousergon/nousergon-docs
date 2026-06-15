#!/usr/bin/env python3
"""Backfill the structured changelog corpus from the legacy event-typed prefixes.

PR 3 of the schema-discipline arc (ROADMAP > Observability >
"System-wide changelog: schema discipline + artifact linking +
aggregation layer"). Converts every entry under

  s3://alpha-engine-research/changelog/{deploys,incidents,manual,recoveries}/...

to a schema-1.0.0 structured entry at

  s3://alpha-engine-research/changelog/entries/{YYYY-MM-DD}/{event_id}.json

Idempotent — `aws s3 cp` is only invoked when the structured entry doesn't
already exist (HEAD probe). Operator runs this ONCE after PR 2 merges; PR 4
of the arc then switches the daily aggregator to read `entries/` exclusively.

Self-contained on stdlib + the `aws` CLI in PATH. No boto3 dependency so
the script runs in any environment where `aws s3` works (i.e., everywhere
the operator already runs `changelog-log` or `ae-changelog`).

Usage:
    python3 scripts/backfill_changelog.py --dry-run            # transform + print, no S3 writes
    python3 scripts/backfill_changelog.py                      # full backfill across all prefixes
    python3 scripts/backfill_changelog.py --prefix deploys     # one prefix only
    python3 scripts/backfill_changelog.py --limit 5            # sample first N entries (per prefix)
    python3 scripts/backfill_changelog.py --reprocess          # ignore "already exists" check + overwrite

Mapping rules — see TRANSFORMS below for the per-event-type logic. The
output schema (schema_version=1.0.0) matches changelog_log.py + the
composite action + SNS-mirror Lambda; backfilled entries carry
`backfilled: true` so future aggregation can flag them as
reconstructed-from-legacy + needing operator review for the controlled-
vocab fields that defaulted (subsystem / root_cause_category / etc.).
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

SCHEMA_VERSION = "1.0.0"
DEFAULT_BUCKET = "alpha-engine-research"
LEGACY_PREFIXES = ["deploys", "incidents", "manual", "recoveries"]
STRUCTURED_PREFIX = "changelog/entries"

# Repo → subsystem mapping. Mirrors the case-block in
# .github/actions/append-changelog/action.yml. Keep aligned.
REPO_SUBSYSTEM = {
    # Both pre- and post-rename short-names map, so historical backfill
    # data (old names) and live events (new names) both resolve.
    "alpha-engine": "executor",
    "crucible-executor": "executor",
    "alpha-engine-research": "research",
    "crucible-research": "research",
    "alpha-engine-predictor": "predictor",
    "crucible-predictor": "predictor",
    "alpha-engine-data": "data_pipeline",
    "nousergon-data": "data_pipeline",
    "alpha-engine-backtester": "backtester",
    "crucible-backtester": "backtester",
    "alpha-engine-dashboard": "dashboard",
    "crucible-dashboard": "dashboard",
    "alpha-engine-config": "infrastructure",
    "alpha-engine-docs": "infrastructure",
    "nousergon-docs": "infrastructure",
    "alpha-engine-lib": "infrastructure",
    "nousergon-lib": "infrastructure",
    "alpha-engine-evaluator": "infrastructure",
    "crucible-evaluator": "infrastructure",
    "mnemon": "infrastructure",
    "flow-doctor": "telemetry",
}


@dataclass
class BackfillStats:
    seen: int = 0
    written: int = 0
    skipped_already_exists: int = 0
    skipped_unrecognized: int = 0
    errors: int = 0


def _aws_s3_ls(bucket: str, prefix: str) -> list[str]:
    """Return list of object keys under `bucket/prefix` (recursive).

    `aws s3 ls` exits 1 when the prefix has no matches AND prints nothing
    on stderr in that case — distinct from real auth/network errors which
    do print to stderr. Treat empty-stdout + empty-stderr exit-1 as
    "prefix is empty" rather than fatal.
    """
    proc = subprocess.run(
        ["aws", "s3", "ls", f"s3://{bucket}/{prefix}", "--recursive"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        if not proc.stdout.strip() and not proc.stderr.strip():
            return []
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"ERROR: aws s3 ls failed (exit {proc.returncode})")
    keys: list[str] = []
    for line in proc.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[3].endswith(".json"):
            keys.append(parts[3])
    return keys


def _aws_s3_get(bucket: str, key: str) -> bytes:
    proc = subprocess.run(
        ["aws", "s3", "cp", f"s3://{bucket}/{key}", "-"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", errors="replace"))
        raise SystemExit(f"ERROR: aws s3 cp (read) failed for {key}")
    return proc.stdout


def _aws_s3_put(bucket: str, key: str, body: bytes) -> None:
    proc = subprocess.run(
        ["aws", "s3", "cp", "-", f"s3://{bucket}/{key}", "--content-type", "application/json"],
        input=body,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", errors="replace"))
        raise SystemExit(f"ERROR: aws s3 cp (write) failed for {key}")


def _aws_s3_exists(bucket: str, key: str) -> bool:
    """HEAD probe via `aws s3api head-object`. Returns True if the object exists."""
    proc = subprocess.run(
        ["aws", "s3api", "head-object", "--bucket", bucket, "--key", key],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def _event_id(ts_utc: str, actor: str, summary: str, *, segment: str | None = None) -> str:
    """Build the structured-corpus event_id.

    The digest input is always `{ts_utc}|{actor}|{summary}` (matches the
    changelog-log CLI + composite action + SNS-mirror Lambda) so the
    7-char hash is comparable across all writers. The HUMAN-READABLE
    middle segment, however, varies by emitter:

        composite action  → REPO_SHORT  (e.g. alpha-engine-data)
        SNS-mirror Lambda → topic name  (e.g. alpha-engine-alerts)
        changelog-log CLI → actor       (operator's username)

    Pass `segment=` explicitly to match a particular emitter's scheme;
    omit to default to the actor (matches the CLI). Critical for
    idempotency — the backfill must produce the same key the auto-emit
    would have, otherwise the HEAD probe sees no collision and writes
    a duplicate next to the auto-emit entry.
    """
    ts_id = ts_utc.replace(":", "-").rstrip("Z")
    digest_input = f"{ts_utc}|{actor}|{summary}".encode()
    h = hashlib.sha1(digest_input).hexdigest()[:7]
    middle = segment if segment is not None else actor
    middle_safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in middle)
    return f"{ts_id}_{middle_safe}_{h}"


def _struct_base(ts_utc: str) -> dict[str, Any]:
    """Skeleton with all schema-1.0.0 fields zeroed. Per-type transforms fill in."""
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": "",
        "ts_utc": ts_utc,
        "event_type": "",
        "severity": None,
        "subsystem": None,
        "root_cause_category": None,
        "resolution_type": None,
        "started_at": None,
        "detected_at": None,
        "resolved_at": None,
        "verified_at": None,
        "summary": "",
        "description": None,
        "resolution_notes": None,
        "actor": "",
        "machine": "",
        "source": "",
        "auto_emitted": True,
        "backfilled": True,
        "git_refs": [],
        "prompt_version": None,
        "run_id": None,
        "eval_run_ref": None,
    }


def transform_deploy(legacy: dict[str, Any]) -> dict[str, Any]:
    """Legacy deploy entry → schema-1.0.0 change/incident entry.

    Mirrors the composite action's mapping (see action.yml). Failed deploys
    become event_type=incident with infrastructure_failure root cause; success
    + merged become event_type=change with code_fix resolution.
    """
    ts_utc = legacy["ts_utc"]
    repo_full = legacy.get("repo", "")
    repo_short = repo_full.split("/", 1)[-1] if "/" in repo_full else repo_full
    subsystem = REPO_SUBSYSTEM.get(repo_short, "infrastructure")

    deploy_status = legacy.get("deploy_status", "success")
    pr_title = legacy.get("pr_title", "")
    pr_body = legacy.get("pr_body", "")
    actor = legacy.get("author", "")
    sha = legacy.get("sha", "")
    pr_number = legacy.get("pr_number")

    if deploy_status == "failure":
        event_type = "incident"
        severity = "medium"
        root_cause = "infrastructure_failure"
        resolution_type = None
    else:
        event_type = "change"
        severity = None
        root_cause = None
        resolution_type = "code_fix"

    out = _struct_base(ts_utc)
    # Deploy entries use REPO_SHORT for the human-readable segment to match
    # the composite action's scheme (action.yml line ~176). Mismatch here
    # produced duplicate entries during the first backfill run on 2026-05-01.
    out["event_id"] = _event_id(ts_utc, actor, pr_title, segment=repo_short)
    out["event_type"] = event_type
    out["severity"] = severity
    out["subsystem"] = subsystem
    out["root_cause_category"] = root_cause
    out["resolution_type"] = resolution_type
    out["detected_at"] = ts_utc
    out["resolved_at"] = ts_utc if event_type == "change" else None
    out["verified_at"] = ts_utc if event_type == "change" else None
    out["summary"] = pr_title or "(no PR title)"
    out["description"] = pr_body or None
    out["actor"] = actor or "ci-deploy"
    out["machine"] = "github-actions"
    out["source"] = "ci-deploy"

    git_ref: dict[str, Any] = {"repo": repo_full}
    if sha:
        git_ref["sha"] = sha
    if pr_number is not None:
        git_ref["pr_number"] = pr_number
    if git_ref.keys() != {"repo"}:
        out["git_refs"] = [git_ref]

    out["deploy"] = {
        "status": deploy_status,
        "workflow": legacy.get("deploy_workflow") or legacy.get("workflow_name", ""),
        "workflow_run_id": legacy.get("workflow_run_id", ""),
        "sha7": legacy.get("sha7", ""),
        "pr_url": legacy.get("pr_url", ""),
        "files_changed": legacy.get("files_changed", 0),
    }
    return out


def transform_incident(legacy: dict[str, Any]) -> dict[str, Any]:
    """Legacy SNS-mirrored incident → schema-1.0.0 incident entry.

    Defaults match the SNS-mirror Lambda's (severity=high, subsystem=
    infrastructure, root_cause_category=infrastructure_failure). Operator
    can refine via a follow-up `changelog-log --event-type investigation`
    entry whose git_refs reference the original event_id.
    """
    ts_utc = legacy["ts_utc"]
    source = legacy.get("source", "sns")
    summary = legacy.get("summary") or legacy.get("subject") or "(no subject)"
    details = legacy.get("details", "")
    sns_msg_id = legacy.get("sns_message_id", "")
    topic_arn = legacy.get("topic_arn", "")
    subject = legacy.get("subject", "")

    out = _struct_base(ts_utc)
    out["event_id"] = _event_id(ts_utc, source, summary)
    out["event_type"] = "incident"
    out["severity"] = "high"
    out["subsystem"] = "infrastructure"
    out["root_cause_category"] = "infrastructure_failure"
    out["detected_at"] = ts_utc
    out["summary"] = summary[:240]
    out["description"] = details or None
    out["actor"] = source
    out["machine"] = "lambda:changelog-incident-mirror"
    out["source"] = "sns-mirror"
    out["sns"] = {
        "subject": subject,
        "topic_arn": topic_arn,
        "message_id": sns_msg_id,
    }
    return out


def transform_manual(legacy: dict[str, Any]) -> dict[str, Any]:
    """Legacy operator-typed manual annotation → schema-1.0.0 change entry.

    Manual entries lack structured fields; default to event_type=change +
    resolution_type=manual_intervention + subsystem=infrastructure. These
    are the most likely candidates for operator refinement post-backfill
    since the original captured no semantic typing.
    """
    ts_utc = legacy["ts_utc"]
    actor = legacy.get("actor", "operator")
    summary = legacy.get("summary", "(no summary)")
    details = legacy.get("details", "")

    out = _struct_base(ts_utc)
    out["event_id"] = _event_id(ts_utc, actor, summary)
    out["event_type"] = "change"
    out["subsystem"] = "infrastructure"
    out["resolution_type"] = "manual_intervention"
    out["detected_at"] = ts_utc
    out["resolved_at"] = ts_utc
    out["verified_at"] = ts_utc
    out["summary"] = summary[:240]
    out["description"] = details or None
    out["actor"] = actor
    out["machine"] = legacy.get("machine", "")
    out["source"] = "changelog-log-legacy"
    out["auto_emitted"] = False
    return out


def transform_recovery(legacy: dict[str, Any]) -> dict[str, Any]:
    """Legacy operator-typed recovery → schema-1.0.0 recovery entry."""
    ts_utc = legacy["ts_utc"]
    actor = legacy.get("actor", "operator")
    summary = legacy.get("summary", "(no summary)")
    details = legacy.get("details", "")

    out = _struct_base(ts_utc)
    out["event_id"] = _event_id(ts_utc, actor, summary)
    out["event_type"] = "recovery"
    out["subsystem"] = "infrastructure"
    out["resolved_at"] = ts_utc
    out["verified_at"] = ts_utc
    out["summary"] = summary[:240]
    out["description"] = details or None
    out["actor"] = actor
    out["machine"] = legacy.get("machine", "")
    out["source"] = "changelog-log-legacy"
    out["auto_emitted"] = False
    return out


TRANSFORMS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "deploys": transform_deploy,
    "incidents": transform_incident,
    "manual": transform_manual,
    "recoveries": transform_recovery,
}


def _structured_key(entry: dict[str, Any]) -> str:
    date = entry["ts_utc"][:10]
    return f"{STRUCTURED_PREFIX}/{date}/{entry['event_id']}.json"


def backfill_one(
    bucket: str,
    legacy_key: str,
    transform: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    dry_run: bool = False,
    reprocess: bool = False,
) -> tuple[str, dict[str, Any] | None, str]:
    """Returns (status, entry, structured_key).

    status ∈ {"written", "skipped_exists", "skipped_unrecognized", "error"}.
    """
    raw = _aws_s3_get(bucket, legacy_key)
    try:
        legacy = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"ERROR: {legacy_key}: invalid JSON: {e}\n")
        return ("error", None, "")

    if "ts_utc" not in legacy:
        sys.stderr.write(f"WARN: {legacy_key}: no ts_utc; skipping\n")
        return ("skipped_unrecognized", None, "")

    entry = transform(legacy)
    s_key = _structured_key(entry)

    if not reprocess and not dry_run and _aws_s3_exists(bucket, s_key):
        return ("skipped_exists", entry, s_key)

    if dry_run:
        return ("written", entry, s_key)

    body = json.dumps(entry, ensure_ascii=False, sort_keys=True).encode("utf-8")
    _aws_s3_put(bucket, s_key, body)
    return ("written", entry, s_key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="backfill_changelog.py",
        description="One-shot backfill of legacy changelog entries to the structured corpus.",
    )
    parser.add_argument(
        "--bucket",
        default=DEFAULT_BUCKET,
        help=f"S3 bucket (default: {DEFAULT_BUCKET})",
    )
    parser.add_argument(
        "--prefix",
        choices=LEGACY_PREFIXES + ["all"],
        default="all",
        help="Which legacy sub-prefix to process (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read + transform + print but do not write to S3.",
    )
    parser.add_argument(
        "--reprocess",
        action="store_true",
        help="Overwrite structured entries that already exist (default: skip).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process at most N entries per prefix (0 = no limit). For sampling.",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print one line per entry processed."
    )
    args = parser.parse_args(argv)

    prefixes = LEGACY_PREFIXES if args.prefix == "all" else [args.prefix]
    grand_stats = BackfillStats()

    for sub in prefixes:
        transform = TRANSFORMS[sub]
        full_prefix = f"changelog/{sub}/"
        keys = _aws_s3_ls(args.bucket, full_prefix)
        if args.limit:
            keys = keys[: args.limit]
        sub_stats = BackfillStats()

        print(f"\n[{sub}] {len(keys)} legacy entries to process")

        for key in keys:
            sub_stats.seen += 1
            grand_stats.seen += 1
            try:
                status, entry, s_key = backfill_one(
                    args.bucket,
                    key,
                    transform,
                    dry_run=args.dry_run,
                    reprocess=args.reprocess,
                )
            except SystemExit:
                raise
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"ERROR processing {key}: {type(e).__name__}: {e}\n")
                sub_stats.errors += 1
                grand_stats.errors += 1
                continue

            if status == "written":
                sub_stats.written += 1
                grand_stats.written += 1
                if args.verbose or args.dry_run:
                    marker = "(dry-run) " if args.dry_run else ""
                    print(f"  {marker}{key} → {s_key}")
            elif status == "skipped_exists":
                sub_stats.skipped_already_exists += 1
                grand_stats.skipped_already_exists += 1
                if args.verbose:
                    print(f"  SKIP exists: {s_key}")
            elif status == "skipped_unrecognized":
                sub_stats.skipped_unrecognized += 1
                grand_stats.skipped_unrecognized += 1
            elif status == "error":
                sub_stats.errors += 1
                grand_stats.errors += 1

        print(
            f"  → seen={sub_stats.seen} written={sub_stats.written} "
            f"skipped_exists={sub_stats.skipped_already_exists} "
            f"skipped_unrecognized={sub_stats.skipped_unrecognized} "
            f"errors={sub_stats.errors}"
        )

    print(
        "\n=== TOTAL ===\n"
        f"seen                  {grand_stats.seen}\n"
        f"written               {grand_stats.written}\n"
        f"skipped (exists)      {grand_stats.skipped_already_exists}\n"
        f"skipped (unrecognized){grand_stats.skipped_unrecognized}\n"
        f"errors                {grand_stats.errors}"
    )

    if args.dry_run:
        print("\n(--dry-run; no S3 writes performed)")

    return 0 if grand_stats.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
