# QDR L2 — Style Rotation & Factor Research
## P0 implementation baseline and research protocol

**Protocol baseline:** P0 audit completed and frozen for implementation.  
**Current engineering status (2026-11-18):** P0–P6 code paths are implemented on `main`; real label/feature bundles, full pytest, genuine-forward evidence and local browser/data acceptance remain required before any model-validity claim.  
**Scope:** L2 research and read-only cross-layer contracts only. No broker-order enablement.  
**Repository baseline audited:** `main` at `4db4c4ce7df0e5f45196879d846880ad8d7da167` (2026-11-18).

---

## 1. Product contract

L2 answers five questions:

1. Which of the seven defined styles is currently relatively strong?
2. Which styles are accelerating, decelerating, improving from weakness, or deteriorating?
3. Which styles are forecast to outperform their specified benchmark over H1/H3/H5?
4. Which observable features explain the current state and model output?
5. Did the frozen forecasts subsequently perform as expected in genuinely out-of-sample observations?

L2 is not the market-direction model (L1), individual-stock selector (L3), or portfolio/risk controller (L4). L2 emits style-level research observations and, only after qualification, style-level forecasts. It does not create orders or position sizes.

Observation, rotation state, forecast, and validation are separate evidence products. A descriptive score must never be presented as a forecast probability.

## 2. Seven style definitions — version 1

The ETF portfolios are investable style proxies, not pure academic factors and not historical constituent/PIT portfolios.

| style_id | Display name | Long / style proxy | Relative benchmark | Notes |
|---|---|---|---|---|
| size | Size | IWM | SPY | Small-cap vs broad US equity |
| value | Value | IWD | IWF | Value vs growth pair |
| growth | Growth | IWF | SPY | Growth proxy vs broad market |
| momentum | Momentum | MTUM | SPY | Rules-based momentum ETF |
| quality | Quality | QUAL | SPY | Quality ETF, not French RMW |
| low_vol | Low volatility | USMV | SPY | Low-volatility ETF |
| cyc_def | Cyclical vs defensive | Equal-weight XLI/XLY/XLB/XLF | Equal-weight XLP/XLU/XLV | Relative return of two fixed sector baskets |

Cyclical and defensive basket membership is versioned and frozen. Initial weights are equal-weight within each basket, rebalanced to equal weights every exchange session (daily constant-weight return series, not a buy-and-hold ETF basket). The spread is cyclical basket return minus defensive basket return. If any required component is missing for a session, the composite for that session is null; no weight redistribution, forward-fill, or fabricated observation is allowed.

Value and Growth are intentionally retained as separate views for user interpretation, but they are a related pair and must not be counted as independent evidence in composite models without correlation/collinearity controls.

The seven proxy definitions and basket membership must be stored in a versioned registry. Changes create a new version; they do not rewrite prior historical results.

## 3. Benchmark and return convention

### 3.1 Observation convention

For each style proxy and its benchmark, use the same session calendar and the same price basis. Prefer split/dividend-adjusted total-return-consistent prices where the source supplies a verifiable basis. Never mix adjusted and unadjusted prices in one pair.

For close-to-close descriptive relative strength:

`RS_{s,b}(t,H) = (P_s(t)/P_s(t-H))/(P_b(t)/P_b(t-H))-1`

Compute H=5, 20, and 60 sessions, plus:
- relative momentum acceleration: current 5-session relative return minus the immediately preceding 5-session relative return;
- relative up days over 10 sessions;
- 20-session sample volatility of daily relative returns (ddof=1);
- 20/60-session relative drawdown and return dispersion where complete inputs exist.

All calculations require complete aligned observations. No forward-fill, zero-fill, bridging across missing sessions, or silent proxy substitution.

### 3.2 Forecast target convention

The primary forecast target is the style portfolio's future return minus its stated benchmark return:

`Y(style,H) = R(style, T+1 Open → T+H Close) - R(benchmark, T+1 Open → T+H Close)`

H is 1, 3, or 5 exchange sessions. Signal cutoff is after the T close snapshot is complete; entry is the next session open. Both legs use identical entry/exit timestamps and corporate-action-consistent prices.

A target is eligible for model training only when it is backed by verified raw, action-consistent returns and an independently attested availability/label record. Exploratory current-vintage ETF prices remain exploratory and cannot be relabelled as verified raw targets.

