# QDR L2 P1–P3 local acceptance — 2026-11-18

Scope: the `codex/l2-style-rotation-build-2026-11-18` branch, seven ETF proxy styles,
four-state rotation engine and the actual `/studio#style` cockpit.

**Acceptance is not established by committed tests alone.** This document is an
execution checklist; it does not claim these commands were run locally.

## 1. Run regression and HTTP contract checks

From the repo root with the lockfile and test dependencies installed:

```bash
uv run --locked pytest -q tests/test_l2_style_rotation.py tests/test_l2_style_workflow.py tests/test_l2_style_api.py tests/test_l2_rotation.py tests/test_l2_cockpit.py
uv run --locked pytest -q tests/test_v4_ui_shell.py tests/test_v4_light_theme.py
uv run --locked pytest -q
```

Run the `node` tests with Node.js installed. Document the exact Python, Pandas,
NumPy, Node and package versions, full command, exit code and failures.

## 2. Test actual existing warehouse; no writes

The source is the existing `data/research.duckdb` Yahoo split-adjusted bundle.
Do **not** import, backfill, sync or mutate source data as part of L2 acceptance.

```bash
uv run --locked python -m quant_research.web --port 8765
```

On the local machine, inspect in a browser:

- `http://127.0.0.1:8765/studio#style`
- `http://127.0.0.1:8765/api/v1/l2/styles/overview?rotation=1`
- `http://127.0.0.1:8765/api/v1/l2/styles/rotation`
- `http://127.0.0.1:8765/api/v1/l2/styles/overview?rotation=1&asof=YYYY-MM-DD`

Verify that both APIs expose the **same** session, source snapshot SHA-256,
cutoff, registry version and source basis. Expected registry: seven styles and
14 named ETF symbols; count and record all blocked/partial styles, rather
than asserting all values are present.

## 3. Validate calculation and chronology

- Compare a sample `IWM/SPY` and `IWD/IWF` 5/20/60-session compound ratio
  against aligned original close prices. Check the **previous** close needed
  for each first daily return in a window.
- Independently check the equal-weight cyclical `XLI/XLY/XLB/XLF` versus
  defensive `XLP/XLU/XLV` basket and its return reset convention.
- Delete one source row only in **isolated test fixtures**, not in real DuckDB.
  Verify no forward fill, zero fill, hidden substitute or silent basket
  reweighting occurs. A missing component blocks that style window.
- Verify 20-session relative-return sign and 5-session acceleration sign
  map to all four descriptive states; a zero/missing or post-cutoff source
  yields UNKNOWN and breaks the streak.
- Test historical replay on at least two market sessions with different
  style status. It must not relabel today's revised data as historical PIT.

## 4. Browser behavior, light theme and error boundaries

- Desktop 1440px, narrow desktop 1024px and mobile 375px: inspect overflow,
  focus, tab selection, date control, blocked states and chart labels.
- Default `/studio#style` should present one L2 workspace: four KPI tiles,
  seven-style table, actual quadrant positions, style detail and honest
  forecast eligibility empty state.
- Select an ETF style; check trend, source pair and state details update.
- Switch tabs: 总览 / 轮动与转折 / 计算证据 / French 因子.
- Select a historical trading date, refresh and return to latest. Confirm
  the date is sent to the backend, and content never uses fabricated values.
- Simulate backend 503 and partial 14-symbol coverage. Verify inline blocked
  states and that the whole application does not white-screen.
- Check developer console for JS errors, including progressive re-renders.
- Verify no P3 code writes DuckDB, creates orders, or emits H1/H3/H5 probabilities.

## 5. Release gate

**BLOCK MERGE** if regressions fail, all seven styles are not individually
reported, symbols are silently substituted, state transitions bridge missing
data, dates are inconsistent, the light UI fails to render, or historical
current-vintage prices are described as PIT-certified.

Even if P1–P3 acceptance passes, keep
`historical_decision_eligible=false`, `real_orders_enabled=false` and
`OBSERVATION_ONLY`. P4/P5 requires separately verified company-action-
consistent T+1-open-to-T+H-close labels, embargoed walk-forward validation
and frozen OOS/calibration evidence; no shortcut from this visual acceptance.

Attach a date-stamped execution report: local environment, test output,
HTML/API snapshots, observed source hash, blocked inputs, browser screenshots,
issues requiring repair and go/no-go recommendation.
