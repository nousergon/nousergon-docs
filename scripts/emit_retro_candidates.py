#!/usr/bin/env python3
"""Emit a rolling `changelog/retro_candidates.json` for the console Retros page.

The weekly/monthly rollups (`aggregate_periodic.py`) already embed a
`retro_candidates` list scoped to their period. This script produces a single,
always-current, rolling-window view of the SAME mined set so the dashboard
console has one small artifact to read instead of stitching period rollups.

Discipline (per `feedback_retros_scaffold_auto_narrative_manual`): this emits the
FACTUAL scaffold only — the qualifying incidents and their operator-authored
`resolution_notes`. It does NOT synthesize a narrative; the retro write-up stays
manual. The filter itself is reused verbatim from
`aggregate_periodic.extract_retro_candidates` (single source of truth — an
incident is a retro candidate iff `event_type=incident` ∧
`severity ∈ {high, critical}` ∧ `root_cause_category` populated ∧
`resolution_notes ≥ 200 chars`).

Run from the daily aggregator workflow (`aggregate-changelog.yml`) after the
entries sync. Self-contained on stdlib + the `aws` CLI subprocess (no boto3),
matching `aggregate_periodic.py`.

JSON shape (schema 1.0.0):
    schema_version: "1.0.0"
    generated_at:   "2026-06-07T06:00:00Z"
    window_days:    90
    window_start:   "2026-03-09"     (inclusive, UTC)
    window_end:     "2026-06-07"     (inclusive, UTC)
    # "Ready for retro" — incidents an operator already wrote up (editorial
    # detail). Empty until someone annotates via changelog-log.
    ready_for_retro_count: N
    ready_for_retro: [
        {event_id, ts_utc, severity, subsystem, root_cause_category,
         resolution_type, summary, resolution_notes, git_refs}, ...
    ]                                 (newest-first)
    # "Incidents to review" — all real high/critical incidents in the window,
    # grouped by (subsystem, normalized summary) so recurring failures collapse
    # to one row with a count. Depends on correct event_type/severity, so
    # requires the alpha-engine-data classifier fix to exclude SUCCESS/OK noise.
    incident_group_count: M
    incident_total:       K           (sum of group counts)
    incident_groups: [
        {subsystem, severity, count, latest_ts, latest_event_id, summary,
         has_writeup}, ...
    ]                                 (newest-first by latest_ts)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Callable, Mapping, Sequence
from typing import NotRequired, TypedDict, cast

# scripts/ is on sys.path[0] when invoked as `python3 scripts/emit_retro_candidates.py`,
# so the sibling module imports resolve without packaging.
import aggregate_periodic

from aggregate_periodic import (
    DEFAULT_BUCKET,
    ENTRIES_PREFIX,
    RETRO_RESOLUTION_NOTES_MIN_CHARS,
    RETRO_SEVERITIES,
    SCHEMA_VERSION,
    extract_retro_candidates,
    load_entries_in_range,
)

DEFAULT_OUT_KEY = "changelog/retro_candidates.json"
DEFAULT_WINDOW_DAYS = 90

# Fields projected into the artifact. Kept explicit (not a passthrough of the raw
# entry) so the dashboard contract is stable even if entry schema 1.0.0 grows.
_PROJECT_FIELDS = (
    "event_id",
    "ts_utc",
    "severity",
    "subsystem",
    "root_cause_category",
    "resolution_type",
    "summary",
    "resolution_notes",
    "git_refs",
)

JSONValue = None | bool | int | float | str | Sequence["JSONValue"] | Mapping[str, "JSONValue"]
_aws_s3_put = cast(Callable[[str, str, bytes, str], None], getattr(aggregate_periodic, "_aws_s3_put"))
_aws_s3_sync = cast(Callable[[str, str, Path], None], getattr(aggregate_periodic, "_aws_s3_sync"))
_utc_today = cast(Callable[[], date], getattr(aggregate_periodic, "_utc_today"))


class ChangelogEntry(TypedDict):
    """Fields read from changelog JSON; producers may omit any field."""

    event_id: NotRequired[str]
    ts_utc: NotRequired[str]
    event_type: NotRequired[str]
    severity: NotRequired[str]
    subsystem: NotRequired[str]
    root_cause_category: NotRequired[str]
    resolution_type: NotRequired[str]
    summary: NotRequired[str]
    resolution_notes: NotRequired[str | None]
    git_refs: NotRequired[list[JSONValue]]


class IncidentGroup(TypedDict):
    subsystem: str
    severity: str
    count: int
    latest_ts: str
    latest_event_id: str
    summary: str
    has_writeup: bool


class Payload(TypedDict):
    schema_version: str
    generated_at: str
    window_days: int
    window_start: str
    window_end: str
    ready_for_retro_count: int
    ready_for_retro: list[dict[str, JSONValue]]
    incident_group_count: int
    incident_total: int
    incident_groups: list[IncidentGroup]


def _normalize_git_refs(refs: JSONValue) -> list[dict[str, JSONValue]]:
    """Coerce git_refs to a list of dicts. Some legacy producers (e.g.
    prompt-version-autoemit) write bare SHA strings; the dashboard renderer
    expects dicts, so normalize here at the contract boundary."""
    out: list[dict[str, JSONValue]] = []
    if not isinstance(refs, list):
        return out
    for r in refs:
        if isinstance(r, dict):
            out.append(r)
        elif isinstance(r, str):
            out.append({"sha": r})
    return out


def project_candidate(e: ChangelogEntry) -> dict[str, JSONValue]:
    """Project a raw entry to the stable console contract subset."""
    proj = {k: e.get(k) for k in _PROJECT_FIELDS}
    proj["git_refs"] = _normalize_git_refs(proj.get("git_refs"))
    return proj


# Severity rank for picking a group's representative (worst) severity.
_SEVERITY_RANK = {"critical": 2, "high": 1}

# Noise stripped when normalizing a summary into a recurrence key. NOTE: the
# quoted CloudWatch alarm name is deliberately KEPT — it's the incident's
# identity, so two different alarms must not collapse into one group. Only
# volatile noise is removed: the constant region suffix, bracketed severity
# tags, digits (ids/timestamps), and punctuation.
_REGION = re.compile(r"in us east \(n\. virginia\)", re.IGNORECASE)
_BRACKET = re.compile(r"\[[^\]]*\]")
_NONWORD = re.compile(r"[^a-z0-9]+")
_DIGITS = re.compile(r"\d+")


def _normalize_summary(summary: str) -> str:
    """Collapse a summary to a stable recurrence key so repeated occurrences of
    the SAME incident (e.g. 39× 'Saturday Pipeline — FAILED', or N firings of a
    given named alarm) group into one row, while distinct incidents stay
    separate."""
    s = (summary or "").lower()
    s = _REGION.sub(" ", s)
    s = _BRACKET.sub(" ", s)
    s = _DIGITS.sub(" ", s)
    s = _NONWORD.sub(" ", s)
    return " ".join(s.split())


def group_incidents(entries: list[ChangelogEntry]) -> list[IncidentGroup]:
    """Group real high/critical incidents by (subsystem, normalized summary) so
    the console shows distinct recurring failures with a count instead of a flat
    list of hundreds of near-duplicate rows. Newest-first by latest occurrence.

    Relies on correct event_type/severity — SUCCESS/OK entries are no longer
    incidents after the classifier fix (alpha-engine-data), so they don't
    appear here.
    """
    groups: dict[tuple[str, str], IncidentGroup] = {}
    for e in entries:
        if e.get("event_type") != "incident":
            continue
        severity_value = e.get("severity")
        if not isinstance(severity_value, str) or severity_value not in RETRO_SEVERITIES:
            continue
        subsystem_value = e.get("subsystem")
        subsystem = subsystem_value if isinstance(subsystem_value, str) else "—"
        summary_value = e.get("summary")
        summary = summary_value if isinstance(summary_value, str) else ""
        key = (subsystem, _normalize_summary(summary))
        ts_value = e.get("ts_utc")
        ts = ts_value if isinstance(ts_value, str) else ""
        notes = e.get("resolution_notes")
        has_writeup = isinstance(notes, str) and len(notes) >= RETRO_RESOLUTION_NOTES_MIN_CHARS
        g = groups.get(key)
        if g is None:
            groups[key] = {
                "subsystem": subsystem,
                "severity": severity_value,
                "count": 1,
                "latest_ts": ts,
                "latest_event_id": e.get("event_id") or "",
                "summary": summary,
                "has_writeup": has_writeup,
            }
        else:
            g["count"] += 1
            severity = severity_value
            if _SEVERITY_RANK.get(severity, 0) > _SEVERITY_RANK.get(g["severity"], 0):
                g["severity"] = severity
            g["has_writeup"] = g["has_writeup"] or has_writeup
            if ts > (g["latest_ts"] or ""):
                g["latest_ts"] = ts
                g["latest_event_id"] = e.get("event_id") or ""
                g["summary"] = summary
    return sorted(groups.values(), key=lambda g: g["latest_ts"] or "", reverse=True)


def build_payload(entries: list[ChangelogEntry], window_days: int,
                  window_start: date, window_end: date) -> Payload:
    # "Ready for retro" — incidents an operator has already written up (full
    # editorial detail, incl. resolution_notes). Empty until annotation happens.
    raw_candidates = extract_retro_candidates(cast(list[dict[str, object]], entries))
    ready = [project_candidate(cast(ChangelogEntry, e)) for e in raw_candidates]
    # "Incidents to review" — all real high/critical incidents, grouped.
    incident_groups = group_incidents(entries)
    total_incidents = sum(g["count"] for g in incident_groups)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_days": window_days,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "ready_for_retro_count": len(ready),
        "ready_for_retro": ready,
        "incident_group_count": len(incident_groups),
        "incident_total": total_incidents,
        "incident_groups": incident_groups,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--out-key", default=DEFAULT_OUT_KEY)
    parser.add_argument(
        "--window-days", type=int, default=DEFAULT_WINDOW_DAYS,
        help="Rolling window size in days (inclusive of today, UTC).",
    )
    parser.add_argument(
        "--corpus-dir", default=None,
        help=(
            "Local dir of already-synced entries (the daily workflow passes "
            "/tmp/entries to avoid a second sync). If omitted, syncs "
            "s3://{bucket}/changelog/entries/ to a temp dir."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the payload to stdout instead of writing to S3.",
    )
    args = parser.parse_args(argv)

    window_end = _utc_today()
    window_start = window_end - timedelta(days=args.window_days)

    def _emit(corpus_dir: Path) -> Payload:
        entries = cast(list[ChangelogEntry], load_entries_in_range(corpus_dir, window_start, window_end))
        return build_payload(entries, args.window_days, window_start, window_end)

    if args.corpus_dir:
        payload = _emit(Path(args.corpus_dir))
    else:
        with tempfile.TemporaryDirectory() as tmp:
            corpus_dir = Path(tmp)
            _aws_s3_sync(args.bucket, ENTRIES_PREFIX + "/", corpus_dir)
            payload = _emit(corpus_dir)

    body = json.dumps(payload, indent=2).encode("utf-8")

    if args.dry_run:
        sys.stdout.write(body.decode("utf-8") + "\n")
    else:
        _aws_s3_put(args.bucket, args.out_key, body, "application/json")
        print(
            f"Wrote s3://{args.bucket}/{args.out_key} "
            f"({payload['ready_for_retro_count']} ready, "
            f"{payload['incident_group_count']} incident group(s), "
            f"window {window_start}..{window_end})"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