## 4. Rotation-state protocol

Four states are required:
- STRONG_ACCELERATING (强势加速)
- STRONG_DECELERATING (强势减速)
- WEAK_IMPROVING (弱势改善)
- WEAK_DETERIORATING (弱势恶化)

For V1, use a transparent, non-fitted descriptive rule:
- strength level = 20-session relative return;
- acceleration = 5-session relative return minus the preceding 5-session relative return;
- positive/negative boundaries are zero;
- missing/incomplete inputs produce UNKNOWN.

This is a descriptive quadrant, not an entry/exit signal. Record state start, prior state, transition timestamp, and consecutive sessions. A transition is not fabricated on the first valid observation. Any future threshold fitting must use training data only and be versioned separately.

## 5. French factors remain a parallel evidence stream

Retain the existing verified French monitor as a separate observation/attribution stream:
- Mkt-RF, SMB, HML, RMW, CMA, Mom, ST_Rev, RF.
- RF is reference-only and excluded from the four-state rotation classification.
- French factor arithmetic rolling sums are descriptive factor-premia aggregates, not ETF total returns, NAV, or strategy P&L.
- Current-vintage historical French values must not be treated as historically available values. Use `available_at` / first-observed provenance; if a valid historical PIT vintage is unavailable, mark the feature ineligible for historical model training.
- RMW is not the same product as QUAL; Mom is not the same product as MTUM.

ETF style proxies and French factor returns must not be silently merged into a single score. They can be compared and later tested via incremental ablation.

## 6. Prediction protocol

### 6.1 Baselines and model progression

Each style/horizon is independently evaluated. Required baselines:
1. zero-excess-return baseline;
2. expanding historical mean baseline;
3. simple relative-momentum baseline.

Initial primary model: StandardScaler + Ridge, fitted separately by style and horizon. ElasticNet and Gradient Boosting are challenger models only after the baseline pipeline is stable and sample size permits. A shared/hierarchical model is a later challenger, not the V1 default.

Feature candidates:
- ETF relative returns at 5/20/60 sessions;
- relative acceleration and up-day count;
- relative volatility and drawdown;
- cross-style dispersion/correlation;
- L1 regime and approved L1 observation features;
- available macro/market variables only when their historical publication times are verified;
- French factors only when point-in-time availability is proven for the relevant historical signal.

No feature can be included solely because it exists in today's revised historical file.

### 6.2 Time-series validation

- No random train/test split.
- Walk-forward / expanding or rolling windows only.
- Purge overlapping H1/H3/H5 labels based on each label's actual exit time.
- Embargo at least H sessions after the training boundary; increase where label overlap requires it.
- All scaling, feature selection, imputation (if ever allowed), hyperparameter selection, and calibration are fitted within the appropriate training/validation window.
- Keep a final sealed test period untouched until the protocol is frozen.
- Seven styles observed on the same date are correlated observations, not seven independent dates.
- Report each style and horizon separately, plus aggregate metrics with date-clustered uncertainty where applicable.

### 6.3 Metrics

Regression: MAE, RMSE, OOS MSE gain versus each baseline.  
Ranking: cross-sectional Rank IC / ICIR only where the cross-section and sample support it.  
Direction: directional accuracy and balanced accuracy.  
Probability: Brier, LogLoss, reliability curve, calibration slope/intercept and ECE only after a properly defined event target and independent calibration sample exist.  
Robustness: per-regime performance, subperiod stability, drawdown/tail error, turnover/cost sensitivity where portfolio simulation is later authorized.

Do not display probabilities before calibration evidence exists. Do not treat directional accuracy as probability calibration.

### 6.4 Qualification states

- OBSERVATION_ONLY: valid descriptive data, no eligible prediction.
- RESEARCH_ONLY: research predictions exist but OOS/calibration/admission criteria are not met.
- OOS_VALIDATED: independent OOS criteria pass for the exact style/horizon/model version.
- MODEL_ADMITTED: complete source/PIT, OOS, calibration, stability, and governance gates pass.

Admission is scoped to style + horizon + model version. Passing H3 for Quality does not admit H1 or other styles. Admission never enables broker orders.

## 7. P0 audit of existing repository

Audited files on main:

