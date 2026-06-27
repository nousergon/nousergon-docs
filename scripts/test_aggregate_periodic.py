#!/usr/bin/env python3
"""Smoke tests for aggregate_periodic.py.

Covers period boundary math (weekly + monthly), rollup counts,
incident metric computation (mean / p50 / p95), open-issue selection,
delta computation, and the markdown render.

  python3 scripts/test_aggregate_periodic.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import aggregate_periodic as ap  # noqa: E402


def _entry(**fields):
    base = {
        "schema_version": "1.0.0",
        "event_type": "change",
        "subsystem": "infrastructure",
        "ts_utc": "2026-04-30T12:00:00Z",
        "summary": "test",
        "actor": "tester",
        "resolution_type": "code_fix",
    }
    base.update(fields)
    return base


# --- period math ----------------------------------------------------

def test_weekly_period_from_monday():
    """Monday reference date → period is the prior Mon→Sun."""
    s, e, pid = ap.weekly_period(date(2026, 5, 4))  # Monday
    assert s == date(2026, 4, 27)
    assert e == date(2026, 5, 3)
    assert pid == "2026-W18"


def test_weekly_period_from_midweek():
    """Mid-week reference → current week's Monday is the start."""
    s, e, _ = ap.weekly_period(date(2026, 5, 6))  # Wednesday
    assert s == date(2026, 5, 4)
    assert e == date(2026, 5, 10)


def test_monthly_period_first_of_month():
    """First-of-month reference → period is the entire prior month."""
    s, e, pid = ap.monthly_period(date(2026, 5, 1))
    assert s == date(2026, 4, 1)
    assert e == date(2026, 4, 30)
    assert pid == "2026-04"


def test_monthly_period_handles_february():
    s, e, pid = ap.monthly_period(date(2026, 3, 1))
    assert s == date(2026, 2, 1)
    assert e == date(2026, 2, 28)
    assert pid == "2026-02"


def test_prior_weekly_period():
    s, e, pid = ap.prior_period("weekly", date(2026, 5, 4))
    assert s == date(2026, 4, 27)
    assert e == date(2026, 5, 3)
    assert pid == "2026-W18"


def test_prior_monthly_period_year_boundary():
    s, e, pid = ap.prior_period("monthly", date(2026, 1, 1))
    assert s == date(2025, 12, 1)
    assert e == date(2025, 12, 31)
    assert pid == "2025-12"


# --- corpus loading -------------------------------------------------

def test_load_entries_in_range(tmp_path: Path):
    import json
    for i, ts in enumerate([
        "2026-04-26T10:00:00Z",  # before
        "2026-04-27T10:00:00Z",  # inside
        "2026-05-03T10:00:00Z",  # inside
        "2026-05-04T10:00:00Z",  # after
    ]):
        d = tmp_path / ts[:10]
        d.mkdir(exist_ok=True)
        with (d / f"e{i}.json").open("w") as f:
            json.dump(_entry(ts_utc=ts, event_id=f"e{i}"), f)
    found = ap.load_entries_in_range(tmp_path, date(2026, 4, 27), date(2026, 5, 3))
    assert len(found) == 2
    assert {e["event_id"] for e in found} == {"e1", "e2"}


# --- rollup math ----------------------------------------------------

def test_rollup_counts():
    entries = [
        _entry(event_type="change", subsystem="executor"),
        _entry(event_type="change", subsystem="executor"),
        _entry(event_type="incident", subsystem="data_pipeline", severity="high",
               root_cause_category="infrastructure_failure"),
    ]
    r = ap.compute_rollup(
        entries,
        period_type="weekly",
        period_id="2026-W18",
        period_start=date(2026, 4, 27),
        period_end=date(2026, 5, 3),
    )
    assert r["entry_count"] == 3
    assert r["by_event_type"] == {"change": 2, "incident": 1}
    assert r["by_subsystem"] == {"executor": 2, "data_pipeline": 1}
    assert r["by_severity"] == {"high": 1}
    assert r["by_root_cause_category"] == {"infrastructure_failure": 1}
    assert r["incidents"]["count"] == 1
    assert r["incidents"]["with_root_cause_pct"] == 100.0


