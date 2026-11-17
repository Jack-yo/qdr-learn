"""L1 V3 production runner: train rarely, predict daily, never train on web GET.

This is an opt-in local runner; launching the CLI/daemon requires the user's
configured host and read-only Alpaca credentials. No market orders are sent.
"""
from __future__ import annotations
from datetime import date, datetime, timezone, timedelta
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import time
import traceback
from uuid import uuid4

from quant_research.clock import TradingClock
from quant_research.data.l1_light_sources import LiveSources, SourceUnavailable
from quant_research.workflow.l1_v3 import (
    latest_completed_session, save_research_snapshot,
    recent_research_snapshots,
)
from quant_research.workflow.l1_v3_persist import (
    CORE_SYMBOLS, build_model_bundle, save_model_bundle,
    find_model_bundle, should_retrain, infer_market_from_bundle,
    _validated_source_bars, canonical
)
from quant_research.workflow.l1_v3_outcomes import (
    settle_due_research, recent_v3_outcomes
)

STUDY_SCHEMA="qdr.l1.probability.v3"
JOB_SCHEMA="qdr.l1.v3.job.v1"
MAX_JOB_LOGS=90
LATEST_GRACE_CALENDAR_DAYS=4


def _job_folder(root):
    return Path(root)/"outputs"/"l1_v3_jobs"


def _run_log(root, event):
    folder=_job_folder(root)
    folder.mkdir(parents=True,exist_ok=True)
    value={**event,"schema":JOB_SCHEMA,
           "recorded_at_utc":datetime.now(timezone.utc).isoformat(),
           "execution_eligible":False}
    data=canonical(value)
    digest=sha256(data).hexdigest()
    path=folder/(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")+
                 "-"+digest[:16]+".json")
    try:
        with path.open("xb") as f:
            f.write(data)
    except FileExistsError:
        pass
    logs=sorted(folder.glob("*.json"))
    for old in logs[:-MAX_JOB_LOGS]:
        old.unlink(missing_ok=True)
    return value


class _JobLock:
    """OS-managed cross-process advisory lock, released even after a crash.

    A stable lock file is intentional; ownership lives in the kernel, not the
    file's existence, so no dangerous stale-lock stealing is necessary.
    """
    def __init__(self,root):
        self.file=_job_folder(root)/".l1_runner.lock"
        self.handle=None

    def __enter__(self):
        self.file.parent.mkdir(parents=True,exist_ok=True)
        handle=self.file.open("a+b")
        try:
            handle.seek(0)
            if os.name=="nt":
                import msvcrt
                if handle.seek(0,2)==0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise SourceUnavailable("V3_JOB_ALREADY_RUNNING") from exc
        self.handle=handle
        return self

    def __exit__(self,exc_type,exc,tb):
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(),fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle=None


def _read_frozen(path):
    blob=path.read_bytes()
    if len(path.stem)!=24 or sha256(blob).hexdigest()[:24]!=path.stem:
        raise SourceUnavailable("V3_FROZEN_HASH_MISMATCH")
    data=json.loads(blob)
    if (data.get("schema")!=STUDY_SCHEMA or
        data.get("status")!="RESEARCH_ONLY" or
        data.get("execution_eligible") is not False or
        data.get("historical_pit_verified") is not False or
        any(v.get("admitted_probabilities") is not None
            for v in data.get("horizons",{}).values())):
        raise SourceUnavailable("V3_FROZEN_CONTRACT_INVALID")
    if path.parent.name!=data.get("asof_session"):
        raise SourceUnavailable("V3_FROZEN_DATE_INVALID")
    horizons=data.get("horizons",{})
    if set(horizons)!={"1","3","5"}:
        raise SourceUnavailable("V3_FROZEN_HORIZONS_INCOMPLETE")
    for key,item in horizons.items():
        p=item.get("research_estimates")
        if p is None:
            continue
        if (not isinstance(p,dict) or set(p)!={"UP","FLAT","DOWN"} or
            any(not isinstance(v,(float,int)) or not 0<=v<=1 for v in p.values()) or
            abs(sum(p.values())-1)>.002):
            raise SourceUnavailable("V3_FROZEN_PROBABILITIES_INVALID")
    return data


