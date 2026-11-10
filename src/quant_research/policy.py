"""Non-configurable REAL_ONLY boundary. Evidence absence never enables execution."""
import re

REAL_SOURCES = frozenset({'ALPACA', 'YAHOO', 'FRENCH', 'KEN_FRENCH', 'SEC'})
SYMBOLS = 'SPY RSP IWM IWD IWF MTUM QUAL USMV HYG LQD XLK XLF XLE XLV XLI XLP XLY XLU XLB XLRE'.split()


class PolicyError(ValueError):
    def __init__(self, code, message, missing=()):
        self.code, self.message, self.missing = code, message, list(missing)
        super().__init__(message)

    def payload(self):
        return {'status':'BLOCKED','code':self.code,'message':self.message,
                'missing_evidence':self.missing,'policy':'REAL_ONLY','real_orders_enabled':False}


def require_real_source(source):
    if str(source).upper() not in REAL_SOURCES:
        raise PolicyError('NON_REAL_SOURCE_REJECTED','Only traceable real sources are accepted')


def require_real_frame(frame):
    if frame.empty:
        raise PolicyError('NO_REAL_DATA','No real market records available',['prices_daily'])
    for source in frame.source.unique():
        require_real_source(source)
    if 'raw_sha256' not in frame or not frame.raw_sha256.map(lambda x:bool(re.fullmatch(r'[0-9a-f]{64}',str(x)))).all():
        raise PolicyError('PROVENANCE_MISSING','Market records require response SHA256',['raw_response_sha256'])
    for col in ('security_id','quality_flag','availability_basis'):
        if col in frame and frame[col].astype(str).str.contains(r'synth|fixture|mock|demo',case=False,regex=True).any():
            raise PolicyError('NON_REAL_RECORD_REJECTED','Non-real market record rejected')


def execution_blocked():
    raise PolicyError('EXECUTION_EVIDENCE_MISSING','Real execution capability has not been accepted',
                      ['verified_raw_prices','security_identity','corporate_action_ledger','decision_snapshot'])