def test_mttd_mttr():
    """3 incidents with timed start/detect/resolve produce expected mean + p50."""
    entries = [
        _entry(event_type="incident",
               started_at="2026-04-30T10:00:00Z",
               detected_at="2026-04-30T10:01:00Z",   # MTTD = 60s
               resolved_at="2026-04-30T10:11:00Z"),  # MTTR = 600s
        _entry(event_type="incident",
               started_at="2026-04-30T11:00:00Z",
               detected_at="2026-04-30T11:02:00Z",   # MTTD = 120s
               resolved_at="2026-04-30T11:32:00Z"),  # MTTR = 1800s
        _entry(event_type="incident",
               started_at="2026-04-30T12:00:00Z",
               detected_at="2026-04-30T12:05:00Z",   # MTTD = 300s
               resolved_at="2026-04-30T13:05:00Z"),  # MTTR = 3600s
    ]
    r = ap.compute_rollup(
        entries, period_type="weekly", period_id="x",
        period_start=date(2026, 4, 27), period_end=date(2026, 5, 3),
    )
    inc = r["incidents"]
    assert inc["mttd_seconds_mean"] == 160.0  # (60+120+300)/3
    assert inc["mttd_seconds_p50"] == 120
    assert inc["mttr_seconds_mean"] == 2000.0  # (600+1800+3600)/3
    assert inc["mttr_seconds_p50"] == 1800


def test_open_issues_sorted_by_age():
    entries = [
        _entry(event_type="incident",
               event_id="old",
               started_at="2026-04-15T00:00:00Z",  # ~ 16d old at 5/1
               summary="The older one"),
        _entry(event_type="incident",
               event_id="newer",
               started_at="2026-04-25T00:00:00Z",
               summary="More recent"),
        _entry(event_type="incident",
               event_id="resolved",
               started_at="2026-04-20T00:00:00Z",
               resolved_at="2026-04-21T00:00:00Z",  # not open
               summary="Resolved"),
    ]
    r = ap.compute_rollup(
        entries, period_type="weekly", period_id="x",
        period_start=date(2026, 4, 1), period_end=date(2026, 5, 31),
    )
    assert [oi["event_id"] for oi in r["open_issues"]] == ["old", "newer"]


def test_delta_computation():
    current = ap.compute_rollup(
        [_entry(event_type="change"), _entry(event_type="incident")],
        period_type="weekly", period_id="now",
        period_start=date(2026, 5, 4), period_end=date(2026, 5, 10),
    )
    prior = ap.compute_rollup(
        [_entry(event_type="change")],
        period_type="weekly", period_id="prev",
        period_start=date(2026, 4, 27), period_end=date(2026, 5, 3),
    )
    out = ap.add_deltas(current, prior)
    d = out["deltas_vs_prior"]
    assert d["entry_count_delta"] == 1
    assert d["incident_count_delta"] == 1
    assert d["prior_period_id"] == "prev"


def test_delta_handles_no_prior():
    current = ap.compute_rollup(
        [_entry()], period_type="weekly", period_id="now",
        period_start=date(2026, 5, 4), period_end=date(2026, 5, 10),
    )
    out = ap.add_deltas(current, None)
    assert out["deltas_vs_prior"] is None


# --- render ---------------------------------------------------------

def test_markdown_render_smoke():
    entries = [
        _entry(event_type="change", subsystem="data_pipeline"),
        _entry(event_type="incident", subsystem="executor", severity="high",
               root_cause_category="code_bug",
               started_at="2026-04-30T10:00:00Z",
               detected_at="2026-04-30T10:01:00Z",
               resolved_at="2026-04-30T10:11:00Z"),
    ]
    r = ap.compute_rollup(
        entries, period_type="weekly", period_id="2026-W18",
        period_start=date(2026, 4, 27), period_end=date(2026, 5, 3),
    )
    md = ap.render_markdown(r)
    assert "# Changelog rollup — weekly 2026-W18" in md
    assert "Entries: 2" in md
    assert "By event type" in md
    assert "MTTR" in md


def test_fmt_secs():
    assert ap._fmt_secs(45) == "45s"
    assert ap._fmt_secs(125) == "2.1m"
    assert ap._fmt_secs(3661) == "1.0h"
    assert ap._fmt_secs(90061) == "1.0d"
    assert ap._fmt_secs(None) == "n/a"


# --- retro candidate mining -----------------------------------------

_QUALIFYING_NOTES = "x" * 250  # > 200 char threshold


def _retro_qualifying_entry(**overrides):
    base = _entry(
        event_type="incident",
        severity="high",
        subsystem="executor",
        root_cause_category="code_bug",
        resolution_notes=_QUALIFYING_NOTES,
        event_id="qualifies-1",
        ts_utc="2026-04-30T12:00:00Z",
        summary="Real bug with real fix",
    )
    base.update(overrides)
    return base


def test_retro_filter_passes_qualifying_entry():
    cands = ap.extract_retro_candidates([_retro_qualifying_entry()])
    assert len(cands) == 1
    assert cands[0]["event_id"] == "qualifies-1"


def test_retro_filter_excludes_non_incident():
    cands = ap.extract_retro_candidates(
        [_retro_qualifying_entry(event_type="change")]
    )
    assert cands == []