| Existing asset | Verified capability | Gap / decision |
|---|---|---|
| `research/v4_style_rotation.py` | Causal ETF ratio observations; 5/20 relative returns, acceleration, up-days, 20d relative volatility; Ridge expanding quarterly OOS and MSE/directional scoring | `STYLE_PAIRS` currently has only small/value/momentum/quality/low_vol. Growth and cyclical/defensive are absent. No 60d relative return, drawdown, cross-style matrix, seven-style registry, calibration, admission, or frozen forecast ledger. Keep the no-future-data and verified-label gates. |
| `research/style_monitor.py` | Eight French series; 5/20/60 arithmetic sums, annualized 20d volatility, four descriptive states, 60d correlation; missing values remain missing | This is French attribution/observation, not ETF style rotation or a forecast. Current-vintage revisions cannot be treated as historical PIT. Retain separately. |
| `workflow/styles.py` | Loads verified French bundle and writes immutable observation reports | Reuse only for French observation stream. |
| `GET /api/v1/styles` | Returns French monitor payload and optional CSV | Does not provide seven ETF style observations or H1/H3/H5 style forecast contracts. |
| `GET /styles`, `/studio#style` | Existing French style monitor UI | Existing V4 page is a French summary; expand/replace only after API contract is defined. |
| `tests/test_v4_style_rotation.py` | Causal-prefix test and strict raw-label requirement for two style pairs | Expand to seven styles, missing component behavior, target timing, and strict OOS evidence. |
| `tests/test_styles.py` | French provenance, formula, availability, prefix, lock, and API checks | Preserve; do not conflate with ETF style tests. |
| Factor lab / multi-factor | Real exploratory factor artifacts and strict snapshot comparability | Existing guide states labels are exploratory proxies; they cannot train admitted L2 forecasts. No silent upgrade. |

### Existing limitations that must remain visible

1. Existing French verified coverage documented through 2026-09-30; that is not the latest ETF market session.
2. The existing style model currently requires `VERIFIED_RAW_RELATIVE_RETURN`, while documented factor-lab experiments include exploratory proxy labels and zero formal raw labels. This is a real blocker for training from those experiments, not a reason to weaken the gate.
3. Current ETF history is not a PIT constituent universe. For the seven liquid ETF proxy portfolios, this does not require reconstructing every historical constituent to describe the traded ETF itself; however, price-source, corporate-action, and historical availability evidence still must be verified.
4. The repository's configured current symbol allowlist includes all 14 required ETF symbols. This is not proof that each symbol has complete historical coverage in the user's local database; P1 workflow emits per-symbol coverage and blocks affected style rows rather than filling gaps. Cyclical/defensive basket data and the IWF/SPY Growth proxy still require local source-coverage verification.
5. Data ingestion, provider setup, warehouse maintenance, and local cache ownership remain outside this L2 implementation scope. Missing sources must be reported as blocked; no synthetic data or automatic source substitution.

## 8. Implementation sequence and deliverables

| Phase | Deliverables | Exit gate |
|---|---|---|
| P0 | This protocol; code reuse/gap audit; versioned seven-style definitions and target conventions | Research protocol reviewed/frozen |
| P1 | Style registry, ETF pair/basket calculator, data quality and coverage report, 5/20/60 observations | All seven styles either valid or individually BLOCKED with reason |
| P2 | Rotation quadrants, transition ledger, state history/replay | Historical state reproducible and causal |
| P3 | L2 V4 cockpit using real API payloads | UI renders data and honest empty states; no demo numbers |
| P4 | H1/H3/H5 target construction, baselines, Ridge walk-forward | Raw-label and PIT gates pass; otherwise explicit BLOCKED |
| P5 | OOS scoring, calibration, ablation, immutable forecast ledger, qualification | Exact style/horizon qualification independently evidenced |
| P6 | L1/L3/L4 read-only contracts, end-to-end tests, acceptance report | Integration and regression suite pass |

Do not create a separate PR for each small phase. Work on one L2 branch and open one consolidated draft PR after a coherent implementation increment; keep Codex/local-only data acceptance as a single explicit handoff if required.

## 9. API contracts

Implemented read-only contracts:

