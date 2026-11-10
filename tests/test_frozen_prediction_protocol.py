"""Protocol-only isolated matrices. Values here are not market observations or performance evidence."""
from datetime import date
import pandas as pd
import pytest

from quant_research.clock import TradingClock
from quant_research.policy import PolicyError
from quant_research.validation.frozen_predictions import validate_frozen_predictions


class ProtocolOnly:
    start = date(2017,1,3)
    validation_end = date(2024,12,31)
    horizons = [1,3,5]


def schema_only_matrix():
    clock = TradingClock()
    day = '2024-01-02'
    rows = []
    for h in (1,3,5):
        w = clock.window(day,h)
        rows.append({
            'date':day, 'security_id':'PROTOCOL-ONLY-1', 'symbol':'SCHEMA', 'sector':'TEST_SECTOR',
            'horizon':h,'variant':'D','decision_eligible':True,
            'signal_time':w.signal_time.isoformat(),
            'feature_available_at':(pd.Timestamp(w.signal_time)-pd.Timedelta(minutes=1)).isoformat(),
            'fit_time':(pd.Timestamp(w.signal_time)-pd.Timedelta(minutes=30)).isoformat(),
            'entry_time':w.entry_time.isoformat(),'exit_time':w.exit_time.isoformat(),
            'adv20':25_000_000.,'atr20':2.,'reference_close':100.,
            'predicted_return':0.01,'expected_excess_return':0.01,'downside_quantile':-0.02,
            'reversal_5d':0.02,'model_version':'PROTOCOL_ONLY',
        })
    predictions = pd.DataFrame(rows)
    prices=pd.DataFrame([{'date':day,'security_id':'PROTOCOL-ONLY-1','symbol':'SCHEMA',
                          'close':100.,'source':'ALPACA','adjustment_basis':'raw'}])
    return predictions,prices,clock


def audit(change=None):
    predictions,prices,clock = schema_only_matrix()
    if change: change(predictions,prices)
    return validate_frozen_predictions(predictions,prices,clock,ProtocolOnly())


def test_protocol_accepts_internal_consistent_unpublished_matrix_only():
    r=audit()
    assert r['rows']==3 and r['status']=='ROW_INTEGRITY_VERIFIED_NOT_INDEPENDENT_MODEL_ATTESTATION'
    assert r['real_orders_enabled'] is False


@pytest.mark.parametrize('edit,code',[
    (lambda p,b:p.__setitem__('actual_return', 0.5),'FROZEN_LABELS_PRESENT'),
    (lambda p,b:p.loc.__setitem__((0,'fit_time'),'2024-01-03T20:00:00Z'),'FROZEN_FUTURE_INPUT'),
    (lambda p,b:p.loc.__setitem__((0,'entry_time'),'2024-01-03T15:00:00Z'),'FROZEN_TRADING_CLOCK_MISMATCH'),
    (lambda p,b:p.loc.__setitem__((0,'signal_time'),'2024-01-02T21:20:00Z'),'FROZEN_TRADING_CLOCK_MISMATCH'),
    (lambda p,b:p.loc.__setitem__((0,'security_id'),'WRONG-ID'),'FROZEN_IDENTITY_PRICE_MISMATCH'),
    (lambda p,b:p.loc.__setitem__((0,'reference_close'),99.9),'FROZEN_PRICE_ANCHOR_CHANGED'),
    (lambda p,b:p.loc.__setitem__((0,'decision_eligible'),False),'FROZEN_SIGNAL_INELIGIBLE'),
    (lambda p,b:p.loc.__setitem__((0,'sector'),'UNKNOWN'),'FROZEN_SECTOR_UNVERIFIED'),
    (lambda p,b:p.__setitem__('research_mode','retrospective'),'FROZEN_RESEARCH_MODE_INVALID'),
    (lambda p,b:p.loc.__setitem__((0,'date'),'2025-01-02'),'FROZEN_TEST_SEAL_VIOLATION'),
    (lambda p,b:p.loc.__setitem__((0,'adv20'),float('nan')),'FROZEN_NUMERIC_INVALID'),
    (lambda p,b:p.loc.__setitem__((0,'horizon'),2),'FROZEN_HORIZON_INVALID'),
    (lambda p,b:p.loc.__setitem__((0,'feature_available_at'),'2024-01-03T00:00:00Z'),'FROZEN_FUTURE_INPUT'),
    (lambda p,b:p.loc.__setitem__((0,'fit_time'),'2024-01-02T20:00:00'),'FROZEN_TIME_INVALID'),
])
def test_fail_closed_schema_rules(edit,code):
    with pytest.raises(PolicyError) as exc:
        audit(edit)
    assert exc.value.code==code
