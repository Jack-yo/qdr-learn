"""P6 binding contract between admitted L2 context and V4 L3 style inputs.

Identity binding and historical PIT attestation are deliberately separate.
A receipt can prove that every numeric style_* feature in market_style is the
exact frozen/admitted L2 value for that date without claiming the underlying
historical source was independently PIT-certified.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
import re

import pandas as pd

from quant_research.clock import TradingClock
from quant_research.research.l2_forecast import HORIZONS, STYLE_IDS
from quant_research.workflow.l2_downstream import build_downstream_context


CONTRACT_VERSION = "qdr-l2-l3-style-binding-v1"
_SCOPE = "HISTORICAL_AND_CURRENT"
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _canonical(value) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    )


def style_column(style_id: str, horizon: int) -> str:
    if style_id not in STYLE_IDS or horizon not in HORIZONS:
        raise ValueError("Invalid L2 style/horizon binding key")
    return f"style_l2_{style_id}_h{horizon}"


def validate_l2_style_binding_receipt(receipt: dict) -> dict:
    """Structural validation used by bundle/archive contracts."""
    required = {
        "contract_version", "scope", "start_session", "end_session", "rows",
        "style_columns", "context_identity_sha256", "model_versions",
        "label_bundle_sha256s", "source_snapshot_sha256s",
        "binding_verified", "historical_pit_attested",
        "decision_eligible", "real_orders_enabled",
    }
    if not isinstance(receipt, dict) or required - set(receipt):
        raise ValueError("L3_L2_STYLE_BINDING_RECEIPT_INCOMPLETE")
    if receipt["contract_version"] != CONTRACT_VERSION or receipt["scope"] != _SCOPE:
        raise ValueError("L3_L2_STYLE_BINDING_RECEIPT_VERSION_INVALID")
    try:
        start = pd.Timestamp(receipt["start_session"])
        end = pd.Timestamp(receipt["end_session"])
    except (TypeError, ValueError):
        raise ValueError("L3_L2_STYLE_BINDING_SESSION_INVALID") from None
    if (
        start.tzinfo is not None or end.tzinfo is not None
        or start != start.normalize() or end != end.normalize() or start > end
    ):
        raise ValueError("L3_L2_STYLE_BINDING_SESSION_INVALID")
    if type(receipt["rows"]) is not int or receipt["rows"] < 1:
        raise ValueError("L3_L2_STYLE_BINDING_ROW_COUNT_INVALID")
    columns = receipt["style_columns"]
    expected_allowed = {
        style_column(style, horizon)
        for style in STYLE_IDS for horizon in HORIZONS
    }
    if (
        not isinstance(columns, list) or not columns
        or columns != sorted(set(columns))
        or not set(columns).issubset(expected_allowed)
    ):
        raise ValueError("L3_L2_STYLE_BINDING_COLUMNS_INVALID")
    if not _SHA.fullmatch(str(receipt["context_identity_sha256"])):
        raise ValueError("L3_L2_STYLE_BINDING_IDENTITY_INVALID")
    for field in (
        "model_versions", "label_bundle_sha256s", "source_snapshot_sha256s"
    ):
        values = receipt[field]
        if not isinstance(values, list) or not values or values != sorted(set(values)):
            raise ValueError("L3_L2_STYLE_BINDING_PROVENANCE_INVALID")
    if any(not isinstance(x, str) or not x for x in receipt["model_versions"]):
        raise ValueError("L3_L2_STYLE_BINDING_MODEL_VERSION_INVALID")
    if any(not _SHA.fullmatch(str(x)) for x in receipt["label_bundle_sha256s"]):
        raise ValueError("L3_L2_STYLE_BINDING_LABEL_SHA_INVALID")
    if any(not _SHA.fullmatch(str(x)) for x in receipt["source_snapshot_sha256s"]):
        raise ValueError("L3_L2_STYLE_BINDING_SOURCE_SHA_INVALID")
    if receipt["binding_verified"] is not True:
        raise ValueError("L3_L2_STYLE_BINDING_NOT_VERIFIED")
    for field in (
        "historical_pit_attested", "decision_eligible", "real_orders_enabled"
    ):
        if type(receipt[field]) is not bool:
            raise ValueError("L3_L2_STYLE_BINDING_BOOLEAN_INVALID")
    if receipt["decision_eligible"] is not False or receipt["real_orders_enabled"] is not False:
        raise ValueError("L3_L2_STYLE_BINDING_CANNOT_ENABLE_EXECUTION")
    return {
        key: receipt[key]
        for key in sorted(required)
    }


def build_l2_style_history_binding(
    root: Path,
    market_style: pd.DataFrame,
    *,
    downstream_builder=build_downstream_context,
    clock: TradingClock | None = None,
) -> dict:
    """Audit every market_style row against the exact frozen L2 context.

    This is an explicit offline bundle-build check. It may be expensive and
    must never run inside a GET endpoint.
    """
    if not isinstance(market_style, pd.DataFrame) or market_style.empty:
        raise ValueError("L3_L2_MARKET_STYLE_FRAME_REQUIRED")
    if {"date", "state_available_at"} - set(market_style):
        raise ValueError("L3_L2_MARKET_STYLE_TIMESTAMPS_REQUIRED")
    dates = pd.to_datetime(market_style["date"], errors="raise")
    if (
        dates.dt.tz is not None or dates.isna().any()
        or not dates.eq(dates.dt.normalize()).all()
        or dates.duplicated().any() or not dates.is_monotonic_increasing
    ):
        raise ValueError("L3_L2_MARKET_STYLE_SESSION_INVALID")
    clock = clock or TradingClock()
    numeric_style_columns = sorted(
        column for column in market_style.columns
        if column.startswith("style_")
        and pd.api.types.is_numeric_dtype(market_style[column])
    )
    if not numeric_style_columns:
        raise ValueError("L3_L2_NUMERIC_STYLE_COLUMNS_REQUIRED")

    identities = []
    model_versions = set()
    label_shas = set()
    source_shas = set()
    all_pit = True
    expected_columns = None
    for index, day in enumerate(dates):
        session = day.date().isoformat()
        context = downstream_builder(Path(root).resolve(), asof=session)
        if context.get("status") != "MODEL_ADMITTED_CONTEXT":
            raise ValueError("L3_L2_CONTEXT_NOT_MODEL_ADMITTED:" + session)
        if not _SHA.fullmatch(str(context.get("forecast_identity") or "")):
            raise ValueError("L3_L2_FORECAST_IDENTITY_MISSING:" + session)
        if not _SHA.fullmatch(str(context.get("validation_identity") or "")):
            raise ValueError("L3_L2_VALIDATION_IDENTITY_MISSING:" + session)
        if not _SHA.fullmatch(str(context.get("label_bundle_sha256") or "")):
            raise ValueError("L3_L2_LABEL_BUNDLE_SHA_MISSING:" + session)
        if not _SHA.fullmatch(str(context.get("source_snapshot_sha256") or "")):
            raise ValueError("L3_L2_SOURCE_SNAPSHOT_SHA_MISSING:" + session)
        model_version = context.get("model_version")
        if not isinstance(model_version, str) or not model_version:
            raise ValueError("L3_L2_MODEL_VERSION_MISSING:" + session)
        admitted = [
            row for row in context.get("contexts", [])
            if row.get("downstream_context_eligible") is True
        ]
        if not admitted:
            raise ValueError("L3_L2_NO_ADMITTED_CONTEXT:" + session)
        column_values = {
            style_column(row["style_id"], int(row["horizon"])):
                float(row["admitted_relative_return"])
            for row in admitted
        }
        columns = sorted(column_values)
        if expected_columns is None:
            expected_columns = columns
        elif columns != expected_columns:
            raise ValueError("L3_L2_ADMITTED_GRID_CHANGED_ACROSS_HISTORY")
        if numeric_style_columns != columns:
            raise ValueError("L3_L2_STYLE_COLUMNS_NOT_EXACTLY_ADMITTED")

        row = market_style.iloc[index]
        for column, expected in column_values.items():
            actual = row[column]
            if (
                pd.isna(actual)
                or not math.isfinite(float(actual))
                or not math.isclose(
                    float(actual), expected, rel_tol=0.0, abs_tol=1e-15
                )
            ):
                raise ValueError("L3_L2_STYLE_VALUE_MISMATCH:" + column)
        available = pd.Timestamp(row["state_available_at"])
        if available.tzinfo is None:
            raise ValueError("L3_L2_STATE_AVAILABILITY_UNZONED")
        signal = pd.Timestamp(clock.signal(session))
        if available.tz_convert("UTC") > signal:
            raise ValueError("L3_L2_STATE_AVAILABLE_AFTER_SIGNAL")

        model_versions.add(model_version)
        label_shas.add(str(context["label_bundle_sha256"]))
        source_shas.add(str(context["source_snapshot_sha256"]))
        all_pit = all_pit and context.get("historical_decision_eligible") is True
        identities.append({
            "date": session,
            "forecast_identity": context["forecast_identity"],
            "validation_identity": context["validation_identity"],
            "model_version": model_version,
            "label_bundle_sha256": context["label_bundle_sha256"],
            "source_snapshot_sha256": context["source_snapshot_sha256"],
            "style_values": {
                column: column_values[column] for column in columns
            },
        })

    receipt = {
        "contract_version": CONTRACT_VERSION,
        "scope": _SCOPE,
        "start_session": dates.iloc[0].date().isoformat(),
        "end_session": dates.iloc[-1].date().isoformat(),
        "rows": int(len(market_style)),
        "style_columns": numeric_style_columns,
        "context_identity_sha256": sha256(
            _canonical(identities).encode("utf-8")
        ).hexdigest(),
        "model_versions": sorted(model_versions),
        "label_bundle_sha256s": sorted(label_shas),
        "source_snapshot_sha256s": sorted(source_shas),
        "binding_verified": True,
        "historical_pit_attested": bool(all_pit),
        "decision_eligible": False,
        "real_orders_enabled": False,
    }
    return validate_l2_style_binding_receipt(receipt)


def verify_l2_style_history_binding(
    root: Path,
    market_style: pd.DataFrame,
    receipt: dict,
    *,
    downstream_builder=build_downstream_context,
    clock: TradingClock | None = None,
) -> dict:
    """Recompute the binding and require byte-equivalent canonical receipt."""
    supplied = validate_l2_style_binding_receipt(receipt)
    actual = build_l2_style_history_binding(
        root,
        market_style,
        downstream_builder=downstream_builder,
        clock=clock,
    )
    if _canonical(actual) != _canonical(supplied):
        raise ValueError("L3_L2_STYLE_BINDING_RECEIPT_MISMATCH")
    return actual


def main(argv=None):
    """Build one audited receipt for an existing market_style file; no bundle mutation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Audit L2 MODEL_ADMITTED history against V4 market_style; no model fit"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--market-style", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Optional new JSON receipt path; existing files are never overwritten",
    )
    args = parser.parse_args(argv)
    path = args.market_style
    if not path.is_file():
        parser.error("market_style file does not exist")
    if path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(path)
    elif path.suffix.lower() == ".csv":
        frame = pd.read_csv(path)
    else:
        parser.error("market_style must be Parquet or CSV")
    receipt = build_l2_style_history_binding(args.root, frame)
    encoded = json.dumps(
        receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    )
    if args.output is not None:
        output = args.output.resolve()
        if output.exists():
            raise FileExistsError("L2_L3_BINDING_RECEIPT_ALREADY_EXISTS")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
