"""Event arithmetic for G2 validation; not a trading/paper execution entry point."""
from decimal import Decimal
from datetime import date
import hashlib
import json
import re

from quant_research.policy import PolicyError,require_real_source


def number(value):
    result=Decimal(str(value))
    if not result.is_finite() or result<0: raise ValueError('Invalid nonnegative amount')
    return result


class ActionAccounting:
    """Scalar accounting state. No prices, fills, strategy returns or historical holdings generated."""
    def __init__(self,symbol,shares=0,cash=0):
        self.symbol=symbol
        self.shares,self.cash=number(shares),number(cash)
        self.receivables,self.applied,self.journal,self.vintages={},{},[],{}
        self.claims={}

    def apply(self,event,day,entitled_quantity=None):
        require_real_source(event['provider'])
        if not re.fullmatch(r'[a-f0-9]{64}',event['raw_sha256']): raise ValueError('Response hash required')
        payload=event['payload'];eid=event['provider_event_id'];kind=event['event_type']
        if event.get('symbol')!=self.symbol:
            raise PolicyError('IDENTITY_MISMATCH','Event cannot be applied to a different security accounting state')
        if payload.get('id')!=eid: raise ValueError('Event identity mismatch')
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        if eid in self.vintages and self.vintages[eid]!=digest:
            raise PolicyError('ACTION_REVISION_REQUIRES_REVIEW','An applied event was revised; no automatic cash adjustment')
        day=date.fromisoformat(str(day))
        effective=date.fromisoformat(payload['ex_date']) if payload.get('ex_date') else None
        if kind in ('forward_splits','reverse_splits'):
            if day!=effective: raise ValueError('Split must apply on trading effective date')
            phase='split'
            if (eid,phase) in self.applied: return False
            old,new=number(payload['old_rate']),number(payload['new_rate'])
            if old==0 or new==0: raise ValueError('Split ratio must be positive')
            quantity=self.shares*new/old
            if quantity!=quantity.to_integral_value():
                raise PolicyError('CASH_IN_LIEU_REQUIRED','Fractional entitlement requires verified settlement')
            delta=quantity-self.shares;self.shares=quantity
            self.journal.append({'event_id':eid,'phase':phase,'cash_delta':Decimal(0),'share_delta':delta,'receivable_delta':Decimal(0)})
        elif kind=='cash_dividends':
            pay=date.fromisoformat(payload['payable_date'])
            if effective is None or pay<effective: raise ValueError('Invalid dividend dates')
            claim=(self.symbol,str(effective),str(pay),str(number(payload['rate'])))
            if claim in self.claims and self.claims[claim]!=eid:
                raise PolicyError('AMBIGUOUS_DIVIDEND_IDENTITY','Potential duplicate entitlement across provider IDs/CUSIPs')
            if day==effective and (eid,'entitlement') not in self.applied:
                quantity=number(self.shares if entitled_quantity is None else entitled_quantity)
                amount=quantity*number(payload['rate'])
                self.receivables[eid]=amount
                self.claims[claim]=eid
                self.applied[eid,'entitlement']=True
                self.vintages[eid]=digest
                self.journal.append({'event_id':eid,'phase':'entitlement','cash_delta':Decimal(0),'share_delta':Decimal(0),'receivable_delta':amount})
                if pay!=day:return True
            if day==effective and pay!=day:return False
            if day!=pay: raise ValueError('Dividend cash belongs to payable date')
            phase='payment'
            if (eid,phase) in self.applied:return False
            if eid not in self.receivables: raise PolicyError('DIVIDEND_ENTITLEMENT_MISSING','Payment requires ex-date entitlement history')
            amount=self.receivables.pop(eid);self.cash+=amount
            self.journal.append({'event_id':eid,'phase':phase,'cash_delta':amount,'share_delta':Decimal(0),'receivable_delta':-amount})
        else:
            raise PolicyError('ACTION_SETTLEMENT_UNVERIFIED','Unsupported event requires verified terms; no zero/last-price settlement')
        self.vintages[eid]=digest;self.applied[eid,phase]=True
        return True
