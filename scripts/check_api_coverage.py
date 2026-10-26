#!/usr/bin/env python3
"""Check that an API sub-site documents every top-level package of its repo.

alpha-engine-config-I12650. Each sub-site under ``api-src/<repo>/`` lists the
modules it renders by hand, as ``::: <identifier>`` lines in ``docs/index.md``.
A package added to a public repo therefore never reaches the reference unless
somebody remembers to add it, and nothing goes red when they do not
(``crucible-dashboard``'s ``results`` was missing for exactly this reason,
fixed by nousergon-docs#68).

This script closes that gap. For one sub-site it:

1. reads the package root from that sub-site's own ``mkdocs.yml``
   (``plugins.mkdocstrings.handlers.python.paths``) — the same declaration
   mkdocstrings resolves identifiers against, so the two can never disagree;
2. lists the top-level packages there (directories carrying ``__init__.py``);
3. subtracts every package named by a ``::: <identifier>`` line in
   ``docs/index.md`` (first dotted component) and every package declared in
   ``api-src/<repo>/exclude.txt`` (one ``<package>  # <reason>`` per line —
   a line with no reason is an error, because an undeclared exclusion is the
   silent gap this check exists to remove);
4. reports each remaining package as a GitHub ``::warning::`` annotation.

It exits 0 in observe mode (the default) and 1 under ``--enforce`` when any
package is uncovered. A malformed ``exclude.txt`` or an unreadable
``mkdocs.yml`` exits 2 in both modes: a check that cannot read its own
declarations has not checked anything.

Usage::

    python3 scripts/check_api_coverage.py api-src/<repo> [--enforce]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PATHS_RE = re.compile(r"^\s*paths:\s*\[([^\]]*)\]", re.MULTILINE)
DIRECTIVE_RE = re.compile(r"^:::\s*([A-Za-z_][\w.]*)", re.MULTILINE)


class DeclarationError(Exception):
    """A sub-site's own declarations cannot be read."""


def package_roots(src_dir: Path) -> list[Path]:
    text = (src_dir / "mkdocs.yml").read_text(encoding="utf-8")
    match = PATHS_RE.search(text)
    if not match:
        raise DeclarationError(f"{src_dir}/mkdocs.yml declares no mkdocstrings `paths: [...]`")
    entries = [e.strip().strip("'\"") for e in match.group(1).split(",") if e.strip()]
    if not entries:
        raise DeclarationError(f"{src_dir}/mkdocs.yml has an empty `paths: []`")
    return [src_dir / e for e in entries]


def top_level_packages(roots: list[Path]) -> set[str]:
    found: set[str] = set()
    for root in roots:
        if not root.is_dir():
            raise DeclarationError(f"package root {root} does not exist (was the repo checked out?)")
        for child in root.iterdir():
            if child.is_dir() and not child.name.startswith(".") and (child / "__init__.py").is_file():
                found.add(child.name)
    return found


def documented_packages(src_dir: Path) -> set[str]:
    text = (src_dir / "docs" / "index.md").read_text(encoding="utf-8")
    return {m.group(1).split(".")[0] for m in DIRECTIVE_RE.finditer(text)}


def excluded_packages(src_dir: Path) -> dict[str, str]:
    path = src_dir / "exclude.txt"
    if not path.exists():
        return {}
    excluded: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, reason = line.partition("#")
        name, reason = name.strip(), reason.strip()
        if not sep or not reason:
            raise DeclarationError(f"{path}:{lineno}: `{name}` has no reason (`<package>  # <reason>`)")
        if not re.fullmatch(r"[A-Za-z_]\w*", name):
            raise DeclarationError(f"{path}:{lineno}: `{name}` is not a package name")
        excluded[name] = reason
    return excluded


def uncovered(src_dir: Path) -> list[str]:
    packages = top_level_packages(package_roots(src_dir))
    return sorted(packages - documented_packages(src_dir) - set(excluded_packages(src_dir)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("src_dir", type=Path, help="api-src/<repo> directory, with its checkout present")
    parser.add_argument("--enforce", action="store_true", help="exit 1 when a package is uncovered")
    args = parser.parse_args(argv)
    repo = args.src_dir.name
    try:
        missing = uncovered(args.src_dir)
    except (DeclarationError, OSError) as exc:
        print(f"::error::API coverage for {repo}: {exc}")
        return 2
    for pkg in missing:
        print(
            f"::warning::API coverage: {repo} has top-level package `{pkg}` that "
            f"api-src/{repo}/docs/index.md does not render. Add a `::: {pkg}` block, "
            f"or declare it in api-src/{repo}/exclude.txt with a reason."
        )
    if not missing:
        print(f"API coverage: {repo} OK")
    return 1 if (missing and args.enforce) else 0


if __name__ == "__main__":
    sys.exit(main())