- `GET /api/v1/l2/styles/overview?asof=&cutoff=&start=&rotation=1` — P1 observations, optional P2 rotation from one source snapshot.
- `GET /api/v1/l2/styles/rotation?asof=&cutoff=&start=` — P2 states, history and genuine transitions.
- `GET /api/v1/l2/styles/forecast?asof=&horizon=&start=` — P4 H1/H3/H5 continuous relative-return research; fails closed without verified label and feature bundles.
- `GET /api/v1/l2/styles/validation?asof=` — reads only an immutable P5 validation report; never runs Walk-forward in the GET request.
- `GET /api/v1/l2/styles/downstream-context?asof=` — P6 L2→L3 contract; only exact MODEL_ADMITTED frozen units can expose numeric downstream context.
- `GET /api/v1/v4/layers?asof=&horizon=` — P6 four-layer evidence snapshot across L1/L2/L3/L4; never grants execution eligibility.

Separate existing French observation API remains `GET /api/v1/styles?mode=observation`.

Optional future convenience endpoints such as style-specific history/drivers or standalone ablation browsing are not required for the P0–P6 evidence chain and should not duplicate existing payloads without a concrete product need.

Every payload must expose schema/version, as-of session, signal cutoff, per-source availability, source snapshot hash, calculation protocol version, missingness/coverage, research status, and eligibility. A missing value is null with a reason, never zero.

## 10. P1 implementation progress

- Added `research/l2_style_rotation.py`: seven-style registry and causal calculations for 5/20/60-session relative return, acceleration, relative up-day count, volatility, and 20/60-session relative drawdown.
- Added `workflow/l2_styles.py`: read-only adapter over the existing verified market bundle; no provider requests, ingestion, or warehouse mutation. V1 currently requires Yahoo split-adjusted price basis and reports the current-vintage/non-total-return limitation.
- Added `GET /api/v1/l2/styles/overview`.
- Added focused unit tests for registry, windows, missing basket components, causal-prefix stability, availability propagation, source basis, and API query validation. These tests have been authored but not executed in the local Codex environment yet.
- Real local symbol coverage and pytest acceptance remain pending. The P1 API alone is an observation endpoint; P2 rotation and P3 cockpit are implemented separately below, while forecasting remains unimplemented.

## 11. Out of scope

- No new data warehouse or parallel history store.
- No paid data subscription or provider onboarding by this implementation.
- No rewriting L1 data management or L1 model logic.
- No stock-level Alpha selection, portfolio sizing, broker integration, or order execution.
- No claims of profitability or trading readiness from descriptive monitoring.


## 12. P2 implementation update (2026-11-18)

- P1 rolling source availability was repaired: pandas cannot run rolling maximum directly over timezone-aware datetime columns. The revised implementation calculates an exact int64 UTC-nanosecond window maximum over all N+1 required closes, preserving missingness and timestamp precision.
- P1 source availability is now an actual observation gate: prices without known availability or first available only after the knowledge cutoff do not participate in relative returns. Symbol coverage distinguishes a raw as-of row from an as-of price available by cutoff.
- P2 descriptive state machine added in `research/l2_rotation.py`: +20d/-20d strength crossed with +5d/-5d relative acceleration yields four states. An exact zero value is neutral UNKNOWN (not a fabricated directional signal). The initial valid state is not a transition.
- Every state event records the versioned protocol, state start, prior state when genuinely transitioned, last transition session, consecutive known exchange-session observations, source timestamp, and explicit missingness reason.
- Missing/late source observations break streaks; UNKNOWN-to-known creates a fresh baseline rather than a false transition.
- New read-only endpoint `GET /api/v1/l2/styles/rotation?asof=&cutoff=&start=` returns seven latest states, recent 126-session history per style and 50 latest genuine transitions; `asof` is a date-based observation replay, not a historical PIT claim.
- Synthetic deterministic Python unit tests and HTTP contract tests have been committed for the core quadrant, gap, replay, missingness, and cutoff rules.
- **Not yet accepted**: full pytest suite, browser behavior, latest live seven-symbol completeness and source entitlement/coverage tests must be executed in the user's local repository environment. No forecast or admission is granted.
- P3 cockpit was subsequently submitted in this L2 branch; P4–P6 forecasting/integration remain incomplete.

### Required local acceptance before merging to main

```bash
python -m pytest -q tests/test_l2_style_rotation.py tests/test_l2_style_workflow.py tests/test_l2_style_api.py tests/test_l2_rotation.py
python -m pytest -q
```

