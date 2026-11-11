"""Frozen quarterly walk-forward studies. Retrospective outputs cannot trade."""
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, mean_squared_error
from threadpoolctl import threadpool_limits

from quant_research.validation.walk_forward import quarterly_folds, training_mask
from .baselines import probabilities, regression
from .dataset import ALPHA_COLUMNS


def evaluate_predictions(predictions,group_columns):
    records,calibration = [],[]
    for key,rows in predictions.groupby(group_columns,sort=False):
        key = key if isinstance(key,tuple) else (key,)
        values = rows.dropna(subset=["actual_return","p_up"])
        if values.empty:
            continue
        y = (values.actual_return>0).astype(int)
        p = values.p_up.clip(1e-8,1-1e-8)
        naive = values.naive_p_up.clip(1e-8,1-1e-8)
        record = dict(zip(group_columns,key))
        record.update(rows=len(values),dates=values.date.nunique(),brier=brier_score_loss(y,p),
            naive_brier=brier_score_loss(y,naive),log_loss=log_loss(y,p,labels=[0,1]),naive_log_loss=log_loss(y,naive,labels=[0,1]),
            return_mse=mean_squared_error(values.actual_return,values.predicted_return),
            naive_return_mse=mean_squared_error(values.actual_return,values.naive_return),status="NOT_READY")
        record["baseline_improvement"] = record["brier"]<record["naive_brier"] and record["log_loss"]<record["naive_log_loss"]
        records.append(record)
        bins = np.minimum((p*5).astype(int),4)
        for bucket in range(5):
            selected = values.loc[bins.eq(bucket)]
            calibration.append({**dict(zip(group_columns,key)),"bin":bucket,"count":len(selected),
                "mean_probability":float(selected.p_up.mean()) if len(selected) else None,
                "observed_up_rate":float((selected.actual_return>0).mean()) if len(selected) else None})
    return pd.DataFrame(records),pd.DataFrame(calibration)


def evaluate_downside(predictions,threshold):
    records=[]
    for horizon,rows in predictions.groupby("horizon"):
        rows=rows.dropna(subset=["actual_return","p_downside","naive_p_downside"])
        if rows.empty:
            continue
        target=(rows.actual_return<threshold).astype(int)
        p=rows.p_downside.clip(1e-8,1-1e-8)
        baseline=rows.naive_p_downside.clip(1e-8,1-1e-8)
        records.append({"horizon":horizon,"threshold":threshold,"rows":len(rows),"risk_event_rate":float(target.mean()),
            "brier":brier_score_loss(target,p),"naive_brier":brier_score_loss(target,baseline),
            "log_loss":log_loss(target,p,labels=[0,1]),"naive_log_loss":log_loss(target,baseline,labels=[0,1]),"status":"NOT_READY"})
    return pd.DataFrame(records)


def train_market(frame,observed,clock,config,mode,forecast_dates=None):
    market = frame.drop_duplicates(["date","horizon"]).copy()
    market["target"] = market.benchmark_target
    # Do not accidentally inherit one arbitrary stock's feature availability.
    market["feature_available_at"] = market.state_available_at
    columns = [c for c in observed if c.startswith("market_")]
    predictions,folds = [],[]
    sessions = observed.index
    forecast_dates = pd.DatetimeIndex(forecast_dates) if forecast_dates is not None else sessions[(sessions>pd.Timestamp(config.train_end))&(sessions<=pd.Timestamp(config.validation_end))]
    with threadpool_limits(limits=1):
        for dates in quarterly_folds(forecast_dates,forecast_dates.min(),forecast_dates.max()):
            test_start = dates.min()
            # Daily query retains the same quarter's frozen training boundary.
            quarter = test_start.to_period("Q").start_time
            quarter_sessions = sessions[sessions>=quarter]
            fit_start = quarter_sessions[0]
            fit_time = clock.signal(fit_start)
            for horizon in config.horizons:
                all_rows = market.loc[market.horizon.eq(horizon)]
                train = all_rows.loc[training_mask(all_rows,sessions,fit_start,fit_time,config.gap_sessions,config.training_window_sessions,mode=="strict") & (all_rows.date<=pd.Timestamp(config.validation_end))].dropna(subset=["target"])
                test = all_rows.loc[all_rows.date.isin(dates)].copy()
                if mode=="strict":
                    test = test.loc[test.feature_available_at<=test.signal_time]
                if train.date.nunique()<config.minimum_training_sessions or test.empty:
                    continue
                x,y = train[columns],train.target.to_numpy()
                p,naive,status = probabilities(x,(y>0).astype(int),test[columns],config)
                down,naive_down,down_status = probabilities(x,(y<config.downside_threshold).astype(int),test[columns],config)
                model = regression(config.ridge_alpha).fit(x,y)
                out = test[["date", "horizon", "signal_time", "feature_available_at",
                            "entry_time", "exit_time", "label_available_at"]].copy()
                out["p_up"],out["p_downside"],out["naive_p_downside"] = p,down,naive_down
                out["downside_probability_status"]=down_status
                out["predicted_return"],out["actual_return"] = model.predict(test[columns]),test.target.to_numpy()
                out["naive_p_up"],out["naive_return"] = naive,float(np.mean(y))
                out["downside_quantile"] = float(np.quantile(y,config.downside_quantile))
                out["uncertainty"],out["probability_status"] = np.nan,status
                out["decision_eligible"] = mode=="strict"
                out["fit_time"],out["model_version"] = fit_time,config.experiment_id+"-market-v1"
                predictions.append(out)
                folds.append({"horizon":horizon,"fit_time":fit_time,"first_prediction":test.date.min(),"last_prediction":test.date.max(),
                    "train_first_signal":train.date.min(),"train_last_signal":train.date.max(),
                    "train_last_exit":train.exit_time.max(),"train_last_available":train.label_available_at.max(),
                    "train_rows":len(train),"train_sessions":train.date.nunique(),"mode":mode})
    return pd.concat(predictions,ignore_index=True) if predictions else pd.DataFrame(),pd.DataFrame(folds)


