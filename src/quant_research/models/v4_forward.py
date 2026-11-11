"""V4 forward-only conditional Alpha forecast generation.

Fit using actual known-at-signal outcomes only, separate calibration window,
and a 5-session embargo. Freeze predictions for an as-of trading session
without reading any future return. Predictions remain RESEARCH_ONLY until
separate source, PIT, model and paper admission have been completed.
"""
from __future__ import annotations

from hashlib import sha256
import json

import numpy as np
import pandas as pd

from quant_research.models.v4_oos import OOSProtocol, _canonical, _regressor, _calibrated_probability


def forecast_asof(panel: pd.DataFrame, feature_sets: dict[str,list[str]],
                  exchange_sessions: pd.DatetimeIndex, asof_session,
                  *, source_snapshot_sha256: str,
                  protocol: OOSProtocol = OOSProtocol()) -> dict:
    """Return dated research projections plus model-training evidence.

    The caller supplies independently archived real feature and outcome data.
    A digest is checked for shape, but not treated as vendor PIT certification.
    """
    if (not isinstance(source_snapshot_sha256,str)
            or len(source_snapshot_sha256)!=64
            or any(c not in '0123456789abcdef' for c in source_snapshot_sha256)):
        raise ValueError('Complete input snapshot digest is required')
    if 'entry_time' not in panel:
        raise ValueError('Forward candidate contract needs next-session entry_time')
    values, _, sessions = _canonical(panel,feature_sets,exchange_sessions)
    values['entry_time'] = pd.to_datetime(values.entry_time,utc=True)
    session = pd.Timestamp(asof_session)
    if session.tzinfo is not None or session not in sessions:
        raise ValueError('Forecast date must be a timezone-naive XNYS session')
    chosen = values.loc[values.date.eq(session)].copy()
    if chosen.empty:
        raise ValueError('No true as-of candidate features')
    if (chosen.gross_return.notna().any() or chosen.excess_return.notna().any()
            or chosen.label_available_at.notna().any()):
        raise ValueError('Forward forecast rows must not contain future outcome labels')
    if chosen.feature_available_at.gt(chosen.signal_time).any():
        raise ValueError('Forward input features were not known by their signal time')
    if chosen.signal_time.nunique()!=1 or pd.Timestamp(chosen.signal_time.iloc[0]).tzinfo is None:
        raise ValueError('Ambiguous as-of decision cutoff')
    from quant_research.clock import TradingClock
    exchange=TradingClock()
    for horizon,rows in chosen.groupby('horizon'):
        window=exchange.window(session,int(horizon))
        if not (rows.entry_time.eq(pd.Timestamp(window.entry_time)).all()
                and rows.exit_time.eq(pd.Timestamp(window.exit_time)).all()
                and rows.signal_time.lt(rows.entry_time).all()):
            raise ValueError('Forecast trade windows violate next-session XNYS execution')
    cutoff=chosen.signal_time.iloc[0]
    loc=sessions.get_loc(session)
    last_fit_session=sessions[loc-protocol.gap_sessions-1] if loc>protocol.gap_sessions else None
    if last_fit_session is None:
        return {'status':'INSUFFICIENT_HISTORY','forecasts':pd.DataFrame(),
                'model_cards':pd.DataFrame(),'execution_eligible':False,
                'real_orders_enabled':False}
    eligible_train_days=sessions[max(0,loc-protocol.gap_sessions-protocol.training_window_sessions):
                                 loc-protocol.gap_sessions]
    historical=values.loc[values.date.isin(eligible_train_days)
                          & values.gross_return.notna()
                          & values.excess_return.notna()
                          & values.label_available_at.le(cutoff)
                          & values.exit_time.lt(cutoff)
                          & values.feature_available_at.le(values.signal_time)].copy()
    if historical.empty:
        return {'status':'NO_KNOWN_TRADE_LABEL_HISTORY','forecasts':pd.DataFrame(),
                'model_cards':pd.DataFrame(),'execution_eligible':False,
                'real_orders_enabled':False}
    predictions, cards=[],[]
    for horizon in (1,3,5):
        future=chosen.loc[chosen.horizon.eq(horizon)].copy()
        history=historical.loc[historical.horizon.eq(horizon)].copy()
        if future.empty or history.date.nunique()<protocol.min_training_sessions:
            continue
        calibration_days=sorted(history.date.unique())[-protocol.calibration_sessions:]
        if len(calibration_days)<protocol.calibration_sessions:
            continue
        first_cal=pd.Timestamp(calibration_days[0])
        cal_loc=sessions.get_loc(first_cal)
        last_base=sessions[cal_loc-protocol.gap_sessions-1] if cal_loc>protocol.gap_sessions else None
        if last_base is None:
            continue
        cal=history.loc[history.date.isin(calibration_days)].copy()
        model_history=history.loc[history.date.le(last_base)
              & history.label_available_at.le(cal.signal_time.min())
              & history.exit_time.lt(cal.signal_time.min())].copy()
        if model_history.date.nunique()<protocol.min_training_sessions:
            continue
        for variant,cols in feature_sets.items():
            past=history.dropna(subset=cols)
            train=model_history.dropna(subset=cols)
            calibration=cal.dropna(subset=cols)
            test=future.dropna(subset=cols).copy()
            if (past.date.nunique()<protocol.min_training_sessions
                    or train.date.nunique()<protocol.min_training_sessions or test.empty):
                continue
            if test.duplicated(['date','security_id','horizon']).any():
                raise ValueError('Ambiguous forward candidate identities')
            pred_gross=_regressor(past[cols],past.gross_return,test[cols],protocol.ridge_alpha)
            pred_excess=_regressor(past[cols],past.excess_return,test[cols],protocol.ridge_alpha)
            up,up_status=_calibrated_probability(train,calibration,test,cols,
                                                 lambda x:(x>0).astype(int),protocol)
            downside,down_status=_calibrated_probability(train,calibration,test,cols,
                         lambda x:(x<=protocol.downside_threshold).astype(int),protocol)
            model_data=past[['date','security_id','horizon','gross_return','excess_return']+cols]
            train_hash=sha256(model_data.to_json(orient='records',date_format='iso',
                                               double_precision=12).encode()).hexdigest()
            version_input={'source':source_snapshot_sha256,
                           'train_digest':train_hash,'horizon':horizon,
                           'features':cols,'variant':variant,'cutoff':cutoff.isoformat(),
                           'protocol':protocol.__dict__}
            model_version='v4-forecast-'+sha256(json.dumps(
                version_input,sort_keys=True).encode()).hexdigest()[:20]
            out=test[['date','security_id','horizon','signal_time',
                      'feature_available_at','entry_time','exit_time']].copy()
            out['model_variant']=variant
            out['model_fit_time']=pd.Timestamp.now(tz='UTC')
            out['expected_gross_trade_return']=pred_gross
            out['expected_excess_return']=pred_excess
            out['p_up']=up
            out['p_downside']=downside
            out['probability_status_up']=up_status
            out['probability_status_downside']=down_status
            out['model_version']=model_version
            out['source_snapshot_sha256']=source_snapshot_sha256
            out['research_only']=True
            out['decision_eligible']=False
            predictions.append(out)
            cards.append({'variant':variant,'horizon':horizon,'model_version':model_version,
                          'training_rows':len(past),'training_sessions':past.date.nunique(),
                          'training_last_label_available':past.label_available_at.max(),
                          'calibration_sessions':calibration.date.nunique(),
                          'training_data_sha256':train_hash,
                          'probability_up_status':up_status,
                          'probability_downside_status':down_status,
                          'asof_session':session,
                          'model_fit_time':out['model_fit_time'].iloc[0],
                          'research_only':True})
    forecast=pd.concat(predictions,ignore_index=True) if predictions else pd.DataFrame()
    return {'status':'FORWARD_RESEARCH_PREDICTIONS_ONLY' if not forecast.empty
                     else 'INSUFFICIENT_RESEARCH_TRAINING_EVIDENCE',
            'asof_session':str(session.date()),
            'source_snapshot_sha256':source_snapshot_sha256,
            'forecasts':forecast,'model_cards':pd.DataFrame(cards),
            'execution_eligible':False,'real_orders_enabled':False,
            'limitations':['Forward predictions are not individually PIT-source attested by this calculator',
                           'A calibrated probability does not establish profitable execution',
                           'A separate immutable archive and paper admission are required']}
