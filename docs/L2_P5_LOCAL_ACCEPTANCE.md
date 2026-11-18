# QDR L2 P5 local acceptance — OOS, ablation and forward qualification

Date: 2026-11-18

Scope: P5 validation for the L2 continuous relative-return model. This phase
evaluates whether the P4 Ridge model adds stable out-of-sample value versus
three frozen baselines and whether genuine forward-frozen predictions confirm
that result.

**P5 does not create a probability target.** Probability calibration is
`NOT_APPLICABLE_CONTINUOUS_RETURN_ONLY` until a separately defined
classification target is researched and validated.

## 1. Prerequisites

P4 must already have:

- an accepted immutable L2 verified-label bundle;
- `configs/l2_forecast.yaml` pointing to that bundle;
- action-consistent T+1-open → T+H-close labels for H1/H3/H5;
- no use of current-vintage Yahoo history as a verified forward label source.

Without the bundle, P5 must return
`L2_VERIFIED_LABEL_BUNDLE_REQUIRED` and write no validation artifact.

## 2. Frozen P5 protocol

The committed `configs/l2_validation.yaml` is the predeclared gate.

Current defaults:

```yaml
oos_evaluation_sessions: 252
min_oos_sessions: 126
min_relative_mse_gain_vs_best_baseline: 0.02
min_directional_accuracy: 0.52
min_rank_ic: 0.05
min_positive_subperiod_fraction: 0.67
min_subperiods: 3
max_subperiod_relative_mse_loss: 0.10
min_forward_frozen_sessions_for_admission: 60
min_forward_relative_mse_gain_vs_best_baseline: 0.0
min_forward_directional_accuracy: 0.50
require_all_baselines_beaten: true
model_admission_enabled: false
```

Do not change these thresholds after inspecting P5 results without creating a
new protocol/model version and clearly treating the change as a new research
hypothesis.

## 3. Deterministic regression

Run:

```bash
uv run --locked pytest -q \
  tests/test_l2_validation.py \
  tests/test_l2_validation_archive.py \
  tests/test_l2_validation_workflow.py \
  tests/test_l2_style_api.py \
  tests/test_l2_cockpit.py

uv run --locked pytest -q
```

The L2 cockpit Node runtime test must not be skipped in the final acceptance
environment.

## 4. Explicit P5 run

Dry-run calculation, no artifact write:

```bash
uv run --locked python -m quant_research.workflow.l2_validation \
  --date YYYY-MM-DD
```

Freeze the exact validation evidence only after inspecting the dry-run:

```bash
uv run --locked python -m quant_research.workflow.l2_validation \
  --date YYYY-MM-DD --freeze
```

The GET API must never invoke this calculation.

## 5. Same-date ablation

P5 runs four predeclared nested feature sets on the same OOS evaluation dates:

1. `returns_only`
2. `returns_dynamics`
3. `returns_dynamics_risk`
4. `full`

The `full` variant is the production P4 research feature set and is reused
from the same ablation pass; it must not be fitted twice merely to produce the
validation report.

Inspect whether added feature groups improve or degrade OOS error. Do not keep
a more complex feature group merely because its in-sample coefficients look
plausible.

## 6. Per-unit OOS gate

There are always exactly 21 style×horizon qualification units.

Each unit must either remain `RESEARCH_ONLY` or become
`OOS_VALIDATED`. A unit cannot disappear because of missing evidence.

For `OOS_VALIDATED`, verify:

- at least 126 scorable OOS sessions;
- Ridge MSE beats Zero, expanding mean and 5D momentum baselines;
- at least 2% MSE improvement versus the best of those baselines;
- directional accuracy at least 52%;
- horizon-level cross-style Rank IC at least 0.05 where valid;
- at least three chronological subperiods;
- at least 67% of subperiods improve on the local best baseline;
- worst subperiod relative MSE loss is not worse than -10%.

These thresholds are research gates, not guarantees of future profit.

## 7. Genuine-forward evidence

Historical/replayed predictions are not forward evidence.

Only a P4 frozen snapshot satisfying:

```text
signal_time <= frozen_at_utc < T+1 entry_time
```

may count as genuine forward evidence. The realized label must also become
available no earlier than its H1/H3/H5 exit.

P5 must exclude:

- snapshots frozen after T+1 entry;
- retrospectively reconstructed old signals;
- corrupt/mismatched archive identities;
- outcomes without verified post-exit availability.

For admission evidence, the default gate requires at least 60 genuine-forward
sessions for the exact style+horizon unit, nonnegative MSE improvement versus
the best baseline, and at least 50% direction accuracy.

## 8. Admission safety switch

`model_admission_enabled: false` is committed intentionally.

Therefore a model that passes OOS and forward evidence still remains
`OOS_VALIDATED` with reason `MODEL_ADMISSION_SWITCH_DISABLED`.

Do not enable this switch until the local acceptance report has been reviewed.
If later enabled, admission remains scoped to exact:

```text
style_id × horizon × model_version × validation protocol
```

and still keeps:

```text
decision_eligible=false
real_orders_enabled=false
```

L2 admission does not authorize a portfolio allocation or broker order.

## 9. Frozen validation report and API

The explicit freeze writes an immutable report beneath:

```text
outputs/l2_validation/<asof-session>/<identity>/manifest.json
```

The identity binds the report contents. Tampering must fail verification.

Read-only API:

```text
GET /api/v1/l2/styles/validation
GET /api/v1/l2/styles/validation?asof=YYYY-MM-DD
```

If no frozen report exists, expected response is:

```text
BLOCKED / L2_P5_VALIDATION_REPORT_NOT_FOUND
```

The API must not trigger Walk-forward, ablation or artifact writes.

## 10. Browser acceptance

In `/studio#style` → 「领先预测」:

- P4 current forecast and P5 validation are visually separate;
- P4 and P5 are loaded only after entering the forecast tab;
- P5 shows OOS status for the selected style's H1/H3/H5;
- display MSE improvement vs best baseline, direction accuracy, Rank IC and
  genuine-forward session count;
- show total OOS-validated, forward-evidenced and MODEL_ADMITTED units;
- with no report, show an inline blocker;
- no probability, win-rate or implied trading-ready language;
- P5 errors must not white-screen P1/P2.

## 11. P5 exit condition

P5 engineering is complete only after the deterministic suite, actual local
label bundle, OOS run, ablation inspection, frozen report, genuine-forward
archive audit and browser checks pass.

A successful P5 report still does not establish profitability. P6 may consume
only the explicit qualification state; it must not reinterpret a
`RESEARCH_ONLY` unit as an admitted style signal.
