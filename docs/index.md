# Crucible API Reference

This site is a companion to **[nousergon.ai](https://nousergon.ai)**, the
canonical narrative/marketing surface for the Crucible (Alpha Engine)
project. It exists for one purpose: publishing an auto-generated Python API
reference from in-source docstrings across the public Crucible repos, via
[mkdocstrings](https://mkdocstrings.github.io/).

For system overview, architecture, phase trajectory, and the blog, see the
[top-level README](https://github.com/nousergon/nousergon-docs#readme) or
[nousergon.ai](https://nousergon.ai) directly.

## API Reference

Each repo below is built as its own small mkdocstrings site (see
[`api-src/README.md`](https://github.com/nousergon/nousergon-docs/blob/main/api-src/README.md)
for why) and published at `/api/<repo>/`:

- [alpha-engine-lib (nousergon-lib)](api/nousergon-lib/)
- [Executor (crucible-executor)](api/crucible-executor/)
- [Data (nousergon-data)](api/nousergon-data/)
- [Predictor (crucible-predictor)](api/crucible-predictor/)
- [Research (crucible-research)](api/crucible-research/)
- [Backtester (crucible-backtester)](api/crucible-backtester/)
- [Dashboard (crucible-dashboard)](api/crucible-dashboard/)
- [Evaluator (crucible-evaluator)](api/crucible-evaluator/)

## Scope note

Only **public** repos are included. `alpha-engine-config` (private — holds
proprietary scoring weights, prompts, and thresholds) and any other private
or `*-ops` repo are intentionally excluded from this site's build, since
this repo and its published site are both public. See
[`api-src/README.md`](https://github.com/nousergon/nousergon-docs/blob/main/api-src/README.md)
for the full repo list, the build mechanism, and the visibility-check
convention to follow before adding a new repo.
