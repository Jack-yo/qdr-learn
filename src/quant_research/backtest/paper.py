"""Transactional local paper account; no broker client, network or real order capability."""
import hashlib
import json
from pathlib import Path
import sqlite3

from .engine import PortfolioEngine


class PaperLedger:
    def __init__(self,path,config,clock,account="forward-shadow-h3"):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(str(self.path),timeout=30,isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""CREATE TABLE IF NOT EXISTS accounts(account TEXT PRIMARY KEY,config_hash TEXT NOT NULL,state_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS days(account TEXT NOT NULL,date TEXT NOT NULL,input_hash TEXT NOT NULL,snapshot_json TEXT NOT NULL,
           source_snapshot_sha256 TEXT,decision_sha256 TEXT,PRIMARY KEY(account,date));
        CREATE TABLE IF NOT EXISTS events(account TEXT NOT NULL,event_id TEXT NOT NULL,date TEXT NOT NULL,kind TEXT NOT NULL,cash_change REAL NOT NULL,body_json TEXT NOT NULL,PRIMARY KEY(account,event_id));""")
        # Safe additive migration for older local paper stores; missing old provenance
        # remains null and therefore never appears as source-accepted performance.
        existing={row[1] for row in self.db.execute('PRAGMA table_info(days)')}
        for col in ('source_snapshot_sha256','decision_sha256'):
            if col not in existing:
                self.db.execute(f'ALTER TABLE days ADD COLUMN {col} TEXT')
        self.config,self.clock,self.account=config,clock,account
        self.config_hash=hashlib.sha256(json.dumps(config.model_dump(mode="json"),sort_keys=True).encode()).hexdigest()

    def __enter__(self): return self
    def __exit__(self,*exc): self.db.close()

    def advance(self,day,bars,signals,source=None,adjustment_basis="raw",events=(),*,bundle=None,decision_sha256=None):
        from quant_research.policy import PolicyError
        if bundle is None:
            raise PolicyError('FORWARD_BUNDLE_REQUIRED','Accepted real-data snapshot required')
        bundle.require('forward_shadow')
        if (not isinstance(decision_sha256,str) or len(decision_sha256)!=64
                or any(c not in '0123456789abcdef' for c in decision_sha256)):
            raise PolicyError('FROZEN_DECISION_DIGEST_REQUIRED','Audited decision SHA256 must accompany paper replay')
        if str(source).upper() != 'ALPACA' or adjustment_basis != 'raw':
            raise PolicyError('RAW_SIP_REQUIRED','Only verified Alpaca SIP raw prices support paper accounting')
        day=str(day)
        if bundle.metadata['asof_date_et'] != day:
            raise PolicyError('FORWARD_DAY_MISMATCH','Paper day must match accepted bundle session')
        current = bundle.prices
        current = current.loc[current.date.astype(str).eq(day)]
        actual = {str(r.security_id):{'open':float(r.open),'high':float(r.high),
                  'low':float(r.low),'close':float(r.close),'volume':int(r.volume)}
                  for r in current.itertuples(index=False)}
        if not actual or set(actual)!=set(bars):
            raise PolicyError('PAPER_BAR_COVERAGE','Real paper bars must match entire eligible session')
        for sid, source_bar in actual.items():
            if any(bars[sid].get(field) != value for field,value in source_bar.items()):
                raise PolicyError('PAPER_BAR_MUTATED','Paper input differs from source-verified raw data',[sid])
        if any(not bool(signal.get('decision_eligible',False)) for signal in signals):
            raise PolicyError('PAPER_SIGNAL_UNVERIFIED','Paper signal must be verified and frozen')
        self.clock.session(day)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row=self.db.execute("SELECT config_hash,state_json FROM accounts WHERE account=?",[self.account]).fetchone()
            if row and row[0]!=self.config_hash:
                raise ValueError("Paper account configuration is frozen; use a distinct account for a new experiment")
            state=json.loads(row[1]) if row else None
            inputs=json.dumps({"bars":bars,"signals":signals,"events":list(events)},sort_keys=True,default=str,allow_nan=False)
            input_hash=hashlib.sha256(inputs.encode()).hexdigest()
            previous=self.db.execute("SELECT input_hash,snapshot_json,source_snapshot_sha256,decision_sha256 FROM days WHERE account=? AND date=?",[self.account,day]).fetchone()
            if previous:
                if (previous[0]!=input_hash or previous[2]!=bundle.metadata['snapshot_sha256']
                        or previous[3]!=decision_sha256):
                    raise ValueError("A processed session cannot be silently revised")
                self.db.execute("COMMIT")
                return json.loads(previous[1]),False
            engine=PortfolioEngine(self.config,self.clock,self.config.default_cost_bps_per_side,True,state=state)
            engine.step(day,bars,signals,events)
            snapshot={"date":day,"cash":engine.cash,"equity":engine.equity(),"positions":engine.state()["positions"],
                      "pending_orders":engine.pending,"new_fills":engine.fills,"new_trades":engine.trades,"flags":sorted(engine.flags)}
            for kind,values in [("fill",engine.fills),("action",engine.actions)]:
                for sequence,value in enumerate(values):
                    event_id=hashlib.sha256(f"{self.account}:{day}:{kind}:{sequence}".encode()).hexdigest()
                    self.db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)",[self.account,event_id,day,kind,value["cash_change"],json.dumps(value,default=str,allow_nan=False)])
            cash=self.config.initial_cash+self.db.execute("SELECT coalesce(sum(cash_change),0) FROM events WHERE account=?",[self.account]).fetchone()[0]
            if abs(cash-engine.cash)>1e-6:
                raise ValueError("Durable paper cash does not reconcile")
            encoded=json.dumps(snapshot,default=str,allow_nan=False)
            self.db.execute("""INSERT INTO days(account,date,input_hash,snapshot_json,source_snapshot_sha256,decision_sha256)
                     VALUES (?,?,?,?,?,?)""",
                    [self.account,day,input_hash,encoded,bundle.metadata['snapshot_sha256'],decision_sha256])
            self.db.execute("INSERT INTO accounts VALUES (?,?,?) ON CONFLICT(account) DO UPDATE SET state_json=excluded.state_json",[self.account,self.config_hash,json.dumps(engine.state(),allow_nan=False)])
            self.db.execute("COMMIT")
            return snapshot,True
        except Exception:
            self.db.execute("ROLLBACK")
            raise


def account_summary(path, config, account="forward-shadow-h3"):
    """Read a source-linked, internally reconciled paper account; no fake balances."""
    import re
    from quant_research.policy import PolicyError

    path=Path(path)
    blocked={"status":"BLOCKED", "account":account,"cash":None,"equity":None,
             "positions":None,"fills":None,"real_orders_enabled":False}
    if not path.is_file():
        return {**blocked,"code":"NO_ACCEPTED_PAPER_LEDGER"}
    uri=path.resolve().as_uri()+"?mode=ro"
    try:
        with sqlite3.connect(uri,uri=True) as db:
            record=db.execute('SELECT config_hash,state_json FROM accounts WHERE account=?',[account]).fetchone()
            if record is None:
                return {**blocked,"code":"NO_ACCEPTED_PAPER_ACCOUNT"}
            current_config=hashlib.sha256(json.dumps(config.model_dump(mode='json'),sort_keys=True).encode()).hexdigest()
            if record[0]!=current_config:
                return {**blocked,"code":"FROZEN_CONFIG_MISMATCH"}
            state=json.loads(record[1])
            dates=db.execute('SELECT date,source_snapshot_sha256,decision_sha256,snapshot_json FROM days WHERE account=? ORDER BY date',[account]).fetchall()
            if not dates or dates[-1][0]!=state['last_date']:
                return {**blocked,"code":"PAPER_DAY_INTEGRITY_ERROR"}
            for date,sha,decision,body in dates:
                if not all(isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value)
                           for value in (sha,decision)):
                    return {**blocked,"code":"LEGACY_ACCOUNT_PROVENANCE_UNVERIFIED"}
                if json.loads(body).get('date')!=date:
                    return {**blocked,"code":"PAPER_SNAPSHOT_INVALID"}
            cash=config.initial_cash+db.execute('SELECT coalesce(sum(cash_change),0) FROM events WHERE account=?',[account]).fetchone()[0]
            if abs(cash-state['cash'])>1e-6:
                return {**blocked,"code":"PAPER_CASH_RECONCILIATION_FAILED"}
            positions=state['positions']
            equity=cash+sum(value['quantity']*state['last_prices'].get(sid,value['raw_entry_price'])
                            for sid,value in positions.items())
            last=json.loads(dates[-1][3])
            if abs(last['cash']-cash)>1e-6 or abs(last['equity']-equity)>1e-6:
                return {**blocked,"code":"PAPER_EQUITY_RECONCILIATION_FAILED"}
            fills=db.execute("SELECT count(*) FROM events WHERE account=? AND kind='fill'",[account]).fetchone()[0]
            return {"status":"INTERNALLY_RECONCILED_PAPER_ESTIMATE","account":account,
                    "last_session":state['last_date'],"cash":cash,"equity":equity,
                    "positions":len(positions),"position_details":positions,"last_prices":state["last_prices"],"fills":fills,
                    "recorded_sessions":len(dates),"real_orders_enabled":False,
                    "notice":"Internal ledger reconciliation only; external source receipts must be rechecked before claiming source-verified fills. No broker fills."}
    except (sqlite3.DatabaseError,ValueError,KeyError,TypeError,OSError):
        return {**blocked,"code":"PAPER_LEDGER_CANNOT_BE_VERIFIED"}
