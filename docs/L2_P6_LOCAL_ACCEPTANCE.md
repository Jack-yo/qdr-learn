# QDR L2 P6 local acceptance — L1/L2/L3/L4 integration contracts

Date: 2026-11-18

P6 does not create a new model. It verifies that each layer consumes only
explicitly qualified upstream evidence and that research artifacts cannot be
silently upgraded to trading eligibility.

## 1. Deterministic regression

Run from the repository root:

```bash
uv run --locked pytest -q \
  tests/test_l2_downstream.py \
  tests/test_l2_l3_binding.py \
  tests/test_l2_p6_v4_style_stage.py \
  tests/test_v4_study_l2_binding_contract.py \
  tests/test_v4_pipeline_preflight.py \
  tests/test_v4_forecast_archive.py \
  tests/test_v4_layer_status.py \
  tests/test_l2_style_api.py

uv run --locked pytest -q
```

P6 acceptance requires the full suite, not only these focused tests.

## 2. L2 downstream context gate

Read-only API:

```text
GET /api/v1/l2/styles/downstream-context?asof=YYYY-MM-DD
```

A numeric L2 value is eligible for L3 context only if all are true:

- current P4 forecast is `RESEARCH_ONLY`;
- the exact P4 style×horizon is `MODEL_ADMITTED` in a frozen P5 report;
- P5 OOS gate passed;
- P5 genuine-forward gate passed;
- model version and label-bundle SHA match P4;
- current P4 forecast is itself frozen;
- that P4 snapshot was frozen after T signal and before T+1 entry;
- frozen and current model output agree;
- all archive identities and hashes verify.

`OOS_VALIDATED` alone is insufficient.

All downstream rows keep:

```text
decision_eligible=false
real_orders_enabled=false
```

## 3. L2 -> L3 history binding

L3 must not consume arbitrary numeric `style_*` columns while claiming they
came from admitted L2.

For a candidate `market_style.parquet`, generate an audited receipt:

```bash
uv run --locked python -m quant_research.workflow.l2_l3_binding \
  --root . \
  --market-style /path/to/market_style.parquet \
  --output /path/to/l2_style_context_receipt.json
```

The audit requires every dated row to map exactly to frozen,
`MODEL_ADMITTED` L2 context. Canonical style columns are:

```text
style_l2_<style_id>_h<horizon>
```

For example:

```text
style_l2_size_h3
style_l2_quality_h3
```

All numeric `style_*` columns must equal the admitted set. An additional
exploratory style column causes the binding audit to fail.

The receipt binds:

- each P4 frozen forecast identity;
- each P5 validation identity;
- model version;
- label-bundle SHA;
- verified historical feature-bundle SHA;
- daily source-snapshot SHA;
- exact style values;
- start/end sessions and row count;
- complete style-column set.

The compact `context_identity_sha256` changes if any of these inputs change.

## 4. Identity binding is not PIT attestation

The receipt has two independent concepts:

```text
binding_verified
historical_pit_attested
```

`binding_verified=true` proves the L3 style input is exactly linked to the
frozen/admitted L2 context.

It does **not** derive PIT status from trading eligibility. The binding audit
must instead verify the dedicated historical feature bundle for every signal
session. When that bundle is independently attested and every bound L2 context
uses it, `historical_pit_attested=true` is permitted while
`historical_decision_eligible` and all execution flags remain false.

A verified identity binding with missing/failed feature-PIT evidence still
produces:

```text
L3_L2_STYLE_HISTORY_NOT_PIT_ATTESTED
```

Do not weaken this blocker merely because the values happen to match.

## 5. Managed V4 bundle contract

For a newly constructed V4 managed input bundle, add the validated receipt
under:

```json
{
  "l2_style_context_receipt": { "...": "..." }
}
```

in its manifest.

Do not mutate an old previously-used bundle in place to make it appear
qualified. Build a new research input identity when binding new evidence.

Old bundles without the receipt remain readable for research, but are
explicitly unbound to formal L2 qualification.

