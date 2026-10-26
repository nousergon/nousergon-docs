"""Tests for check_api_coverage.py (alpha-engine-config-I12650)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_api_coverage as cac  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish-docs.yml"


def _subsite(tmp_path: Path, packages, directives, exclude=None, paths="[checkout]") -> Path:
    src = tmp_path / "api-src" / "demo"
    (src / "docs").mkdir(parents=True)
    (src / "mkdocs.yml").write_text(
        "plugins:\n  - mkdocstrings:\n      handlers:\n        python:\n"
        f"          paths: {paths}\n"
    )
    (src / "docs" / "index.md").write_text(
        "# Demo\n\n" + "".join(f"::: {d}\n    options:\n      show_submodules: true\n\n" for d in directives)
    )
    root = src / "checkout"
    root.mkdir()
    for pkg in packages:
        (root / pkg).mkdir(parents=True)
        (root / pkg / "__init__.py").write_text("")
    if exclude is not None:
        (src / "exclude.txt").write_text(exclude)
    return src


def test_package_added_on_purpose_is_flagged(tmp_path, capsys):
    # The Closes-when demonstration: a package added upstream with no doc entry.
    src = _subsite(tmp_path, ["alpha", "brand_new"], ["alpha"])
    assert cac.main([str(src)]) == 0  # observe mode never fails
    out = capsys.readouterr().out
    assert "::warning::" in out and "`brand_new`" in out
    assert cac.main([str(src), "--enforce"]) == 1


def test_fully_covered_passes(tmp_path, capsys):
    src = _subsite(tmp_path, ["alpha", "beta"], ["alpha", "beta.sub"])
    assert cac.main([str(src), "--enforce"]) == 0
    assert "OK" in capsys.readouterr().out


def test_declared_exclusion_with_reason_covers(tmp_path):
    src = _subsite(tmp_path, ["alpha", "tests"], ["alpha"], exclude="# header\n\ntests  # test suite\n")
    assert cac.uncovered(src) == []


def test_exclusion_without_reason_is_a_hard_error(tmp_path, capsys):
    src = _subsite(tmp_path, ["alpha", "tests"], ["alpha"], exclude="tests\n")
    assert cac.main([str(src)]) == 2
    assert "::error::" in capsys.readouterr().out


def test_non_packages_and_hidden_dirs_ignored(tmp_path):
    src = _subsite(tmp_path, ["alpha"], ["alpha"])
    (src / "checkout" / "docs").mkdir()  # no __init__.py
    (src / "checkout" / ".hidden").mkdir()
    (src / "checkout" / ".hidden" / "__init__.py").write_text("")
    (src / "checkout" / "module.py").write_text("")
    assert cac.uncovered(src) == []


def test_src_layout_root_comes_from_mkdocs_paths(tmp_path):
    src = _subsite(tmp_path, [], ["pkg"], paths="[checkout/src]")
    (src / "checkout" / "src" / "pkg").mkdir(parents=True)
    (src / "checkout" / "src" / "pkg" / "__init__.py").write_text("")
    (src / "checkout" / "src" / "other").mkdir()
    (src / "checkout" / "src" / "other" / "__init__.py").write_text("")
    assert cac.uncovered(src) == ["other"]


def test_missing_checkout_is_a_hard_error(tmp_path):
    src = _subsite(tmp_path, [], ["alpha"])
    (src / "checkout").rmdir()
    assert cac.main([str(src)]) == 2


def _workflow_repos() -> list[str]:
    match = re.search(r"for repo in ([^;]+); do", WORKFLOW.read_text())
    assert match, "publish-docs.yml no longer declares its sub-site roster as `for repo in ...; do`"
    return match.group(1).split()


def test_every_subsite_in_the_workflow_roster_has_its_declarations():
    repos = _workflow_repos()
    assert len(repos) == 8
    for repo in repos:
        src = REPO_ROOT / "api-src" / repo
        assert cac.package_roots(src), repo
        assert cac.documented_packages(src), f"{repo}: docs/index.md renders no ::: identifiers"
        cac.excluded_packages(src)  # raises on a reasonless line


def test_workflow_runs_the_check_and_gates_the_scheduled_run():
    text = WORKFLOW.read_text()
    assert 'scripts/check_api_coverage.py "${src_dir}" --enforce' in text
    assert "api-coverage:" in text and "github.event_name == 'schedule'" in text