def frozen_for_session(root,session):
    session=date.fromisoformat(str(session)).isoformat()
    folder=Path(root)/"outputs"/"l1_v3_research"/session
    if not folder.is_dir():
        return None
    paths=[]
    for candidate in sorted(folder.glob("*.json")):
        try:
            item=_read_frozen(candidate)
        except (OSError,ValueError,TypeError,KeyError,SourceUnavailable):
            raise SourceUnavailable("V3_FROZEN_UNVERIFIABLE")
        if item.get("snapshot_status")=="IMMUTABLE_DAILY_FROZEN":
            paths.append(candidate)
    if not paths:
        return None
    # More than one daily freeze is a contract violation; never silently choose
    # the newest and retroactively change the public prediction.
    if len(paths)!=1:
        raise SourceUnavailable("V3_MULTIPLE_DAILY_FREEZES")
    data=_read_frozen(paths[0])
    return data,{"path":str(paths[0].relative_to(Path(root))),
                 "sha256":sha256(paths[0].read_bytes()).hexdigest()}


def latest_frozen(root, *, now=None):
    """Read-only and offline. It MUST NOT download prices or fit estimators."""
    now=now or datetime.now(timezone.utc)
    current=latest_completed_session(now)
    files=sorted((Path(root)/"outputs"/"l1_v3_research").glob("20??-??-??/*.json"),
                 reverse=True)
    for path in files[:100]:
        if path.parent.name>current:
            continue
        try:
            data=_read_frozen(path)
            if data.get("snapshot_status")!="IMMUTABLE_DAILY_FROZEN":
                continue
            out=dict(data)
            out["served_from"]="IMMUTABLE_FROZEN_RESEARCH"
            out["source_snapshot_sha256"]=sha256(path.read_bytes()).hexdigest()
            out["freshness_status"]="CURRENT" if data["asof_session"]==current else "STALE"
            out["latest_completed_session"]=current
            out["model_service_state"]="FROZEN_RESEARCH_ONLY"
            return out
        except (OSError,ValueError,TypeError,KeyError,SourceUnavailable):
            continue
    return {"schema":STUDY_SCHEMA,"status":"NO_FROZEN_RESEARCH",
            "admitted_probabilities":None,
            "freshness_status":"UNAVAILABLE","horizons":{},
            "execution_eligible":False,
            "notice":"No verified frozen research forecast. Run the daily job on the local host."}


def current_pipeline_status(root, *, now=None):
    now=now or datetime.now(timezone.utc)
    current=latest_completed_session(now)
    model_info=find_model_bundle(root,asof=current)
    frozen=latest_frozen(root,now=now)
    daily_count=0
    for record in recent_research_snapshots(root,limit=15):
        try:
            entry=frozen_for_session(root,record['asof_session'])
            if entry and entry[1]['sha256']==record['sha256']:
                daily_count+=1
        except (OSError,ValueError,TypeError,KeyError,SourceUnavailable):
            continue
    jobs=sorted(_job_folder(root).glob("*.json"),reverse=True)
    last_job=None
    for path in jobs[:5]:
        try:
            log=json.loads(path.read_text(encoding="utf-8"))
            if log.get("schema")==JOB_SCHEMA:
                last_job={k:log.get(k) for k in ("mode","status","asof_session",
                     "code","recorded_at_utc","model_sha256")}
                break
        except (OSError,ValueError,TypeError):
            continue
    return {
        "schema":"qdr.l1.v3.pipeline.status",
        "asof_session":current,
        "model_available":bool(model_info),
        "model_reference":model_info[1] if model_info else None,
        "model_retrain_due":should_retrain(model_info[0],current) if model_info else True,
        "frozen_session":frozen.get("asof_session"),
        "frozen_current":frozen.get("freshness_status")=="CURRENT",
        "frozen_count_recent":daily_count,
        "settled_count_recent":len(recent_v3_outcomes(root,limit=30)),
        "last_job":last_job,
        "status":"CURRENT_RESEARCH" if frozen.get("freshness_status")=="CURRENT"
                 else "STALE_OR_UNAVAILABLE",
        "historical_pit_verified":False,"execution_eligible":False
    }


def _bar_request(feed, *, days, session, adjustment="split", refresh=False,
                 preserve_source_evidence=False):
    try:
        return feed.bars(days=days, symbols=CORE_SYMBOLS,
                         end_date=session, adjustment=adjustment,refresh=refresh,
                         preserve_source_evidence=preserve_source_evidence)
    except TypeError as exc:
        # Do not hide incompatible adapter signatures or silently fall back
        # to raw / delayed-sip data.
        raise SourceUnavailable("V3_SOURCE_ADAPTER_INCOMPATIBLE") from exc


