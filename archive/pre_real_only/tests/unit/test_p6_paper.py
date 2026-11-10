import pytest

from quant_research.backtest.paper import PaperLedger
from quant_research.clock import TradingClock
from quant_research.data.providers.stream_fixture import stream_fixture_records
from quant_research.models.settings import load_settings


def test_fixture_extension_cannot_rewrite_history():
    clock=TradingClock()
    first,_=stream_fixture_records(clock,"2024-11-01","2024-11-27")
    extended,_=stream_fixture_records(clock,"2024-11-01","2024-11-29")
    keys=lambda rows:[r.model_dump(exclude={"raw_sha256"}) for r in rows if str(r.date)<="2024-11-27"]
    assert keys(first)==keys(extended)


def test_paper_restart_idempotency_and_atomic_failure(tmp_path):
    config=load_settings("configs/experiments/baseline.yaml")
    clock=TradingClock()
    signal={"security_id":"A","symbol":"A","sector":"UNKNOWN","signal_time":str(clock.signal("2024-11-27")),
        "feature_available_at":str(clock.close("2024-11-27")),"exit_date":"2024-12-03","adv20":1e8,"atr20":1.0,"decision_eligible":True,"adjustment_basis":"raw"}
    bars={"A":{"open":100.0,"close":100.0,"low":99.0,"high":101.0,"volume":1000000}}
    path=tmp_path/"paper.sqlite3"
    with PaperLedger(path,config,clock) as ledger:
        first,changed=ledger.advance("2024-11-27",bars,[signal])
        assert changed and not first["positions"]
        repeat,changed=ledger.advance("2024-11-27",bars,[signal])
        assert repeat==first and not changed
    with PaperLedger(path,config,clock) as ledger:
        second,changed=ledger.advance("2024-11-29",bars,[])
        assert changed and second["positions"]
        with pytest.raises(ValueError,match="exactly one"):
            ledger.advance("2024-12-03",bars,[])
        assert ledger.db.execute("SELECT count(*) FROM days").fetchone()[0]==2
        third,_=ledger.advance("2024-12-02",bars,[])
        assert third["positions"]
        fourth,_=ledger.advance("2024-12-03",bars,[])
        assert not fourth["positions"]
        cash=ledger.db.execute("SELECT sum(cash_change) FROM events").fetchone()[0]
        assert fourth["cash"]==pytest.approx(config.initial_cash+cash)
        with pytest.raises(ValueError,match="requires verified"):
            ledger.advance("2024-12-04",bars,[],source="yahoo",adjustment_basis="yahoo_split_adjusted")


def test_live_forecast_after_seal_never_reads_heldout_outcomes():
    import pandas as pd
    from quant_research.features.context import make_context
    from quant_research.models.dataset import prepare
    clock=TradingClock()
    records,_=stream_fixture_records(clock,"2024-10-01","2025-01-03")
    context=make_context(pd.DataFrame([r.model_dump() for r in records]),clock)
    frame,_,_,_=prepare(context,clock,"strict","raw",label_end="2024-12-31",forecast_dates=["2025-01-03"])
    forecast=frame.loc[frame.date.eq(pd.Timestamp("2025-01-03"))]
    assert len(forecast)==17*3
    assert forecast.target.isna().all() and forecast.benchmark_target.isna().all()
    assert set(forecast.label_kind)=={"LIVE_FORECAST_NO_OUTCOME_READ"}
    assert frame.loc[frame.target.notna(),"exit_date"].astype(str).max()<="2024-12-31"
