"""Paired, daily-aggregated probability score improvements; positive means lower Brier."""
import pandas as pd

from .statistics import circular_block_ci


def probability_increment(predictions, seed=42):
    if predictions.empty:
        return pd.DataFrame()
    frame = predictions.copy()
    frame = frame.loc[frame.actual_return.notna() & frame.p_up.notna() & frame.naive_p_up.notna()].copy()
    if not (frame.p_up.between(0,1).all() and frame.naive_p_up.between(0,1).all()):
        raise ValueError("Invalid probabilities")
    frame["loss"] = (frame.p_up - frame.actual_return.gt(0).astype(float)) ** 2
    frame["naive_loss"] = (frame.naive_p_up - frame.actual_return.gt(0).astype(float)) ** 2
    groups = ["variant", "horizon"] if "variant" in frame else ["horizon"]
    keys = ["date", "security_id", "horizon"] if "security_id" in frame else ["date", "horizon"]
    if frame.duplicated(keys + (["variant"] if "variant" in frame else [])).any():
        raise ValueError("Duplicate prediction keys invalidate paired scoring")
    baseline = frame.loc[frame.variant.eq("A"),keys + ["loss","actual_return"]].rename(columns={"loss":"alpha_only_loss","actual_return":"baseline_actual_return"}) if "variant" in frame else None
    rows = []
    for group, values in frame.groupby(groups):
        group = group if isinstance(group, tuple) else (group,)
        comparisons = [("constant_probability", values.assign(delta=values.naive_loss-values.loss))]
        if baseline is not None:
            paired = values.merge(baseline, on=keys, validate="one_to_one")
            if not paired.actual_return.eq(paired.baseline_actual_return).all():
                raise ValueError("Paired models disagree on target outcomes")
            comparisons.append(("alpha_only_A", paired.assign(delta=paired.alpha_only_loss-paired.loss)))
        for name, paired in comparisons:
            daily = paired.groupby("date").delta.mean().sort_index()
            low, high = circular_block_ci(daily,20,500,seed)
            rows.append({**dict(zip(groups,group)), "baseline":name, "matched_rows":len(paired),
                         "matched_dates":len(daily), "mean_brier_improvement":float(daily.mean()),
                         "ci95_low":low, "ci95_high":high, "bootstrap_block_sessions":20,
                         "interpretation":"DESCRIPTIVE_NOT_DEPLOYMENT_EVIDENCE"})
    return pd.DataFrame(rows)
