#!/usr/bin/env python3
"""Smoke tests for emit_retro_candidates.py.

Covers summary normalization (collapse repeats, keep distinct alarms),
incident grouping (count / worst-severity / non-incident + medium exclusion),
and the payload shape.

  python3 -m pytest scripts/test_emit_retro_candidates.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import emit_retro_candidates as erc  # noqa: E402


def _entry(**fields):
    base = {
        "schema_version": "1.0.0",
        "event_id": "e",
        "ts_utc": "2026-06-01T00:00:00Z",
        "event_type": "incident",
        "severity": "high",
        "subsystem": "infrastructure",
        "root_cause_category": "infrastructure_failure",
        "resolution_notes": None,
        "summary": "Something failed",
    }
    base.update(fields)
    return base


# ---- normalization ---------------------------------------------------------

def test_normalize_collapses_volatile_noise():
    a = erc._normalize_summary('ALARM: "my-alarm" in US East (N. Virginia) 12345')
    b = erc._normalize_summary('ALARM: "my-alarm" in US East (N. Virginia) 99999')
    assert a == b  # digits + region stripped -> same key


def test_normalize_keeps_distinct_alarm_names():
    a = erc._normalize_summary('ALARM: "alpha-engine-saturday-sf-failed"')
    b = erc._normalize_summary('ALARM: "alpha-engine-research-runner-timeout"')
    assert a != b  # the alarm name is identity and must be preserved


# ---- grouping --------------------------------------------------------------

def test_group_counts_repeats():
    entries = [
        _entry(ts_utc="2026-06-01T00:00:00Z", summary="Saturday Pipeline — FAILED"),
        _entry(ts_utc="2026-06-02T00:00:00Z", summary="Saturday Pipeline — FAILED"),
        _entry(ts_utc="2026-06-03T00:00:00Z", summary="Saturday Pipeline — FAILED"),
    ]
    groups = erc.group_incidents(entries)
    assert len(groups) == 1
    assert groups[0]["count"] == 3
    assert groups[0]["latest_ts"] == "2026-06-03T00:00:00Z"


def test_group_excludes_non_incidents():
    entries = [
        _entry(event_type="change", severity="informational", summary="Pipeline SUCCESS"),
        _entry(event_type="recovery", severity="informational", summary="OK cleared"),
        _entry(event_type="incident", severity="high", summary="real failure"),
    ]
    groups = erc.group_incidents(entries)
    assert len(groups) == 1
    assert groups[0]["summary"] == "real failure"


def test_group_excludes_medium_severity():
    entries = [
        _entry(severity="medium", summary="a warning"),
        _entry(severity="high", summary="a failure"),
        _entry(severity="critical", summary="a crit"),
    ]
    groups = erc.group_incidents(entries)
    summaries = {g["summary"] for g in groups}
    assert summaries == {"a failure", "a crit"}


def test_group_takes_worst_severity_and_writeup_flag():
    long_notes = "x" * erc.RETRO_RESOLUTION_NOTES_MIN_CHARS
    entries = [
        _entry(severity="high", summary="flapping thing", ts_utc="2026-06-01T00:00:00Z"),
        _entry(severity="critical", summary="flapping thing", ts_utc="2026-06-02T00:00:00Z",
               resolution_notes=long_notes),
    ]
    groups = erc.group_incidents(entries)
    assert len(groups) == 1
    assert groups[0]["severity"] == "critical"
    assert groups[0]["has_writeup"] is True


# ---- payload ---------------------------------------------------------------

def test_build_payload_shape():
    entries = [_entry(summary="boom")]
    p = erc.build_payload(entries, 90, date(2026, 3, 9), date(2026, 6, 7))
    assert p["window_days"] == 90
    assert p["incident_group_count"] == 1
    assert p["incident_total"] == 1
    assert p["ready_for_retro_count"] == 0  # no resolution_notes


def test_ready_for_retro_requires_resolution_notes():
    long_notes = "x" * erc.RETRO_RESOLUTION_NOTES_MIN_CHARS
    entries = [_entry(summary="written up", resolution_notes=long_notes)]
    p = erc.build_payload(entries, 90, date(2026, 3, 9), date(2026, 6, 7))
    assert p["ready_for_retro_count"] == 1
