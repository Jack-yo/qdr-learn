"""Source-free refusal and product-state contract, never mock market values."""
from pathlib import Path
import pytest

from quant_research.policy import PolicyError
from quant_research.workflow.research_readiness import research_readiness


def test_no_real_inputs_yield_actionable_blockers_without_writes(tmp_path):
    result=research_readiness(tmp_path)
    assert result['status']=='NOT_READY'
    assert result['real_orders_enabled'] is False
    assert result['complete_product_acceptance'] is False
    assert result['historical_backtest_data_eligible'] is False
    assert result['forward_shadow_data_eligible'] is False
    assert result['stages']['dataset']['code']=='NO_REAL_DATA'
    assert result['stages']['strategy_versions']['code']=='NO_FROZEN_STRATEGY'
    assert result['stages']['verified_backtest_runs']['status']=='BLOCKED'
    assert result['stages']['paper_account']['status']=='BLOCKED'
    assert len(result['next_steps']) > 5
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('date_value', ['2099-01-01','2026/11/10','not-a-date','2024-02-30', 0, '2024-01-01T00:00:00Z'])
def test_bad_or_future_date_rejected(tmp_path,date_value):
    with pytest.raises(PolicyError) as exc:
        research_readiness(tmp_path,asof=date_value)
    assert exc.value.code=='READINESS_ASOF_INVALID'
    assert not list(tmp_path.iterdir())


def test_external_database_path_rejected_without_reading(tmp_path):
    with pytest.raises(PolicyError) as exc:
        research_readiness(tmp_path,db='../outside.db')
    assert exc.value.code=='READINESS_DB_PATH_INVALID'
    assert not list(tmp_path.iterdir())


def test_unknown_source_flags_cannot_enable_signals(tmp_path):
    # An arbitrary file named 'latest.json' is not a real provider response.
    folder=tmp_path/'data/managed/asset_observations'
    folder.mkdir(parents=True)
    (folder/'latest.json').write_text('{}',encoding='utf-8')
    result=research_readiness(tmp_path)
    assert result['stages']['asset_directory']['status']=='BLOCKED'
    assert result['forward_shadow_data_eligible'] is False
    assert result['complete_product_acceptance'] is False
