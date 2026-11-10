import json
import hashlib
from pathlib import Path

import pandas as pd

from quant_research.backtest.simulation import simulate
from quant_research.models.dataset import load_panel
from quant_research.models.settings import load_settings
from quant_research.data.store import Warehouse
from quant_research.features.states import observations,frozen_states
from .common import fingerprint, finish, line_svg, new_run, report, save_frame


def execute(args):
    config = load_settings(args.experiment)
    from quant_research.data.bundle import load_real_bundle
    bundle=load_real_bundle(args.db,args.source,asof=str(config.validation_end),start=str(config.start))
    bundle.require('historical_backtest')
    from quant_research.policy import require_real_source
    require_real_source(args.source)
    prices,_,_ = load_panel(args.source,args.db,config)
    output,manifest = new_run(args,config,"P5",prices)
    manifest.update(status="BLOCKED_RAW_PRICE_AND_PIT_REQUIRED",prediction_rows=0,
        reason="Missing verified raw prices, identities, universe and corporate-action evidence")
    report(output,"真实回测阻断",manifest,{},note=manifest["reason"])
    finish(args,output,manifest)
    return 4
