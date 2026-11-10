from math import floor, isfinite


def stop_or_target(bar,stop=None,target=None):
    """Opening gaps execute at the worse available open; unknown intrabar path is conservative."""
    if stop is not None and bar["open"]<=stop:
        return float(bar["open"]),"GAP_STOP"
    if stop is not None and bar["low"]<=stop:
        return float(stop),"STOP_FIRST_UNKNOWN_PATH"
    if target is not None and bar["open"]>=target:
        return float(target),"GAP_TARGET"
    if target is not None and bar["high"]>=target:
        return float(target),"TARGET"
    return None,None


def allocation_notional(config,equity,cash,gross,sector_value,price,adv20,atr20,risk_enabled):
    if not all(isfinite(v) for v in (equity,cash,gross,sector_value,price,adv20,atr20)):
        return 0.0
    if equity<=0 or price<config.minimum_price or adv20<config.minimum_adv20 or atr20<=0:
        return 0.0
    limits = [config.max_stock_weight*equity,config.max_total_weight*equity-gross,
              config.max_sector_weight*equity-sector_value,config.max_participation*adv20,cash]
    if risk_enabled:
        stop_distance = config.stop_atr_multiple*atr20
        if stop_distance>=price:
            return 0.0
        limits.append(config.equity_risk_per_trade*equity*price/stop_distance)
    return max(0.0,min(limits))
