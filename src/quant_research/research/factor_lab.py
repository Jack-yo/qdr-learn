"""Immutable factor versions and experiments. Templates never evaluate user code."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Literal
from uuid import UUID,uuid4
from contextlib import contextmanager

import numpy as np
from pydantic import BaseModel,ConfigDict,Field,StrictInt,model_validator

from quant_research.features.factors import FunctionalFactor
from quant_research.features.expression import compile_expression
from quant_research.policy import PolicyError,SYMBOLS


def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def fingerprint(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def valid_id(value):return str(UUID(str(value)))


class FactorSpec(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    name:str=Field(min_length=1,max_length=80)
    template:Literal['reversal','momentum','volatility','liquidity','amihud','size','quality','sector_relative','custom']
    window:StrictInt=Field(ge=1,le=252)
    expression:str|None=None
    direction:StrictInt=1
    hypothesis:str=Field(default='',max_length=1000)
    parent_version_id:str|None=None

    @model_validator(mode='after')
    def validate_definition(self):
        if not re.fullmatch(r'[\w\u4e00-\u9fff .-]+',self.name) or not self.name.strip():raise ValueError('Invalid factor name')
        if self.direction not in (-1,1):raise ValueError('Direction must be +1 or -1')
        if self.template=='custom':
            compiled=compile_expression(self.expression)
            if compiled.lookback>self.window:
                raise ValueError(f'Custom expression requires window >= {compiled.lookback} sessions')
        elif self.expression is not None:
            raise ValueError('Expressions are supported only for custom factors')
        if self.template in ('volatility','liquidity','amihud') and self.window<5:raise ValueError('Rolling template needs at least 5 sessions')
        if self.template in ('size','quality') and self.window!=1:raise ValueError('PIT financial templates use window=1')
        if self.template=='sector_relative' and self.window!=5:raise ValueError('Sector-relative template requires 5 sessions')
        if self.parent_version_id:valid_id(self.parent_version_id)
        return self


class ExperimentSpec(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    factor_version_id:str
    source:Literal['yahoo','alpaca']
    symbols:list[str]|None=None

    @model_validator(mode='after')
    def validate_version(self):
        valid_id(self.factor_version_id)
        if self.symbols is not None:
            if (not 5<=len(self.symbols)<=1000 or len(set(self.symbols))!=len(self.symbols)
                    or 'SPY' not in self.symbols
                    or any(not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}',s) for s in self.symbols)):
                raise ValueError('Custom real research universe requires 5–1000 unique symbols including SPY')
        return self


def template_factor(spec,version_hash):
    w,d=spec.window,spec.direction
    if spec.template=='custom':
        compiled=compile_expression(spec.expression)
        function=lambda c: d*compiled.compute(c)
        definition=f'{d} * ({compiled.formula})'
        return FunctionalFactor(spec.name,w,function,definition,
                                dependency='cross_section' if compiled.cross_sectional else 'self',
                                version=version_hash[:16])
    elif spec.template=='reversal':
        function=lambda c: d*-(c.close/c.close.shift(w)-1)
        definition=f'{d} * -(close/close.shift({w})-1)'
    elif spec.template=='momentum':
        function=lambda c: d*(c.close/c.close.shift(w)-1)
        definition=f'{d} * (close/close.shift({w})-1)'
    elif spec.template=='volatility':
        function=lambda c:d*c.returns.rolling(w,min_periods=w).std(ddof=1)*np.sqrt(252)
        definition=f'{d} * std(daily_return,{w},ddof=1)*sqrt(252)'
    elif spec.template=='liquidity':
        function=lambda c:d*(c.close*c.panels['volume']).rolling(w,min_periods=w).mean()
        definition=f'{d} * mean(close*volume,{w})'
    elif spec.template=='amihud':
        function=lambda c:d*(c.returns.abs()/(c.close*c.panels['volume']).replace(0,np.nan)).rolling(w,min_periods=w).mean()
        definition=f'{d} * mean(abs(ret)/dollar_volume,{w})'
    elif spec.template in ('size','quality'):
        # Financial values must be joined point-in-time from accepted filings.
        # A configured template must NEVER silently become a zero/NaN "successful" factor.
        raise PolicyError('PIT_INPUT_REQUIRED',
            'Size/quality factor requires time-stamped historical market cap or financial filings',
            ['fundamentals_pit','security_identity','filing_accepted_at'])
    else:
        raise PolicyError('SECTOR_PIT_REQUIRED',
            'Sector-relative factor requires accepted historical classification and proxy map',
            ['historical_sector_membership','sector_proxy_mapping'])
    return FunctionalFactor(spec.name,w,function,definition,version=version_hash[:16])


class Registry:
    def __init__(self,root):
        self.root=Path(root).resolve();self.path=self.root/'data/managed/factor_lab/registry.sqlite3'

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(self.path,timeout=15);db.row_factory=sqlite3.Row
        db.executescript('''PRAGMA foreign_keys=ON;
          CREATE TABLE IF NOT EXISTS factor_versions(id TEXT PRIMARY KEY,name TEXT NOT NULL,version INTEGER NOT NULL,
           parent_id TEXT,config_json TEXT NOT NULL,config_sha256 TEXT NOT NULL,created_at_utc TEXT NOT NULL,
           UNIQUE(name,version),FOREIGN KEY(parent_id) REFERENCES factor_versions(id));
          CREATE TABLE IF NOT EXISTS experiments(id TEXT PRIMARY KEY,factor_version_id TEXT NOT NULL,config_json TEXT NOT NULL,
           config_sha256 TEXT NOT NULL,created_at_utc TEXT NOT NULL,status TEXT NOT NULL,result_path TEXT,error_json TEXT,
           FOREIGN KEY(factor_version_id) REFERENCES factor_versions(id));''')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback();raise
        finally:db.close()

    def create_factor(self,body):
        spec=FactorSpec.model_validate(body);identifier=str(uuid4());stamp=datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT max(version) FROM factor_versions WHERE name=?',[spec.name]).fetchone()[0]
            if spec.parent_version_id:
                parent=db.execute('SELECT * FROM factor_versions WHERE id=?',[spec.parent_version_id]).fetchone()
                if not parent:raise PolicyError('FACTOR_VERSION_NOT_FOUND','Parent factor version is unavailable')
                parent_spec=FactorSpec.model_validate_json(parent['config_json'])
                if parent_spec.name!=spec.name or parent_spec.template!=spec.template:
                    raise ValueError('Copied versions must preserve the factor name and template')
            elif previous is not None:raise ValueError('Name exists; copy an existing version instead')
            config=spec.model_dump();digest=fingerprint(config)
            db.execute('INSERT INTO factor_versions VALUES (?,?,?,?,?,?,?)',
                       [identifier,spec.name,(previous or 0)+1,spec.parent_version_id,canonical(config),digest,stamp])
        return self.factor(identifier)

    def factor(self,identifier):
        identifier=valid_id(identifier)
        with self.connect() as db:row=db.execute('SELECT * FROM factor_versions WHERE id=?',[identifier]).fetchone()
        if not row:raise PolicyError('FACTOR_VERSION_NOT_FOUND','Factor version is unavailable')
        result=dict(row);config=json.loads(result.pop('config_json'))
        if fingerprint(config)!=result['config_sha256']:raise PolicyError('FACTOR_CONFIG_CORRUPT','Factor definition hash mismatch')
        FactorSpec.model_validate(config);result['config']=config
        return result

    def factors(self):
        with self.connect() as db:ids=[r[0] for r in db.execute('SELECT id FROM factor_versions ORDER BY created_at_utc DESC')]
        return [self.factor(i) for i in ids]

    def create_experiment(self,body):
        spec=ExperimentSpec.model_validate(body);factor=self.factor(spec.factor_version_id)
        from .experiment import load_experiment
        protocol=load_experiment(self.root/'configs/experiments/p2_factors.yaml').model_dump(mode='json')
        stamp=datetime.now(timezone.utc).isoformat();identifier=str(uuid4())
        config={**spec.model_dump(),'factor_config_sha256':factor['config_sha256'],'mode':'retrospective',
                'start':'2017-01-01','train_end':'2022-12-31','validation_end':'2024-12-31',
                'horizons':[1,3,5],'knowledge_cutoff_utc':stamp,'protocol':'factor-lab-descriptive-v1',
                'research_protocol':protocol,'symbols':list(spec.symbols if spec.symbols is not None else SYMBOLS),
                'universe_version':(
                    'EXPLICIT_CURRENT_ETF_LIST_NOT_PIT'
                    if spec.symbols is None else 'EXPLICIT_CUSTOM_SECURITY_LIST_NOT_HISTORICAL_PIT'
                )}
        with self.connect() as db:
            db.execute('INSERT INTO experiments VALUES (?,?,?,?,?,?,?,?)',
                       [identifier,spec.factor_version_id,canonical(config),fingerprint(config),stamp,'CREATED',None,None])
        return self.experiment(identifier)

    def experiment(self,identifier):
        identifier=valid_id(identifier)
        with self.connect() as db:row=db.execute('SELECT * FROM experiments WHERE id=?',[identifier]).fetchone()
        if not row:raise PolicyError('EXPERIMENT_NOT_FOUND','Factor experiment is unavailable')
        result=dict(row);config=json.loads(result.pop('config_json'))
        if fingerprint(config)!=result['config_sha256']:raise PolicyError('EXPERIMENT_CONFIG_CORRUPT','Experiment config hash mismatch')
        result['config']=config;error=result.pop('error_json');result['error']=json.loads(error) if error else None
        return result

    def experiments(self):
        with self.connect() as db:ids=[r[0] for r in db.execute('SELECT id FROM experiments ORDER BY created_at_utc DESC LIMIT 100')]
        return [self.experiment(i) for i in ids]

    def claim(self,identifier):
        identifier=valid_id(identifier)
        with self.connect() as db:
            changed=db.execute("UPDATE experiments SET status='RUNNING' WHERE id=? AND status='CREATED'",[identifier]).rowcount
        return bool(changed)

    def finish(self,identifier,status,result_path=None,error=None):
        if status not in ('COMPLETED','BLOCKED','FAILED'):raise ValueError('Invalid experiment terminal status')
        with self.connect() as db:
            changed=db.execute('UPDATE experiments SET status=?,result_path=?,error_json=? WHERE id=? AND status=\'RUNNING\'',
                [status,result_path,canonical(error) if error else None,valid_id(identifier)]).rowcount
            if changed!=1:raise PolicyError('EXPERIMENT_STATE_CONFLICT','Only a running experiment can be finalized')
