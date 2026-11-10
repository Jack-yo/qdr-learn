from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
import yaml


class SystemConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    experiment_id: str
    start: date
    train_end: date
    validation_end: date
    sealed_test_start: Literal["2025-01-01"]
    horizons: list[int]
    gap_sessions: int = Field(ge=5)
    minimum_training_sessions: int = Field(ge=60)
    training_window_sessions: int = Field(ge=252)
    refit_frequency: Literal["quarter"]
    ridge_alpha: float = Field(gt=0)
    logistic_c: float = Field(gt=0)
    downside_threshold: float = Field(lt=0)
    downside_quantile: float = Field(gt=0, lt=0.5)
    max_unconditional_downside: float = Field(gt=0, le=0.2)
    state_threshold_quantile: float = Field(gt=0, lt=1)
    seed: int
    initial_cash: float = Field(gt=0)
    max_stock_weight: float = Field(gt=0, le=0.1)
    max_total_weight: float = Field(gt=0, le=0.5)
    max_sector_weight: float = Field(gt=0, le=0.25)
    equity_risk_per_trade: float = Field(gt=0, le=0.003)
    stop_atr_multiple: float = Field(ge=2)
    minimum_price: float = Field(ge=5)
    minimum_adv20: float = Field(ge=20000000)
    max_participation: float = Field(gt=0, le=0.01)
    fee_bps_per_side: float = Field(ge=0)
    impact_bps_per_full_adv: float = Field(ge=0)
    cost_scenarios_bps_per_side: list[int]
    default_cost_bps_per_side: int = Field(ge=0)
    top_n: int = Field(ge=1, le=10)
    paper_horizon: Literal[1,3,5]
    research_grade_required: Literal[True]

    @model_validator(mode="after")
    def valid(self):
        if not self.start <= self.train_end < self.validation_end < date(2025,1,1):
            raise ValueError("Development window must precede sealed 2025 test")
        if self.horizons != [1,3,5] or self.cost_scenarios_bps_per_side != [5,10,20,50]:
            raise ValueError("Horizon and cost experiments are frozen")
        if self.default_cost_bps_per_side not in self.cost_scenarios_bps_per_side:
            raise ValueError("Default cost must be one frozen scenario")
        return self


def load_settings(path):
    return SystemConfig.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
