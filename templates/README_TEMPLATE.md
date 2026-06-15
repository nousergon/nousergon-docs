# README Template — Per-Module Public Repo

Canonical lean structure for every public alpha-engine repo. Bird's-eye only — answers *"what is this module"*. Detail beyond that lives in [`OVERVIEW_TEMPLATE.md`](OVERVIEW_TEMPLATE.md) (the "where is the code" index) or in `alpha-engine-docs/private/interview_kit/` (the *"how does it work + what to say if asked"* private prep material).

> Per the presentation-revamp plan §1.1.

---

## Three-tier presentation surface (locked)

| Surface | Audience | Scope | Public? |
|---|---|---|---|
| **README** (~60 lines) | Recruiters skimming, casual visitors | What is this module | ✅ |
| **OVERVIEW.md** (~80 lines) | Interviewers digging in, future-you finding code | Where is the code | ✅ |
| **`private/interview_kit/`** | Brian during interview prep / live demo | How does it work + what to say if asked X | ❌ |

Each surface answers a different question. Even an interviewer who digs only finds the index in OVERVIEW.md — the trade-offs, failure modes, line-range code tour, and "if asked X look at file Y" pointers stay private.

## Zones of responsibility — what belongs in this README vs elsewhere

Module READMEs are **module-only content at the bird's-eye level**. System-level content lives in `alpha-engine-docs/README.md`; live performance and detailed prose live on `nousergon.ai`. Same fact never appears in two places.

| Content | `alpha-engine-docs` | This module's repo (README) | This module's repo (OVERVIEW.md) | `nousergon.ai` |
|---|:---:|:---:|:---:|:---:|
| System architecture diagram (all modules) | ✅ canonical | ❌ | ❌ | ✅ /architecture |
| Saturday + weekday + EOD Step Function pipelines | ✅ canonical | ❌ | ❌ | ✅ /architecture |
| Phase trajectory (Phase 1/2/3/4 status) | ✅ canonical | ❌ — Phase 2 badge only | ❌ | ✅ home page |
| 4-capability narrative ("What this is") | ✅ canonical | ❌ | ❌ | ✅ home page |
| Modules table (all modules described) | ✅ canonical | ❌ — minimal Sister Repos links only | ❌ | ✅ home page |
| Autonomous feedback loop (cross-module) | ✅ canonical | ❌ | ❌ | ✅ /architecture |
| Headline metrics, live alpha curve | ❌ | ❌ | ❌ | ✅ canonical (/metrics) |
| Public retros / postmortems | ❌ | ❌ | ❌ | ✅ canonical (/retros) |
| Blog posts | ❌ | ❌ | ❌ | ✅ canonical (/blog) |
| **Module purpose (1 line)** | ✅ row in modules table | ✅ canonical (here) | ✅ as the index header | ✅ /Docs |
| **What this module does** (3–5 capability bullets) | ❌ | ✅ canonical (here) | ❌ | ✅ /Docs |
| **Phase 2 measurement contribution** | ❌ | ✅ canonical (here) | ❌ | ❌ |
| **Module-internal architecture diagram** (high-level) | ❌ | ✅ canonical (here) | ✅ optionally more detailed | ✅ /Docs |
| **Configuration / disclosure boundary** (1–2 sentences) | ❌ | ✅ canonical (here) | ❌ | ❌ |
| Entry points + module file map | ❌ | ❌ | ✅ canonical | ❌ |
| Inputs / outputs (S3 paths, data contracts) | ❌ | ❌ | ✅ canonical | ❌ |
| Run modes (prod / dry-run / stub commands) | ❌ | ❌ | ✅ canonical | ❌ |
| Tests layout + conventions | ❌ | ❌ | ✅ canonical | ❌ |
| Trade-offs commentary, code tour with line ranges | ❌ | ❌ | ❌ | ❌ private |
| Failure modes + retros (this module) | ❌ | ❌ | ❌ | ❌ private |
| "If asked X look at Y" pointers, anticipated questions | ❌ | ❌ | ❌ | ❌ private |
| Brand banner (one-line disambiguation) | ✅ verbatim | ✅ verbatim | ❌ | ✅ implicit |
| License (MIT) | ✅ | ✅ | ❌ | (footer) |

---

## Section order (locked — 11 elements)

