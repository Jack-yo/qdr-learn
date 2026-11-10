from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
import yaml


class Experiment(BaseModel):
    model_config = ConfigDict(extra="forbid",frozen=True)
    experiment_id: str
    start: date
    train_end: date
    validation_end: date
    sealed_test_start: Literal["2025-01-01"]
    horizons: list[int]
    embargo_sessions: int = Field(ge=5)
    exclude_symbols: list[str]
    benchmark: str
    min_cross_section: int = Field(ge=5)
    quantiles: Literal[5]
    bootstrap_block_sessions: int = Field(ge=5)
    bootstrap_replicates: int = Field(ge=100)
    seed: int
    costs: Literal["NOT_IMPLEMENTED_P5"]
    success_criterion: Literal["ENGINEERING_AND_FORMULA_VALIDATION_ONLY"]

    @model_validator(mode="after")
    def valid(self):
        if not self.start <= self.train_end < self.validation_end < date(2025,1,1):
            raise ValueError("Invalid temporal split; final test from 2025 remains sealed")
        if self.horizons != [1,3,5]:
            raise ValueError("Horizons must be frozen [1,3,5]")
        return self


def load_experiment(path):
    return Experiment.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
