"""Real French factor monitor and export, independent of ETF execution capabilities."""
from datetime import datetime,timezone
import hashlib
import html
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from quant_research.data.french_bundle import load_french_bundle
from quant_research.research.style_monitor import monitor


def calculate(root,asof=None,cutoff=None,mode='observation',start='2017-01-03'):
    bundle=load_french_bundle(root/'data/managed/classic_factors/factors.duckdb',root/'data/raw',start,asof,cutoff,mode)
    history,latest,correlations,metadata=monitor(bundle)
    records=lambda frame:json.loads(frame.to_json(orient='records',date_format='iso'))
    series=history.groupby('factor_name',sort=False).tail(126)
    payload={**metadata,'run_id':None,'generated_at_utc':datetime.now(timezone.utc).isoformat(),
             'data_quality_flags':metadata['limitations'].copy(),
             'latest':records(latest),'series':records(series),'correlations_60d':records(correlations),
             'source_notes':['French现存版本仅用于观察与归因，不代表历史当时已公开。',
                 '滚动值为每日因子收益算术和，非可交易净值或策略回测。',
                 'RF为无风险参考，不参加风格四态分类。',
                 '官方自2025年起改用CIZ数据格式；历史数据可能修订。']}
    return history,latest,correlations,payload


def execute(args):
    cutoff=datetime.fromisoformat(args.cutoff) if args.cutoff else None
    history,latest,correlations,payload=calculate(Path.cwd(),args.asof,cutoff,args.mode,args.start)
    output=args.output/str(uuid4());output.mkdir(parents=True)
    payload['run_id']=output.name
    history.to_parquet(output/'style_history.parquet',index=False)
    history.to_csv(output/'style_history.csv',index=False)
    latest.to_csv(output/'style_summary.csv',index=False)
    correlations.to_csv(output/'correlations_60d.csv',index=False)
    package=Path(__file__).resolve().parents[1]
    payload['code_sha256']=hashlib.sha256(b''.join(p.relative_to(package).as_posix().encode()+p.read_bytes() for p in sorted(package.rglob('*.py')))).hexdigest()
    payload['config_sha256']=hashlib.sha256(json.dumps(payload['protocol'],sort_keys=True).encode()).hexdigest()
    (output/'monitor.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    display=latest[['factor_label','factor_name','sum_5d','sum_20d','sum_60d','volatility_20d_annualized','state','missing_reason']].copy()
    for col in ['sum_5d','sum_20d','sum_60d','volatility_20d_annualized']:display[col]=display[col]*100
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>经典因子观察报告</title><style>body{font:15px system-ui;margin:32px}td,th{padding:10px;border-bottom:1px solid #ccc}pre{white-space:pre-wrap}.notice{padding:18px;background:#fff0c9}</style><h1>经典因子观察报告</h1><p class="notice">当前版本观察/归因；非预测、回测收益或交易建议。滚动算术和与年化波动的显示单位为百分比；RF只作参考。</p><p>因子日期：'+html.escape(payload['asof_date_et'])+'；知识截止：'+html.escape(payload['data_cutoff_utc'])+'</p>'+display.to_html(index=False,escape=True,na_rep='N/A')+'<details><summary>真实来源、方法与限制</summary><pre>'+html.escape(json.dumps({k:v for k,v in payload.items() if k not in ('latest','series','correlations_60d')},indent=2,ensure_ascii=False))+'</pre></details></html>'
    (output/'report.html').write_text(page,encoding='utf-8')
    payload['artifacts_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}
    (output/'manifest.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    pointer={'run_id':output.name,'manifest':str((output/'manifest.json').resolve()),'snapshot_sha256':payload['snapshot_sha256']}
    from quant_research.data.http import atomic_write
    atomic_write(Path('data/managed/classic_factors/monitor_latest.json'),json.dumps(pointer,indent=2).encode())
    atomic_write(Path('data/managed/classic_factors')/('monitor_latest_'+args.mode+'.json'),json.dumps(pointer,indent=2).encode())
    print(json.dumps({'output':str(output.resolve()),'status':payload['status'],'asof':payload['asof_date_et'],
                      'verified_rows':payload['rows'],'latest_factors':len(latest)}),flush=True)
    return 0 if payload['status']=='DESCRIPTIVE_CURRENT_VINTAGE_ONLY' else 4