1. **H1 title** — repo name (`alpha-engine-<module>`)
2. **Brand banner** — copy from [`../branding/brand_banner.md`](../branding/brand_banner.md)
3. **Badge bar** — copy from [`../branding/badge_bar.md`](../branding/badge_bar.md)
4. **One-line module statement** — what this module does in one sentence
5. **Pointer to docs + OVERVIEW.md** — sends curious readers to the right deeper home
6. **What this does** (3–5 bullets) — concrete capabilities
7. **Phase 2 measurement contribution** — what this module *measures* and why that matters for Phase 3 alpha tuning
8. **Architecture** — module-internal mermaid diagram (high-level — leave the granular flow to OVERVIEW.md or skip entirely)
9. **Configuration / disclosure boundary** — 1–2 sentences naming what's gitignored vs public; do NOT enumerate files
10. **Sister repos** — 7-row links-only table (the 6 modules + `alpha-engine-lib` + `alpha-engine-docs`)
11. **License** — one-line MIT pointer

Target length: **50–80 lines per repo**. PR #98 (alpha-engine-research, 58 lines) is the working reference.

---

## Boilerplate (copy-paste, fill in `<>` placeholders)

```markdown
# alpha-engine-<module>

> Part of [**Nous Ergon**](https://nousergon.ai) — Autonomous Multi-Agent Trading System. Repo and S3 names use the underlying project name `alpha-engine`.

[![Part of Nous Ergon](https://img.shields.io/badge/Part_of-Nous_Ergon-1a73e8?style=flat-square)](https://nousergon.ai)
[![CI](https://img.shields.io/github/actions/workflow/status/nousergon/alpha-engine-<module>/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/nousergon/alpha-engine-<module>/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.13+-blue?style=flat-square)](https://www.python.org/)
<!-- 2-3 stack badges per branding/badge_bar.md -->
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)
[![Phase 2 · Reliability](https://img.shields.io/badge/Phase_2-Reliability-e9c46a?style=flat-square)](https://github.com/nousergon/nousergon-docs#phase-trajectory)

<ONE-LINE MODULE STATEMENT — what this module does in one sentence.>

> System overview, Step Function orchestration, and module relationships live in [`alpha-engine-docs`](https://github.com/nousergon/nousergon-docs). Code index lives in [`OVERVIEW.md`](OVERVIEW.md).

## What this does

- <Bullet 1 — concrete capability>
- <Bullet 2>
- <Bullet 3>
- <Bullet 4 (optional)>
- <Bullet 5 (optional)>

## Phase 2 measurement contribution

<2–4 sentences on what this module *measures* and why that's load-bearing for Phase 3 alpha tuning. Concrete substrate, not metaphor.>

## Architecture

```mermaid
<MODULE-INTERNAL DIAGRAM — high-level, ~5 boxes. Granular flow belongs in OVERVIEW.md or stays private.>
```

<Optional 1-paragraph explanation if the diagram needs context.>

## Configuration

This repo is **public**. <Sentence on what's gitignored locally vs what's in the private [`alpha-engine-config`](https://github.com/nousergon/alpha-engine-config) repo.> Architecture and approach are public; specific values are private.

## Sister repos

| Module | Repo |
|---|---|
| Executor | [`alpha-engine`](https://github.com/nousergon/crucible-executor) |
| Data | [`alpha-engine-data`](https://github.com/nousergon/nousergon-data) |
| Research | [`alpha-engine-research`](https://github.com/nousergon/crucible-research) |
| Predictor | [`alpha-engine-predictor`](https://github.com/nousergon/crucible-predictor) |
| Backtester | [`alpha-engine-backtester`](https://github.com/nousergon/crucible-backtester) |
| Dashboard | [`alpha-engine-dashboard`](https://github.com/nousergon/crucible-dashboard) |
| Library | [`alpha-engine-lib`](https://github.com/nousergon/nousergon-lib) |
| Docs | [`alpha-engine-docs`](https://github.com/nousergon/nousergon-docs) |

## License

MIT — see [LICENSE](LICENSE).
```

---

## Notes on applying this template

- **Don't paraphrase the brand banner** — copy verbatim from `../branding/brand_banner.md`
- **Don't reorder section order** — recruiters reading multiple repos benefit from visual consistency
- **Mermaid renders natively on GitHub** — no external tooling needed
- **Phase 2 measurement contribution paragraph is mandatory** — ties the repo back to the central narrative
- **For repos with substantial private config dependencies** (e.g., `alpha-engine-research` with prompt loaders), make the proprietary boundary explicit in the Configuration section
- **No "Quick start" / "How it runs" / "Key files" / "Outputs" / "Testing" sections in the README** — those go in OVERVIEW.md
- **No "Failure modes / retros" section in the README** — link to the public `/retros` page on `nousergon.ai` if surfaced anywhere
- **Resist drift back toward verbosity** — if you find yourself adding a 12th section, it probably belongs in OVERVIEW.md or the private interview kit
