"""Structural/source-chain tests only: no generated market bars, labels or returns.

The empty corporate-actions JSON objects below test a pagination *protocol*,
not market data or a successful real-world provider query.
"""
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import pytest

from quant_research.data.action_pages import audit_action_pages, _checked_query, _key, ENDPOINT
from quant_research.backtest.verified_results import list_verified_backtests, verified_backtest
from quant_research.policy import PolicyError


BASE={'symbols':['AAPL'], 'start':'2024-01-01', 'end':'2024-12-31', 'page_size':1000}


def _save_protocol_page(root, params, token=None, when=None, events=None):
    folder=Path(root)/'data/raw'; (folder/'receipts').mkdir(parents=True,exist_ok=True)
    (folder/'objects').mkdir(parents=True,exist_ok=True)
    raw=json.dumps({'corporate_actions':{'splits':events or []},'next_page_token':token}).encode()
    digest=sha256(raw).hexdigest();(folder/'objects'/digest).write_bytes(raw)
    receipt={'url':ENDPOINT,'params':params,'sha256':digest,
             'request_key':_key(params),'fetched_at':(when or datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()}
    (folder/'receipts'/(str(uuid4())+'.json')).write_text(json.dumps(receipt))
    return digest


def test_no_source_does_not_invent_action_coverage(tmp_path):
    with pytest.raises(PolicyError) as exc: audit_action_pages(tmp_path,**BASE)
    assert exc.value.code=='ACTION_RECEIPTS_MISSING'
    assert not (tmp_path/'data').exists()


@pytest.mark.parametrize('change',[
    {'symbols':[]},{'symbols':['aapl']},{'symbols':['AAPL','AAPL']},
    {'start':'bad'},{'end':'2023-12-31'},{'page_size':0},
    {'asof_utc':'2024-01-01'},{'asof_utc':'2099-01-01T00:00:00+00:00'},
    {'max_pages':0},
])
def test_invalid_source_query_blocks(tmp_path,change):
    with pytest.raises(PolicyError):audit_action_pages(tmp_path,**{**BASE,**change})


def test_single_protocol_page_proves_only_exact_query(tmp_path):
    params=_checked_query(**BASE)
    _save_protocol_page(tmp_path,params)
    result=audit_action_pages(tmp_path,**BASE)
    assert result['source_query_pagination_complete'] is True
    assert result['verified_page_count']==1
    assert result['unique_source_event_count']==0
    assert result['full_historical_action_coverage_verified'] is False
    assert result['historical_pit_eligible'] is False
    assert result['historical_backtest_eligible'] is False
    assert result['real_orders_enabled'] is False
    with pytest.raises(PolicyError) as exc:
        audit_action_pages(tmp_path,**{**BASE,'symbols':['MSFT']})
    assert exc.value.code=='ACTION_FIRST_PAGE_MISSING'


def test_two_page_source_chain_cannot_be_silently_shortened(tmp_path):
    first=_checked_query(**BASE)
    now=datetime.now(timezone.utc)-timedelta(hours=1)
    _save_protocol_page(tmp_path,first,token='page-2',when=now)
    with pytest.raises(PolicyError) as exc: audit_action_pages(tmp_path,**BASE)
    assert exc.value.code=='ACTION_PAGE_CHAIN_INCOMPLETE'
    _save_protocol_page(tmp_path,{**first,'page_token':'page-2'},when=now+timedelta(seconds=1))
    d=audit_action_pages(tmp_path,**BASE)
    assert d['verified_page_count']==2 and d['source_query_pagination_complete']
    assert not d['settlement_verified']


def test_response_change_blocks_even_when_receipt_unchanged(tmp_path):
    params=_checked_query(**BASE)
    digest=_save_protocol_page(tmp_path,params)
    (tmp_path/'data/raw/objects'/digest).write_bytes(b'corrupt')
    with pytest.raises(PolicyError) as exc:audit_action_pages(tmp_path,**BASE)
    assert exc.value.code=='ACTION_PAGE_HASH_MISMATCH'


def test_repeated_event_ids_never_certify_chain(tmp_path):
    params=_checked_query(**BASE)
    now=datetime.now(timezone.utc)-timedelta(hours=1)
    _save_protocol_page(tmp_path,params,token='next',when=now,events=[{'id':'same-id'}])
    _save_protocol_page(tmp_path,{**params,'page_token':'next'},when=now+timedelta(seconds=1),events=[{'id':'same-id'}])
    with pytest.raises(PolicyError) as exc:audit_action_pages(tmp_path,**BASE)
    assert exc.value.code=='ACTION_PAGE_DUPLICATE_EVENTS'


def test_prior_source_not_known_before_fetch(tmp_path):
    params=_checked_query(**BASE)
    now=datetime.now(timezone.utc)-timedelta(hours=1)
    _save_protocol_page(tmp_path,params,when=now)
    with pytest.raises(PolicyError) as exc:audit_action_pages(tmp_path,**{**BASE,'asof_utc':(now-timedelta(seconds=1)).isoformat()})
    assert exc.value.code=='ACTION_FIRST_PAGE_MISSING'


def test_backtest_no_archive_never_returns_demo_numbers(tmp_path):
    response=list_verified_backtests(tmp_path)
    assert response['status']=='BLOCKED' and response['results']==[]
    assert response['real_orders_enabled'] is False
    with pytest.raises(PolicyError) as exc:verified_backtest(tmp_path,'../fake')
    assert exc.value.code=='BACKTEST_RUN_ID_INVALID'
    with pytest.raises(PolicyError) as exc:verified_backtest(tmp_path,str(uuid4()))
    assert exc.value.code=='BACKTEST_MANIFEST_UNAVAILABLE'


def test_backtest_unverified_manifest_cannot_be_viewed(tmp_path):
    run=str(uuid4());folder=tmp_path/'outputs/system'/run;folder.mkdir(parents=True)
    (folder/'manifest.json').write_text(json.dumps({'run_id':run,'stage':'P5','source':'ALPACA',
                 'status':'MODELED_HISTORICAL_FILLS_NOT_BROKER_ORDERS','historical_decision_eligible':False}))
    with pytest.raises(PolicyError) as exc:verified_backtest(tmp_path,run)
    assert exc.value.code=='BACKTEST_RUN_NOT_VERIFIED'
    assert list_verified_backtests(tmp_path)['results']==[]


def test_four_layer_missing_strategy_is_blocked(tmp_path):
    from quant_research.research.four_layers import evaluate_four_layers
    with pytest.raises(PolicyError) as exc:evaluate_four_layers(tmp_path,str(uuid4()))
    assert exc.value.code=='STRATEGY_NOT_FOUND'


def test_g9_price_regime_fails_without_real_prices():
    import pandas as pd
    from quant_research.research.four_layers import _price_regimes
    with pytest.raises(PolicyError) as exc:_price_regimes(pd.DataFrame())
    assert exc.value.code=='G9_PRICE_FIELDS_MISSING'
