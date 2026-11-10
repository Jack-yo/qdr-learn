"""P2 CLI workflow, frozen development window and reproducible research artifacts."""
from datetime import date, datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from quant_research.clock import TradingClock
from quant_research.policy import require_real_source
from quant_research.data.bundle import load_real_bundle
from quant_research.data.store import Warehouse
from quant_research.features.context import make_context
from quant_research.features.engine import compute_features
from quant_research.features.factors import builtin_factors
from quant_research.reports.factors import render_report
from .evaluate import evaluate
from .experiment import load_experiment
from .labels import make_labels


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def execute(args, factors=None):
    require_real_source(args.source)
    experiment = load_experiment(args.experiment)
    if args.horizons != "1,3,5":
        raise ValueError("P2 horizons frozen to 1,3,5")
    start = args.start or str(experiment.start)
    end = args.asof if args.command == "features" else (args.end or str(experiment.validation_end))
    if not end:
        raise ValueError("features requires --asof")
    if not experiment.start <= date.fromisoformat(start) <= date.fromisoformat(end) <= experiment.validation_end or date.fromisoformat(end)>=date(2025,1,1):
        raise ValueError("P2 window must remain inside frozen development period; final test from 2025 is sealed")
    clock = TradingClock()
    if args.command == "features":
        clock.signal(end)  # reject weekends/future/unclosed dates before loading data
    now,run_id = datetime.now(timezone.utc),str(uuid4())
    destination = args.output/run_id
    registry = list(builtin_factors() if factors is None else factors)
    bundle=load_real_bundle(args.db,args.source,end,now,start=start)
    bundle.require('exploratory_price_factors')
    prices=bundle.prices
    with Warehouse(args.db) as store:
        context = make_context(prices,clock,experiment.benchmark,start,end)
        features = compute_features(context,clock,registry,args.mode,experiment.exclude_symbols)
        if args.command == "features":
            features = features.loc[features.date.eq(pd.Timestamp(end))].copy()
        basis = prices.adjustment_basis.iloc[0]
        destination.mkdir(parents=True,exist_ok=False)
        config = {"experiment":experiment.model_dump(mode="json"),"source":args.source,"mode":args.mode,"start":start,"end":end,
                  "factors":[{"name":f.name,"version":f.version,"lookback":f.lookback,"dependency":f.dependency,
                              "definition":getattr(f,"definition", "custom plugin")} for f in registry]}
        data_hash = hashlib.sha256(prices.sort_values(["date","security_id"]).to_json(orient="records",date_format="iso").encode()).hexdigest()
        root = Path(__file__).resolve().parents[1]
        code_hash = hashlib.sha256(b"".join(p.relative_to(root).as_posix().encode()+p.read_bytes() for p in sorted(root.rglob("*.py")))).hexdigest()
        manifest = {"run_id":run_id,"stage":"P2","created_at_utc":now.isoformat(),"asof_timestamp_utc":now.isoformat(),
            "data_cutoff_utc":now.isoformat(),"universe_version":"synthetic-etf-proxy-v1" if args.source=="fixture" else "current-etf-proxy-list-not-pit-v1",
            "model_version":"none-p2","config_sha256":digest(config),"data_sha256":data_hash,"code_sha256":code_hash,
            "source":args.source,"mode":args.mode,"adjustment_basis":basis,"experiment":experiment.model_dump(mode="json"),
            "input_rows":len(prices),"input_first_date":str(pd.Timestamp(prices.date.min()).date()),"input_last_date":str(pd.Timestamp(prices.date.max()).date()),
            "feature_rows":len(features),"feature_nonnull":int(features.value.notna().sum()),
            "decision_eligible_features":int(features.decision_eligible.sum()),"target_securities":int(features.security_id.nunique()),
            "sealed_test_start":"2025-01-01","sealed_test_used":False,"research_grade":False,"performance":None,
            "flags":["SYNTHETIC" if args.source=="fixture" else "EXPLORATORY","ETF_PROXY_NOT_EQUITY_ALPHA","DATA_INCOMPLETE","NOT_READY"]+
                    (["SURVIVORSHIP_BIASED","NOT_RAW_EXECUTION_PRICE","CURRENT_VINTAGE_NOT_HISTORICAL_PIT"] if args.source=="yahoo" else []),
            "runtime_versions":{name:importlib.metadata.version(name) for name in ["pandas","numpy","duckdb","pyarrow"]}}
        features["run_id"] = run_id
        store.insert_frame("features_daily",features)
        features.to_parquet(destination/"features.parquet",index=False)
        if args.command == "factor-report":
            labels = make_labels(context,clock,experiment.horizons,basis,experiment.exclude_symbols)
            results = evaluate(features,labels,context,experiment)
            labels["run_id"] = run_id
            store.insert_frame("labels",labels)
            labels.to_parquet(destination/"labels.parquet",index=False)
            statistics = results["summary"].to_json(orient="records",double_precision=15)
            manifest["statistics_sha256"] = hashlib.sha256(statistics.encode()).hexdigest()
            manifest["label_rows"] = len(labels)
            manifest["formal_raw_label_count"] = int(labels.forward_return.notna().sum())
            manifest["proxy_label_count"] = int(labels.proxy_forward_return.notna().sum())
            for key,frame in results.items():
                frame.to_parquet(destination/(key+".parquet"),index=False)
                if key not in ("daily_ic","daily_groups"):
                    frame.to_csv(destination/(key+".csv"),index=False)
            manifest["status"] = "ENGINEERING_ONLY" if args.source=="fixture" else "RETROSPECTIVE_EXPLORATORY_ONLY"
            if not features.value.notna().any():
                manifest["status"] = "NO_ASOF_ELIGIBLE_FEATURES"
            render_report(destination,manifest,results)
        else:
            manifest["status"] = "FEATURES_COMPUTED" if features.value.notna().any() else "NO_ASOF_ELIGIBLE_FEATURES"
        (destination/"config.json").write_text(json.dumps(config,indent=2,ensure_ascii=False),encoding="utf-8")
        (destination/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False,allow_nan=False),encoding="utf-8")
        (destination/"run.log").write_text(f"{now.isoformat()} run_id={run_id} status={manifest['status']}\n",encoding="utf-8")
        store.insert_rows("runs",[{**{k:manifest[k] for k in ["run_id","created_at_utc","asof_timestamp_utc","data_cutoff_utc","universe_version",
            "model_version","config_sha256","data_sha256","status"]},"manifest_json":json.dumps(manifest)}])
    print(json.dumps({"run_id":run_id,"status":manifest["status"],"output":str(destination.resolve())}),flush=True)
    return 4 if manifest["status"]=="NO_ASOF_ELIGIBLE_FEATURES" else 0
