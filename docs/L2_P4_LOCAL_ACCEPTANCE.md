# QDR L2 P4 local acceptance — H1/H3/H5 style-leading research

Date: 2026-11-18  
Scope: P4 label construction, immutable label bundle, 21 Ridge research units,
three baselines, source-gated API/UI, OOS research utilities and write-once
forecast snapshots.

**This is an execution checklist, not a claim that the user's local data has
passed. P4 remains RESEARCH_ONLY even after the code tests pass.**

## 1. Deterministic regression

Run from the repo root:

```bash
uv run --locked pytest -q \
  tests/test_l2_labels.py \
  tests/test_l2_label_bundle.py \
  tests/test_l2_forecast.py \
  tests/test_l2_forecast_workflow.py \
  tests/test_l2_forecast_archive.py \
  tests/test_l2_forecast_freeze.py \
  tests/test_l2_style_api.py \
  tests/test_l2_cockpit.py

uv run --locked pytest -q
```

Node.js must be installed so the L2 cockpit runtime fixture and syntax check
execute instead of skipping.

## 2. Confirm fail-closed default

The committed `configs/l2_forecast.yaml` intentionally has
`label_bundle_id: null`.

Start the local console and request:

```text
GET /api/v1/l2/styles/forecast
```

Expected:

- HTTP 200 research response, status `BLOCKED`.
- code `L2_VERIFIED_LABEL_BUNDLE_REQUIRED`.
- zero eligible forecasts.
- no output archive is written.
- `/studio#style` → 「领先预测」 renders the blocker inline without
  replacing the P1/P2 observation page or displaying any probability.

## 3. Label-source gate

Do not build P4 labels from the P1 Yahoo split-adjusted/current-vintage history.

The label builder accepts only:

```text
VERIFIED_ACTION_CONSISTENT_TRADE_RETURN_BASIS
```

and explicit per-session action evidence.

For sample dates independently recompute:

```text
signal: T close + protocol delay
entry:  T+1 open
exit:   T+H close, H ∈ {1,3,5}

style target =
(1 + style-leg trade return) / (1 + benchmark-leg trade return) - 1
```

For the cyclical/defensive style, verify fixed entry equal weights for
XLI/XLY/XLB/XLF versus XLP/XLU/XLV. Any missing entry open, exit close,
source availability, or action evidence must return a blocked/null label.

## 4. Immutable small label bundle

Freeze only derived labels and source evidence hashes under
`data/managed/l2_style_labels/<bundle_id>/`. This is not a duplicate price
warehouse.

Verify:

- `labels.parquet` SHA256 equals the manifest.
- seven style IDs and H1/H3/H5 are all present.
- source evidence SHA256 refers to the independently reviewed price/action
  evidence used to construct labels.
- rewriting the same bundle ID is rejected.
- corrupting `labels.parquet` blocks load.
- `historical_pit_attested` stays false; the label bundle by itself does not
  admit a forecasting model.

Only after this local review, set `label_bundle_id` in
`configs/l2_forecast.yaml` to the accepted immutable bundle.

## 5. Forecast chronology and 21-unit contract

For one completed session, `GET /api/v1/l2/styles/forecast` must return
exactly seven styles × three horizons when a bundle is configured. Every unit
must be either `RESEARCH_ONLY` or `BLOCKED`; no unit disappears.

Independently verify:

- current feature availability ≤ the exact signal timestamp;
- training observation availability ≤ each historical signal timestamp;
- training label availability ≤ current/historical model-fit signal;
- label exit ≤ the embargo cutoff;
- embargo is at least five sessions;
- all scaling and Ridge fitting use the training sample only;
- future observation/label mutations do not change an earlier forecast.

Features currently include 5/20/60 relative returns, five-day acceleration,
relative up-day count, relative volatility/drawdown, cross-style 20-day
dispersion and explicit four-quadrant indicators.

## 6. Baselines and P4 interpretation

Each style/horizon must expose:

- Ridge predicted relative return;
- Zero baseline;
- expanding historical mean baseline;
- five-day momentum extrapolation baseline;
- training-session count and training boundaries;
- exact feature values and standardized Ridge coefficients.

These are **relative-return research estimates**, not:

- absolute ETF return forecasts;
- calibrated probabilities;
- claimed win rates;
- position sizes;
- trading recommendations.

Use `walk_forward_oos_v1` and `score_oos_v1` to compare model MSE against
all three baselines. P4 does not grant admission even if one backtest metric is
positive.

## 7. Explicit forward freeze

The GET endpoint must never write a prediction archive.

Only the explicit command may freeze:

```bash
uv run --locked python -m quant_research.workflow.l2_forecast_freeze --date YYYY-MM-DD
```

Expected behavior:

- if P4 is BLOCKED: `BLOCKED_NO_ARCHIVE_WRITE`, no manifest created;
- if P4 has eligible research predictions: one immutable
  `outputs/l2_style_forecasts/<date>/<model-version>/manifest.json`;
- same exact identity is idempotent;
- a different prediction for the same session/model version is rejected;
- snapshot contains the exact 7×3 grid, source snapshot hash, label bundle
  hash, model/config and no execution eligibility.

## 8. Browser acceptance

At 1440 / 1024 / 375 widths:

- P1/P2 default page does not call the P4 endpoint.
- opening 「领先预测」 lazily requests P4.
- BLOCKED shows evidence reason, not zero returns.
- RESEARCH_ONLY shows H1/H3/H5 values and three-baseline detail for selected
  style.
- historical date control is passed to P4.
- no probability/胜率 copy appears.
- no whole-page white screen on a P4 4xx/5xx response.

## 9. Release boundary

P4 can be called **engineering complete** after deterministic tests and the
local data/browser checks pass, but model usefulness still belongs to P5.

Do not set `MODEL_ADMITTED`, `historical_decision_eligible=true` or enable
orders. P5 must supply adequate walk-forward OOS sample size, baseline
improvement, stability/ablation, immutable forward outcomes and any separately
defined probability target/calibration evidence.
