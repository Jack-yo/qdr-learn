"""Read-only G12 research readiness matrix across existing REAL_ONLY stores.

The status is an evidence inventory, not a signal generator, training job,
security-master builder, PIT grant, or paper account. Nothing is created here.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from quant_research.policy import PolicyError


_DEFAULT_DB = Path('data/real_v21.duckdb')


def _entry(code, description, *, state='BLOCKED', missing=(), evidence=None, href='/data'):
    return {'status': state, 'code': code, 'description': description,
            'missing_evidence': list(dict.fromkeys(str(x) for x in missing)),
            'evidence': evidence or {}, 'view': href}


def _failure(exc, purpose, href='/data'):
    if isinstance(exc, PolicyError):
        return _entry(exc.code, purpose, missing=[exc.message, *exc.missing], href=href)
    return _entry('LOCAL_EVIDENCE_UNREADABLE', purpose,
                  missing=[type(exc).__name__], href=href)


def research_readiness(root, *, db=None, asof=None, symbols=None):
    """Expose only actually verified facts, without side effects or advisory scores.

    No file existence, account plan, observed asset UUID or previous experimental
    IC ever grants historical PIT, historical_backtest, or forward_shadow PASS.
    """
    root = Path(root).resolve()
    if asof is not None:
        try:
            if date.fromisoformat(asof).isoformat() != asof or asof > datetime.now(timezone.utc).date().isoformat():
                raise ValueError('Invalid cutoff')
        except (TypeError, ValueError):
            raise PolicyError('READINESS_ASOF_INVALID', 'As-of must be a nonfuture ISO calendar date') from None
    database = (root / (db if db is not None else _DEFAULT_DB)).resolve()
    if not database.is_relative_to((root/'data').resolve()):
        raise PolicyError('READINESS_DB_PATH_INVALID', 'Database path must remain under the local project data directory')

    stages = {}
    capabilities = {}
    if not database.is_file():
        stages['dataset'] = _entry('NO_REAL_DATA', '来源与能力核验',
                                   missing=['No real DuckDB source warehouse at the selected path'])
    else:
        try:
            from quant_research.data.bundle import load_real_bundle
            bundle = load_real_bundle(database, 'alpaca', asof=asof,
                                      raw_root=root/'data/raw',symbols=symbols)
            if bundle.capabilities.get('observation',{}).get('status')!='PASS':
                raise PolicyError('SESSION_SOURCE_COVERAGE_INCOMPLETE',
                                  'Requested stock and ETF basket lacks complete observed-session coverage')
            capabilities = bundle.capabilities
            stages['dataset'] = _entry('SOURCE_OBSERVATION_VERIFIED', '来源与能力核验',
                                       state='OBSERVATION_ONLY', evidence={
                                           'asof_date_et':bundle.metadata['asof_date_et'],
                                           'source_snapshot_sha256':bundle.metadata['snapshot_sha256'],
                                           'source':bundle.metadata['source'],
                                           'feed':bundle.metadata['feed'],
                                           'rows':bundle.metadata['rows'],
                                           'latest_session_complete':bundle.metadata['latest_session_complete'],
                                           'symbols':bundle.metadata['symbols'],
                                       })
        except (PolicyError, OSError, ValueError) as exc:
            stages['dataset'] = _failure(exc,'来源与能力核验')

    for title, capability, label in (
        ('historical_model', 'historical_model', '历史模型 PIT 准入'),
        ('historical_backtest', 'historical_backtest', '严格原价回测准入'),
        ('forward_data', 'forward_data', '前向数据准入'),
        ('forward_shadow', 'forward_shadow', '冻结模型与前向决策准入'),
        ('pit_fundamentals', 'pit_fundamentals', '已披露基本面时点资格'),
        ('industry_factors', 'industry_factors', '历史行业分类资格'),
    ):
        check = capabilities.get(capability, {'status':'BLOCKED', 'missing_evidence':['Source-backed dataset capability unavailable']})
        state = 'PASS' if check.get('status') == 'PASS' else 'BLOCKED'
        stages[title] = _entry('CAPABILITY_'+state, label, state=state,
                                missing=check.get('missing_evidence',[]))

    try:
        from quant_research.data.forward_universe import asof_directory
        observed = asof_directory(root,
            asof_utc=(asof + 'T23:59:59+00:00') if asof else None,
            limit=0)
        stages['asset_directory'] = _entry('SOURCE_ASSET_OBSERVATION_ONLY', '实际采集的证券目录',
            state='OBSERVATION_ONLY', evidence={'snapshot_id':observed['snapshot_id'],
                'observed_at_utc':observed['observed_at_utc'],
                'historical_pit_eligible':False},
            missing=['Provider UUID does not prove effective-dated issuer identity or PIT membership'])
    except (PolicyError, OSError, ValueError) as exc:
        stages['asset_directory'] = _failure(exc, '实际采集的证券目录')

    try:
        registry_path = root/'data/managed/strategies/registry.sqlite3'
        if registry_path.is_file():
            from quant_research.research.strategy import StrategyRegistry
            versions = StrategyRegistry(root).versions()
        else:
            versions = []
        frozen = [x for x in versions if x['status']=='FROZEN']
        stages['strategy_versions'] = _entry(
            'FROZEN_STRATEGY_CONFIGS_PRESENT' if frozen else 'NO_FROZEN_STRATEGY',
            '策略配置与不可变版本',state='OBSERVATION_ONLY' if frozen else 'BLOCKED',
            evidence={'stored_versions':len(versions),'frozen_versions':len(frozen)},
            missing=['Frozen configuration is not a qualified live model'] if frozen else ['Save and freeze a source-verified strategy version'],href='/strategies')
    except (PolicyError,OSError,ValueError) as exc:
        stages['strategy_versions'] = _failure(exc,'策略配置与不可变版本',href='/strategies')

    try:
        close_db = root/'data/managed/close_snapshots/observations.sqlite3'
        if close_db.is_file():
            from quant_research.workflow.forward_observations import inventory
            observations = inventory(root)
        else:
            observations = {'status':'BLOCKED','observations':{}}
        details = observations.get('observations') or {}
        count = int(details.get('verified_displayed_count') or 0)
        gaps = details.get('missing_xnys_sessions') or []
        state = 'OBSERVATION_ONLY' if count >= 2 and not gaps else 'BLOCKED'
        stages['forward_observations'] = _entry('FORWARD_OBSERVATIONS_PRESENT' if state != 'BLOCKED' else 'FORWARD_OBSERVATIONS_INCOMPLETE',
            '连续真实前向观察',state=state,
            evidence={'verified_observation_days':count, 'missing_sessions':gaps[:12]},
            missing=['At least two consecutive verified exchange sessions required for continuity checks'] if state=='BLOCKED' else ['Observations alone do not prove model signals or fills'],href='/paper')
    except (PolicyError,OSError,ValueError) as exc:
        stages['forward_observations'] = _failure(exc,'连续真实前向观察',href='/paper')

    try:
        from quant_research.workflow.frozen_decisions import inspect_frozen_decision
        frozen=inspect_frozen_decision(root,session=asof,db=database)
        accepted=frozen['status']=='ATTESTED_FORWARD_DECISION_RESEARCH_ONLY'
        stages['frozen_decision'] = _entry(
            'FROZEN_DECISION_HASH_AND_DATA_VERIFIED' if accepted else frozen['code'],
            '实际冻结的前向候选',state='OBSERVATION_ONLY' if accepted else 'BLOCKED',
            evidence={'session':frozen.get('session_date_et'),'candidates':frozen.get('candidate_count')},
            missing=['Frozen decision is research-only, not proof of predictive advantage or executed paper fills'] if accepted
                else ['No verified model, decision, exact-price snapshot and forward capability'],href='/signals')
    except (PolicyError,OSError,ValueError) as exc:
        stages['frozen_decision']=_failure(exc,'实际冻结的前向候选',href='/signals')

    try:
        from quant_research.backtest.verified_results import list_verified_backtests
        result = list_verified_backtests(root)
        runs = result.get('results') or []
        stages['verified_backtest_runs'] = _entry(
            'VERIFIED_MODELED_BACKTEST_RUNS_PRESENT' if runs else 'NO_ACCEPTED_REAL_BACKTEST',
            '真实来源严格回测产物',state='OBSERVATION_ONLY' if runs else 'BLOCKED',
            evidence={'verified_runs':len(runs)},
            missing=[] if runs else ['No source-verified, strict PIT historical replay with hashed results'],href='/backtests')
    except (PolicyError,OSError,ValueError) as exc:
        stages['verified_backtest_runs'] = _failure(exc,'真实来源严格回测产物',href='/backtests')

    try:
        config_file = root/'configs/experiments/baseline.yaml'
        if not config_file.is_file():
            raise PolicyError('PAPER_CONFIG_MISSING','An accepted paper configuration was not found')
        from quant_research.backtest.paper import account_summary
        from quant_research.models.settings import load_settings
        summary = account_summary(root/'data/paper.sqlite3',load_settings(config_file))
        if summary.get('status') == 'INTERNALLY_RECONCILED_PAPER_ESTIMATE':
            stages['paper_account'] = _entry('PAPER_LEDGER_RECONCILED_INTERNAL_ONLY',
                '本地模拟现金/持仓对账', state='OBSERVATION_ONLY',
                evidence={'last_session':summary.get('last_session'),
                    'recorded_sessions':summary.get('recorded_sessions')},
                missing=['Broker execution and external fill confirmation are not implied'],href='/paper')
        else:
            stages['paper_account'] = _entry(str(summary.get('code') or 'NO_ACCEPTED_PAPER_LEDGER'),
                '本地模拟现金/持仓对账', missing=['No accepted continuous source-linked paper account'],href='/paper')
    except (PolicyError,OSError,ValueError) as exc:
        stages['paper_account'] = _failure(exc,'本地模拟现金/持仓对账',href='/paper')

    try:
        from quant_research.workflow.paper_timeline import paper_timeline
        ledger=paper_timeline(root,limit=1)
        accepted=ledger['status']=='INTERNALLY_RECONCILED_PAPER_ESTIMATE'
        stages['paper_timeline']=_entry('PAPER_TIMELINE_CASH_RECONCILED' if accepted else ledger['code'],
            '逐日模拟账户现金与交易日序列',state='OBSERVATION_ONLY' if accepted else 'BLOCKED',
            evidence={'recorded_sessions':ledger.get('recorded_sessions')},
            missing=['Internal ledger consistency does not certify market source or broker executions'] if accepted
            else ['No accepted continuous real decision/price-linked ledger'],href='/paper')
    except (PolicyError,OSError,ValueError) as exc:
        stages['paper_timeline']=_failure(exc,'逐日模拟账户现金与交易日序列',href='/paper')

    # Work order reflects business dependencies, not naive PASS counts.
    sequence = ('dataset','historical_model','asset_directory','strategy_versions',
                'historical_backtest','forward_data','forward_shadow','verified_backtest_runs',
                'forward_observations','frozen_decision','paper_account','paper_timeline')
    next_steps = [
        {'module':name,'reason':stages[name]['code'],
         'description':stages[name]['description'],'view':stages[name]['view']}
        for name in sequence if stages[name]['status']=='BLOCKED'
    ]
    return {
        'status':'NOT_READY' if next_steps else 'EVIDENCE_INVENTORY_ONLY',
        'policy':'REAL_ONLY', 'asof_date_et':asof,
        'checked_at_utc':datetime.now(timezone.utc).isoformat(),
        'stages':stages, 'next_steps':next_steps,
        'historical_backtest_data_eligible':stages['historical_backtest']['status']=='PASS',
        'forward_shadow_data_eligible':stages['forward_shadow']['status']=='PASS',
        'complete_product_acceptance':False,
        'real_orders_enabled':False,
        'disclaimer':'No source observation, file hash, strategy configuration or ledger balance by itself proves forecast skill, PIT eligibility, broker fills or tradability.',
    }
