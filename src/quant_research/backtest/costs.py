from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class CostModel:
    slippage_bps: float
    fee_bps: float = 0.0
    impact_bps_per_full_adv: float = 100.0

    def __post_init__(self):
        if not all(isfinite(v) and v>=0 for v in (self.slippage_bps,self.fee_bps,self.impact_bps_per_full_adv)):
            raise ValueError("Costs must be finite nonnegative values")

    def fill(self,side,raw_price,quantity,adv20):
        if side not in ("BUY","SELL") or not all(isfinite(v) for v in (raw_price,quantity,adv20)) or raw_price<=0 or quantity<=0 or adv20<=0:
            raise ValueError("Invalid fill inputs")
        notional = raw_price*quantity
        rate = (self.slippage_bps+self.impact_bps_per_full_adv*notional/adv20)/10000
        if rate>=1:
            raise ValueError("Cost exceeds feasible fill price")
        price = raw_price*(1+rate if side=="BUY" else 1-rate)
        fee = notional*self.fee_bps/10000
        return price,fee,abs(price-raw_price)*quantity+fee

    def round_trip_fraction(self,notional,adv20):
        return 2*(self.slippage_bps+self.fee_bps+self.impact_bps_per_full_adv*notional/adv20)/10000
