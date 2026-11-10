from pathlib import Path

import pytest

from quant_research.config import Settings, load_config


@pytest.mark.parametrize("change", [{"calendar": "24/7"}, {"signal_delay_minutes": 0}, {"horizons": [1, 5]}, {"unknown": True}])
def test_protocol_config_rejects_invalid_changes(change):
    settings = load_config(Path("configs/base.yaml"))
    with pytest.raises(ValueError):
        Settings.model_validate({**settings.model_dump(), **change})