def _validate_receipt_times(receipts, frozen_at):
    """Refuse to freeze a forecast using a source receipt from its future."""
    if not isinstance(receipts,list) or not receipts:
        raise SourceUnavailable("V3_SOURCE_RECEIPTS_MISSING")
    for receipt in receipts:
        if not isinstance(receipt,dict):
            raise SourceUnavailable("V3_SOURCE_RECEIPT_INVALID")
        try:
            fetched=datetime.fromisoformat(str(receipt["fetched_at"]).replace("Z","+00:00"))
        except (KeyError,TypeError,ValueError,OverflowError) as exc:
            raise SourceUnavailable("V3_SOURCE_RECEIPT_TIME_INVALID") from exc
        if fetched.tzinfo is None or fetched.utcoffset() is None:
            raise SourceUnavailable("V3_SOURCE_RECEIPT_TIME_INVALID")
        if fetched.astimezone(timezone.utc)>frozen_at.astimezone(timezone.utc):
            raise SourceUnavailable("V3_SOURCE_RECEIPT_AFTER_FREEZE")


def _train(root, feed, asof, *, refresh):
    bars,receipts=_bar_request(feed,days=2500,session=asof,
                                adjustment="split",refresh=refresh)
    _validated_source_bars(bars,asof)
    bundle=build_model_bundle(bars,receipts=receipts,asof=asof)
    ref=save_model_bundle(root,bundle)
    return bundle,ref,bars,receipts


def _settlements_pending(root,asof):
    """Skip redundant data downloads when every matured label is settled."""
    clock=TradingClock()
    try:
        current_pos=clock.calendar.sessions.get_loc(clock.session(asof))
    except (ValueError,KeyError):
        return False
    settled={(r["frozen_sha256"],int(r["horizon"]))
             for r in recent_v3_outcomes(root,limit=400)}
    visited=set()
    for item in recent_research_snapshots(root,limit=30):
        try:
            session=item["asof_session"]
            if session in visited:
                continue
            visited.add(session)
            frozen=frozen_for_session(root,session)
            if not frozen:
                continue
            snapshot,reference=frozen
            if snapshot.get("minimum_embargo_sessions",0)<5:
                continue  # Older models remain archived but cannot enter scorecard.
            origin=clock.calendar.sessions.get_loc(
                clock.session(session))
            for key,row in snapshot["horizons"].items():
                h=int(key)
                if row.get("research_estimates") is not None and origin+h<=current_pos and (reference["sha256"],h) not in settled:
                    return True
        except (KeyError,ValueError,TypeError):
            continue
    return False


def _settle_existing(root,feed,asof, *,refresh=False,action_checker=None):
    """Only download short history when a real horizon has actually matured."""
    if not _settlements_pending(root,asof):
        return {"checked":0,"new_outcomes":0,"status":"NO_DUE_OUTCOMES"}
    # The model's target is price-only and SPLIT-adjusted, not portfolio P&L.
    # Alpaca corporate-actions process_date cannot certify an empty ex-date
    # window, so relying on it would block every honest forward score.
    bars,receipts=_bar_request(feed,days=90,session=asof,
                               adjustment="split",refresh=True,
                               preserve_source_evidence=True)
    return settle_due_research(root,bars,latest_session=asof,limit=30,
                               price_receipts=receipts)


