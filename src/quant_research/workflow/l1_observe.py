"""Research-only L1 observation CLI; independent of the four-layer live runner.

Example:
 python -m quant_research.workflow.l1_observe --bars BARS.csv \
   --cutoffs CLOCK.csv --universe PIT_UNIVERSE.csv --output outputs/l1/attempt-001
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from quant_research.research.l1_observatory import (
    DOMAINS, compute_l1_observations, scan_l1_anomalies,
)


def _read(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f'L1 input missing: {path}')
    if path.suffix.lower() == '.csv':
        return pd.read_csv(path)
    if path.suffix.lower() == '.parquet':
        return pd.read_parquet(path)
    raise ValueError('L1 inputs must be CSV or Parquet')


def run(*, bars: Path, cutoffs: Path, output: Path,
        universe: Path | None = None, benchmark: str = 'SPY') -> dict:
    """Compute and archive observations; never grant PIT or forecast eligibility."""
    source_paths = {'bars': Path(bars), 'cutoffs': Path(cutoffs)}
    if universe is not None:
        source_paths['universe'] = Path(universe)
    frames = {name: _read(path) for name, path in source_paths.items()}
    observations, coverage = compute_l1_observations(
        frames['bars'], frames['cutoffs'], frames.get('universe'), benchmark=benchmark)
    anomalies = scan_l1_anomalies(observations)
    dest = Path(output)
    if dest.exists():
        raise FileExistsError('L1 observation output already exists; never overwrite an archive')
    dest.mkdir(parents=True, exist_ok=False)
    results = {'observations.csv': observations, 'coverage.csv': coverage,
               'anomalies.csv': anomalies}
    digests = {}
    for name, frame in results.items():
        target = dest / name
        frame.to_csv(target, index=False, date_format='%Y-%m-%dT%H:%M:%S%z')
        digests[name] = sha256(target.read_bytes()).hexdigest()
    manifest = {
        'kind': 'L1_RESEARCH_OBSERVATIONS_ONLY',
        'schema_version': 1,
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'benchmark': benchmark,
        'rows': int(len(observations)),
        'anomaly_rows': int(len(anomalies)),
        'registered_domains': [d.key for d in DOMAINS],
        'actual_computed_domains': ['price', 'volatility', 'breadth', 'cross_asset', 'path'],
        'inputs_sha256': {name: sha256(path.read_bytes()).hexdigest()
                          for name, path in source_paths.items()},
        'outputs_sha256': digests,
        'source_independently_attested': False,
        'historical_pit_verified': False,
        'forecast_eligible': False,
        'trade_eligible': False,
        'notes': 'Raw input digests prove byte identity, not historical PIT or vendor authenticity.',
    }
    (dest / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False,
        indent=2, sort_keys=True), encoding='utf-8')
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='QDR L1 observation-only computation')
    parser.add_argument('--bars', type=Path, required=True)
    parser.add_argument('--cutoffs', type=Path, required=True)
    parser.add_argument('--universe', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--benchmark', default='SPY')
    args = parser.parse_args(argv)
    result = run(bars=args.bars, cutoffs=args.cutoffs, universe=args.universe,
                 output=args.output, benchmark=args.benchmark)
    print(json.dumps({'status': result['kind'], 'rows': result['rows'],
                      'anomaly_rows': result['anomaly_rows'],
                      'forecast_eligible': False}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
