"""Deterministic cash-book scenario from frozen V4 research plans and outcomes.

This is *not* a paper broker ledger. Entry/exit prices come from the modeled
future OHLC path; capital and costs are explicit research assumptions.
Overlapping positions reserve cash until their observed modeled exit.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from hashlib import sha256
import json
import math

from quant_research.workflow.v4_candidate_bridge import read_indicative_review
from quant_research.workflow.v4_plan_outcomes import read_research_outcomes


def replay_research_cash_book(root, keys: list[tuple[str,str]], *,
                              initial_cash: float) -> dict:
    if (isinstance(initial_cash,bool) or not isinstance(initial_cash,(int,float))
            or not math.isfinite(initial_cash) or initial_cash<=0):
        raise ValueError("RESEARCH_CASH_BUDGET_INVALID")
    if not isinstance(keys,list) or len(keys)>10000 or len(keys)!=len(set(keys)):
        raise ValueError("RESEARCH_PLAN_KEYS_INVALID_OR_DUPLICATE")
    events=defaultdict(list)
    for day,identity in keys:
        plan=read_indicative_review(root,day,identity)
        result=read_research_outcomes(root,day,identity)
        if result['source_plan_sha256']!=plan['content_sha256']:
            raise ValueError("RESEARCH_OUTCOME_PLAN_SOURCE_MISMATCH")
        if plan.get('account_evidence')!='EXPLICIT_EMPTY_RESEARCH_BUDGET_NOT_A_PAPER_ACCOUNT':
            raise ValueError("ONLY_EMPTY_BUDGET_RESEARCH_SCENARIOS_SUPPORTED")
        expected={str(x['security_id']):x for x in plan['plans']}
        observed={str(x['security_id']):x for x in result['evaluated']}
        if len(expected)!=len(plan['plans']) or set(expected)!=set(observed):
            raise ValueError("RESEARCH_OUTCOME_COVERAGE_INCOMPLETE")
        for sid,p in expected.items():
            o=observed[sid]
            entry=date.fromisoformat(o['planned_entry_session'])
            end=date.fromisoformat(o['modeled_exit_session'])
            if entry<=date.fromisoformat(day) or end<entry:
                raise ValueError("RESEARCH_OUTCOME_SESSION_ORDER_INVALID")
            weight=float(p['indicative_weight'])
            cost=float(o['assumed_round_trip_cost'])
            entry_price=float(o['modeled_entry_price'])
            exit_price=float(o['modeled_exit_price'])
            if (not all(math.isfinite(v) for v in (weight,cost,entry_price,exit_price))
                    or not 0<weight<=1 or not 0<=cost<=.2
                    or min(entry_price,exit_price)<=0):
                raise ValueError("RESEARCH_CASH_BOOK_NUMERIC_INVALID")
            key=f"{day}:{identity}:{sid}"
            events[entry].append(('enter',key,weight,entry_price,exit_price,cost,end))
            # An exit-only day must participate in the chronological event
            # loop; otherwise reserved cash would be released too late.
            events[end].append(('exit',key,weight,entry_price,exit_price,cost,end))
    cash=float(initial_cash)
    holdings={}
    transactions=[]
    for session in sorted(events):
        # Exit before same-day entries, freeing settled scenario capital.
        for key,h in sorted(list(holdings.items())):
            if h['exit_session']==session:
                proceeds=h['notional']*(h['exit_price']/h['entry_price']-h['cost'])
                cash+=proceeds
                transactions.append({'session':session.isoformat(),'event':'MODELED_EXIT',
                                     'position_id':key,'cash_delta':proceeds,
                                     'reason':'OBSERVED_FUTURE_PATH_SCENARIO'})
                del holdings[key]
        entering=sorted((event for event in events[session] if event[0]=='enter'),
                        key=lambda x:x[1])
        requested=sum(float(x[2])*initial_cash for x in entering)
        # Conservative policy: block, never silently rescale an overbooked day.
        if requested>cash+1e-8:
            raise ValueError("RESEARCH_CASH_OVERCOMMITTED_ON_ENTRY")
        for _,key,weight,entry,exit_price,cost,end in entering:
            notional=weight*initial_cash
            cash-=notional
            holdings[key]={'notional':notional,'entry_price':entry,
                           'exit_price':exit_price,'cost':cost,'exit_session':end}
            transactions.append({'session':session.isoformat(),'event':'MODELED_ENTRY',
                                 'position_id':key,'cash_delta':-notional,
                                 'reason':'FROZEN_RESEARCH_WEIGHT_ONLY'})
    if holdings:
        raise ValueError("RESEARCH_CASH_BOOK_HAS_UNSETTLED_POSITIONS")
    result={'status':'MODELED_RESEARCH_CASH_SCENARIO_ONLY',
            'initial_cash':float(initial_cash),'final_cash':cash,
            'modeled_total_return':cash/initial_cash-1,
            'transactions':transactions,'plan_count':len(keys),
            'broker_fills_observed':False,'paper_ledger_advanced':False,
            'real_orders_enabled':False,
            'warning':'Research weights and daily OHLC assumed fills; not actual account equity'}
    result['content_sha256']=sha256(json.dumps(result,sort_keys=True,
        separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return result