Start the existing local console on the machine with access to the existing real-data DuckDB, then request `/api/v1/l2/styles/overview` and `/api/v1/l2/styles/rotation` (optionally with `asof`). Confirm all fourteen proxies have first/last session and cutoff-qualified freshness, seven latest states are either known or explicitly UNKNOWN with reasons, source hashes match, all payloads remain observation-only, and no data writes/forecasts/broker orders occur.

## 13. P3 cockpit implementation update (2026-11-18)

- New standalone `assets/v4_ui_l2.js` and `v4_ui_l2.css` load *after* the existing V4 fidelity/theme layer on the original `/studio#style` route; no duplicate workspace or standalone navigation created.
- The L2 page contains data-derived four-quadrant style positions (20-session relative return and five-session acceleration), seven-style ranked observations, selected-style historical curve (breaks at missing data), state duration, transition list, source coverage, calculation basis, and a separate French observation view.
- One endpoint request `GET /api/v1/l2/styles/overview?rotation=1&asof=YYYY-MM-DD` calculates both P1 and P2 from the same existing read-only snapshot, avoiding duplicate reads on first render. `/api/v1/l2/styles/rotation` remains available as a standalone API.
- The date selector is an *exploratory current-vintage replay*, not evidence that the downloaded prices were historically available on that date. The UI includes this limitation and keeps `historical_decision_eligible=false`.
- Nulls and post-cutoff observations are never converted to zero or filled by the page. Incomplete 5-, 20- and 60-session availability now have distinct status/reason strings.
- Forecast/H1/H3/H5 intentionally has a clearly labelled blocked placeholder pending validated T+1-open-to-T+H-close labels and OOS research.
- Static tests, Node.js isolated page-runtime fixture, API query tests and source-gated Python calculations have been committed. The **actual committed JS blob** passed an isolated V8 runtime check against data/empty French-response fixtures; a separate Pandas test verified the time-availability rolling window. These checks **do not substitute** for the complete repository test suite or actual browser/database acceptance.
- Latest main research-readiness navigation text was incorporated into the L2 branch shell to avoid overwriting a contemporaneous change.
- Local runbook: [L2 P1–P3 acceptance](L2_P1_P3_LOCAL_ACCEPTANCE.md). Merge remains pending full tests, real-source coverage audit, and browser smoke. Do not claim model readiness.

## 14. Remaining work

- **P1–P3 local release gate:** execute complete pytest/browser checks and verify real 14-symbol source coverage on the user's local repository.
- **P4 local data gate:** build and accept the independently verified action-consistent label bundle. Engineering is present, but the committed default remains blocked until that evidence exists.
- **P5 local validation gate:** run the fixed OOS/ablation protocol against the accepted bundle, freeze the report, accumulate genuine-forward P4 snapshots and review the admission evidence. Engineering is present; no model is claimed validated in this environment.
- **P6 integration:** consume only explicit L1/L2 qualification states in L3/L4 read-only contracts; no brokerage order execution.

## 15. P4 implementation update (2026-11-18)

P4 engineering has been added to the same L2 branch without changing the
P1/P2 evidence boundary.

### Implemented

- `research/l2_labels.py`: exact T+1-open → T+H-close, H1/H3/H5 style-relative
  label construction for all seven styles. It accepts only
  `VERIFIED_ACTION_CONSISTENT_TRADE_RETURN_BASIS` and per-session corporate
  action/source-availability evidence. P1 Yahoo current-vintage history is
  intentionally rejected as a label basis.
- `research/l2_label_bundle.py`: small immutable derived-label bundle with
  SHA256 verification, seven-style/H1-H3-H5 scope checks and write-once bundle
  IDs. It does not create a parallel price warehouse.
- `research/l2_forecast.py`: 21 independent style×horizon research units,
  StandardScaler + Ridge(alpha=1), fail-closed missing/current-late features,
  at least five-session embargo, verified-label availability gating and three
  baselines: zero, expanding mean and 5D momentum extrapolation.
- Model features: 5/20/60 relative return, five-day acceleration, ten-session
  relative up-day count, 20D relative volatility, 20/60 drawdown, cross-style
  20D dispersion and four explicit rotation-quadrant indicators.
- `walk_forward_oos_v1` and `score_oos_v1`: causal date-by-date OOS output,
  MAE/RMSE/MSE, gains versus all three baselines and direction accuracy.
  These are research metrics only and do not admit the model.