def test_retro_filter_excludes_low_severity():
    """Medium/low/info/null severity all filtered out."""
    for sev in ("medium", "low", "informational", None):
        cands = ap.extract_retro_candidates(
            [_retro_qualifying_entry(severity=sev)]
        )
        assert cands == [], f"severity={sev} should not qualify"


def test_retro_filter_excludes_missing_root_cause():
    """Auto-emitted entries without root_cause_category filtered out."""
    for rcc in (None, "", "  "):
        cands = ap.extract_retro_candidates(
            [_retro_qualifying_entry(root_cause_category=rcc)]
        )
        assert cands == [], f"root_cause_category={rcc!r} should not qualify"


def test_retro_filter_excludes_short_resolution_notes():
    """Resolution notes < 200 chars filtered (excludes auto-emit + thin writeups)."""
    for notes in (None, "", "x" * 199):
        cands = ap.extract_retro_candidates(
            [_retro_qualifying_entry(resolution_notes=notes)]
        )
        assert cands == [], f"len={len(notes or '')} should not qualify"


def test_retro_filter_passes_critical_severity():
    cands = ap.extract_retro_candidates(
        [_retro_qualifying_entry(severity="critical", event_id="crit-1")]
    )
    assert len(cands) == 1


def test_retro_filter_sorts_newest_first():
    entries = [
        _retro_qualifying_entry(event_id="a", ts_utc="2026-04-28T00:00:00Z"),
        _retro_qualifying_entry(event_id="b", ts_utc="2026-05-01T00:00:00Z"),
        _retro_qualifying_entry(event_id="c", ts_utc="2026-04-30T00:00:00Z"),
    ]
    cands = ap.extract_retro_candidates(entries)
    assert [c["event_id"] for c in cands] == ["b", "c", "a"]


def test_retro_oneliner_includes_severity_emoji_and_subsystem():
    line = ap.render_retro_candidate_oneliner(
        _retro_qualifying_entry(severity="critical", subsystem="predictor")
    )
    assert ap.SEVERITY_EMOJI["critical"] in line
    assert "`predictor`" in line
    assert "`code_bug`" in line


def test_retro_oneliner_renders_git_refs():
    line = ap.render_retro_candidate_oneliner(
        _retro_qualifying_entry(git_refs=["alpha-engine#145", "abc1234"])
    )
    assert "`alpha-engine#145`" in line
    assert "`abc1234`" in line


def test_retro_stub_includes_facts_and_narrative_todo():
    stub = ap.render_retro_candidate_stub(
        _retro_qualifying_entry(severity="critical"), "2026-W18"
    )
    # Facts surface
    assert "## Facts (from changelog corpus)" in stub
    assert "**Subsystem:** `executor`" in stub
    assert "**Severity:** `critical`" in stub
    assert "**Root cause category:** `code_bug`" in stub
    # Narrative scaffold surface (for operator)
    assert "## Narrative — TODO" in stub
    assert "### What happened" in stub
    assert "### Why it was interesting" in stub
    assert "### Generalizable lesson" in stub
    # Resolution notes copied verbatim
    assert _QUALIFYING_NOTES in stub


def test_rollup_includes_retro_candidates_field():
    entries = [
        _retro_qualifying_entry(event_id="x"),
        _entry(event_type="change"),  # not a candidate
    ]
    r = ap.compute_rollup(
        entries, period_type="weekly", period_id="2026-W18",
        period_start=date(2026, 4, 27), period_end=date(2026, 5, 3),
    )
    assert "retro_candidates" in r
    assert len(r["retro_candidates"]) == 1
    cand = r["retro_candidates"][0]
    assert cand["event_id"] == "x"
    assert cand["severity"] == "high"
    assert cand["subsystem"] == "executor"
    assert cand["root_cause_category"] == "code_bug"


def test_markdown_render_includes_retro_section_when_present():
    entries = [_retro_qualifying_entry(event_id="r1")]
    r = ap.compute_rollup(
        entries, period_type="weekly", period_id="2026-W18",
        period_start=date(2026, 4, 27), period_end=date(2026, 5, 3),
    )
    md = ap.render_markdown(r)
    assert "## Retro candidates" in md
    assert "event_id=r1" in md


def test_markdown_render_omits_retro_section_when_empty():
    entries = [_entry(event_type="change")]
    r = ap.compute_rollup(
        entries, period_type="weekly", period_id="2026-W18",
        period_start=date(2026, 4, 27), period_end=date(2026, 5, 3),
    )
    md = ap.render_markdown(r)
    assert "## Retro candidates" not in md


