# Phase trajectory

> Centralized snippet — single source of truth for the Nous Ergon / Alpha Engine phase narrative. Surfaces that reference this file: `alpha-engine-docs/README.md` (system map), `nousergon.ai` Home page hero, `private/interview_kit/README.md` and `private/interview_kit/talking_points/*.md` (Phase 2 anchor sections). One edit propagates.

| Phase | Focus | Status |
|---|---|---|
| **Phase 1** | Build the system end-to-end | ✅ Complete — 6 modules, 7 public repos, full pipeline running, autonomous SF orchestration |
| **Phase 2** | Reliability + measurability buildout | 🟡 **Current** — pipeline reliability, every decision point measurable, autonomous feedback loop |
| **Phase 3** | Parameter tuning toward alpha | ⏳ Next — operates on the substrate Phase 2 is making trustworthy |
| **Phase 4** | Live capital | ⏳ Gated on sustained Phase 3 outperformance |

The presentation layer leads with reliability and measurability, not returns. Long-term alpha — portfolio return minus SPY, risk-adjusted — is the metric Phase 3 is engineered to inflect.

## Per-phase key objectives

### Phase 1 — Build (✅)

End-to-end system standing. Six modules wired together via S3, with weekly + weekday + EOD Step Functions running autonomously.

- 6 modules built and integrated (Data, Research, Predictor, Executor, Backtester, Dashboard)
- Multi-agent research pipeline (LangGraph + Claude) producing weekly signals
- Stacked meta-ensemble predictor (Layer-1 specialized GBMs + Layer-2 Ridge meta-learner) producing daily forecasts
- Risk-gated executor trading paper account via IB Gateway with daemon-level safety checks
- Backtester writing optimized configs back to S3 weekly (autonomous feedback loop wired)
- Read-only Streamlit dashboard with public + private surfaces

### Phase 2 — Reliability + measurability buildout (🟡 current)

Every aspect of the system reliable and measurable, so Phase 3 can evaluate decisions on data, not vibes. Reliability and measurability are co-load-bearing — alpha can't be refined when pipelines break unpredictably (reliability), and tuning is meaningless on noisy measurements (measurability). Phase 2 closes both gaps by making every decision point in the system emit a measurement output AND running the pipelines that produce them reliably end-to-end.

Key objectives:

- **Pipeline reliability.** Saturday + weekday + EOD Step Functions reliable end-to-end. Drift detection, asymmetric-IAM-grant codification, runtime trend alarms.
- **Decision-point transparency.** Every decision the system makes — agent recommendations, predictor verdicts, trade executions, risk overrides, P&L attribution, config changes — emits a structured measurement output that downstream evaluation can read.
- **Autonomous feedback loop.** Backtester writing 4 optimized configs to S3 weekly with holdout validation; downstream modules read on cold-start. Per-component named-baseline gates on every L1 model.
- **Strict-by-default validation.** Typed-state hard-fail on all 8 with-structured-output sites; LLM-as-judge rubric layer; prompt versioning with frontmatter + cost telemetry.

Key receipts (current):

- EOD pipeline 50 min → 4.5 min after 3-PR same-day fix arc
- Predictor val_ic 0.053 → 0.132 after meta-collapse fix; per-component baseline discipline
- Test surface 380 → 589 in 6 weeks
- 6 console surfaces shipped (Signal Lifecycle, Feedback Loop, Feature Store, RAG Inventory, Architecture, Metrics) covering every measurement output the system produces
- 4 curated production retros documenting fix discipline
- Console subdomain rename + Cloudflare Access gating live

### Phase 3 — Parameter tuning toward alpha (⏳ next)

Operate the autonomous feedback loop on a Phase-2-trustworthy substrate. The machinery exists; Phase 3 is running it with confidence in the inputs.

Key objectives:

- Broader feature breadth in inference (current 21-feature subset → expand toward the ~50-feature ArcticDB store)
- L1 component upgrades through named-baseline gates (research-score calibrator: lookup table → GBM; regime model returns as Tier-1 LightGBM after clearing its baseline)
- Walking-forward verification that promoted configs deliver the predicted improvement
- Backtester sweep cadence + dimensionality expansion (Tier 4 vectorized sweep gated on remaining P0s)

**Gating to enter Phase 3 — the transparency inventory:**

Phase 3 begins when every decision point in the system emits a measurement output, each at expected coverage, sustained over a rolling 8-week window. The gate is a checklist, not a single number — *because no single number captures whether the substrate is ready to be evaluated against.*

| Decision point | Measurement output | Status |
|---|---|---|
| Pipeline execution | SF success rate ≥ 99% (Saturday + weekday + EOD) + per-stage durations | ✅ live |
| Agent decisions (research, CIO, judge) | Per-call artifact: prompt version + decision-capture record + cost telemetry + judge rubric scores; coverage ≥ 99% | ⚠️ artifacts exist; need coverage % published |
| Predictor decisions | Per-L1-component IC + L2 IC + confidence calibration + feature contributions | ✅ live |
| Trade execution decisions | Per-fill: entry trigger + sizing breakdown + signal_date + prediction_date lineage | ⚠️ partial — needs `signal_date` + `prediction_date` columns in `trades_full.csv` |
| Risk decisions (veto / override / halt) | Per-event log with rule + reason + value at threshold | ⚠️ partial — events fire today; structured-log coverage unconfirmed |
| P&L attribution | Per-day attributed dollars (research / predictor / sizing / market) + unattributed residual ≤ 1% | ⚠️ attribution exists; residual % needs publication as a named field |
| Config changes (autonomous loop) | Per-change diff log + rationale + subsequent-week behavioral delta | ✅ live |
| Data quality | Per-row source attribution + per-feature NaN/outlier rates + freshness | ✅ live |
| Agent quality | Rolling-mean LLM-as-judge rubric scores | ✅ live |

**Upstream work to close the ⚠️ rows** (Phase 2 work in its own right; each ~1 PR; tracked in ROADMAP.md as Phase 2 P1s):

- Backtester evaluator: emit decision-capture coverage %
- EOD reconcile: publish unattributed P&L residual % as a named field in `eod_pnl.csv`
- Trade logger: add `signal_date` + `prediction_date` columns to `trades_full.csv`
- Risk guard: structured event log with rule + reason for every veto / override / halt

Per Decision 11 of the presentation revamp plan (presentation surfaces are views, never measurement layers), each gating metric is tracked on its own.

### Phase 4 — Live capital (⏳ gated)

Paper → live, with capital sizing staged from small-position-on-positive-α-month to growth based on continued outperformance.

Key objectives:

- Live brokerage credentials with separate-account discipline (daemon hard-exits on non-paper account today)
- Capital sizing protocol staged from small-position-on-positive-α-month → growth based on continued outperformance
- 2FA + heightened operational discipline on the live surface
- Tax-aware position management

**Gating to enter Phase 4:**

- Sustained meaningful positive alpha vs SPY (risk-adjusted) over a 12-week Phase 3 paper-trading window
- Portfolio-level risk overlays — sector + correlation gates beyond per-position limits — before live capital
- Operational discipline: live-account credentials separate from paper, 2FA-gated, daemon-level safety check enforced

---

*Phase 2 is reliability + measurability buildout — making the substrate trustworthy enough that Phase 3 alpha tuning has something to tune against.*
