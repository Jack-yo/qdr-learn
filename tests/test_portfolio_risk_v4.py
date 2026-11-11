"""V4 portfolio risk unit tests; test arrays are not claimed as market data."""
import numpy as np
import pandas as pd
import pytest

from quant_research.risk.portfolio import RiskPolicy, assess_portfolio


def _inputs():
    positions = pd.DataFrame([
        {'security_id':'A','weight':0.15,'sector':'Tech','beta':1.5},
        {'security_id':'B','weight':0.14,'sector':'Tech','beta':0.8},
    ])
    sessions = pd.bdate_range('2025-01-02', periods=90)
    x = np.sin(np.arange(90)*0.2)*0.01
    returns = pd.DataFrame({'A':x,'B':x*0.5}, index=sessions)
    return positions, returns


def test_risk_metrics_and_alerts():
    p,r = _inputs()
    result = assess_portfolio(p,r,r.index[-1],RiskPolicy(max_stock_weight=.1,max_sector_weight=.25))
    assert result['status']=='RISK_MEASURED' and not result['source_attested']
    assert result['gross_weight']==pytest.approx(.29)
    assert result['weighted_market_beta']==pytest.approx(.15*1.5+.14*.8)
    codes={x['code'] for x in result['alerts']}
    assert {'STOCK_LIMIT','SECTOR_LIMIT'} <= codes
    assert result['daily_expected_shortfall95']>=result['daily_var95']>=0


def test_future_missing_and_duplicate_inputs_rejected():
    p,r=_inputs()
    with pytest.raises(ValueError,match='future'):assess_portfolio(p,r,r.index[-2])
    missing=r.copy();missing.iloc[-1,0]=np.nan
    with pytest.raises(ValueError,match='Incomplete'):assess_portfolio(p,missing,r.index[-1])
    duplicate=pd.concat([p,p.iloc[:1]])
    with pytest.raises(ValueError,match='Duplicate'):assess_portfolio(duplicate,r,r.index[-1])


def test_no_positions_is_not_fabricated_risk():
    _,r=_inputs()
    result=assess_portfolio(pd.DataFrame(columns=['security_id','weight','sector','beta']),r,r.index[-1])
    assert result['status']=='EMPTY_PORTFOLIO' and result['alerts']==[]



def test_concentration_uses_real_paper_marks_and_blocks_missing_evidence():
    from quant_research.risk.portfolio import assess_paper_concentration
    account={'status':'INTERNALLY_RECONCILED_PAPER_ESTIMATE','equity':1000,
             'last_session':'2025-01-20','last_prices':{'S1':20},
             'position_details':{'S1':{'quantity':10,'sector':'UNKNOWN'}}}
    output=assess_paper_concentration(account)
    assert output['status']=='CONCENTRATION_MEASURED'
    assert output['position_weights']['S1']==pytest.approx(.2)
    assert {'STOCK_LIMIT','SECTOR_CLASSIFICATION_UNAVAILABLE'} <= {x['code'] for x in output['alerts']}
    assert output['daily_var95'] is None
    del account['last_prices']
    assert assess_paper_concentration(account)['status']=='BLOCKED'
