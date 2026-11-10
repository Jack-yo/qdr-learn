"""Factor diagnostics for development partitions only; never a strategy backtest."""
import numpy as np
import pandas as pd

from .statistics import circular_block_ci, daily_rank_ic, quintile_returns


def finite(value):
    return float(value) if value is not None and np.isfinite(value) else None


def evaluate(features, labels, context, experiment):
    labels = labels.copy()
    labels["target"] = labels.forward_return.fillna(labels.proxy_forward_return)
    labels["benchmark_target"] = labels.benchmark_return.fillna(labels.proxy_benchmark_return)
    labels["excess_target"] = labels.target-labels.benchmark_target
    market = context.close[context.benchmark_id]/context.close[context.benchmark_id].shift(20)-1
    states = pd.Series(np.where(market>0,"UP_20D","DOWN_20D"),index=market.index).where(market.notna(),"UNKNOWN")
    summaries, daily_outputs, group_outputs, conditions = [],[],[],[]
    partitions = [("train",str(experiment.start),str(experiment.train_end)),
                  ("validation",str(experiment.train_end+pd.Timedelta(days=1)),str(experiment.validation_end))]
    train_sessions = context.close.index[(context.close.index>=str(experiment.start))&(context.close.index<=str(experiment.train_end))]
    train_evaluation_dates = train_sessions[:-experiment.embargo_sessions] if len(train_sessions)>experiment.embargo_sessions else train_sessions[:0]
    for partition,start,end in partitions:
        dates = context.close.index[(context.close.index>=start)&(context.close.index<=end)]
        f = features.loc[features.date.between(start,end)]
        if partition == "train":
            dates = train_evaluation_dates
            f = f.loc[f.date.isin(dates)]
        # Purge boundary-spanning labels before describing a partition.
        lab = labels.loc[labels.date.between(start,end)&(labels.exit_date.astype(str)<=end)]
        for name,values in f.groupby("feature_name",sort=False):
            possible = len(values)
            for horizon in experiment.horizons:
                merged = values[["date","security_id","value"]].merge(
                    lab.loc[lab.horizon.eq(horizon),["date","security_id","target","excess_target"]],
                    on=["date","security_id"],how="left",validate="one_to_one")
                ic = daily_rank_ic(merged,min_count=experiment.min_cross_section)
                excess_ic = daily_rank_ic(merged,y="excess_target",min_count=experiment.min_cross_section)
                series = ic.set_index("date").rank_ic.reindex(dates).astype(float)
                valid = series.dropna()
                low,high = circular_block_ci(series,experiment.bootstrap_block_sessions,experiment.bootstrap_replicates,experiment.seed)
                std = valid.std(ddof=1)
                groups,turnover = quintile_returns(merged,experiment.min_cross_section)
                summary = {"partition":partition,"factor":name,"horizon":horizon,
                    "feature_coverage":float(values.value.notna().sum()/possible) if possible else 0,
                    "feature_missing_rate":float(values.value.isna().sum()/possible) if possible else 1,
                    "label_pair_coverage":float(merged[["value","target"]].notna().all(axis=1).sum()/possible) if possible else 0,
                    "daily_ic_count":len(valid),"rank_ic_mean":finite(valid.mean()),"rank_ic_std":finite(std),
                    "icir_unannualized":finite(valid.mean()/std) if pd.notna(std) and std>0 else None,
                    "ic_mean_ci95_low":low,"ic_mean_ci95_high":high,
                    "ic_p05":finite(valid.quantile(0.05)),"ic_median":finite(valid.median()),"ic_p95":finite(valid.quantile(0.95)),
                    "mean_covered_securities":finite(ic.n.mean()),
                    "excess_rank_ic_mean":finite(excess_ic.rank_ic.mean()),
                    "top_quintile_membership_turnover":turnover,
                    "sector_exposure":None,"size_exposure":None,"style_correlation":None,
                    "exposure_status":"PIT_SECTOR_SIZE_UNAVAILABLE_STYLE_P3_NOT_IMPLEMENTED"}
                by_group = groups.groupby("quintile").mean_forward_return.mean() if len(groups) else pd.Series(dtype=float)
                for group in range(1,6):
                    summary[f"q{group}_mean_forward_price_return"] = finite(by_group.get(group))
                summary["q5_minus_q1_price_return_spread"] = finite(by_group.get(5,np.nan)-by_group.get(1,np.nan))
                summaries.append(summary)
                ic["factor"],ic["horizon"],ic["partition"] = name,horizon,partition
                if len(ic):
                    daily_outputs.append(ic)
                if len(groups):
                    groups["factor"],groups["horizon"],groups["partition"] = name,horizon,partition
                    group_outputs.append(groups)
                for state in ("UP_20D","DOWN_20D","UNKNOWN"):
                    conditional = series.loc[states.reindex(dates).eq(state)].dropna()
                    conditions.append({"partition":partition,"factor":name,"horizon":horizon,"state":state,
                                       "daily_ic_count":len(conditional),"rank_ic_mean":finite(conditional.mean())})
    correlations = []
    for partition,start,end in partitions:
        selection = features.date.between(start,end)
        if partition == "train":
            selection &= features.date.isin(train_evaluation_dates)
        wide = features.loc[selection].pivot(index=["date","security_id"],columns="feature_name",values="value")
        names = list(wide.columns)
        for i,left in enumerate(names):
            for right in names[i:]:
                pairs = wide[[left]].rename(columns={left:"value"}).join(wide[[right]].rename(columns={right:"target"})).reset_index()
                ic = daily_rank_ic(pairs,min_count=experiment.min_cross_section)
                correlations.append({"partition":partition,"factor_a":left,"factor_b":right,
                                     "mean_daily_rank_correlation":finite(ic.rank_ic.mean()),"daily_count":int(ic.rank_ic.notna().sum())})
    return {"summary":pd.DataFrame(summaries),"daily_ic":pd.concat(daily_outputs,ignore_index=True) if daily_outputs else pd.DataFrame(columns=["date","rank_ic","n","factor","horizon","partition"]),
            "daily_groups":pd.concat(group_outputs,ignore_index=True) if group_outputs else pd.DataFrame(),
            "conditional_ic":pd.DataFrame(conditions),"factor_correlations":pd.DataFrame(correlations)}
