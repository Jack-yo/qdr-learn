from argparse import Namespace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_research.backtest.engine import PortfolioEngine
from quant_research.backtest.paper import PaperLedger
from quant_research.backtest.simulation import candidates
from quant_research.clock import TradingClock
from quant_research.features.states import frozen_states, observations
from quant_research.models.dataset import load_panel, prepare
from quant_research.models.settings import load_settings
from quant_research.models.walk_forward import train_alpha, train_market
from quant_research.risk.limits import allocation_notional
from .common import fingerprint, finish, new_run, report, save_frame


def resolve_day(value,config,clock):
    if value and value!="auto":
        clock.signal(value)
        return str(clock.session(value).date())
    if not value:
        return str(config.validation_end)
    now=datetime.now(timezone.utc)
    dates=clock.calendar.sessions_in_range((now-timedelta(days=15)).date(),now.date())
    eligible=[d for d in dates if clock.close(d)+clock.delay<=now]
    if not eligible:
        raise ValueError("No completed session found")
    return str(eligible[-1].date())


def plan(predictions,config,clock,day):
    orders,rows=[],[]
    if predictions.empty:
        return orders,pd.DataFrame(columns=["symbol","horizon","p_up","expected_return","expected_excess_return","uncertainty","planned_weight","stop_price"])
    for horizon in config.horizons:
        engine=PortfolioEngine(config,clock,config.default_cost_bps_per_side,True)
        selected=predictions.loc[predictions.variant.eq("D")&predictions.horizon.eq(horizon)]
        end=str(clock.window(day,horizon).exit_time.date())
        chosen=candidates(selected,engine,config,day,end,horizon)
        used,sector_values=0.0,{}
        for order in chosen:
            match=selected.loc[selected.security_id.eq(order["security_id"])].iloc[0]
            size=allocation_notional(config,config.initial_cash,config.initial_cash-used,used,sector_values.get(order["sector"],0),
                match.reference_close,match.adv20,match.atr20,True)
            if size<=0:
                continue
            used+=size
            sector_values[order["sector"]]=sector_values.get(order["sector"],0)+size
            rows.append({"symbol":order["symbol"],"security_id":order["security_id"],"horizon":horizon,"p_up":float(match.p_up),
                "expected_return":float(match.predicted_return),"expected_excess_return":float(match.expected_excess_return),"uncertainty":None,
                "planned_weight":size/config.initial_cash,"stop_price":float(match.reference_close-config.stop_atr_multiple*match.atr20),
                "entry_time":str(match.entry_time),"exit_time":str(match.exit_time),"probability_status":str(match.probability_status),"status":"MODELLED_FILL_NOT_ENABLED"})
            if horizon==config.paper_horizon:
                orders.append(order)
    return orders,pd.DataFrame(rows) if rows else pd.DataFrame(columns=["symbol","horizon","p_up","expected_return","expected_excess_return","uncertainty","planned_weight","stop_price"])


def daily(args,return_data=False):
    config=load_settings(args.experiment)
    clock=TradingClock()
    day=resolve_day(args.asof,config,clock)
    prices,context,clock=load_panel(args.source,args.db,config,end=day,
        capability='forward_shadow' if args.mode=='strict' else 'exploratory_price_factors')
    output,manifest=new_run(args,config,"P6",prices)
    manifest.update(requested_session=day,signal_time=str(clock.signal(day)),asof_timestamp_utc=str(clock.signal(day)),data_cutoff_utc=str(clock.signal(day)))
    current=prices.loc[pd.to_datetime(prices.date).eq(pd.Timestamp(day))]
    fresh=len(current)==len(context.symbols) and current.available_at.map(lambda v:pd.Timestamp(v)<=pd.Timestamp(clock.signal(day))).all()
    executable=False  # Real execution requires G4 evidence acceptance
    observed=observations(context)
    states,thresholds=frozen_states(observed,min(str(config.train_end),day),config.state_threshold_quantile)
    state=states.loc[[pd.Timestamp(day)]].copy()
    eligible=state.state_available_at.le(pd.Timestamp(clock.signal(day)))&state.market_return_20.notna()&state.market_vol_20.notna()&(args.mode=="strict")
    state["decision_eligible"]=eligible
    if args.mode=="strict":
        state.loc[~eligible,[c for c in state if c.endswith("_state")]]="UNKNOWN"
        state.loc[~eligible,[c for c in state if c.startswith(("market_","style_")) and not c.endswith("_state")]]=np.nan
    predictions,market_predictions,orders,recommendations=pd.DataFrame(),pd.DataFrame(),[],pd.DataFrame(columns=["symbol","horizon","p_up","expected_return","uncertainty"])
    folds=pd.DataFrame()
    if executable:
        frame,observed,market_columns,style_columns=prepare(context,clock,"strict",prices.adjustment_basis.iloc[0],label_end=min(day,str(config.validation_end)),forecast_dates=[day])
        predictions,folds=train_alpha(frame,observed,clock,config,"strict",market_columns,style_columns,forecast_dates=[day])
        market_predictions,_=train_market(frame,observed,clock,config,"strict",forecast_dates=[day])
        orders,recommendations=plan(predictions,config,clock,day)
    manifest.update(status="FORWARD_SHADOW_READY" if executable else "NO_NEW_TRADING_ADVICE",fresh_asof_data=bool(fresh),
        raw_execution_eligible=bool(executable),candidate_rows=len(recommendations),pending_order_count=len(orders),thresholds=thresholds,
        no_advice_reason=None if executable else "RAW/PIT_UNVERIFIED_OR_DATA_NOT_AVAILABLE_AT_SIGNAL",model_final_test_evaluated=False)
    for name,frame in [("market_style",state.reset_index()),("daily_predictions",predictions),("daily_market_predictions",market_predictions),("candidates",recommendations),("training_folds",folds)]:
        save_frame(frame,output,name)
    (output/"alerts.json").write_text(json.dumps({"status":manifest["status"],"reason":manifest["no_advice_reason"],"real_orders_enabled":False},indent=2),encoding="utf-8")
    report(output,"P6 每日市场、风格与候选清单",manifest,{"市场风格与实际可用时间":state.reset_index(),"市场概率与下行风险（未校准）":market_predictions,"候选（允许为空）":recommendations},
        note="研究输出受真实行情、时点、身份和公司行为准入约束。缺项时保留空候选及阻断原因。")
    if not return_data:
        finish(args,output,manifest)
    if return_data:
        bars={str(r.security_id):{"open":float(r.open),"high":float(r.high),"low":float(r.low),"close":float(r.close),"volume":int(r.volume)} for r in current.itertuples(index=False)}
        return output,manifest,orders,bars,config,clock,day
    return 0 if executable else 4