## 6. Preflight and model-fit checks

`preflight_v4_day` must:

- structurally read the bundle;
- re-run the L2/L3 binding audit before any model archive is written;
- expose `l2_style_binding_verified`;
- expose `l2_style_historical_pit_attested`;
- fail on a forged/mismatched receipt.

`run_managed_forward` and the L3 OOS study independently re-run the binding
audit. The receipt is checked again after model fitting so a bundle change
during fit causes:

```text
MODEL_INPUT_CHANGED_DURING_FIT_NO_ARCHIVE_WRITE
```

## 7. L3 forward archive binding

The verified receipt is included inside the V4 forward `input_contract`.
Therefore it participates in L3 forecast identity.

Changing only the L2 context receipt must create a different L3 forecast
archive identity.

`latest_forward_research` exposes separately:

```text
l2_style_binding_verified
l2_style_historical_pit_attested
l2_style_binding_context_sha256
```

Legacy archives remain false/null for these fields.

## 8. V4 daily style stage

The V4 daily `styles` stage now uses the P6 L2 downstream contract.

Expected:

- missing/P4/P5 research only -> `RESEARCH_ONLY`;
- integrity mismatch -> `BLOCKED`;
- exact MODEL_ADMITTED frozen L2 context -> `PASS`.

French factors remain an independent descriptive stream. French availability
must never upgrade or downgrade L2 qualification.

## 9. Four-layer evidence snapshot

Read-only API:

```text
GET /api/v1/v4/layers?horizon=3
GET /api/v1/v4/layers?asof=YYYY-MM-DD&horizon=3
```

It summarizes evidence only and never trains or writes.

The current implementation checks:

- L1 explicit model admission + forecast presence;
- L2 admitted downstream context;
- L3 latest nonfuture forward-research archive;
- L2->L3 style binding receipt;
- L2 style historical PIT attestation;
- receipt coverage through the current signal session;
- receipt model version matches current admitted L2;
- receipt label-bundle SHA matches current admitted L2;
- receipt feature-bundle SHA matches current admitted L2;
- receipt L2 source-snapshot set contains the current L2 source snapshot;
- L4 latest nonfuture risk/research-plan review;
- L3/L4 session freshness;
- L3/L4 source-snapshot consistency.

All top-level execution flags remain false.

## 10. Honest expected blockers today

Until local P4/P5/P6 data acceptance exists, it is valid and expected to see
one or more of:

```text
L1_NOT_MODEL_ADMITTED
L2_NO_MODEL_ADMITTED_STYLE_CONTEXT
L3_FORWARD_RESEARCH_MISSING
L3_L2_STYLE_BINDING_NOT_VERIFIED
L3_L2_STYLE_HISTORY_NOT_PIT_ATTESTED
L3_L2_BINDING_SESSION_MISMATCH
L3_L2_MODEL_VERSION_BINDING_MISMATCH
L3_L2_LABEL_BUNDLE_BINDING_MISMATCH
L3_L2_FEATURE_BUNDLE_BINDING_MISMATCH
L3_L2_SOURCE_BINDING_MISMATCH
L3_SESSION_NOT_CURRENT
L4_RISK_REVIEW_MISSING
L4_SESSION_NOT_CURRENT
L3_L4_SOURCE_SNAPSHOT_MISMATCH
```

Do not turn these into warnings merely to obtain a green status.

## 11. P6 exit condition

P6 engineering is accepted only after:

1. full pytest passes;
2. P4 label bundle is locally accepted;
3. P5 OOS/forward validation is frozen;
4. admitted P4 forecasts are genuinely frozen before next-session entry;
5. an L2->L3 binding receipt passes across the actual L3 style-history rows;
6. V4 preflight re-verifies that receipt;
7. L3 forecast archive preserves it in identity;
8. L4 review uses the matching L3 source snapshot;
9. four-layer API/browser review shows only evidence-supported statuses.

Even when these pass, `complete_four_layer_context=true` is still a research
context state. It does not itself enable paper execution or broker orders.