- `workflow/l2_forecast.py` + `GET /api/v1/l2/styles/forecast`: read-only
  source-gated P4 API. Default configuration has no label bundle and therefore
  returns `L2_VERIFIED_LABEL_BUNDLE_REQUIRED` rather than generating numbers.
- P4 is lazy-loaded in the existing `/studio#style` workspace under
  「领先预测」. Default P1/P2 page does not invoke model fitting.
- `research/l2_forecast_archive.py` and
  `workflow/l2_forecast_freeze.py`: explicit write-once forward-research
  snapshot. GET never writes. The archive requires the exact 7×3 grid, source
  SHA, label bundle SHA, research-only eligibility and no order capability.

### Tests authored

- label timing, pair/basket arithmetic and action-evidence blockers;
- immutable label bundle round-trip/hash/scope protection;
- 21-unit forecast output, H1/H3/H5, baselines, embargo and future-mutation
  causality;
- OOS score contract;
- source-gated forecast workflow and strict HTTP query validation;
- lazy P4 UI BLOCKED/RESEARCH_ONLY rendering;
- immutable forecast snapshot identity and no-write blocker behavior.

The actual committed L2 JavaScript P4 tab has passed an isolated runtime
smoke in this connector environment. Full Python pytest, user's real DuckDB
evidence, actual label source, and real browser acceptance remain local gates.

### P4 status

**Engineering: implemented, not accepted.** The committed
`configs/l2_forecast.yaml` has `label_bundle_id: null` on purpose. No
qualified label bundle has been supplied in this environment, so no real P4
forecast is claimed. All system-level eligibility remains
`historical_decision_eligible=false`, `real_orders_enabled=false`.

Local acceptance: [L2 P4 checklist](L2_P4_LOCAL_ACCEPTANCE.md).

P5 remains responsible for adequate OOS sample size, baseline improvement,
stability/ablation, immutable forward-outcome accumulation and any separately
defined probability calibration/model admission.


## 16. P5 implementation update (2026-11-18)

P5 engineering is now implemented on `main` while preserving the P4
research-only boundary.

### Validation protocol

- `configs/l2_validation.yaml` freezes a 252-session OOS evaluation span and
  predeclared gates before local results are inspected.
- Each of the 21 `style_id × H1/H3/H5` units is always explicit. Missing
  evidence remains `RESEARCH_ONLY`; a unit never disappears from the report.
- OOS validation requires at least 126 scorable sessions, Ridge improvement
  against Zero / expanding mean / 5D momentum, at least 2% relative MSE gain
  versus the best baseline, ≥52% directional accuracy, horizon-level
  cross-style Rank IC ≥0.05, and chronological subperiod stability.
- Probability calibration is intentionally
  `NOT_APPLICABLE_CONTINUOUS_RETURN_ONLY`. P4/P5 predicts continuous relative
  return, so no win-rate or probability field is inferred from the regression.

### Ablation

- P5 evaluates four nested feature sets on the exact same OOS dates:
  `returns_only`, `returns_dynamics`, `returns_dynamics_risk`, and
  `full`.
- P4 forecasting now accepts a fixed feature subset solely for this ablation
  research; the default production-research feature set is unchanged.
- The `full` fold is reused from the ablation pass instead of being fitted a
  second time.

### Genuine-forward evidence and qualification

- P5 reads integrity-checked P4 frozen snapshots and counts a forecast as
  forward evidence only when
  `signal_time <= frozen_at_utc < T+1 entry_time`.
- Labels must remain unavailable until at least the corresponding H1/H3/H5
  exit. Retrospectively frozen snapshots do not count.
- Default forward admission gate requires 60 genuine-forward sessions for the
  exact style/horizon, nonnegative MSE gain versus the best baseline and at
  least 50% direction accuracy.
- `model_admission_enabled: false` is committed intentionally. Even an
  OOS/forward-passing unit remains `OOS_VALIDATED` until the admission switch
  is explicitly enabled after local evidence review.
- `MODEL_ADMITTED` remains scoped to style × horizon × model version ×
  validation protocol and still sets `decision_eligible=false` and
  `real_orders_enabled=false`.

### Execution and artifacts

- `python -m quant_research.workflow.l2_validation --date YYYY-MM-DD` runs a
  dry P5 calculation with no report write.
- Adding `--freeze` writes one immutable validation artifact under
  `outputs/l2_validation/<session>/<identity>/manifest.json`.
