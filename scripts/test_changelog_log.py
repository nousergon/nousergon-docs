#!/usr/bin/env python3
"""Smoke tests for changelog_log.py — covers vocab loading, validation
rules, S3 key derivation, and the legacy-positional shim error path.

Run from repo root:

  python3 scripts/test_changelog_log.py

No external deps beyond PyYAML (already required by the CLI itself).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import changelog_log as cl  # noqa: E402

VOCAB_YAML = """
version: "1.0.0"
event_type:
  - incident
  - change
  - recovery
  - investigation
  - regression_test_added
  - prompt_version_change
  - infrastructure_change
  - eval_score_regression
severity: [critical, high, medium, low, informational]
subsystem:
  - retrieval
  - agents
  - predictor
  - executor
  - backtester
  - dashboard
  - research
  - infrastructure
  - prompts
  - eval
  - data_pipeline
  - telemetry
root_cause_category:
  - data_quality
  - model_behavior
  - infrastructure_failure
  - code_bug
  - third_party_api
  - prompt_regression
  - schema_evolution
  - configuration
resolution_type:
  - code_fix
  - prompt_revision
  - config_change
  - dependency_update
  - architectural_refactor
  - monitoring_added
  - manual_intervention
  - no_action_required
"""


def _vocab() -> cl.Vocab:
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(VOCAB_YAML)
        path = Path(f.name)
    return cl.Vocab.load(path)


def _base_entry(**overrides) -> cl.Entry:
    kwargs = dict(
        event_type="change",
        summary="test",
        actor="tester",
        ts_utc="2026-05-01T19:30:00Z",
        machine="testhost",
    )
    kwargs.update(overrides)
    return cl.Entry(**kwargs)


def test_vocab_load() -> None:
    v = _vocab()
    assert v.version == "1.0.0"
    assert "incident" in v.event_type
    assert "infrastructure" in v.subsystem


def test_validate_invalid_event_type() -> None:
    v = _vocab()
    e = _base_entry(event_type="bogus")
    errs = cl.validate(e, v)
    assert any("event_type" in x for x in errs), errs


def test_validate_incident_requires_all_fields() -> None:
    v = _vocab()
    e = _base_entry(event_type="incident")
    errs = cl.validate(e, v)
    expected_required = {
        "severity",
        "subsystem",
        "root_cause_category",
        "started_at",
        "detected_at",
        "resolved_at",
        "verified_at",
        "resolution_notes",
    }
    missing_mentions = {field for field in expected_required if any(field in x for x in errs)}
    assert missing_mentions == expected_required, missing_mentions


def test_validate_incident_resolution_notes_too_short() -> None:
    v = _vocab()
    e = _base_entry(
        event_type="incident",
        severity="high",
        subsystem="executor",
        root_cause_category="code_bug",
        started_at="2026-05-01T13:00:00Z",
        detected_at="2026-05-01T13:01:00Z",
        resolved_at="2026-05-01T14:00:00Z",
        verified_at="2026-05-01T14:05:00Z",
        resolution_notes="too short",
    )
    errs = cl.validate(e, v)
    assert any("too short" in x for x in errs), errs


def test_validate_incident_passes() -> None:
    v = _vocab()
    e = _base_entry(
        event_type="incident",
        severity="high",
        subsystem="executor",
        root_cause_category="code_bug",
        started_at="2026-05-01T13:00:00Z",
        detected_at="2026-05-01T13:01:00Z",
        resolved_at="2026-05-01T14:00:00Z",
        verified_at="2026-05-01T14:05:00Z",
        resolution_notes="x" * 250,
    )
    errs = cl.validate(e, v)
    assert errs == [], errs


def test_validate_change_requires_three_timestamps() -> None:
    v = _vocab()
    e = _base_entry(event_type="change")
    errs = cl.validate(e, v)
    for ts in ("detected_at", "resolved_at", "verified_at"):
        assert any(ts in x for x in errs), (ts, errs)
    assert not any("started_at" in x for x in errs), errs


def test_validate_iso8601_timestamp() -> None:
    v = _vocab()
    e = _base_entry(
        event_type="change",
        subsystem="executor",
        resolution_type="code_fix",
        detected_at="not-a-date",
        resolved_at="2026-05-01T14:00:00Z",
        verified_at="2026-05-01T14:05:00Z",
    )
    errs = cl.validate(e, v)
    assert any("ISO-8601" in x and "detected_at" in x for x in errs), errs


def test_validate_summary_length() -> None:
    v = _vocab()
    e = _base_entry(event_type="recovery", subsystem="executor", summary="x" * 300,
                    resolved_at="2026-05-01T14:00:00Z", verified_at="2026-05-01T14:05:00Z")
    errs = cl.validate(e, v)
    assert any("summary too long" in x for x in errs), errs


def test_s3_keys_dual_write() -> None:
    e = _base_entry(event_type="incident", summary="test summary")
    new_key, legacy_key = e.s3_keys()
    assert new_key.startswith("changelog/entries/2026-05-01/")
    assert new_key.endswith(".json")
    assert legacy_key.startswith("changelog/incidents/2026/05/")
    assert legacy_key.endswith(".json")


def test_s3_keys_change_maps_to_legacy_manual() -> None:
    e = _base_entry(event_type="change", summary="test")
    _, legacy_key = e.s3_keys()
    assert legacy_key.startswith("changelog/manual/"), legacy_key


def test_event_id_deterministic() -> None:
    e1 = _base_entry(summary="same")
    e2 = _base_entry(summary="same")
    assert e1._event_id() == e2._event_id()


def test_event_id_changes_on_summary_diff() -> None:
    e1 = _base_entry(summary="one")
    e2 = _base_entry(summary="two")
    assert e1._event_id() != e2._event_id()


def test_parse_git_refs_sha() -> None:
    refs = cl._parse_git_refs(["alpha-engine@abc1234", "alpha-engine-data@def5678"])
    assert refs == [
        {"repo": "alpha-engine", "sha": "abc1234"},
        {"repo": "alpha-engine-data", "sha": "def5678"},
    ]


def test_parse_git_refs_pr() -> None:
    refs = cl._parse_git_refs(["alpha-engine#125", "alpha-engine-docs#10"])
    assert refs == [
        {"repo": "alpha-engine", "pr_number": 125},
        {"repo": "alpha-engine-docs", "pr_number": 10},
    ]


def test_parse_prompt_version() -> None:
    pv = cl._parse_prompt_version("agents/researcher:1.2.0")
    assert pv == {"prompt_id": "agents/researcher", "version": "1.2.0"}
    assert cl._parse_prompt_version(None) is None
    assert cl._parse_prompt_version("") is None


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    """End-to-end: dry-run path validates + prints but doesn't call aws.

    `--ts-utc` is passed explicitly and is what the assertion below reads.
    It used to be omitted while the assertion expected the S3 key to carry
    `--detected-at`'s date — and `s3_keys()` has always built the key from
    `ts_utc`, which defaults to `_now_iso()`. So this test was green on
    exactly one day: 2026-05-01, when the wall clock happened to equal the
    `--detected-at` in the fixture. It shipped in the same commit as the code
    (#10) and has failed every day since.

    The two fields are not interchangeable and the fix is not to key the path
    off `detected_at`: `ts_utc` is when the entry was RECORDED, which is what
    an append-only log partitions by, and `detected_at` is when the event
    happened. Backfilling a past event is what `--ts-utc` is for.

    Nothing reported this for 112 days because this repo runs no test job at
    all — the CI job added alongside this change is the other half of the fix.
    """
    vocab_file = tmp_path / "vocab.yaml"
    vocab_file.write_text(VOCAB_YAML)
    env = dict(os.environ)
    env["ALPHA_ENGINE_CHANGELOG_VOCAB"] = str(vocab_file)

    proc = subprocess.run(
        [
            sys.executable,
            str(HERE / "changelog_log.py"),
            "--event-type", "investigation",
            "--subsystem", "telemetry",
            "--detected-at", "2026-05-01T19:00:00Z",
            "--ts-utc", "2026-05-01T19:01:00Z",
            "--summary", "Investigated changelog dual-write",
            "--description", "Smoke test for the new schema-disciplined CLI.",
            "--actor", "smoke-test",
            "--dry-run",
        ],
        env=env,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr.decode()
    out = proc.stdout.decode()
    assert "NEW path: s3://alpha-engine-research/changelog/entries/2026-05-01/" in out
    assert "--dry-run; not calling S3" in out
    payload_line = [line for line in out.splitlines() if line.startswith("{")][0]
    payload = json.loads(payload_line)
    assert payload["event_type"] == "investigation"
    assert payload["schema_version"] == "1.0.0"
    assert payload["subsystem"] == "telemetry"


def test_legacy_positional_shim_errors() -> None:
    """Bash shim must reject `changelog-log manual "summary"` style calls."""
    proc = subprocess.run(
        [str(HERE / "changelog-log.sh"), "manual", "test"],
        capture_output=True,
    )
    assert proc.returncode == 2, proc.stdout.decode() + proc.stderr.decode()
    err = proc.stderr.decode()
    assert "legacy positional interface was removed" in err


def main() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            if "tmp_path" in t.__code__.co_varnames:
                with tempfile.TemporaryDirectory() as td:
                    t(Path(td))
            else:
                t()
            print(f"ok   {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"ERR  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
