"""Daily cross-sectional diagnostics; overlapping horizons are never iid tests."""
import numpy as np
import pandas as pd


def daily_rank_ic(data, x="value", y="target", min_count=10):
    pairs = data.dropna(subset=[x,y]).copy()
    if pairs.empty:
        return pd.DataFrame(columns=["date","rank_ic","n"])
    a = pairs.groupby("date")[x].rank(method="average")
    b = pairs.groupby("date")[y].rank(method="average")
    a = a - a.groupby(pairs.date).transform("mean")
    b = b - b.groupby(pairs.date).transform("mean")
    numerator = (a*b).groupby(pairs.date).sum()
    denominator = np.sqrt((a*a).groupby(pairs.date).sum()*(b*b).groupby(pairs.date).sum())
    count = pairs.groupby("date").size()
    value = (numerator/denominator.replace(0,np.nan)).where(count>=min_count)
    return pd.DataFrame({"rank_ic":value,"n":count}).rename_axis("date").reset_index()


def circular_block_ci(values, block_length=20, replicates=500, seed=42):
    """95% percentile CI for mean daily IC. Calendar positions/gaps preserved."""
    values = np.asarray(values,dtype=float)
    if np.isfinite(values).sum() < 2*block_length or len(values) < 2*block_length:
        return None,None
    rng = np.random.default_rng(seed)
    blocks = int(np.ceil(len(values)/block_length))
    starts = rng.integers(0,len(values),size=(replicates,blocks))
    indices = ((starts[:,:,None]+np.arange(block_length))%len(values)).reshape(replicates,-1)[:,:len(values)]
    sampled = values[indices]
    valid = np.isfinite(sampled)
    sums = np.where(valid,sampled,0).sum(axis=1)
    means = np.divide(sums,valid.sum(axis=1),out=np.full(replicates,np.nan),where=valid.sum(axis=1)>0)
    means = means[np.isfinite(means)]
    if not len(means):
        return None,None
    return tuple(float(x) for x in np.quantile(means,[0.025,0.975]))


def quintile_returns(data, min_count=10):
    pairs = data.dropna(subset=["value","target"]).copy()
    if pairs.empty:
        return pd.DataFrame(columns=["date","quintile","mean_forward_return","n"]),None
    groups = pairs.groupby("date")
    count = groups.value.transform("count")
    unique = groups.value.transform("nunique")
    # Average ranks preserve ties; do not invent an ordering with rank(method=first).
    pairs["quintile"] = np.ceil(groups.value.rank(method="average") / count * 5)
    pairs = pairs.loc[(count>=min_count)&(unique>=5)]
    if pairs.empty:
        return pd.DataFrame(columns=["date","quintile","mean_forward_return","n"]),None
    daily = pairs.groupby(["date","quintile"]).target.agg(mean_forward_return="mean",n="size").reset_index()
    turnover, previous = [], None
    all_dates = sorted(data.date.unique())
    grouped = {day: rows for day,rows in pairs.loc[pairs.quintile.eq(5)].groupby("date")}
    for day in all_dates:
        rows = grouped.get(day)
        current = None if rows is None or rows.empty else {sid:1/len(rows) for sid in rows.security_id}
        if current is not None and previous is not None:
            turnover.append(0.5*sum(abs(current.get(sid,0)-previous.get(sid,0)) for sid in set(current)|set(previous)))
        previous = current
    return daily, float(np.mean(turnover)) if turnover else None
