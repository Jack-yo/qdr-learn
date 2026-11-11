"""V4 portfolio risk diagnostics on frozen holdings and dated return inputs.

Caller must separately attest price origin and PIT availability. This module
calculates risk only: it never generates orders or claims historical eligibility.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RiskPolicy:
    max_stock_weight: float = 0.10
    max_sector_weight: float = 0.25
    max_gross_weight: float = 0.50
    max_daily_var95: float = 0.025
    min_daily_observations: int = 60
    covariance_shrinkage: float = 0.20

    def __post_init__(self):
        for name in ('max_stock_weight', 'max_sector_weight', 'max_gross_weight', 'max_daily_var95'):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f'Invalid risk policy: {name}')
        if not 0 <= self.covariance_shrinkage <= 1:
            raise ValueError('Covariance shrinkage must be 0 to 1')
        if self.min_daily_observations < 20:
            raise ValueError('Risk window needs at least 20 sessions')


def assess_portfolio(positions: pd.DataFrame, daily_returns: pd.DataFrame,
                     asof: pd.Timestamp, policy: RiskPolicy = RiskPolicy()) -> dict:
    """No ffill, lookahead, silent removal of holdings or fabricated prices.

    positions: security_id, NAV weight, sector, beta. daily_returns: dated
    security columns, indexed by unique monotonically increasing sessions.
    """
    required = {'security_id', 'weight', 'sector', 'beta'}
    if required - set(positions):
        raise ValueError('Positions require security_id, weight, sector and beta')
    if positions.empty:
        return {'status':'EMPTY_PORTFOLIO','alerts':[], 'gross_weight':0.0,
                'research_only':True}
    if positions.security_id.duplicated().any():
        raise ValueError('Duplicate holdings identity')
    asof = pd.Timestamp(asof)
    if asof.tzinfo is not None:
        raise ValueError('Use a market-session date without timezone')
    if not isinstance(daily_returns.index, pd.DatetimeIndex):
        raise ValueError('Daily returns must be indexed by session date')
    if daily_returns.index.tz is not None:
        raise ValueError('Session timestamps must be timezone naive')
    if not daily_returns.index.is_monotonic_increasing or daily_returns.index.has_duplicates:
        raise ValueError('Return sessions must be unique and time ordered')
    if daily_returns.index.max() > asof:
        raise ValueError('Return panel contains future sessions')
    ids = positions.security_id.astype(str).tolist()
    if any(i not in daily_returns.columns for i in ids):
        raise ValueError('Missing returns for at least one holding')
    weights = positions.set_index('security_id').loc[ids,'weight'].to_numpy(dtype=float)
    beta = positions.set_index('security_id').loc[ids,'beta'].to_numpy(dtype=float)
    if not np.isfinite(weights).all() or (weights < 0).any() or not np.isfinite(beta).all():
        raise ValueError('Nonfinite or negative holding weight / beta')
    gross = float(weights.sum())
    if gross > 1 + 1e-9:
        raise ValueError('Holdings exceed 100% of portfolio NAV')
    panel = daily_returns[ids].tail(max(policy.min_daily_observations, 63)).astype(float)
    if len(panel) < policy.min_daily_observations or panel.isna().any().any() or not np.isfinite(panel.to_numpy()).all():
        raise ValueError('Incomplete return window; no implicit price filling')
    covariance = panel.cov().to_numpy(dtype=float)
    shrink = policy.covariance_shrinkage
    covariance = (1-shrink)*covariance + shrink*np.diag(np.diag(covariance))
    annualized_vol = float(np.sqrt(max(0,weights @ covariance @ weights)*252))
    weighted_returns = panel.to_numpy() @ weights
    loss = -weighted_returns
    var95 = max(0.0,float(np.quantile(loss,.95)))
    cvar95 = max(0.0,float(loss[loss>=np.quantile(loss,.95)].mean()))
    sector_weights = positions.assign(weight=weights).groupby('sector',dropna=False).weight.sum().to_dict()
    alerts = []
    for sid,weight in zip(ids,weights):
        if weight > policy.max_stock_weight + 1e-9:
            alerts.append({'code':'STOCK_LIMIT','subject':sid,'actual':float(weight),'limit':policy.max_stock_weight})
    for sector,weight in sector_weights.items():
        if weight > policy.max_sector_weight + 1e-9:
            alerts.append({'code':'SECTOR_LIMIT','subject':str(sector),'actual':float(weight),'limit':policy.max_sector_weight})
    if gross > policy.max_gross_weight + 1e-9:
        alerts.append({'code':'GROSS_LIMIT','subject':'portfolio','actual':gross,'limit':policy.max_gross_weight})
    if var95 > policy.max_daily_var95 + 1e-9:
        alerts.append({'code':'VAR95_LIMIT','subject':'portfolio','actual':var95,'limit':policy.max_daily_var95})
    return {'status':'RISK_MEASURED','research_only':True,'return_sessions':len(panel),
            'asof_date':asof.date().isoformat(),'gross_weight':gross,
            'weighted_market_beta':float(weights@beta),
            'annualized_volatility':annualized_vol,'daily_var95':var95,
            'daily_expected_shortfall95':cvar95,
            'sector_weights':{str(k):float(v) for k,v in sector_weights.items()},
            'alerts':alerts,'source_attested':False}



def assess_paper_concentration(account: dict, policy: RiskPolicy = RiskPolicy()) -> dict:
    """Compute concentration using actual reconciled ledger positions and marks.

    Historical VaR/ES are explicitly unavailable until a dated, eligible
    security-return history is supplied. Never infer unknown sector labels.
    """
    if account.get('status') != 'INTERNALLY_RECONCILED_PAPER_ESTIMATE':
        return {'status':'BLOCKED','code':account.get('code','PAPER_ACCOUNT_UNVERIFIED'),
                'alerts':[],'real_orders_enabled':False}
    positions = account.get('position_details')
    marks = account.get('last_prices')
    equity = account.get('equity')
    if not isinstance(positions,dict) or not isinstance(marks,dict) or not isinstance(equity,(int,float)) or not np.isfinite(equity) or equity<=0:
        return {'status':'BLOCKED','code':'PAPER_RISK_INPUT_UNVERIFIED','alerts':[],'real_orders_enabled':False}
    exposures={}
    sector_weights={}
    missing_sector=[]
    for sid,p in positions.items():
        mark=marks.get(sid)
        q=p.get('quantity') if isinstance(p,dict) else None
        if not isinstance(mark,(int,float)) or not isinstance(q,(int,float)) or not np.isfinite(mark) or not np.isfinite(q) or mark<=0 or q<=0:
            return {'status':'BLOCKED','code':'PAPER_MARK_MISSING','alerts':[],
                    'real_orders_enabled':False,'missing_security_id':sid}
        w=float(mark*q/equity)
        exposures[sid]=w
        sector=p.get('sector')
        if not isinstance(sector,str) or sector.upper() in ('UNKNOWN','', 'N/A'):
            missing_sector.append(sid)
        else:
            sector_weights[sector]=sector_weights.get(sector,0.)+w
    alerts=[]
    for sid,w in exposures.items():
        if w>policy.max_stock_weight+1e-9:
            alerts.append({'code':'STOCK_LIMIT','subject':sid,'actual':w,'limit':policy.max_stock_weight})
    for sector,w in sector_weights.items():
        if w>policy.max_sector_weight+1e-9:
            alerts.append({'code':'SECTOR_LIMIT','subject':sector,'actual':w,'limit':policy.max_sector_weight})
    gross=float(sum(exposures.values()))
    if gross>policy.max_gross_weight+1e-9:
        alerts.append({'code':'GROSS_LIMIT','subject':'portfolio','actual':gross,'limit':policy.max_gross_weight})
    if missing_sector:
        alerts.append({'code':'SECTOR_CLASSIFICATION_UNAVAILABLE','subject':'unclassified',
                       'affected_securities':missing_sector})
    return {'status':'CONCENTRATION_MEASURED','last_session':account.get('last_session'),
            'gross_weight':gross,'position_weights':exposures,'sector_weights':sector_weights,
            'alerts':alerts,'daily_var95':None,'daily_expected_shortfall95':None,
            'historical_return_risk_status':'NOT_EVALUATED_WITH_VERIFIED_INPUTS',
            'real_orders_enabled':False,'research_only':True}
