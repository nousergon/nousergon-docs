#!/usr/bin/env python3
"""changelog-log — emit a structured entry to the system-wide changelog.

PR 1 of the schema-discipline arc (ROADMAP > Observability >
"System-wide changelog: schema discipline + artifact linking +
aggregation layer"). Replaces the freeform-text body of the legacy
shim with controlled-vocab validation + structured-fields persistence.

Writes entries to TWO S3 prefixes during the back-compat window per
CLAUDE.md S3 contract ("write to BOTH old and new paths for at least
1 week before removing the old path"):

  1. NEW (structured corpus, source-of-truth going forward):
     s3://alpha-engine-research/changelog/entries/{YYYY-MM-DD}/{event_id}.json

  2. OLD (legacy event-typed prefix, still consumed by the daily
     aggregator at this point — read by the existing Markdown
     renderer in alpha-engine-docs/.github/workflows/aggregate-changelog.yml):
     s3://alpha-engine-research/changelog/{deploys|incidents|manual|recoveries}/...

The dual-write window closes when the aggregator switches to reading
`entries/` exclusively (PR 4 of this arc) and the legacy Markdown
corpus has been backfilled from `entries/` (PR 2).

Validation: required-fields + controlled-vocab enforcement happens at
write time. Invalid invocations exit non-zero and write nothing — no
quarantine path here because the CLI is operator-facing and the
operator can fix the invocation. Auto-emitters (composite action,
SNS-mirror Lambda, future cost-anomaly hooks) WILL use a quarantine
prefix when those PRs land — different surface, different policy.

Vocab source-of-truth lives at `~/Development/alpha-engine-config/changelog/vocab.yaml`.
The path is resolved via $ALPHA_ENGINE_CONFIG (set on EC2) or
$HOME/Development/alpha-engine-config locally; the script fails
loudly if it cannot find the vocab file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

SCHEMA_VERSION = "1.0.0"
DEFAULT_BUCKET = "alpha-engine-research"
NEW_PREFIX = "changelog/entries"
LEGACY_PREFIX_BY_TYPE = {
    "incident": "changelog/incidents",
    "change": "changelog/manual",
    "recovery": "changelog/recoveries",
    "investigation": "changelog/manual",
    "regression_test_added": "changelog/manual",
    "prompt_version_change": "changelog/manual",
    "infrastructure_change": "changelog/manual",
    "eval_score_regression": "changelog/incidents",
}
RESOLUTION_NOTES_MIN_CHARS = 200


class GitRefSha(TypedDict):
    """`git_refs` element pinning a repo to a commit SHA (`repo@sha`)."""

    repo: str
    sha: str


class GitRefPr(TypedDict):
    """`git_refs` element pinning a repo to a PR number (`repo#pr_number`)."""

    repo: str
    pr_number: int


# One `git_refs` element: a repo pinned to either a SHA or a PR number.
GitRef = GitRefSha | GitRefPr


class PromptVersion(TypedDict):
    """`prompt_version` payload built from `--prompt-version prompt_id:version`."""

    prompt_id: str
    version: str


@dataclass
class Vocab:
    event_type: list[str]
    severity: list[str]
    subsystem: list[str]
    root_cause_category: list[str]
    resolution_type: list[str]
    version: str = "0.0.0"

    @classmethod
    def load(cls, path: Path) -> "Vocab":
        if not path.exists():
            raise SystemExit(
                f"ERROR: vocab file not found: {path}\n"
                "Set $ALPHA_ENGINE_CONFIG or check that "
                "alpha-engine-config is cloned in ~/Development/."
            )
        text = path.read_text()
        try:
            import yaml  # PyYAML — preferred when available
            data = yaml.safe_load(text)
        except ImportError:
            data = _parse_vocab_yaml_subset(text)
        return cls(
            version=str(data.get("version", "0.0.0")),
            event_type=list(data["event_type"]),
            severity=list(data["severity"]),
            subsystem=list(data["subsystem"]),
            root_cause_category=list(data["root_cause_category"]),
            resolution_type=list(data["resolution_type"]),
        )


def _parse_vocab_yaml_subset(text: str) -> dict[str, str | list[str]]:
    """Stdlib-only parser for the vocab.yaml format.

    Supports exactly the subset we use:
      key: "value"            # scalar string
      key: value              # bare scalar string
      key:                    # list-of-strings
        - item_a              # block style
        - item_b
      key: [a, b, c]          # flow-style list of bare/quoted strings

    Whitespace + `# ...` comments tolerated. Anything else raises a
    clear error rather than silently parsing wrong — vocab files are
    short and the failure mode of "guessed wrong about a field"
    silently breaks validation.
    """
    out: dict[str, str | list[str]] = {}
    current_key: str | None = None
    current_list: list[str] | None = None

    for raw_line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        if line.startswith(("  - ", "    - ", "\t- ")) or line.lstrip().startswith("- "):
            if current_list is None or current_key is None:
                raise ValueError(
                    f"vocab.yaml line {raw_line_no}: list item without an open key"
                )
            current_list.append(_unquote(line.lstrip()[2:].strip()))
            continue

        if line[0] in (" ", "\t"):
            raise ValueError(
                f"vocab.yaml line {raw_line_no}: unexpected indentation: {raw!r}"
            )

        if ":" not in line:
            raise ValueError(f"vocab.yaml line {raw_line_no}: expected 'key: value' or 'key:': {raw!r}")

        key, _, rest = line.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest == "":
            current_key = key
            current_list = []
            out[key] = current_list
        elif rest.startswith("[") and rest.endswith("]"):
            items = [_unquote(p.strip()) for p in rest[1:-1].split(",") if p.strip()]
            out[key] = items
            current_key = None
            current_list = None
        else:
            out[key] = _unquote(rest)
            current_key = None
            current_list = None
    return out


def _unquote(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def _vocab_path() -> Path:
    override = os.environ.get("ALPHA_ENGINE_CHANGELOG_VOCAB")
    if override:
        return Path(override)
    base = os.environ.get("ALPHA_ENGINE_CONFIG") or str(
        Path.home() / "Development" / "alpha-engine-config"
    )
    return Path(base) / "changelog" / "vocab.yaml"


@dataclass
class Entry:
    event_type: str
    summary: str
    actor: str
    ts_utc: str
    severity: str | None = None
    subsystem: str | None = None
    root_cause_category: str | None = None
    resolution_type: str | None = None
    started_at: str | None = None
    detected_at: str | None = None
    resolved_at: str | None = None
    verified_at: str | None = None
    description: str | None = None
    resolution_notes: str | None = None
    git_refs: list[GitRef] = field(default_factory=list)
    prompt_version: PromptVersion | None = None
    run_id: str | None = None
    eval_run_ref: str | None = None
    machine: str = ""
    source: str = "changelog-log"

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "event_id": self._event_id(),
            "ts_utc": self.ts_utc,
            "event_type": self.event_type,
            "summary": self.summary,
            "source": self.source,
            "actor": self.actor,
            "machine": self.machine,
        }
        for k in (
            "severity",
            "subsystem",
            "root_cause_category",
            "resolution_type",
            "started_at",
            "detected_at",
            "resolved_at",
            "verified_at",
            "description",
            "resolution_notes",
            "run_id",
            "eval_run_ref",
        ):
            v = getattr(self, k)
            d[k] = v if v else None
        d["git_refs"] = self.git_refs
        d["prompt_version"] = self.prompt_version
        return d

    def _event_id(self) -> str:
        ts_key = self.ts_utc.replace(":", "-").replace("Z", "")
        digest_input = f"{self.ts_utc}|{self.actor}|{self.summary}".encode()
        h = hashlib.sha1(digest_input).hexdigest()[:7]
        actor_safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.actor)
        return f"{ts_key}_{actor_safe}_{h}"

    def s3_keys(self) -> tuple[str, str]:
        ts = self.ts_utc[:10]
        new_key = f"{NEW_PREFIX}/{ts}/{self._event_id()}.json"

        legacy_prefix = LEGACY_PREFIX_BY_TYPE.get(self.event_type)
        if legacy_prefix:
            ts_path = self.ts_utc[:4] + "/" + self.ts_utc[5:7] + "/"
            time_part = self.ts_utc[8:10] + "T" + self.ts_utc[11:13] + "-" + self.ts_utc[14:16] + "-" + self.ts_utc[17:19]
            actor_safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.actor)
            digest_input = f"{self.ts_utc}|{self.actor}|{self.summary}".encode()
            h = hashlib.sha1(digest_input).hexdigest()[:7]
            legacy_key = f"{legacy_prefix}/{ts_path}{time_part}_{actor_safe}_{h}.json"
        else:
            legacy_key = ""
        return new_key, legacy_key


REQUIRED_BY_TYPE: dict[str, list[str]] = {
    "incident": [
        "severity",
        "subsystem",
        "root_cause_category",
        "started_at",
        "detected_at",
        "resolved_at",
        "verified_at",
        "resolution_notes",
    ],
    "change": [
        "subsystem",
        "resolution_type",
        "detected_at",
        "resolved_at",
        "verified_at",
    ],
    "recovery": [
        "subsystem",
        "resolved_at",
        "verified_at",
    ],
    "investigation": [
        "subsystem",
        "detected_at",
    ],
    "regression_test_added": [
        "subsystem",
        "resolved_at",
    ],
    "prompt_version_change": [
        "subsystem",
        "resolution_type",
        "resolved_at",
        "prompt_version",
    ],
    "infrastructure_change": [
        "subsystem",
        "resolution_type",
        "resolved_at",
        "verified_at",
    ],
    "eval_score_regression": [
        "subsystem",
        "severity",
        "detected_at",
        "eval_run_ref",
    ],
}


def validate(entry: Entry, vocab: Vocab) -> list[str]:
    """Return a list of human-readable validation errors. Empty = OK."""
    errors: list[str] = []

    if entry.event_type not in vocab.event_type:
        errors.append(
            f"event_type='{entry.event_type}' not in vocab; allowed: {vocab.event_type}"
        )
    if entry.severity and entry.severity not in vocab.severity:
        errors.append(
            f"severity='{entry.severity}' not in vocab; allowed: {vocab.severity}"
        )
    if entry.subsystem and entry.subsystem not in vocab.subsystem:
        errors.append(
            f"subsystem='{entry.subsystem}' not in vocab; allowed: {vocab.subsystem}"
        )
    if entry.root_cause_category and entry.root_cause_category not in vocab.root_cause_category:
        errors.append(
            f"root_cause_category='{entry.root_cause_category}' not in vocab; "
            f"allowed: {vocab.root_cause_category}"
        )
    if entry.resolution_type and entry.resolution_type not in vocab.resolution_type:
        errors.append(
            f"resolution_type='{entry.resolution_type}' not in vocab; "
            f"allowed: {vocab.resolution_type}"
        )

    required = REQUIRED_BY_TYPE.get(entry.event_type, [])
    for f_name in required:
        v = getattr(entry, f_name, None)
        if v in (None, "", [], {}):
            errors.append(f"event_type='{entry.event_type}' requires field '{f_name}'")

    if entry.event_type == "incident" and entry.resolution_notes:
        if len(entry.resolution_notes) < RESOLUTION_NOTES_MIN_CHARS:
            errors.append(
                f"resolution_notes too short ({len(entry.resolution_notes)} chars); "
                f"incident entries require ≥ {RESOLUTION_NOTES_MIN_CHARS} for "
                "root-cause depth (see ROADMAP sub-item 3)."
            )

    for ts_field in ("started_at", "detected_at", "resolved_at", "verified_at"):
        v = getattr(entry, ts_field, None)
        if v and not _is_iso8601_utc(v):
            errors.append(
                f"{ts_field}='{v}' is not ISO-8601 UTC (expected like '2026-05-01T19:30:00Z')"
            )

    if not entry.summary or not entry.summary.strip():
        errors.append("summary is required and must be non-empty")
    if entry.summary and len(entry.summary) > 240:
        errors.append(
            f"summary too long ({len(entry.summary)} chars); keep ≤ 240 — long-form goes in description"
        )

    return errors


def _is_iso8601_utc(s: str) -> bool:
    try:
        if not s.endswith("Z"):
            return False
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return True
    except (ValueError, TypeError):
        return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_git_refs(values: list[str]) -> list[GitRef]:
    refs: list[GitRef] = []
    for v in values:
        if "@" in v:
            repo, sha = v.split("@", 1)
            refs.append({"repo": repo.strip(), "sha": sha.strip()})
        elif "#" in v:
            repo, pr = v.split("#", 1)
            try:
                pr_num = int(pr.strip())
            except ValueError:
                raise SystemExit(f"ERROR: --git-ref '{v}' has non-integer PR number")
            refs.append({"repo": repo.strip(), "pr_number": pr_num})
        else:
            raise SystemExit(
                f"ERROR: --git-ref '{v}' must be 'repo@sha' or 'repo#pr_number'"
            )
    return refs


def _parse_prompt_version(s: str | None) -> PromptVersion | None:
    if not s:
        return None
    if ":" not in s:
        raise SystemExit(
            f"ERROR: --prompt-version '{s}' must be 'prompt_id:version'"
        )
    pid, ver = s.split(":", 1)
    return {"prompt_id": pid.strip(), "version": ver.strip()}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="changelog-log",
        description="Emit a structured entry to the system-wide changelog.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Incident (all 4 timestamps + root-cause + resolution required)\n"
            '  changelog-log --event-type incident --severity high \\\n'
            '    --subsystem infrastructure --root-cause infrastructure_failure \\\n'
            '    --started-at 2026-05-01T13:00:00Z --detected-at 2026-05-01T13:01:00Z \\\n'
            '    --resolved-at 2026-05-01T14:30:00Z --verified-at 2026-05-01T14:35:00Z \\\n'
            '    --summary "SF DeployDriftCheck timeout" \\\n'
            '    --resolution-notes "yfinance VWAP=None silently coerced to NaN..."\n'
            "\n"
            "  # Manual operator action (event_type=change)\n"
            '  changelog-log --event-type change --subsystem executor \\\n'
            '    --resolution-type manual_intervention \\\n'
            '    --detected-at 2026-05-01T19:00:00Z --resolved-at 2026-05-01T19:05:00Z \\\n'
            '    --verified-at 2026-05-01T19:06:00Z \\\n'
            '    --summary "Killed hung daemon pid 12345 on ae-trading"\n'
            "\n"
            "Vocab source: $ALPHA_ENGINE_CONFIG/changelog/vocab.yaml (alpha-engine-config repo)."
        ),
    )
    p.add_argument("--event-type", required=True)
    p.add_argument("--summary", required=True, help="One-line description (≤ 240 chars)")
    p.add_argument("--severity")
    p.add_argument("--subsystem")
    p.add_argument("--root-cause", dest="root_cause_category")
    p.add_argument("--resolution-type", dest="resolution_type")
    p.add_argument("--started-at", dest="started_at")
    p.add_argument("--detected-at", dest="detected_at")
    p.add_argument("--resolved-at", dest="resolved_at")
    p.add_argument("--verified-at", dest="verified_at")
    p.add_argument("--description", help="Free-form long body")
    p.add_argument(
        "--resolution-notes",
        dest="resolution_notes",
        help="Root-cause + resolution narrative (≥ 200 chars on incidents)",
    )
    p.add_argument(
        "--git-ref",
        dest="git_refs",
        action="append",
        default=[],
        help="Repeatable. Format: 'repo@sha' or 'repo#pr_number'",
    )
    p.add_argument(
        "--prompt-version",
        dest="prompt_version",
        help="Format: 'prompt_id:version' (e.g., 'agents/researcher:1.2.0')",
    )
    p.add_argument("--run-id", dest="run_id")
    p.add_argument("--eval-run-ref", dest="eval_run_ref")
    p.add_argument("--actor", default=os.environ.get("USER", "unknown"))
    p.add_argument(
        "--ts-utc",
        dest="ts_utc",
        help="Override entry timestamp (default: now). ISO-8601 UTC.",
    )
    p.add_argument(
        "--bucket",
        default=os.environ.get("CHANGELOG_BUCKET", DEFAULT_BUCKET),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate + print intended write but do not call S3.",
    )
    p.add_argument(
        "--no-legacy-mirror",
        action="store_true",
        help=(
            "Skip writing to the legacy event-typed prefix. "
            "Default behavior writes to BOTH new and legacy prefixes during back-compat window."
        ),
    )
    return p


def build_entry(args: argparse.Namespace) -> Entry:
    return Entry(
        event_type=args.event_type,
        summary=args.summary,
        actor=args.actor,
        ts_utc=args.ts_utc or _now_iso(),
        severity=args.severity,
        subsystem=args.subsystem,
        root_cause_category=args.root_cause_category,
        resolution_type=args.resolution_type,
        started_at=args.started_at,
        detected_at=args.detected_at,
        resolved_at=args.resolved_at,
        verified_at=args.verified_at,
        description=args.description,
        resolution_notes=args.resolution_notes,
        git_refs=_parse_git_refs(args.git_refs),
        prompt_version=_parse_prompt_version(args.prompt_version),
        run_id=args.run_id,
        eval_run_ref=args.eval_run_ref,
        machine=socket.gethostname() or platform.node() or "",
    )


def _put_to_s3(bucket: str, key: str, body: bytes) -> None:
    cmd = [
        "aws",
        "s3",
        "cp",
        "-",
        f"s3://{bucket}/{key}",
        "--content-type",
        "application/json",
    ]
    proc = subprocess.run(cmd, input=body, capture_output=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", errors="replace"))
        raise SystemExit(f"ERROR: aws s3 cp failed (exit {proc.returncode})")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    vocab = Vocab.load(_vocab_path())
    entry = build_entry(args)

    errs = validate(entry, vocab)
    if errs:
        sys.stderr.write("Validation failed — entry NOT written:\n")
        for e in errs:
            sys.stderr.write(f"  - {e}\n")
        sys.stderr.write(
            "\nFix the invocation and rerun. See `changelog-log --help` for examples.\n"
        )
        return 2

    payload = json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True)
    body = payload.encode("utf-8")
    new_key, legacy_key = entry.s3_keys()

    print(f"→ event_id: {entry._event_id()}")
    print(f"→ NEW path: s3://{args.bucket}/{new_key}")
    if legacy_key and not args.no_legacy_mirror:
        print(f"→ legacy:   s3://{args.bucket}/{legacy_key}  (back-compat mirror)")
    print(f"→ summary:  {entry.summary}")

    if args.dry_run:
        print("\n--dry-run; not calling S3. Payload:")
        print(payload)
        return 0

    _put_to_s3(args.bucket, new_key, body)
    if legacy_key and not args.no_legacy_mirror:
        _put_to_s3(args.bucket, legacy_key, body)

    print("Posted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
