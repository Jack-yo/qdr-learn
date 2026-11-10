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
        CREATE TABLE IF NOT EXISTS days(account TEXT NOT NULL,date TEXT NOT NULL,input_hash TEXT NOT NULL,snapshot_json TEXT NOT NULL,PRIMARY KEY(account,date));
        CREATE TABLE IF NOT EXISTS events(account TEXT NOT NULL,event_id TEXT NOT NULL,date TEXT NOT NULL,kind TEXT NOT NULL,cash_change REAL NOT NULL,body_json TEXT NOT NULL,PRIMARY KEY(account,event_id));""")
        self.config,self.clock,self.account=config,clock,account
        self.config_hash=hashlib.sha256(json.dumps(config.model_dump(mode="json"),sort_keys=True).encode()).hexdigest()

    def __enter__(self): return self
    def __exit__(self,*exc): self.db.close()

    def advance(self,day,bars,signals,source=None,adjustment_basis="raw",events=()):
        from quant_research.policy import execution_blocked
        execution_blocked()
        day=str(day)
        self.clock.session(day)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row=self.db.execute("SELECT config_hash,state_json FROM accounts WHERE account=?",[self.account]).fetchone()
            if row and row[0]!=self.config_hash:
                raise ValueError("Paper account configuration is frozen; use a distinct account for a new experiment")
            state=json.loads(row[1]) if row else None
            inputs=json.dumps({"bars":bars,"signals":signals,"events":list(events)},sort_keys=True,default=str,allow_nan=False)
            input_hash=hashlib.sha256(inputs.encode()).hexdigest()
            previous=self.db.execute("SELECT input_hash,snapshot_json FROM days WHERE account=? AND date=?",[self.account,day]).fetchone()
            if previous:
                if previous[0]!=input_hash:
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
            self.db.execute("INSERT INTO days VALUES (?,?,?,?)",[self.account,day,input_hash,encoded])
            self.db.execute("INSERT INTO accounts VALUES (?,?,?) ON CONFLICT(account) DO UPDATE SET state_json=excluded.state_json",[self.account,self.config_hash,json.dumps(engine.state(),allow_nan=False)])
            self.db.execute("COMMIT")
            return snapshot,True
        except Exception:
            self.db.execute("ROLLBACK")
            raise