- `GET /api/v1/l2/styles/validation` reads only the latest frozen report.
  The GET endpoint never triggers Walk-forward/ablation or an artifact write.
- The existing L2 「领先预测」 page now displays P4 forecasts and P5 frozen
  validation as separate evidence layers: MSE improvement, direction accuracy,
  Rank IC, genuine-forward sessions and qualification status.
- With no frozen P5 report the page shows
  `L2_P5_VALIDATION_REPORT_NOT_FOUND`, not synthetic validation numbers.

Tests cover OOS gates, poor-model rejection, insufficient samples,
genuine-forward timing, default admission lock, explicit admission, immutable
validation-report identity, read-only API behavior and P5 UI rendering. The
actual committed L2 JavaScript has passed an isolated runtime smoke for both
BLOCKED and OOS_VALIDATED states.

**P5 status: engineering implemented, not locally accepted.** No real P5
validation result is claimed until the user's accepted P4 label bundle,
complete pytest, actual OOS/ablation run, forward archive evidence and browser
acceptance are executed locally.

Local acceptance: [L2 P5 checklist](L2_P5_LOCAL_ACCEPTANCE.md).


## 17. P6 implementation update (2026-11-18)

P6 engineering now defines explicit read-only contracts from L2 into L3/L4
instead of allowing downstream modules to infer style qualification from
displayed observations.

### L2 downstream context

- `workflow/l2_downstream.py` aligns current P4 forecast with the newest
  nonfuture P5 validation report.
- A style×horizon value is exposed as `admitted_relative_return` only when its
  exact P5 qualification is `MODEL_ADMITTED`, OOS and genuine-forward gates
  passed, and model/label-bundle identities match.
- Formal downstream consumption additionally requires the current P4 forecast
  itself to exist as an immutable snapshot frozen after T signal and before
  T+1 entry. Live recomputation alone is never sufficient.
- The frozen snapshot must match the current model output and source/label
  provenance. Mismatch blocks the bridge.
- Read-only API:
  `GET /api/v1/l2/styles/downstream-context?asof=YYYY-MM-DD`.

### L2 -> L3 style binding

- `workflow/l2_l3_binding.py` audits L3 `market_style` rows against exact
  frozen/admitted L2 context.
- Canonical L2 columns use
  `style_l2_<style_id>_h<horizon>`.
- Every numeric `style_*` column must equal the admitted L2 set. Extra
  exploratory style columns, missing admitted units, changed values, late
  availability, non-admitted history or a changing admitted grid fail closed.
- The compact receipt binds P4 forecast identities, P5 validation identities,
  model versions, label-bundle SHA256 values, daily source-snapshot SHA256
  values and exact style values.
- `binding_verified` and `historical_pit_attested` are independent. Current
  evidence may prove identity binding while historical PIT remains false.
- Explicit receipt command:
  `python -m quant_research.workflow.l2_l3_binding --market-style <file> --output <receipt.json>`.

### V4 bundle, preflight and L3 archive

- Managed V4 bundles may include `l2_style_context_receipt`; old bundles
  remain readable but unbound.
- Bundle load performs structural receipt validation.
- V4 preflight re-runs the L2/L3 history binding before model fit and reports
  binding/PIT status.
- Both the L3 OOS study and forward runner independently re-run the binding
  audit.
- L3 forward fitting rechecks the receipt after model work and refuses archive
  writes if it changed during fit.
- The receipt becomes part of the L3 forward `input_contract`, so changing
  L2 qualification/style evidence changes the L3 forecast archive identity.
- L3 archive index exposes `l2_style_binding_verified`,
  `l2_style_historical_pit_attested` and the context-binding digest.

### Daily four-layer integration

- V4 daily `styles` stage now uses the formal L2 downstream context.
  `OOS_VALIDATED` is still RESEARCH_ONLY; only MODEL_ADMITTED context may
  cause the style stage to PASS.
- French factors remain separate descriptive observations and do not alter L2
  qualification.
- `workflow/v4_layer_status.py` provides a unified read-only evidence
  snapshot for L1/L2/L3/L4.
- Read-only API:
  `GET /api/v1/v4/layers?asof=YYYY-MM-DD&horizon=1|3|5`.
