"""L2 seven-style registry and causal observation calculations."""
import pandas as pd
import pytest

from quant_research.research.l2_style_rotation import (
    REQUIRED_SYMBOLS, STYLE_REGISTRY, registry_payload, style_observations_v1,
)


def _inputs(n=100):
    sessions = pd.bdate_range("2025-01-02", periods=n)
    symbols = list(REQUIRED_SYMBOLS)
    ix = range(n)
    prices = pd.DataFrame(
        {symbol: [80 + i * 0.7 + j * (0.03 + i * 0.001)
                  for j in ix]
         for i, symbol in enumerate(symbols)},
        index=sessions,
    )
    availability = pd.DataFrame(
        {symbol: [pd.Timestamp(day, tz="UTC") + pd.Timedelta(hours=22)
                  for day in sessions] for symbol in symbols},
        index=sessions,
    )
    return sessions, prices, availability


def test_registry_contains_seven_styles_and_fixed_sector_baskets():
    payload = registry_payload()
    assert len(STYLE_REGISTRY) == 7
    assert {x["style_id"] for x in payload["styles"]} == {
        "size", "value", "growth", "momentum", "quality", "low_vol", "cyc_def"
    }
    cyc = next(x for x in payload["styles"] if x["style_id"] == "cyc_def")
    assert cyc["numerator"] == ["XLI", "XLY", "XLB", "XLF"]
    assert cyc["denominator"] == ["XLP", "XLU", "XLV"]
    assert len(payload["required_symbols"]) == 13


def test_observation_outputs_all_styles_and_expected_windows():
    sessions, prices, availability = _inputs()
    result = style_observations_v1(prices, availability)
    assert result.style_id.nunique() == 7
    assert len(result) == len(sessions) * 7
    assert set(result.protocol_version) == {"qdr-l2-style-observation-v1"}
    assert set(result.registry_version) == {"seven-style-etf-proxy-v1"}
    assert not result.decision_eligible.any()
    assert result.loc[result.date.eq(sessions[0]), "relative_return_5d"].isna().all()
    assert result.loc[result.date.eq(sessions[59]), "relative_return_60d"].isna().all()
    assert result.loc[result.date.eq(sessions[60]), "relative_return_60d"].notna().all()


def test_missing_required_basket_member_blocks_only_affected_style_window():
    sessions, prices, availability = _inputs()
    prices.loc[sessions[80], "XLY"] = float("nan")
    result = style_observations_v1(prices, availability)
    cyc = result.loc[result.style_id.eq("cyc_def")].set_index("date")
    assert pd.isna(cyc.loc[sessions[80], "relative_return_5d"])
    assert pd.isna(cyc.loc[sessions[80], "relative_return_60d"])
    other = result.loc[result.style_id.eq("size")].set_index("date")
    assert pd.notna(other.loc[sessions[80], "relative_return_5d"])


def test_no_forward_fill_and_prefix_causality():
    sessions, prices, availability = _inputs()
    baseline = style_observations_v1(prices, availability)
    changed = prices.copy()
    changed.loc[sessions[-1], :] *= 3
    recomputed = style_observations_v1(changed, availability)
    before = baseline.loc[baseline.date.lt(sessions[-1])].reset_index(drop=True)
    after = recomputed.loc[recomputed.date.lt(sessions[-1])].reset_index(drop=True)
    pd.testing.assert_frame_equal(before, after)
    prices.loc[sessions[50], "SPY"] = float("nan")
    gap = style_observations_v1(prices, availability)
    size = gap.loc[gap.style_id.eq("size")].set_index("date")
    assert pd.isna(size.loc[sessions[50], "relative_return_5d"])
    assert pd.isna(size.loc[sessions[51], "relative_return_5d"])


def test_availability_timestamp_uses_latest_source_in_complete_window():
    sessions, prices, availability = _inputs()
    availability.loc[sessions[90], "IWM"] = pd.Timestamp("2025-06-01T00:00:00Z")
    result = style_observations_v1(prices, availability)
    size = result.loc[result.style_id.eq("size")].set_index("date")
    assert size.loc[sessions[90], "relative_return_5d_available_at"] == pd.Timestamp("2025-06-01T00:00:00Z")
    assert size.loc[sessions[91], "relative_return_5d_available_at"] == pd.Timestamp("2025-06-01T00:00:00Z")


def test_rejects_missing_symbols_and_misaligned_input_matrices():
    sessions, prices, availability = _inputs()
    with pytest.raises(ValueError, match="Missing required"):
        style_observations_v1(prices.drop(columns=["XLY"]), availability.drop(columns=["XLY"]))
    with pytest.raises(ValueError, match="identical"):
        style_observations_v1(prices, availability.iloc[:-1])


def test_nonpositive_prices_are_rejected():
    sessions, prices, availability = _inputs()
    prices.loc[sessions[5], "SPY"] = 0
    with pytest.raises(ValueError, match="positive"):
        style_observations_v1(prices, availability)


def test_cyclical_defensive_is_not_silently_reweighted_when_member_missing():
    sessions, prices, availability = _inputs()
    prices.loc[sessions[70], "XLB"] = float("nan")
    result = style_observations_v1(prices, availability)
    cyc = result.loc[result.style_id.eq("cyc_def")].set_index("date")
    assert pd.isna(cyc.loc[sessions[70], "daily_relative_return"])
    assert pd.isna(cyc.loc[sessions[70], "relative_return_5d"])


def test_return_window_availability_includes_the_prior_close_needed_for_first_return():
    sessions, prices, availability = _inputs()
    availability.loc[sessions[84], "IWM"] = pd.Timestamp("2025-06-01T00:00:00Z")
    result = style_observations_v1(prices, availability)
    size = result.loc[result.style_id.eq("size")].set_index("date")
    # A five-session close-to-close return ending at session 89 uses prices
    # from sessions 84 through 89, i.e. six dated price observations.
    assert size.loc[sessions[89], "relative_return_5d_available_at"] == pd.Timestamp("2025-06-01T00:00:00Z")
