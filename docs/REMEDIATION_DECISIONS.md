# Remediation decisions

This record accompanies the structural remediation work. It makes explicit the
parts of the supplied plan that cannot be applied literally without violating
the repository's current V4 data and research constraints.

## Completed foundation work

- Development caches, AI-assistant logs, local data outputs, archives and IDE
  files are ignored by Git.
- The untracked `qdr-real-data.tar.gz` and the legacy ZIP copy were moved under
  `archive/`; neither is source-controlled.
- Ruff and mypy are locked development dependencies. `scripts/dev.ps1` offers
  test, lint, format and scoped typecheck commands and propagates tool failures.
- The backtest engine has a decomposed `step()` workflow without changing its
  replay semantics. The task runner and verified read models are now application
  services, and the extracted `/api/v1/data/` routes are dispatched through a
  route module while the remaining route groups are retained for staged
  migration.

## Intentionally not applied literally

### Retain `src/quant_research_v1`

`docs/V4_UI_ACCEPTANCE.md` identifies this package as a historical research
archive and explicitly says to retain its algorithms. It is therefore not
deleted merely because the active wheel packages `quant_research`; deleting it
would discard project evidence rather than remove an unused generated artifact.

### No global `mvp` policy bypass

The suggested mode that accepts arbitrary sources conflicts with the repository
REAL_ONLY boundary and the V4 requirement that formal data, probabilities,
backtests and paper positions never use fabricated records. Exploratory work may
use real, current-vintage sources only when it is explicitly labelled
research-only and remains outside formal model qualification. It cannot change
the production policy or enable execution.

### No duplicate Yahoo MVP backtest

The repository already has versioned research, factor and backtest workflows.
Adding a standalone script that calculates an unqualified Sharpe ratio from a
new Yahoo download would create an untracked parallel methodology and could be
mistaken for qualified performance evidence. Improvements must extend the
existing workflows with their data contracts, time separation and artifact
receipts.

## Quality baseline

The newly configured full Ruff rule set currently reports historical violations
outside the remediation scope. The command now reports that failure correctly;
it is not represented as a passing repository-wide lint gate. New and touched
modules are formatted and checked in their focused verification commands.
