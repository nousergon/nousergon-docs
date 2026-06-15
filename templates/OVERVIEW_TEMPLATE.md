# OVERVIEW.md Template — Per-Module Code Index

Canonical structure for each public alpha-engine repo's `OVERVIEW.md`. **An index of where the code lives, not a tour of how it works.** A tool for Brian + viewers to find their way around the repo without reading every file.

> Per the presentation-revamp plan §1.2. Companion: [`README_TEMPLATE.md`](README_TEMPLATE.md) for the bird's-eye README.

---

## Three-tier presentation surface (locked)

| Surface | Audience | Scope | Public? |
|---|---|---|---|
| **README** (~60 lines) | Recruiters skimming, casual visitors | What is this module | ✅ |
| **OVERVIEW.md** (~80 lines) | Interviewers digging in, future-you finding code | Where is the code | ✅ |
| **`private/interview_kit/`** | Brian during interview prep / live demo | How does it work + what to say if asked X | ❌ |

**OVERVIEW.md answers "where is the code." Nothing more.**

What does NOT belong in OVERVIEW.md:
- Code-tour with line ranges and key-function annotation → `private/interview_kit/talking_points/0X_<module>.md`
- Trade-offs commentary, design-rationale prose → `private/interview_kit/architecture_decision_log.md`
- Failure modes + retros → `private/interview_kit/retros_private/`
- "If asked X look at file Y" pointers → `private/interview_kit/talking_points/0X_<module>.md`
- Anticipated interview questions + answers → `private/interview_kit/talking_points/0X_<module>.md`

If you find yourself writing prose that explains *why* a design choice was made, that prose belongs in the private interview kit, not in OVERVIEW.md.

---

## Section order (locked — 7 sections, optionally 8)

1. **H1 + one-line context** — repo name; pointer back to README + system overview
2. **Module purpose** (one sentence) — same as README open; duplication is fine in an index
3. **Architecture** *(optional)* — skip if the README's diagram is sufficient. If kept, slightly more detail than the README's, still high-level.
4. **Entry points** — 2–3 files where execution starts (e.g., `lambda/handler.py`, `weekly_collector.py`, `daemon.py`). Just file links + one-line description each.
5. **Where things live** — concept → file map. *"scoring formula → `scoring/composite.py`; trade logger → `executor/trade_logger.py`"* — an index for finding code without reading the whole repo.
6. **Inputs / outputs** — S3 paths the module reads + writes. Tables, no schemas, no commentary.
7. **Run modes** — production cadence + dry-run + stub. Three rows max, no walkthrough.
8. **Tests** *(optional, one paragraph)* — `tests/` layout + conventions. Skip if there's nothing distinctive about the suite.

Target length: **60–100 lines per repo**. Each row of each table is a couple words to a half-sentence.

---

## Boilerplate (copy-paste, fill in `<>` placeholders)

```markdown
# alpha-engine-<module> — Code Index

> Index of entry points, key files, and data contracts for this repo. Companion to [README.md](README.md). System overview lives in [`alpha-engine-docs`](https://github.com/nousergon/nousergon-docs).
>
> Last reviewed: <YYYY-MM-DD>

## Module purpose

<One sentence — same as README open.>

## Architecture (optional)

<Skip if README's diagram is enough. If kept, slightly more detailed mermaid flow.>

## Entry points

| File | What it does |
|---|---|
| [`<file.py>`](<path>) | <One-line description> |
| [`<file.py>`](<path>) | <One-line description> |

## Where things live

| Concept | File |
|---|---|
| <Concept 1> | [`<path/file.py>`](<path/file.py>) |
| <Concept 2> | [`<path/file.py>`](<path/file.py>) |
| <Concept 3> | [`<path/file.py>`](<path/file.py>) |
| <…> | <…> |

## Inputs / outputs

### Reads
| Source | Path |
|---|---|
| <Source> | <path> |

### Writes
| Destination | Path |
|---|---|
| <Dest> | <path> |

## Run modes

| Mode | Where | Command |
|---|---|---|
| Production | <Lambda / EC2 / spot / systemd> | <deploy mechanism, e.g. `./infrastructure/deploy.sh main`> |
| Dry run | Local | `<command>` |
| Stub run (no API spend) | Local | `<command>` *(if applicable)* |

## Tests (optional)

<One paragraph: test layout (`tests/unit/`, `tests/integration/`, fixtures, replay patterns); test count and conventions. Skip if not distinctive.>
```

---

## Notes on applying this template

- **No code-tour with line ranges.** If `path/file.py` is interesting enough to annotate at the line level, that annotation belongs in `private/interview_kit/talking_points/0X_<module>.md`.
- **No design rationale prose.** *"We chose X over Y because Z"* belongs in `private/interview_kit/architecture_decision_log.md`.
- **No "What this measures" or Phase 2 contribution paragraph.** That's a README concept; OVERVIEW.md skips it.
- **Each table row is a one-liner.** If a row needs a paragraph of explanation, the explanation belongs private.
- **Architecture diagram is optional.** Don't duplicate the README's diagram unless the OVERVIEW version genuinely shows more useful detail without slipping into "how does it work."
- **No "Failure modes" / retros section.** Public retros live on `nousergon.ai/retros`; private retros live in `private/interview_kit/retros_private/`.
- **Resist drift back toward the old tier-based code tour.** Tier 1/2/3/4 was previously the locked structure; it's been retired in favor of this lean index.
