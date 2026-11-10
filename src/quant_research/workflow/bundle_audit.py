"""A real current-vintage quote report, not a forecast or execution report."""
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from quant_research.data.bundle import load_real_bundle
from quant_research.clock import TradingClock


def timing_coverage(frame):
    """Coverage of selected receipt-backed versions, with an independent entry boundary."""
    clock = TradingClock()
    dates = pd.to_datetime(frame.date)
    windows = {day: clock.window(day, 1) for day in dates.unique()}
    signal = dates.map({day: window.signal_time for day, window in windows.items()})
    entry = dates.map({day: window.entry_time for day, window in windows.items()})
    known = frame[["available_at", "ingested_at"]].max(axis=1)
    tagged = frame[["symbol"]].assign(
        known_at_signal=known.le(signal),
        known_before_next_open=known.lt(entry),
        permanent_identity_unverified=frame.security_id.str.contains("SYMBOL-UNVERIFIED:", regex=False),
    )
    return tagged.groupby("symbol").agg(
        selected_rows=("known_at_signal", "size"),
        known_at_signal=("known_at_signal", "sum"),
        known_before_next_open=("known_before_next_open", "sum"),
        permanent_identity_unverified=("permanent_identity_unverified", "sum"),
    ).reset_index()


def execute(args):
    cutoff=datetime.fromisoformat(args.cutoff) if args.cutoff else None
    bundle=load_real_bundle(args.db,args.source,args.asof,cutoff,raw_root=args.data_dir/'raw')
    bundle.require('observation')
    output=args.output/str(uuid4());output.mkdir(parents=True)
    frame=bundle.prices
    latest=frame.loc[pd.to_datetime(frame.date).eq(pd.Timestamp(bundle.metadata['asof_date_et']))]
    columns=['symbol','date','open','high','low','close','volume','adjustment_basis','available_at','raw_sha256']
    latest[columns].to_csv(output/'quotes.csv',index=False)
    timing = timing_coverage(frame)
    timing.to_csv(output/'timing_coverage.csv',index=False)
    manifest={**bundle.metadata,'run_id':output.name,'stage':'G4','status':'OBSERVATION_ONLY',
        'model_version':None,'data_cutoff_utc':bundle.metadata['knowledge_cutoff_utc'],
        'dataset_capabilities':bundle.capabilities,'prediction_rows':0,'modelled_fills':0,
        'selected_version_timing':{name:int(timing[name].sum()) for name in timing if name!='symbol'},
        'research_grade':False,'execution_ready':False,'sealed_test_used':False}
    package=Path(__file__).resolve().parents[1]
    manifest['code_sha256']=hashlib.sha256(b''.join(p.relative_to(package).as_posix().encode()+p.read_bytes() for p in sorted(package.rglob('*.py')))).hexdigest()
    text='<!doctype html><meta charset="utf-8"><title>真实行情与能力审计</title><style>body{font:15px system-ui;margin:32px}td,th{padding:8px;border:1px solid #ccc}pre{white-space:pre-wrap}</style><h1>真实行情观察 · 无预测／成交</h1><p>价格为标示口径；当前版本回看不代表历史当时已知。raw跨期收益未做公司行为调整，禁止据此生成策略收益或因子。</p>'+latest[columns].to_html(index=False,escape=True)+'<h2>能力证据</h2><pre>'+html.escape(json.dumps(manifest,ensure_ascii=False,indent=2))+'</pre>'
    text += '<h2>所选版本的实际回执覆盖</h2>'+timing.to_html(index=False,escape=True)
    (output/'report.html').write_text(text,encoding='utf-8')
    manifest['artifacts_sha256']={n:hashlib.sha256((output/n).read_bytes()).hexdigest() for n in ('quotes.csv','timing_coverage.csv','report.html')}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'output':str(output.resolve()),'status':manifest['status'],'rows':len(latest),'verified_price_rows':len(frame)}),flush=True)
    return 0