def paper(args):
    from quant_research.data.bundle import load_real_bundle
    from quant_research.policy import execution_blocked
    bundle=load_real_bundle(args.db,args.source,asof=None if args.asof in (None,'auto') else args.asof)
    bundle.require('forward_shadow')
    execution_blocked()


def run_all(args):
    config=load_settings(args.experiment)
    prices,_,_=load_panel(args.source,args.db,config)
    output,manifest=new_run(args,config,"P3-P6",prices)
    from .market import execute as market
    from .train import execute as train
    from .backtest import execute as backtest
    market_args=Namespace(**{**vars(args),"command":"train-market","asof":None})
    stage3=market(market_args)
    training,trained,_,_,_,_=train(args,return_data=True)
    back_args=Namespace(**{**vars(args),"command":"backtest","training_run":training})
    stage5=backtest(back_args)
    daily_args=Namespace(**{**vars(args),"command":"daily-report","asof":str(config.validation_end)})
    stage6=daily(daily_args)
    manifest.update(status="ENGINEERING_WORKFLOW_COMPLETE" if stage3==stage5==stage6==0 and trained["prediction_rows"] else "DATA_BLOCKED_NOT_READY",
        stages={"P3_exit":stage3,"P4_training_run":str(training),"P5_exit":stage5,"P6_exit":stage6},real_orders_enabled=False)
    report(output,"P3–P6 本地工程运行总览",manifest,{"阶段状态":pd.DataFrame([{k:str(v) for k,v in manifest["stages"].items()}])})
    finish(args,output,manifest)
    return 0 if manifest["status"]=="ENGINEERING_WORKFLOW_COMPLETE" else 4


def execute(args):
    if args.command=="scheduled-run": return scheduled(args)
    if args.command=="run-all": return run_all(args)
    if args.command in ("paper-step","paper-replay"): return paper(args)
    return daily(args)


def scheduled(args):
    """Refresh then report; a failed refresh creates an explicit empty-advice artifact."""
    config=load_settings(args.experiment)
    day=resolve_day(args.asof or "auto",config,TradingClock())
    if args.source=="yahoo":
        from quant_research.data.pipeline import execute as ingest
        ingest_args=Namespace(command="ingest",source="yahoo",feed="iex",symbols=",".join(__import__("quant_research.policy",fromlist=["SYMBOLS"]).SYMBOLS),
            start=str(config.start),end=day,db=args.db,data_dir=args.db.parent,output=args.output,sources_config=Path("configs/sources.yaml"),
            offline=False,refresh=True,repair_gaps=False)
        try:
            code=ingest(ingest_args)
        except Exception:
            code=3
        if code!=0:
            empty=pd.DataFrame({"date":pd.Series(dtype="datetime64[ns]")})
            output,manifest=new_run(args,config,"P6",empty)
            manifest.update(status="DATA_REFRESH_FAILED_NO_NEW_ADVICE",candidate_rows=0,real_orders_enabled=False,paper_state_advanced=False)
            (output/"alerts.json").write_text(json.dumps({"status":manifest["status"],"candidate_rows":0}),encoding="utf-8")
            save_frame(pd.DataFrame(columns=["symbol","horizon","p_up","expected_return"]),output,"candidates")
            report(output,"P6 数据刷新失败",manifest,{},note="没有生成新交易建议，也没有推进模拟账户。请检查数据来源与缓存。")
            finish(args,output,manifest)
            return 4
    return daily(Namespace(**{**vars(args),"asof":day,"command":"daily-report"}))
