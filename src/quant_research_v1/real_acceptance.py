"""Offline P1-P6 acceptance on an immutable copy of the free real-data warehouse."""
import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

from .data.store import duckdb
from .policy import SYMBOLS


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def freeze_database(source, destination):
    if not source.is_file():
        raise ValueError("Real warehouse is missing; ingest real data first")
    # A copied main file without its outstanding WAL is not a database snapshot.
    if Path(str(source) + ".wal").exists():
        raise ValueError("Outstanding WAL: close the warehouse writer and checkpoint before acceptance")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(source), read_only=True) as db:
        count = db.execute("SELECT count(*) FROM prices_daily WHERE source='YAHOO'").fetchone()[0]
        if not count:
            raise ValueError("No real Yahoo prices; fixture fallback is prohibited")
        if destination.exists():
            raise ValueError("Snapshot destination already exists")
        shutil.copyfile(source, destination)
        if sha(source) != sha(destination):
            raise ValueError("Warehouse changed during snapshot")
    return sha(destination)


def commands(database, output, end):
    common = ["--source", "yahoo", "--db", str(database), "--output", str(output)]
    return [
        ("P1", ["data-audit", *common, "--offline", "--start", "2017-01-03", "--end", end, "--symbols", ",".join(SYMBOLS)]),
        ("P2", ["factor-report", *common, "--mode", "retrospective"]),
        ("P3", ["train-market", *common, "--mode", "retrospective"]),
        ("P4", ["train", *common, "--mode", "retrospective"]),
        ("P5", ["backtest", *common, "--mode", "strict"]),
        ("P6", ["daily-report", *common, "--mode", "retrospective", "--asof", end]),
    ]


def classify(stage, code, manifest):
    if code not in (0, 4):
        return "FAILED"
    if stage in ("P5", "P6"):
        return "DATA_BLOCKED"  # Explicitly never infer execution readiness from exit 0.
    if not manifest:
        return "FAILED_MISSING_MANIFEST"
    if stage == "P1":
        return "FREE_DATA_COVERAGE_PASS" if manifest.get("coverage_complete") else "DATA_BLOCKED"
    if stage == "P4" and not manifest.get("prediction_rows"):
        return "DATA_BLOCKED"
    return "EXPLORATORY_COMPUTATION_PASS" if code == 0 else "DATA_BLOCKED"


def run(source, output):
    run_id = str(uuid4())
    root = output.resolve() / run_id
    root.mkdir(parents=True)
    database = root / "snapshot.duckdb"
    original_hash = freeze_database(source.resolve(), database)
    with duckdb.connect(str(database), read_only=True) as db:
        end = str(db.execute("SELECT max(date) FROM prices_daily WHERE source='YAHOO'").fetchone()[0])
    result = {"run_id":run_id, "created_at_utc":datetime.now(timezone.utc).isoformat(),
              "source":"YAHOO", "source_database_sha256":original_hash,
              "snapshot":str(database), "last_observed_session":end, "offline":True,
              "research_grade":False, "execution_ready":False, "real_orders_enabled":False,
              "final_test_status":"SEALED", "stages":[],
              "blocking_data":["PIT_UNIVERSE_AND_DELISTED_HISTORY", "STABLE_SECURITY_IDENTITIES",
                               "VERIFIED_RAW_PRICES_AND_CORPORATE_ACTIONS", "HISTORICAL_PIT_FUNDAMENTALS"],
              "scope":"20 current ETF proxies; not a historical individual-stock universe"}
    for stage, command in commands(database, root / "stages", end):
        before = set((root / "stages").glob("*/manifest.json"))
        log = root / f"{stage}.log"
        with log.open("w", encoding="utf-8") as stream:
            try:
                process = subprocess.run([sys.executable, "-m", "quant_research.cli", *command],
                                         stdout=stream, stderr=subprocess.STDOUT, timeout=3600, shell=False)
                code = process.returncode
            except subprocess.TimeoutExpired:
                code = 124
                stream.write("Stage exceeded 3600 seconds; acceptance failed.\n")
        added = set((root / "stages").glob("*/manifest.json")) - before
        manifests = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(added)]
        manifest = manifests[0] if len(manifests) == 1 else {}
        item = {"stage":stage, "exit_code":code, "status":classify(stage, code, manifest),
                "command":[sys.executable,"-m","quant_research.cli",*command],
                "source_status":manifest.get("status"), "manifest":str(next(iter(added)).relative_to(root)) if len(added)==1 else None,
                "log":log.name, "prediction_rows":manifest.get("prediction_rows"),
                "research_grade":False}
        result["stages"].append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
        (root / "acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["status"] = "FAILED" if any(s["status"].startswith("FAILED") for s in result["stages"]) else "FREE_REAL_WORKFLOW_VERIFIED_RESEARCH_BLOCKED"
    result["snapshot_after_sha256"] = sha(database)
    result["artifacts_sha256"] = {p.relative_to(root).as_posix():sha(p) for p in root.rglob("*") if p.is_file() and p.suffix in {".json", ".csv", ".parquet", ".html", ".log"} and p.name != "acceptance.json"}
    (root / "acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = "".join(f'<tr><td>{s["stage"]}</td><td>{s["status"]}</td><td>{html.escape(str(s["source_status"]))}</td><td><a href="{s["log"]}">日志</a></td></tr>' for s in result["stages"])
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>免费真实数据 P1–P6 验收</title><style>body{font:15px system-ui;max-width:1200px;margin:40px}td,th{padding:12px;border-bottom:1px solid #ccc}pre{white-space:pre-wrap}</style><h1>免费真实数据 P1–P6 验收</h1><p>真实来源、离线数据快照。探索计算通过不等同真实研究或可执行验收通过。P5/P6 保留数据阻断；不使用合成成交代替。</p><table><tr><th>阶段</th><th>验收结论</th><th>运行状态</th><th>证据</th></tr>'+rows+'</table><p><a href="acceptance.json">完整命令、快照哈希与证据清单</a></p><pre>'+html.escape(json.dumps(result["blocking_data"],ensure_ascii=False,indent=2))+'</pre></html>'
    (root / "report.html").write_text(page, encoding="utf-8")
    print(json.dumps({"report":str(root / "report.html"), "status":result["status"]}), flush=True)
    return 1 if result["status"]=="FAILED" else 4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/research.duckdb"))
    parser.add_argument("--output", type=Path, default=Path("outputs/real_acceptance"))
    args = parser.parse_args()
    return run(args.db,args.output)


if __name__ == "__main__":
    raise SystemExit(main())
