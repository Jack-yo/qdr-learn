"""Mathematical as-of universe contract tests, not real PIT data evidence."""
import pandas as pd
import pytest

from quant_research.data.v4_universe import reconstruct_asof_stock_universe


def _fixture():
    sessions=pd.bdate_range('2026-03-02',periods=3)
    source='a'*64
    members=pd.DataFrame([
        {'session_date':day,'security_id':sid,'symbol':sid,'security_type':'COMMON_STOCK',
         'listed':True,'tradable':True,'observed_at':pd.Timestamp(day).tz_localize('UTC')+pd.Timedelta(hours=21,minutes=5),
         'source_sha256':source}
        for day in sessions for sid in ('AAA','BBB')
    ])
    receipts=pd.DataFrame([
        {'session_date':day,'capture_finished_at':pd.Timestamp(day).tz_localize('UTC')+pd.Timedelta(hours=21,minutes=10),
         'source_sha256':source,'full_snapshot':True}
        for day in sessions
    ])
    signals={day:pd.Timestamp(day).tz_localize('UTC')+pd.Timedelta(hours=21,minutes=15) for day in sessions}
    return sessions,members,receipts,signals


def test_universe_stays_research_only_without_raw_source_audit():
    dates,members,receipts,signals=_fixture()
    panel,status=reconstruct_asof_stock_universe(members,receipts,dates,signals)
    assert len(panel)==6 and status['requested_sessions']==3
    assert not status['source_independently_attested'] and not status['real_orders_enabled']


def test_historical_snapshot_arriving_after_signal_is_rejected():
    dates,members,receipts,signals=_fixture()
    receipts.loc[0,'capture_finished_at']=pd.Timestamp('2026-03-03T02:00:00Z')
    with pytest.raises(ValueError,match='known by signal'):
        reconstruct_asof_stock_universe(members,receipts,dates,signals)


def test_missing_snapshot_and_duplicate_member_rejected():
    dates,members,receipts,signals=_fixture()
    with pytest.raises(ValueError,match='Missing entire'):
        reconstruct_asof_stock_universe(members,receipts.iloc[:2],dates,signals)
    with pytest.raises(ValueError,match='Ambiguous'):
        reconstruct_asof_stock_universe(pd.concat([members,members.iloc[:1]]),receipts,dates,signals)


def test_current_snapshot_must_not_be_backfilled_into_history():
    dates,members,receipts,signals=_fixture()
    members['observed_at']=pd.Timestamp('2026-11-11T20:00:00Z')
    receipts['capture_finished_at']=pd.Timestamp('2026-11-11T20:00:00Z')
    with pytest.raises(ValueError,match='known by signal'):
        reconstruct_asof_stock_universe(members,receipts,dates,signals)