def run_pipeline(root, *, mode="daily", now=None, sources=None,
                 refresh=False, force_train=False, action_checker=None):
    """Execute on user's host. Results are never promoted to live trading."""
    root=Path(root)
    live_clock=now is None
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Time zone required")
    asof=latest_completed_session(now)
    if mode not in ("daily","train","settle"):
        raise ValueError("Invalid L1 job mode")
    feed=sources or LiveSources(root)
    started=time.monotonic()
    try:
        with _JobLock(root):
            existing=frozen_for_session(root,asof) if mode=="daily" else None
            if mode=="daily" and existing and not force_train:
                try:
                    outcome=_settle_existing(root,feed,asof,refresh=refresh,action_checker=action_checker)
                except SourceUnavailable as exc:
                    outcome={"status":"PENDING_SOURCE","code":exc.code}
                result={"mode":mode,"status":"ALREADY_FROZEN",
                        "asof_session":asof,
                        "frozen_sha256":existing[1]["sha256"],
                        "outcomes":outcome}
            elif mode=="settle":
                outcome=_settle_existing(root,feed,asof,refresh=refresh,action_checker=action_checker)
                result={"mode":mode,"status":"SETTLEMENT_CHECKED",
                        "asof_session":asof,"outcomes":outcome}
            else:
                available=find_model_bundle(root,asof=asof)
                needs_train=(mode=="train" or force_train or not available or
                             should_retrain(available[0],asof))
                if needs_train:
                    bundle,ref,training_bars,training_receipts=_train(
                        root,feed,asof,refresh=refresh)
                else:
                    bundle,ref=available
                if mode=="train":
                    result={"mode":mode,"status":"MODEL_TRAINED",
                            "asof_session":asof,"model_sha256":ref["model_sha256"],
                            "model_reference":ref}
                else:
                    if needs_train:
                        bars,receipts=training_bars,training_receipts
                    else:
                        bars,receipts=_bar_request(feed,days=420,session=asof,
                                                  adjustment=bundle["input_basis"],
                                                  refresh=refresh)
                    research=infer_market_from_bundle(
                        bars,model=bundle,model_ref=ref,
                        receipts=receipts,asof=asof)
                    research["pipeline_version"]="L1_V3_DAILY_V1"
                    research["snapshot_status"]="IMMUTABLE_DAILY_FROZEN"
                    clock=TradingClock()
                    next_session=clock.calendar.next_session(clock.session(asof))
                    frozen_at=datetime.now(timezone.utc) if live_clock else now.astimezone(timezone.utc)
                    try:
                        clock.signal(asof,now=frozen_at)
                    except ValueError as exc:
                        raise SourceUnavailable("V3_ASOF_SESSION_NOT_CLOSED") from exc
                    if frozen_at>=clock.calendar.session_open(next_session).to_pydatetime():
                        raise SourceUnavailable("V3_NEXT_SESSION_ALREADY_OPEN")
                    _validate_receipt_times(receipts,frozen_at)
                    research["frozen_at_utc"]=frozen_at.isoformat()
                    # Never overwrite a prior official daily freeze. Even with
                    # force_train, preserve any earlier prediction.
                    if existing:
                        result={"mode":mode,"status":"ALREADY_FROZEN",
                                "asof_session":asof,
                                "frozen_sha256":existing[1]["sha256"],
                                "model_sha256":ref["model_sha256"]}
                    else:
                        frozen=save_research_snapshot(root,research)
                        result={"mode":mode,"status":"FROZEN_RESEARCH_ONLY",
                                "asof_session":asof,
                                "frozen_sha256":frozen["sha256"],
                                "model_sha256":ref["model_sha256"]}
                    try:
                        result["outcomes"]=_settle_existing(root,feed,asof,refresh=refresh,action_checker=action_checker)
                    except (OSError,SourceUnavailable) as exc:
                        result["outcomes"]={"status":"PENDING",
                                            "code":getattr(exc,"code",type(exc).__name__)}
            result["elapsed_seconds"]=round(time.monotonic()-started,3)
            _run_log(root,result)
            return result
    except (SourceUnavailable,ValueError,OSError,KeyError,TypeError) as exc:
        code=getattr(exc,"code",type(exc).__name__)
        _run_log(root,{"mode":mode,"status":"BLOCKED",
                       "asof_session":asof,"code":code,
                       "elapsed_seconds":round(time.monotonic()-started,3)})
        raise


def daemon(root, *, interval_seconds=900, once=False):
    """Explicit foreground scheduler; supervise with Task Scheduler/systemd."""
    if not 60<=interval_seconds<=86400:
        raise ValueError("Invalid interval")
    while True:
        try:
            run_pipeline(root,mode="daily")
        except (SourceUnavailable,OSError,ValueError,TypeError,KeyError):
            # Error is already recorded. Retry on the next bounded polling tick.
            pass
        if once:
            return
        time.sleep(interval_seconds)


def main(argv=None):
    parser=argparse.ArgumentParser(description="QDR L1 V3 local daily research runner")
    parser.add_argument("--root",type=Path,default=Path("."))
    sub=parser.add_subparsers(dest="command",required=True)
    for name in ("train","daily","settle"):
        p=sub.add_parser(name)
        p.add_argument("--refresh",action="store_true")
        p.add_argument("--force-train",action="store_true")
    sub.add_parser("status")
    sub.add_parser("latest")
    sub.add_parser("daemon").add_argument("--interval",type=int,default=900)
    args=parser.parse_args(argv)
    try:
        credentials=args.root / '.env'
        if credentials.is_file():
            from quant_research.cli import load_local_credentials
            load_local_credentials(credentials)
        if args.command=="status":
            data=current_pipeline_status(args.root)
        elif args.command=="latest":
            data=latest_frozen(args.root)
        elif args.command=="daemon":
            daemon(args.root,interval_seconds=args.interval)
            return 0
        else:
            data=run_pipeline(args.root,mode=args.command,
                              refresh=args.refresh,force_train=args.force_train)
        print(canonical(data).decode("utf-8"))
        return 0
    except (SourceUnavailable,ValueError,OSError,TypeError,KeyError) as exc:
        print(canonical({"status":"BLOCKED",
                         "code":getattr(exc,"code",type(exc).__name__)}).decode())
        return 2


if __name__=="__main__":
    raise SystemExit(main())
