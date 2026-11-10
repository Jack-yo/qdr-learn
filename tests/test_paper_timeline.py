"""Read-only ledger admission tests. No quotes, market bars or P&L are created."""
from pathlib import Path

import pytest

from quant_research.policy import PolicyError
from quant_research.workflow.paper_timeline import paper_timeline


def test_missing_paper_account_is_blocked_and_no_db_created(tmp_path):
    result=paper_timeline(tmp_path)
    assert result['status']=='BLOCKED'
    assert result['code']=='NO_ACCEPTED_PAPER_LEDGER'
    assert result['sessions']==[]
    assert result['real_orders_enabled'] is False
    assert result['externally_verified_fills'] is False
    assert not (tmp_path/'data').exists()


@pytest.mark.parametrize('limit',[0,-1,101,1.0,'5',None,True])
def test_timeline_limit_is_bounded_before_access(tmp_path,limit):
    with pytest.raises(PolicyError) as exc:
        paper_timeline(tmp_path,limit=limit)
    assert exc.value.code=='PAPER_TIMELINE_QUERY_INVALID'
    assert not (tmp_path/'data').exists()


def test_cli_reports_missing_actual_account_without_generating_figures(tmp_path,monkeypatch,capsys):
    from quant_research.cli import main
    monkeypatch.chdir(tmp_path)
    code=main(['paper-timeline'])
    assert code==4
    output=capsys.readouterr().out
    assert 'NO_ACCEPTED_PAPER_LEDGER' in output
    assert '"sessions": []' in output
    assert not (tmp_path/'data').exists()


def test_ui_uses_source_observations_and_read_only_account_timeline():
    root=Path(__file__).resolve().parents[1]
    js=(root/'src/quant_research/assets/studio.js').read_text(encoding='utf-8')
    web=(root/'src/quant_research/web.py').read_text(encoding='utf-8')
    assert "'/api/v1/paper/timeline'" in web
    assert "request('/api/v1/paper/timeline')" in js
    assert 'observation.snapshots||[]' in js
    assert 'timeline.sessions||[]' in js
    assert 'externally_verified_fills' in (root/'src/quant_research/workflow/paper_timeline.py').read_text()
