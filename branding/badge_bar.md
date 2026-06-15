# Badge Bar

Canonical badge bar for the top of every public repo's README. Standardized order, same color palette across repos.

## Order (left to right)

1. **Brand badge** — *"Part of Nous Ergon"* — links to nousergon.ai
2. **CI status** — GitHub Actions workflow badge (tests passing on main)
3. **Test count** — auto-generated count badge
4. **Python version** — runtime version
5. **Key stack badges** — 2–3 stack-specific (LangGraph, LightGBM, Streamlit, AWS Lambda, etc.)
6. **License** — MIT (Decision 10 across all public repos)
7. **Phase badge** — *"Phase 2 · Reliability"* — ties presentation back to the Phase 2 narrative

## Snippet template

Replace `<REPO_NAME>` and stack badges per repo. Phase badge color (`amber`) matches our current Phase 2 status — when we transition to Phase 3, update this snippet first and downstream READMEs follow.

```markdown
[![Part of Nous Ergon](https://img.shields.io/badge/Part_of-Nous_Ergon-1a73e8?style=flat-square)](https://nousergon.ai)
[![CI](https://img.shields.io/github/actions/workflow/status/nousergon/<REPO_NAME>/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/nousergon/<REPO_NAME>/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/dynamic/json?url=https://raw.githubusercontent.com/nousergon/<REPO_NAME>/main/.github/badges/tests.json&query=$.message&label=tests&style=flat-square&color=brightgreen)](https://github.com/nousergon/<REPO_NAME>/actions)
[![Python](https://img.shields.io/badge/python-3.13+-blue?style=flat-square)](https://www.python.org/)
<!-- 2-3 stack badges, e.g.: -->
[![LangGraph](https://img.shields.io/badge/LangGraph-1C3D5A?style=flat-square)](https://langchain-ai.github.io/langgraph/)
[![AWS Lambda](https://img.shields.io/badge/AWS_Lambda-FF9900?style=flat-square&logo=awslambda&logoColor=white)](https://aws.amazon.com/lambda/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)
[![Phase 2 · Reliability](https://img.shields.io/badge/Phase_2-Reliability-e9c46a?style=flat-square)](https://github.com/nousergon/nousergon-docs#phase-trajectory)
```

## Per-repo stack badge picks (suggested)

| Repo | Stack badges |
|---|---|
| `alpha-engine` (executor) | Interactive Brokers · AWS EC2 · vectorbt |
| `alpha-engine-research` | LangGraph · Anthropic Claude · AWS Lambda |
| `alpha-engine-predictor` | LightGBM · ArcticDB · AWS Lambda |
| `alpha-engine-data` | ArcticDB · Polygon.io · AWS Step Functions |
| `alpha-engine-backtester` | vectorbt · LightGBM · AWS EC2 (spot) |
| `alpha-engine-dashboard` | Streamlit · Plotly · pandas |
| `alpha-engine-docs` | (omit stack row — meta repo) |

## Style guide

- All badges: `style=flat-square` (visual consistency across repos)
- Brand color: `#1a73e8` Google-blue (extracted from `alpha-engine-dashboard/public/.streamlit/config.toml`; see `design_tokens.json`)
- Phase 2 color: `amber/#e9c46a` — readable, not alarming, distinct from green (which means CI passing)
- Tests count uses GitHub Actions to write to `.github/badges/tests.json` so the badge auto-updates on each test-suite run
- License = MIT yellow (the standard shields.io MIT color)

## When Phase changes

When the system transitions to Phase 3 (Alpha Tuning):
1. Update this file's Phase badge snippet (color → green or distinct accent)
2. Search-and-replace the snippet across all 7 public repos
3. Update related Phase-trajectory references in `alpha-engine-docs/README.md`
