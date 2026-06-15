#!/usr/bin/env python3
"""Smoke tests for backfill_changelog.py — covers the four legacy
event-type transforms (deploy, incident, manual, recovery) and the
deterministic event_id derivation.

Run from repo root:

  python3 scripts/test_backfill_changelog.py

No external deps. Does not call AWS (transform layer is pure).
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import backfill_changelog as bf  # noqa: E402


def _legacy_deploy(**overrides):
    base = {
        "ts_utc": "2026-05-01T16:09:17Z",
        "event_type": "deploy",
        "repo": "nousergon/nousergon-data",
        "branch": "main",
        "sha": "acb7496ef38b99f834cb74ee50161ccdb6980c6f",
        "sha7": "acb7496",
        "pr_number": 122,
        "pr_title": "feat(orchestration): SNS→S3 changelog incident mirror Lambda",
        "pr_body": "## Summary\nAdds a small Lambda...",
        "pr_url": "https://github.com/nousergon/nousergon-data/pull/122",
        "author": "cipher813",
        "files_changed": 4,
        "deploy_workflow": "deploy-infrastructure.yml",
        "deploy_status": "success",
        "event_name": "push",
        "workflow_name": "Deploy Infrastructure",
        "workflow_run_id": "25221882385",
    }
    base.update(overrides)
    return base


def _legacy_incident(**overrides):
    base = {
        "ts_utc": "2026-05-01T20:23:29Z",
        "event_type": "incident",
        "source": "alpha-engine-alerts",
        "subject": "Alpha Engine EOD Pipeline — FAILED",
        "summary": "Alpha Engine EOD Pipeline — FAILED",
        "details": "EOD pipeline failed. Error: ...",
        "sns_message_id": "94949139-e0ad-5ef5-a0b2-f356eeac2a34",
        "topic_arn": "arn:aws:sns:us-east-1:711398986525:alpha-engine-alerts",
    }
    base.update(overrides)
    return base


def _legacy_manual(**overrides):
    base = {
        "ts_utc": "2026-05-01T17:00:00Z",
        "event_type": "manual",
        "source": "changelog-log",
        "actor": "brianmcmahon",
        "summary": "Patched live SF DeployDriftCheck timeout 60→300",
        "details": "Increased timeout after observing the cascade",
        "machine": "MacBook-Pro.local",
    }
    base.update(overrides)
    return base


def _legacy_recovery(**overrides):
    base = {
        "ts_utc": "2026-05-01T18:00:00Z",
        "event_type": "recovery",
        "source": "changelog-log",
        "actor": "brianmcmahon",
        "summary": "Morning planner ran clean — order book written to S3",
        "details": "",
        "machine": "MacBook-Pro.local",
    }
    base.update(overrides)
    return base


def test_deploy_success_to_change():
    out = bf.transform_deploy(_legacy_deploy())
    assert out["schema_version"] == "1.0.0"
    assert out["event_type"] == "change"
    assert out["severity"] is None
    assert out["subsystem"] == "data_pipeline"
    assert out["root_cause_category"] is None
    assert out["resolution_type"] == "code_fix"
    assert out["actor"] == "cipher813"
    assert out["machine"] == "github-actions"
    assert out["source"] == "ci-deploy"
    assert out["auto_emitted"] is True
    assert out["backfilled"] is True
    assert out["detected_at"] == "2026-05-01T16:09:17Z"
    assert out["resolved_at"] == "2026-05-01T16:09:17Z"
    assert out["verified_at"] == "2026-05-01T16:09:17Z"
    assert out["git_refs"] == [
        {
            "repo": "nousergon/nousergon-data",
            "sha": "acb7496ef38b99f834cb74ee50161ccdb6980c6f",
            "pr_number": 122,
        }
    ]
    assert out["deploy"]["status"] == "success"
    assert out["deploy"]["workflow"] == "deploy-infrastructure.yml"
    assert out["deploy"]["pr_url"] == "https://github.com/nousergon/nousergon-data/pull/122"


def test_deploy_failure_to_incident():
    out = bf.transform_deploy(_legacy_deploy(deploy_status="failure"))
    assert out["event_type"] == "incident"
    assert out["severity"] == "medium"
    assert out["root_cause_category"] == "infrastructure_failure"
    assert out["resolution_type"] is None
    assert out["resolved_at"] is None
    assert out["verified_at"] is None


def test_deploy_subsystem_inference():
    cases = [
        ("alpha-engine", "executor"),
        ("alpha-engine-research", "research"),
        ("alpha-engine-predictor", "predictor"),
        ("alpha-engine-backtester", "backtester"),
        ("alpha-engine-dashboard", "dashboard"),
        ("alpha-engine-config", "infrastructure"),
        ("alpha-engine-docs", "infrastructure"),
        ("alpha-engine-lib", "infrastructure"),
        ("flow-doctor", "telemetry"),
        ("mnemon", "infrastructure"),
        ("unknown-repo", "infrastructure"),
    ]
    for repo_short, expected in cases:
        out = bf.transform_deploy(_legacy_deploy(repo=f"nousergon/{repo_short}"))
        assert out["subsystem"] == expected, f"{repo_short} → {out['subsystem']}, expected {expected}"


def test_deploy_handles_missing_pr_number():
    out = bf.transform_deploy(_legacy_deploy(pr_number=None))
    assert out["git_refs"] == [
        {
            "repo": "nousergon/nousergon-data",
            "sha": "acb7496ef38b99f834cb74ee50161ccdb6980c6f",
        }
    ]


def test_incident_transform():
    out = bf.transform_incident(_legacy_incident())
    assert out["event_type"] == "incident"
    assert out["severity"] == "high"
    assert out["subsystem"] == "infrastructure"
    assert out["root_cause_category"] == "infrastructure_failure"
    assert out["actor"] == "alpha-engine-alerts"
    assert out["source"] == "sns-mirror"
    assert out["auto_emitted"] is True
    assert out["backfilled"] is True
    assert out["detected_at"] == "2026-05-01T20:23:29Z"
    assert out["resolved_at"] is None
    assert out["sns"]["message_id"] == "94949139-e0ad-5ef5-a0b2-f356eeac2a34"
    assert out["sns"]["subject"] == "Alpha Engine EOD Pipeline — FAILED"
    assert out["summary"] == "Alpha Engine EOD Pipeline — FAILED"


def test_incident_truncates_summary():
    legacy = _legacy_incident(summary="x" * 300)
    out = bf.transform_incident(legacy)
    assert len(out["summary"]) == 240


def test_manual_to_change():
    out = bf.transform_manual(_legacy_manual())
    assert out["event_type"] == "change"
    assert out["subsystem"] == "infrastructure"
    assert out["resolution_type"] == "manual_intervention"
    assert out["actor"] == "brianmcmahon"
    assert out["source"] == "changelog-log-legacy"
    assert out["auto_emitted"] is False
    assert out["backfilled"] is True
    assert out["detected_at"] == "2026-05-01T17:00:00Z"
    assert out["resolved_at"] == "2026-05-01T17:00:00Z"
    assert out["verified_at"] == "2026-05-01T17:00:00Z"
    assert "Patched live SF" in out["summary"]


def test_recovery_transform():
    out = bf.transform_recovery(_legacy_recovery())
    assert out["event_type"] == "recovery"
    assert out["subsystem"] == "infrastructure"
    assert out["resolved_at"] == "2026-05-01T18:00:00Z"
    assert out["verified_at"] == "2026-05-01T18:00:00Z"
    assert out["source"] == "changelog-log-legacy"
    assert out["auto_emitted"] is False
    assert out["backfilled"] is True
    assert out["resolution_type"] is None  # not required for recovery


def test_event_id_deterministic_across_transforms():
    """Two runs of the same transform produce the same event_id."""
    out1 = bf.transform_deploy(_legacy_deploy())
    out2 = bf.transform_deploy(_legacy_deploy())
    assert out1["event_id"] == out2["event_id"]


def test_deploy_event_id_uses_repo_short_segment():
    """Deploy event_id middle segment matches composite action's scheme.

    Regression: the first backfill run on 2026-05-01 used the actor for
    the middle segment, which diverged from the composite action's
    `{ts}_{repo_short}_{hash}` and produced duplicate entries (auto-emit
    at one path, backfill at another with the same hash). HEAD-probe
    idempotency depends on this matching exactly.
    """
    out = bf.transform_deploy(_legacy_deploy())
    # Format: {ts_id}_{repo_short}_{hash}
    parts = out["event_id"].split("_")
    assert parts[0] == "2026-05-01T16-09-17"
    assert parts[1] == "nousergon-data"
    assert len(parts[2]) == 7


def test_incident_event_id_uses_source_segment():
    """Incident event_id middle segment matches SNS-mirror Lambda's scheme."""
    out = bf.transform_incident(_legacy_incident())
    parts = out["event_id"].split("_")
    assert parts[0] == "2026-05-01T20-23-29"
    assert parts[1] == "alpha-engine-alerts"
    assert len(parts[2]) == 7


def test_structured_key_format():
    out = bf.transform_deploy(_legacy_deploy())
    key = bf._structured_key(out)
    assert key.startswith("changelog/entries/2026-05-01/")
    assert key.endswith(".json")


def test_all_outputs_have_schema_version_and_event_id():
    for transform, factory in [
        (bf.transform_deploy, _legacy_deploy),
        (bf.transform_incident, _legacy_incident),
        (bf.transform_manual, _legacy_manual),
        (bf.transform_recovery, _legacy_recovery),
    ]:
        out = transform(factory())
        assert out["schema_version"] == "1.0.0"
        assert out["event_id"]
        assert out["backfilled"] is True
        # All entries must populate ts_utc + summary + actor
        assert out["ts_utc"]
        assert out["summary"]
        assert out["actor"]


def test_deploy_with_empty_pr_title_falls_back():
    out = bf.transform_deploy(_legacy_deploy(pr_title=""))
    assert out["summary"] == "(no PR title)"


def main() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
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