- The four-layer snapshot never trains, writes decisions or enables execution.
  It checks no-lookahead artifact selection, L1/L2 qualification, L3 binding,
  L2 historical PIT attestation, L3/L4 freshness and L3/L4 source identity.

### Current evidence boundary

P6 engineering can prove that downstream artifacts are linked to the exact
upstream evidence they claim to use. It cannot create missing historical PIT
proof. In particular, a valid L2→L3 receipt may still carry
`historical_pit_attested=false`, which must remain visible as
`L3_L2_STYLE_HISTORY_NOT_PIT_ATTESTED`.

**P6 status: engineering implemented, not locally accepted.** Full pytest,
actual accepted P4/P5 evidence, genuine forward archives, L2→L3 receipt over
real style history, L3/L4 source alignment and browser/API acceptance remain
local gates.

Local acceptance: [L2 P6 checklist](L2_P6_LOCAL_ACCEPTANCE.md).


## 17. P6.1 causal replay/forward binding update (2026-11-18)

The L2→L3 integration was tightened after identifying two temporal deadlocks in
the original P6 bridge.

### Layered L3 clock

L2 genuine-forward forecasts can only be frozen after the base T-close signal,
so L3 cannot require every upstream style value to have existed at that same
base timestamp. L3 now uses one causal staged cutoff:

```text
l3_signal_time = max(
  base close+delay signal,
  latest registered stock-factor availability,
  L2/market-style availability,
  candidate-metadata availability
)
```

The final cutoff must exist at the actual preflight moment and stay strictly
before T+1 entry. The same rule is used by historical panel assembly, current
preflight and forward inference. The forward archive protocol is versioned
(`v4-forward-layered-signal-v2`) so old timestamp semantics are not silently
reused.

### Historical L2 replay versus current forward evidence

Requiring years of genuine frozen L2 predictions before L3 could train would
make a newly admitted L2 model unusable. The v2 L2→L3 contract therefore
separates two evidence modes:

- `HISTORICAL_PIT_REPLAY`: deterministic causal replay using independently
  PIT-attested L2 feature/label bundles under one fixed P5 admission report;
  used as historical L3 model input and never described as a live frozen
  prediction.
- `CURRENT_FROZEN_FORWARD`: the final current-session row, bound to the
  genuine prospective P4 archive.

The v2 receipt binds the exact P5 admission identity, admission as-of session,
actual admission freeze timestamp, model/bundle/source provenance, exact
style values, context availability and the current-forward session. V1
receipts remain readable for archive compatibility but cannot satisfy the new
P6 readiness requirements.

### Selection-bias boundary

Historical PIT replay may cover the full training history, including dates
before and after the L2 admission report. Independent L3 OOS evaluation,
however, must begin strictly after L2 admission became real. The effective
admission date is the later of the P5 validation as-of session and the New York
calendar date of the immutable report's `frozen_at_utc`.

This lets L3 train on a long, reproducible fixed-model history without using
post-selection periods as an allegedly independent L3 test.

### Immutable operational chain

New explicit helpers:

- `workflow/v4_l2_bind_bundle.py` derives a new immutable V4 bundle; it never
  mutates the source bundle. Unchanged factors/labels/candidate bytes preserve
  their SHA256, while a new L2-bound `market_style.parquet` and v2 receipt are
  added and self-verified.
- `workflow/four_layer_day.py` advances one EOD research day:
  prospective P4 freeze → stop normally while admission is pending → derive
  an L2-bound bundle once admitted → L3 forecast → L4 review → four-layer
  status.
- The source bundle's latest session must exactly match the requested research
  day; stale source bundles are rejected before L3 work.

### P6 current readiness rule

`FOUR_LAYER_RESEARCH_CONTEXT_READY` requires all of the following to agree
for the target session:

- L1 admitted research context;
- current L2 admitted context and current genuine forward P4 row;
- L3 receipt verified with PIT-attested history;
- exact L2 model version, P5 admission identity, label bundle SHA, feature
  bundle SHA and current source snapshot represented in the L3 archive;
- L4 review bound to the exact L3 forecast identity and matching source;
- current-session freshness across layers.

Even this state remains research context only:

```text
decision_eligible=false
execution_eligible=false
real_orders_enabled=false
```

Local execution of the complete pytest suite, real label/feature bundles,
prospective close-to-open snapshots and browser acceptance remain mandatory
before any empirical model-validity claim.
