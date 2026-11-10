from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    calendar: Literal["XNYS"]
    calendar_start: str
    calendar_end: str
    signal_delay_minutes: int = Field(gt=0)
    horizons: list[int]
    fixture_start: str
    fixture_end: str
    fixture_asof: str
    seed: int
    universe_version: str
    model_version: str

    @model_validator(mode="after")
    def valid(self):
        if self.horizons != [1, 3, 5]:
            raise ValueError("P0 protocol requires independent horizons [1, 3, 5]")
        return self


def load_config(path: Path) -> Settings:
    return Settings.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
