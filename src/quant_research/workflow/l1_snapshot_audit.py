"""Audit a real, pre-entry ETF close snapshot without backdating history."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from quant_research.data.close_snapshot import read_snapshot
from quant_research.research.l1_features import add_l1_features
from quant_research.research.l1_observatory import compute_l1_observations
from quant_research.workflow.l1_runtime import feature_coverage_report


def audit_snapshot(root: Path, asof: str, output: Path) -> dict:
    snapshot = read_snapshot(root, asof)
    bars = pd.DataFrame(snapshot['rows'])
    cutoffs = pd.DataFrame([{'date': asof, 'decision_cutoff_utc': snapshot['frozen_at_utc']}])
    base, _ = compute_l1_observations(bars, cutoffs)
    _, audit = add_l1_features(base, bars, cutoffs)
    report = feature_coverage_report(audit)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    report.to_csv(output / 'feature_coverage.csv', index=False)
    result = {'status': 'SINGLE_SESSION_OBSERVATION_ONLY', 'asof_session': asof,
              'source': snapshot['source'], 'feed': snapshot['feed'],
              'source_snapshot_sha256': snapshot['source_snapshot_sha256'],
              'knowledge_cutoff_utc': snapshot['frozen_at_utc'],
              'sessions': 1, 'registered_features': len(report),
              'observed_features': int(report.coverage_ratio.eq(1).sum()),
              'historical_pit_verified': False, 'model_admitted': False,
              'real_orders_enabled': False,
              'notice': 'One session only; rolling features need separate qualified history.'}
    (output / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--asof', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit_snapshot(args.root, args.asof, args.output), ensure_ascii=False))


if __name__ == '__main__':
    main()
