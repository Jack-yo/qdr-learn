"""Read-only CLI for a modeled cash-constrained V4 research scenario."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from quant_research.workflow.v4_cash_scenario import replay_research_cash_book


def main(argv=None):
    parser=argparse.ArgumentParser(description="Research cash replay, not a paper broker ledger")
    parser.add_argument("--root",type=Path,default=Path.cwd())
    parser.add_argument("--initial-cash",type=float,required=True)
    parser.add_argument("--plan",action="append",required=True,
                        help="Repeat as YYYY-MM-DD:16-character-plan-id")
    args=parser.parse_args(argv)
    keys=[]
    for value in args.plan:
        parts=value.split(":")
        if len(parts)!=2:
            parser.error("Each --plan must be YYYY-MM-DD:PLAN_ID")
        keys.append(tuple(parts))
    output=replay_research_cash_book(args.root,keys,initial_cash=args.initial_cash)
    print(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
