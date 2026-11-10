import pandas as pd

from quant_research.clock import TradingClock
from quant_research.data.bundle import load_real_bundle
from quant_research.features.context import make_context
from quant_research.models.dataset import prepare, prepare_market
from quant_research.models.settings import load_settings
from quant_research.models.walk_forward import evaluate_predictions, train_alpha, train_market
from quant_research.policy import PolicyError
from quant_research.research.statistics import circular_block_ci, daily_rank_ic, quintile_returns
from quant_research.research.increment import probability_increment
from .common import finish, line_svg, new_run, report, save_frame


def execute(args,return_data=False):
    config = load_settings(args.experiment)
    end = args.asof or str(config.validation_end)
    if pd.Timestamp(end) > pd.Timestamp(config.validation_end):
        raise ValueError("Historical alpha study cannot open sealed final period")
    clock = TradingClock()
    day = clock.session(end)
    if day <= pd.Timestamp(config.train_end):
        raise PolicyError("NO_VALIDATION_SESSIONS", "Alpha study cutoff must be in the validation period")
    # Load and gate the immutable real snapshot before creating any output.
    bundle = load_real_bundle(args.db, args.source, day.date().isoformat(), start=str(config.start))
    if args.mode == "strict":
        bundle.require("historical_model")
    bundle.require("exploratory_price_factors")
    bundle.require("observation")
    prices = bundle.prices
    context = make_context(prices, clock, "SPY", str(config.start), str(day.date()))
    output,manifest = new_run(args,config,"P4",prices)
    manifest.update(workflow="train", asof_date_et=str(day.date()),
        data_cutoff_utc=bundle.metadata["knowledge_cutoff_utc"],
        source_provenance=bundle.metadata["source_provenance"],
        source_snapshot_sha256=bundle.metadata["snapshot_sha256"],
        adjustment_basis=prices.adjustment_basis.iloc[0], symbols=bundle.metadata["symbols"],
        execution_ready=False, historical_decision_eligible=False,
        observational_coverage={"source":bundle.metadata["source"], "feed":bundle.metadata["feed"],
                                "asof_date_et":bundle.metadata["asof_date_et"],
                                "latest_session_complete":bundle.metadata["latest_session_complete"],
                                "verified_rows":bundle.metadata["source_provenance"]["verified_rows"]})
    frame,observed,market_columns,style_columns = prepare(
        context,clock,args.mode,prices.adjustment_basis.iloc[0],label_end=str(day.date()))
    frame = frame.dropna(subset=["target", "excess_target"])
    forecast_dates = observed.index[(observed.index > pd.Timestamp(config.train_end)) &
                                    (observed.index <= day)]
    market_frame = prepare_market(context, observed, clock, config.horizons, manifest["adjustment_basis"])
    market_frame = market_frame.dropna(subset=["benchmark_target"])
    market,market_folds = train_market(market_frame,observed,clock,config,args.mode,forecast_dates=forecast_dates)
    predictions,folds = train_alpha(frame,observed,clock,config,args.mode,market_columns,style_columns,
                                    forecast_dates=forecast_dates)
    # Retrospective studies are descriptive only, including any rows emitted by the model helper.
    if len(predictions):
        predictions["decision_eligible"] = False
    if len(market):
        market["decision_eligible"] = False
    metrics,calibration = evaluate_predictions(predictions,["variant","horizon"]) if len(predictions) else (pd.DataFrame(),pd.DataFrame())
    ranks,group_data = [],[]
    if len(predictions):
        for (variant,horizon),values in predictions.groupby(["variant","horizon"]):
            pairs = values.rename(columns={"expected_excess_return":"value","actual_excess_return":"target"})
            ic = daily_rank_ic(pairs,min_count=10)
            baseline = daily_rank_ic(pairs.rename(columns={"value":"model_value","reversal_5d":"value"}),min_count=10)
            low,high = circular_block_ci(ic.rank_ic,20,500,config.seed)
            ranks.append({"variant":variant,"horizon":horizon,"mean_rank_ic":float(ic.rank_ic.mean()) if ic.rank_ic.notna().any() else None,
                "reversal_baseline_ic":float(baseline.rank_ic.mean()) if baseline.rank_ic.notna().any() else None,
                "ic_ci95_low":low,"ic_ci95_high":high,"decision":"NOT_READY"})
            daily,_ = quintile_returns(pairs,min_count=10)
            if len(daily):
                daily["variant"],daily["horizon"] = variant,horizon
                group_data.append(daily)
    rank_metrics = pd.DataFrame(ranks)
    increment = probability_increment(predictions,config.seed)
    save_frame(increment,output,"paired_probability_increment")
    for name,data in [("predictions",predictions),("alpha_metrics",metrics),("probability_calibration",calibration),
                      ("alpha_training_folds",folds),("market_predictions",market),("market_training_folds",market_folds),
                      ("rank_metrics",rank_metrics),("prediction_groups",pd.concat(group_data,ignore_index=True) if group_data else pd.DataFrame())]:
        save_frame(data,output,name)
    manifest.update(status="RETROSPECTIVE_MODEL_STUDY_NOT_TRADING",
        prediction_rows=len(predictions),market_prediction_rows=len(market),folds=len(folds),decision_eligible_rows=int(predictions.decision_eligible.sum()) if len(predictions) else 0,
        uncertainty_status="UNAVAILABLE_NOT_CALIBRATED",lightgbm_status="NOT_ENABLED_NO_VALIDATED_INCREMENT",final_test_status="SEALED",
        asset_scope="CURRENT_ETF_PROXIES_NOT_INDIVIDUAL_STOCK_ALPHA",
        ablations={"A":"Alpha","B":"Alpha + observed market","C":"Alpha + ETF style proxies","D":"all + causal interactions"})
    if predictions.empty:
        manifest["status"] = "NO_ELIGIBLE_TRAINING_DATA"
    charts = []
    if len(market):
        h = market.loc[market.horizon.eq(3)]
        charts.append(line_svg(h.p_up,"SPY H3 方向概率：未校准基线"))
    report(output,"P4 Alpha 基线与 A–D 消融",manifest,{"回归与分类对照":metrics,"按日配对Brier增量与20日块Bootstrap":increment,"Rank IC 与单因子对照":rank_metrics,"概率校准":calibration},charts,
        "按季度滚动拟合，训练内缺失填充和标准化。使用标签退出时点剔除和至少 5 个交易日间隔。A–D 使用相同样本和目标。Yahoo 当前版本 ETF 回溯输出仅供研究，未估计的不确定性保持空值。")
    finish(args,output,manifest,register=False)
    if return_data:
        return output,manifest,predictions,prices,context,clock
    return 4 if predictions.empty else 0
