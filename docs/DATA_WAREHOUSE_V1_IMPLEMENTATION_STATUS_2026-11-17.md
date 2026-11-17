# QDR V4 Data Warehouse V1 — Implementation Status

Date: 2026-11-17
Branch: `codex/warehouse-v1-2026-11-17`
Base: current `main` at implementation start
Status: implementation submitted for review; tests not executed in this remote editing session.

## Implemented in this branch

- Added a read-only warehouse observability service.
- Inventory includes the 11 L1 logical tables, the existing six fixed database assets, and four explicitly unavailable dependencies.
- Exposes all 21 L1 source registry entries even before an L1 database exists.
- Keeps registry/code status separate from latest recorded source-health status.
- Reads DuckDB using `read_only=True`; does not instantiate `L1MarketStore`, run DDL, create missing databases, or call providers.
- Blocks reads while the existing data-maintenance lock is present.
- Adds allowlisted overview, dataset detail, preview, and L1 run-history GET endpoints.
- Adds source-filtered preview for primary Alpaca SIP/raw prices and KEN_FRENCH attribution-only factors; other legacy assets explicitly report preview unsupported.
- Adds V4 navigation and a responsive Data Warehouse page with search, category/status filters, table-level record counts, distinct business counts where defined, observation/availability/fetch/ingestion timestamps, source registry/run states, data preview, schema view, and use restrictions.
- Separates reference-series history from live feature coverage and path outcomes from model inputs.
- Redacts arbitrary source metadata and run-log error detail from API responses.

## Explicit limitations

- This first delivery does not add new provider ingestion, retry, backfill, database writes, or eligibility changes.
- Non-L1 legacy databases are inventoried using existing fixed read-only inspection, but only the primary SIP/raw price and classic-factor tables have sample-preview support so far.
- Maintenance history currently reads the L1 run-log table; existing maintenance manifest history outside that table is not yet unified.
- Field null rates, schema drift, detailed lineage graph, and receipt-object hash audit history are deferred to P1.
- No live source-health status is inferred when no observation exists.

## Regression tests added

- Missing database GET does not create data directories or files.
- All 21 sources appear as NOT_OBSERVED before first L1 run.
- Registry status and real run-health status remain separate.
- Existing catalog assets and unsupported-preview states are explicit.
- L1 table details distinguish physical rows, unique rows, and symbols.
- Read-only sample preview is paginated and filter-validated.
- Primary market price preview is fixed to ALPACA/SIP/raw.
- Maintenance lock blocks reads.
- Run-history output is bounded and redacted.
- HTTP routes and static UI assets are registered and JSON-serializable.

## Local validation still required

Run from the repository root:

```powershell
uv run --locked --all-groups --env-file .env -- python -m pytest -q \
  tests/test_warehouse_observability.py tests/test_web.py --tb=short
node --check src/quant_research/assets/v4_ui_warehouse.js
node --check src/quant_research/assets/v4_ui_core.js
git diff --check
```

Also open V4 locally and verify the Data Warehouse navigation, asset filtering, source-state distinction, detail tabs, and actual preview data against the local DuckDB. This UI has not been browser-accepted in this session.

No model thresholds, prediction probabilities, PIT qualification, forecast eligibility, or trading eligibility were changed.
