from datetime import datetime, timezone
import hashlib
import html
import importlib.metadata
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from quant_research.data.store import Warehouse


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str,allow_nan=False).encode()).hexdigest()


def new_run(args,config,stage,prices):
    from quant_research.policy import require_real_source, require_real_frame
    require_real_source(args.source)
    if len(prices): require_real_frame(prices)
    now,run_id = datetime.now(timezone.utc),str(uuid4())
    root = Path(__file__).resolve().parents[1]
    output = args.output/run_id
    output.mkdir(parents=True,exist_ok=False)
    manifest = {"run_id":run_id,"stage":stage,"created_at_utc":now.isoformat(),"asof_timestamp_utc":now.isoformat(),
        "data_cutoff_utc":now.isoformat(),"source":args.source,"mode":args.mode,
        "universe_version":"current-etf-not-pit-v1",
        "model_version":config.experiment_id,"config_sha256":fingerprint(config.model_dump(mode="json")),
        "data_sha256":hashlib.sha256(prices.to_json(orient="records",date_format="iso").encode()).hexdigest(),
        "code_sha256":hashlib.sha256(b"".join(p.relative_to(root).as_posix().encode()+p.read_bytes() for p in sorted(root.rglob("*.py")))).hexdigest(),
        "experiment":config.model_dump(mode="json"),"input_rows":len(prices),
        "input_last_date":str(pd.Timestamp(prices.date.max()).date()) if len(prices) else None,
        "status":"NOT_READY","research_grade":False,"sealed_test_used":False,"real_orders_enabled":False,
        "flags":["EXPLORATORY","SURVIVORSHIP_BIASED","NOT_HISTORICAL_PIT"] + ([] if len(prices) and set(prices.adjustment_basis)=={"raw"} else ["NOT_RAW_EXECUTION_PRICE"]),
        "runtime_versions":{n:importlib.metadata.version(n) for n in ["pandas","numpy","scikit-learn","duckdb"]}}
    (output/"config.json").write_text(json.dumps(config.model_dump(mode="json"),indent=2),encoding="utf-8")
    return output,manifest


def finish(args,output,manifest,*,register=True):
    files = {}
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name not in ("manifest.json","run.log"):
            files[path.relative_to(output).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest["artifacts_sha256"] = files
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False,default=str,allow_nan=False),encoding="utf-8")
    (output/"run.log").write_text(f"{datetime.now(timezone.utc).isoformat()} run_id={manifest['run_id']} status={manifest['status']}\n",encoding="utf-8")
    if register:
        with Warehouse(args.db) as store:
            store.insert_rows("runs",[{**{k:manifest[k] for k in ["run_id","created_at_utc","asof_timestamp_utc","data_cutoff_utc","universe_version","model_version","config_sha256","data_sha256","status"]},"manifest_json":json.dumps(manifest,default=str)}])
    print(json.dumps({"run_id":manifest["run_id"],"stage":manifest["stage"],"status":manifest["status"],"output":str(output.resolve())}),flush=True)


def save_frame(frame,output,name):
    frame.to_parquet(output/(name+".parquet"),index=False)
    frame.to_csv(output/(name+".csv"),index=False)


def line_svg(series,title):
    values = pd.to_numeric(series,errors="coerce").dropna()
    if values.empty:
        return '<p>'+html.escape(title)+'：无可用数据</p>'
    # Keep every endpoint in summaries; chart is a bounded display sample only.
    if len(values)>700:
        values = values.iloc[sorted(set([int(i*(len(values)-1)/699) for i in range(700)]))]
    low,high = float(values.min()),float(values.max())
    span = high-low or 1
    points = " ".join(f"{40+i/max(len(values)-1,1)*700:.2f},{165-(float(v)-low)/span*130:.2f}" for i,v in enumerate(values))
    return f'<h3>{html.escape(title)}</h3><svg viewBox="0 0 780 200" width="780" role="img" aria-label="{html.escape(title)}"><text x="2" y="18" font-size="11">{high:.5f}</text><text x="2" y="185" font-size="11">{low:.5f}</text><polyline points="{points}" fill="none" stroke="#2563eb" stroke-width="1.5"/></svg>'


def report(output,title,manifest,tables,charts=(),note=""):
    header = ('VERIFIED HISTORICAL RESEARCH · MODELED FILLS'
              if manifest.get('status')=='MODELED_HISTORICAL_FILLS_NOT_BROKER_ORDERS'
              and manifest.get('research_grade') is True
              and manifest.get('historical_decision_eligible') is True
              else 'NOT_READY')
    body = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+html.escape(title)+'</title><style>body{font:15px system-ui;margin:32px;max-width:1300px;color:#172033}.notice{padding:18px;background:#fff3dc;border-left:5px solid #d97706}table{display:block;overflow:auto;border-collapse:collapse;font-size:12px}td,th{padding:7px;border:1px solid #ddd}svg{max-width:100%}pre{white-space:pre-wrap}</style><h1>'+html.escape(title)+'</h1><div class="notice"><strong>'+html.escape(header)+' / '+html.escape(manifest["source"].upper())+'</strong><p>'+html.escape(note or '仅工程或探索性研究；不是已验证盈利或实盘可交易信号。')+'</p></div>'
    body += "".join(charts)
    for name,table in tables.items():
        body += '<h2>'+html.escape(name)+'</h2>'+table.to_html(index=False,na_rep="缺失",escape=True)
    body += '<details><summary>来源、参数与运行元信息</summary><pre>'+html.escape(json.dumps(manifest,indent=2,ensure_ascii=False,default=str))+'</pre></details></html>'
    (output/"report.html").write_text(body,encoding="utf-8")
