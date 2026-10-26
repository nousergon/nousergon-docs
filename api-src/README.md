# `api-src/` — per-repo mkdocstrings sub-sites

Each subdirectory here (`nousergon-lib/`, `crucible-executor/`, etc.) is a
**separate, self-contained `mkdocs.yml`** whose only job is to render one
public Crucible repo's docstrings via
[mkdocstrings](https://mkdocstrings.github.io/) (Python handler). The
`.github/workflows/publish-docs.yml` workflow builds each of these as its
own isolated `mkdocs build` and copies the output into
`site/api/<repo>/` alongside the top-level landing page
(`mkdocs.yml` / `docs/index.md` at the repo root).

## Why one `mkdocs.yml` per repo, not one combined config

mkdocstrings' Python handler resolves `::: identifier` directives against a
single global `paths:` search list for the whole site (see
`mkdocstrings_handlers.python`'s handler — `paths` is handler-instance-wide,
not overridable per-page or per-`:::`-block). The 7 flat-layout Crucible
repos share several top-level module names — `config`, `data`, `store`,
`infrastructure`, `docs`, `tests`, `scripts` all appear in 2+ repos. Loading
every repo's checkout onto one combined `paths:` list would make `:::
config` ambiguous: Python's import resolution (and Griffe's, which
mkdocstrings uses) just picks whichever repo's `config/` was inserted last
on the search path and silently renders the wrong repo's docstrings under
the right repo's page — no error, just wrong content. (Verified empirically
while building this: a two-package `sys.path` collision test resolved to
whichever path was inserted last, no warning.)

Splitting into one `mkdocs.yml` per repo, each with `paths:` scoped to only
that repo's own checkout, avoids the collision entirely by construction —
each build only ever has one repo's modules on its search path. The cost is
duplicated boilerplate (theme/plugin config) across 8 small YAML files
instead of one; that trade favors correctness over DRY-ness here since a
silent cross-repo docstring mix-up would be a much worse failure mode than
a few duplicated `theme:` blocks.

## Build-time checkout mechanism

None of these `api-src/<repo>/mkdocs.yml` files reference committed source
code — `nousergon-docs` never vendors another repo's files. Each config
points `paths:` at a `checkout/` (or `checkout/src` for `nousergon-lib`,
which has a real `src/` package layout) directory that does not exist in
git; the publish workflow creates it fresh on every run via a shallow
`git clone --depth 1` of the target repo's `main` branch immediately before
running `mkdocs build` for that sub-site, then deletes it after. See
`.github/workflows/publish-docs.yml`'s `Build per-repo API sub-sites` step.

This was chosen over:
- **`pip install`** — only `nousergon-lib` (`src/nousergon_lib`, real
  `pyproject.toml` package) is cleanly installable. The other 7 repos are
  flat-layout app repos (`requirements.txt`, no clean top-level package
  name) not designed to be installed as libraries.
- **git submodules** — would require every source repo to carry a reverse
  dependency on `nousergon-docs`' submodule pointer and a manual bump step
  on every docs refresh; a plain shallow clone at build time needs zero
  coordination with the source repos and always reflects `main` as of the
  build.

## Public-repo scope (hygiene boundary)

`nousergon-docs` and its published GitHub Pages site are **public**. Only
the 7 public Crucible code repos plus `nousergon-lib` are checked out and
rendered here:

`nousergon-lib`, `crucible-executor`, `nousergon-data`, `crucible-predictor`,
`crucible-research`, `crucible-backtester`, `crucible-dashboard`,
`crucible-evaluator`.

`alpha-engine-config` (private — proprietary scoring weights, agent
prompts, model parameters) and any other private or `*-ops` repo are
deliberately **excluded** — never cloned, never referenced in any
`mkdocs.yml` here. Before adding a new repo to this directory, verify its
visibility first:

```bash
gh repo view nousergon/<repo> --json visibility
```

Only add a repo here if that returns `"visibility": "PUBLIC"`.

## Adding a new repo

1. `mkdir -p api-src/<repo>/docs`
2. Copy an existing `api-src/<existing-repo>/mkdocs.yml`, update
   `site_name`, `site_url`, `repo_url`, `repo_name`, and `paths:` (usually
   just `[checkout]`, or `[checkout/src]` if the repo has a `src/` layout).
3. Write `api-src/<repo>/docs/index.md` with one `::: <module>` block per
   top-level importable package. Every package you leave out (`tests`,
   operational tooling) goes in `api-src/<repo>/exclude.txt` as
   `<package>  # <reason>` — see "Coverage check" below. Hyphenated
   directory names aren't Python packages and are never counted.
4. Add `<repo>` to the `for repo in ...` sub-site list in
   `.github/workflows/publish-docs.yml`.
5. Link the new page from `docs/index.md` (repo root) and from this
   README's repo list above.

## Coverage check

`docs/index.md` lists its modules by hand, so a package added to a public
repo used to never reach the reference, and nothing went red
(alpha-engine-config-I12650; nousergon-docs#68 added the four that had
been missed). `scripts/check_api_coverage.py` now runs inside
`publish-docs.yml` right after each sub-site's checkout:

- it lists the top-level packages (directories with `__init__.py`) under
  the root that sub-site's own `mkdocs.yml` `paths:` declares, and
  subtracts the packages named by `:::` lines in `docs/index.md` and the
  ones declared in `exclude.txt`;
- every package left over is a `::warning::` annotation on every run;
- the `api-coverage` job fails the **scheduled** weekly run when any
  sub-site has one, so a new upstream package goes red without anyone
  reading annotations. PR and push runs stay warn-only, and the deploy
  still ships;
- an `exclude.txt` line with no reason, or a missing package root, fails
  the build outright: a check that cannot read its declarations has not
  checked anything.

The roster it covers is the workflow's own `for repo in ...` list, the
same one that decides what gets built. Run it locally against a checkout:

    git clone --depth 1 https://github.com/nousergon/<repo>.git api-src/<repo>/checkout
    python3 scripts/check_api_coverage.py api-src/<repo> --enforce
