# QDR L2 — Style Rotation & Factor Research
## P0 implementation baseline and research protocol

**Status:** P0 audit complete; protocol baseline proposed for implementation.  
**Scope:** L2 only. No data ingestion, warehouse, provider setup, local cache maintenance, model execution, or UI implementation in P0.  
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

Cyclical and defensive basket membership is versioned and frozen. Initial weights are equal-weight within each basket, reset on a common, explicit schedule. The spread is cyclical basket return minus defensive basket return. If any required component is missing for a session, the composite for that session is null; no weight redistribution, forward-fill, or fabricated observation is allowed.

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

Implemented in the initial P1 increment:

- `GET /api/v1/l2/styles/overview?asof=&cutoff=&start=` — read-only observation payload using the existing verified Yahoo split-adjusted bundle. It returns the registry, latest seven style rows, 126-session history per style, per-symbol coverage, source snapshot hash, and explicit observation-only limitations.

Still proposed, not implemented:

- `GET /api/v1/l2/styles/history?style_id=&start=&end=`
- `GET /api/v1/l2/styles/rotation?asof=`
- `GET /api/v1/l2/styles/forecast?style_id=&horizon=&asof=`
- `GET /api/v1/l2/styles/drivers?style_id=&asof=`
- `GET /api/v1/l2/styles/validation?style_id=&horizon=&model_version=`
- `GET /api/v1/l2/styles/replay?asof=`
- `GET /api/v1/l2/french/monitor?asof=&cutoff=`
- `GET /api/v1/l2/research/ablation?experiment_id=`

Every payload must expose schema/version, as-of session, signal cutoff, per-source availability, source snapshot hash, calculation protocol version, missingness/coverage, research status, and eligibility. A missing value is null with a reason, never zero.

## 10. P1 implementation progress

- Added `research/l2_style_rotation.py`: seven-style registry and causal calculations for 5/20/60-session relative return, acceleration, relative up-day count, volatility, and 20/60-session relative drawdown.
- Added `workflow/l2_styles.py`: read-only adapter over the existing verified market bundle; no provider requests, ingestion, or warehouse mutation. V1 currently requires Yahoo split-adjusted price basis and reports the current-vintage/non-total-return limitation.
- Added `GET /api/v1/l2/styles/overview`.
- Added focused unit tests for registry, windows, missing basket components, causal-prefix stability, availability propagation, source basis, and API query validation. These tests have been authored but not executed in the local Codex environment yet.
- Real local symbol coverage and pytest acceptance remain pending. The API is not yet the final L2 UI and has no forecast or rotation-state engine.

## 11. Out of scope

- No new data warehouse or parallel history store.
- No paid data subscription or provider onboarding by this implementation.
- No rewriting L1 data management or L1 model logic.
- No stock-level Alpha selection, portfolio sizing, broker integration, or order execution.
- No claims of profitability or trading readiness from descriptive monitoring.
