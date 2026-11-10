import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_research.clock import TradingClock
from quant_research.data.bundle import load_real_bundle
from quant_research.features.context import make_context
from quant_research.features.states import frozen_states, observations
from quant_research.models.dataset import prepare_market
from quant_research.models.settings import load_settings
from quant_research.models.walk_forward import evaluate_predictions, evaluate_downside, train_market
from quant_research.policy import PolicyError
from quant_research.research.increment import probability_increment
from .common import finish, line_svg, new_run, report, save_frame


def execute(args):
    config = load_settings(args.experiment)
    end = args.asof or str(config.validation_end)
    if pd.Timestamp(end) > pd.Timestamp(config.validation_end):
        raise ValueError("Historical market study cannot open sealed final period")
    if (Path.cwd() / "data/catalog/.maintenance.lock").is_file():
        raise PolicyError("DATA_MAINTENANCE_RUNNING", "Data maintenance is running")
    clock = TradingClock()
    day = clock.session(end)
    training = args.command == "train-market"
    if training and day <= pd.Timestamp(config.train_end):
        raise PolicyError("NO_VALIDATION_SESSIONS", "Market study cutoff must be in the validation period")
    bundle = load_real_bundle(args.db, args.source, end, start=str(config.start),symbols=args.symbols.split(',') if getattr(args,'symbols',None) else None)
    if training and args.mode == "strict":
        bundle.require("historical_model")
    bundle.require("exploratory_price_factors")
    bundle.require("observation")
    prices = bundle.prices
    context = make_context(prices, clock, "SPY", str(config.start), end)
    output,manifest = new_run(args,config,"P3",prices)
    manifest.update(
        workflow=args.command, asof_date_et=str(day.date()),
        data_cutoff_utc=bundle.metadata["knowledge_cutoff_utc"],
        source_provenance=bundle.metadata["source_provenance"],
        source_snapshot_sha256=bundle.metadata["snapshot_sha256"],
        adjustment_basis=prices.adjustment_basis.iloc[0],
        symbols=bundle.metadata["symbols"], execution_ready=False,
        historical_decision_eligible=False,
    )
    observed = observations(context)
    threshold_end = min(pd.Timestamp(config.train_end), day)
    states,thresholds = frozen_states(observed,threshold_end,config.state_threshold_quantile)
    # Thresholds fitted over the training segment are unavailable on its earlier dates.
    before_threshold = states.index <= threshold_end
    states.loc[before_threshold, [name for name in states if name.endswith("_state")]] = "UNKNOWN"
    signals = pd.Series([clock.signal(d) for d in states.index],index=states.index)
    states["decision_eligible"] = states.state_available_at.le(signals)&states.market_return_20.notna()&states.market_vol_20.notna()&(args.mode=="strict")
    if args.mode=="strict":
        states.loc[~states.decision_eligible,[c for c in states if c.endswith("_state")]] = "UNKNOWN"
        states.loc[~states.decision_eligible,[c for c in states if c.startswith(("market_","style_")) and not c.endswith("_state")]]=np.nan
    if args.asof and not training:
        states = states.loc[[day]]
    save_frame(states.reset_index(),output,"market_style_states")
    market_predictions,metrics,calibration,folds,downside_metrics = pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),pd.DataFrame()
    if training:
        frame = prepare_market(context, observed, clock, config.horizons, manifest["adjustment_basis"])
        frame = frame.dropna(subset=["benchmark_target"])
        market_predictions,folds = train_market(frame,observed,clock,config,args.mode)
        if len(market_predictions):
            metrics,calibration = evaluate_predictions(market_predictions,["horizon"])
            downside_metrics=evaluate_downside(market_predictions,config.downside_threshold)
            market_predictions["label_kind"] = "EXPLORATORY_SPY_PRICE_PROXY"
        for name,data in [("market_predictions",market_predictions),("market_metrics",metrics),("calibration",calibration),("training_folds",folds)]:
            save_frame(data,output,name)
        save_frame(downside_metrics,output,"downside_metrics")
    increment=probability_increment(market_predictions,config.seed)
    save_frame(increment,output,"paired_probability_increment")
    charts = [line_svg(states.market_return_20,"SPY 过去 20 日价格收益"),line_svg(states.market_vol_20,"SPY 20 日实现波动率（年化）")]
    manifest.update(status="DESCRIPTIVE_CURRENT_VINTAGE_ONLY",
        thresholds=thresholds,state_rows=len(states),eligible_state_rows=int(states.decision_eligible.sum()),prediction_rows=len(market_predictions),
        market_model_usage="REPORT_ONLY",breadth_status="ETF_PROXY_NOT_PIT_STOCK_BREADTH",yield_input_status="OPTIONAL_NOT_AVAILABLE")
    if training and not len(market_predictions):
        manifest["status"] = "BLOCKED_NO_EVALUABLE_FOLDS"
    if args.mode=="strict" and not states.decision_eligible.any():
        manifest["status"] = "NO_ASOF_ELIGIBLE_DATA"
    if training and manifest["status"] == "DESCRIPTIVE_CURRENT_VINTAGE_ONLY":
        tables = {"direction": metrics, "downside": downside_metrics,
                  "calibration": calibration, "increment": increment}
        summary = {name: json.loads(table.to_json(orient="records")) for name, table in tables.items()}
        (output / "market_summary.json").write_text(
            json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8"
        )
    report(output,"P3 市场与风格状态",manifest,{"状态及输入可用时间":states.reset_index().tail(40),"方向模型与常数概率基线":metrics,"按日配对Brier增量与20日块Bootstrap":increment,"下行事件与常数基线":downside_metrics,"概率校准分箱":calibration},charts,
        "当前版本价格回溯。概率为未校准基线；状态阈值冻结到验证段。French 归因在风格监控单独查看。")
    finish(args,output,manifest,register=False)
    return 0 if manifest["status"] == "DESCRIPTIVE_CURRENT_VINTAGE_ONLY" else 4