def train_alpha(frame,observed,clock,config,mode,market_columns,style_columns,forecast_dates=None):
    columns_by_variant = {"A":ALPHA_COLUMNS,"B":ALPHA_COLUMNS+market_columns,"C":ALPHA_COLUMNS+style_columns,
                          "D":ALPHA_COLUMNS+market_columns+style_columns+["interaction_reversal_market","interaction_momentum_style"]}
    sessions = observed.index
    forecast_dates = pd.DatetimeIndex(forecast_dates) if forecast_dates is not None else sessions[(sessions>pd.Timestamp(config.train_end))&(sessions<=pd.Timestamp(config.validation_end))]
    outputs,folds = [],[]
    with threadpool_limits(limits=1):
        for dates in quarterly_folds(forecast_dates,forecast_dates.min(),forecast_dates.max()):
            quarter = dates.min().to_period("Q").start_time
            fit_start = sessions[sessions>=quarter][0]
            fit_time = clock.signal(fit_start)
            for horizon in config.horizons:
                all_rows = frame.loc[frame.horizon.eq(horizon)]
                train = all_rows.loc[training_mask(all_rows,sessions,fit_start,fit_time,config.gap_sessions,config.training_window_sessions,mode=="strict") & (all_rows.date<=pd.Timestamp(config.validation_end))].dropna(subset=["target","excess_target"])
                test = all_rows.loc[all_rows.date.isin(dates)].copy()
                if mode=="strict":
                    test = test.loc[test.feature_available_at<=test.signal_time]
                if train.date.nunique()<config.minimum_training_sessions or test.empty:
                    continue
                for variant,columns in columns_by_variant.items():
                    # Gross trade return and benchmark-relative excess return are
                    # distinct targets; the latter must never masquerade as a
                    # directly tradable total-return forecast.
                    reg_excess = regression(config.ridge_alpha).fit(train[columns],train.excess_target)
                    reg_gross = regression(config.ridge_alpha).fit(train[columns],train.target)
                    p,naive,status = probabilities(train[columns],(train.target>0).astype(int),test[columns],config)
                    expected_excess = reg_excess.predict(test[columns])
                    expected_gross = reg_gross.predict(test[columns])
                    out = test[["date","security_id","symbol","horizon","signal_time","feature_available_at","entry_time","exit_time",
                                "label_available_at","atr20","reference_close","adv20","sector","reversal_5d"]].copy()
                    out["variant"],out["p_up"],out["expected_excess_return"] = variant,p,expected_excess
                    out["expected_gross_trade_return"] = expected_gross
                    out["predicted_return"] = expected_gross
                    out["actual_return"],out["actual_excess_return"] = test.target.to_numpy(),test.excess_target.to_numpy()
                    out["naive_return"],out["naive_p_up"] = float(train.target.mean()),naive
                    out["downside_quantile"] = float(train.target.quantile(config.downside_quantile))
                    out["uncertainty"],out["probability_status"] = np.nan,status
                    out["decision_eligible"],out["fit_time"] = mode=="strict",fit_time
                    out["model_version"] = config.experiment_id+"-"+variant+"-v1"
                    outputs.append(out)
                    folds.append({"variant":variant,"horizon":horizon,"fit_time":fit_time,"first_prediction":test.date.min(),
                        "last_prediction":test.date.max(),"train_last_signal":train.date.max(),"train_last_exit":train.exit_time.max(),
                        "train_last_available":train.label_available_at.max(),"train_rows":len(train),"train_sessions":train.date.nunique(),"mode":mode})
    return pd.concat(outputs,ignore_index=True) if outputs else pd.DataFrame(),pd.DataFrame(folds)