def test_write_retro_stubs_creates_files(tmp_path: Path):
    cands = [
        _retro_qualifying_entry(event_id="evt-a"),
        _retro_qualifying_entry(event_id="evt-b", severity="critical"),
    ]
    written = ap.write_retro_candidate_stubs(cands, "2026-W18", tmp_path)
    assert len(written) == 2
    assert (tmp_path / "2026-W18" / "evt-a.md").exists()
    assert (tmp_path / "2026-W18" / "evt-b.md").exists()


def test_write_retro_stubs_skips_existing(tmp_path: Path):
    """Pre-existing stubs preserved — operator may have started editing."""
    period_dir = tmp_path / "2026-W18"
    period_dir.mkdir()
    existing = period_dir / "evt-a.md"
    existing.write_text("# operator's draft, do not overwrite")
    written = ap.write_retro_candidate_stubs(
        [_retro_qualifying_entry(event_id="evt-a")], "2026-W18", tmp_path
    )
    assert written == []
    assert existing.read_text() == "# operator's draft, do not overwrite"


# --- stale auto-emitted default triage (config#866) -----------------

def _recent_ts_utc(days_ago: float) -> str:
    from datetime import timedelta, timezone, datetime as _dt
    return (_dt.now(timezone.utc) - timedelta(days=days_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _stale_default_entry(**fields):
    """An auto-emitted incident still carrying the default root_cause."""
    base = dict(
        event_type="incident",
        auto_emitted=True,
        root_cause_category="infrastructure_failure",
        started_at=None,  # mirrors emit null started_at
    )
    base.update(fields)
    return _entry(**base)


def test_stale_default_flagged_past_grace():
    entries = [
        _stale_default_entry(
            event_id="stale", ts_utc=_recent_ts_utc(10), summary="old default"
        ),
    ]
    r = ap.compute_rollup(
        entries, period_type="weekly", period_id="x",
        period_start=date(2026, 1, 1), period_end=date(2030, 1, 1),
    )
    ids = [s["event_id"] for s in r["stale_default_triage"]]
    assert ids == ["stale"]
    assert r["stale_default_triage"][0]["age_days"] > ap.STALE_DEFAULT_GRACE_DAYS


def test_stale_default_within_grace_excluded():
    entries = [
        _stale_default_entry(
            event_id="fresh", ts_utc=_recent_ts_utc(2), summary="recent default"
        ),
    ]
    r = ap.compute_rollup(
        entries, period_type="weekly", period_id="x",
        period_start=date(2026, 1, 1), period_end=date(2030, 1, 1),
    )
    assert r["stale_default_triage"] == []


def test_stale_default_requires_auto_emitted():
    # Same age + root_cause but NOT auto-emitted (operator-authored) → excluded.
    entries = [
        _stale_default_entry(
            event_id="manual", ts_utc=_recent_ts_utc(20), auto_emitted=False
        ),
    ]
    r = ap.compute_rollup(
        entries, period_type="weekly", period_id="x",
        period_start=date(2026, 1, 1), period_end=date(2030, 1, 1),
    )
    assert r["stale_default_triage"] == []


def test_stale_default_excluded_when_root_cause_refined():
    # Operator refined the default away → no longer flagged even if old.
    entries = [
        _stale_default_entry(
            event_id="refined",
            ts_utc=_recent_ts_utc(30),
            root_cause_category="code_bug",
        ),
    ]
    r = ap.compute_rollup(
        entries, period_type="weekly", period_id="x",
        period_start=date(2026, 1, 1), period_end=date(2030, 1, 1),
    )
    assert r["stale_default_triage"] == []


def test_stale_default_sorted_oldest_first():
    entries = [
        _stale_default_entry(event_id="b", ts_utc=_recent_ts_utc(9)),
        _stale_default_entry(event_id="a", ts_utc=_recent_ts_utc(25)),
    ]
    r = ap.compute_rollup(
        entries, period_type="weekly", period_id="x",
        period_start=date(2026, 1, 1), period_end=date(2030, 1, 1),
    )
    assert [s["event_id"] for s in r["stale_default_triage"]] == ["a", "b"]


def test_markdown_includes_triage_section_when_present():
    entries = [
        _stale_default_entry(event_id="t1", ts_utc=_recent_ts_utc(12)),
    ]
    r = ap.compute_rollup(
        entries, period_type="weekly", period_id="x",
        period_start=date(2026, 1, 1), period_end=date(2030, 1, 1),
    )
    md = ap.render_markdown(r)
    assert "Needs operator triage" in md
    assert "event_id=t1" in md


def test_markdown_omits_triage_section_when_empty():
    entries = [_entry(event_type="change")]
    r = ap.compute_rollup(
        entries, period_type="weekly", period_id="x",
        period_start=date(2026, 1, 1), period_end=date(2030, 1, 1),
    )
    md = ap.render_markdown(r)
    assert "Needs operator triage" not in md


def main() -> int:
    import tempfile
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
