"""Canonical QDR L1 market-data catalogue.

Six data systems organise twelve research dimensions. Registry entries describe
requirements and current code coverage; they never assert live provider access,
dataset completeness, PIT eligibility, or predictive validity.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True)
class SystemSpec:
    key: str
    name: str
    purpose: str
    dimensions: tuple[str, ...]
    priority: str


@dataclass(frozen=True)
class DimensionSpec:
    key: str
    name: str
    description: str
    system_keys: tuple[str, ...]
    role: str
    priority: str


@dataclass(frozen=True)
class FeatureSpec:
    key: str
    dimension: str
    name: str
    unit: str
    cadence: str
    sources: tuple[str, ...]
    history_days: int
    priority: str
    implementation: str
    access: str
    pit_requirement: str


@dataclass(frozen=True)
class SourceSpec:
    key: str
    name: str
    provider_type: str
    datasets: tuple[str, ...]
    cadence: str
    scope: str
    access: str
    code_status: str
    pit_status: str
    limitation: str


SYSTEMS = (
    SystemSpec("breadth_structure", "全市场广度与行业结构",
               "判断市场上涨/下跌是否扩散、集中或衰竭。",
               ("breadth", "correlation"), "P0"),
    SystemSpec("volatility_options", "波动率与期权风险定价",
               "衡量已实现波动、隐含风险定价、尾部保护和期权仓位。",
               ("volatility", "options_pricing", "options_positioning"), "P0/P1"),
    SystemSpec("sector_style", "行业轮动与风格因子",
               "识别行业相对强弱、风格偏好、轮动和内部离散度。",
               ("price", "correlation"), "P0"),
    SystemSpec("liquidity_flows", "市场流动性与资金流",
               "监测交易流动性、ETF 资金、短仓和杠杆持仓。",
               ("microstructure", "positioning", "funding"), "P1/P2"),
    SystemSpec("macro_cross_asset", "宏观与跨资产风险传导",
               "监测利率、信用、美元、商品和融资环境对股票的传导。",
               ("cross_asset", "funding"), "P0/P1"),
    SystemSpec("catalysts_expectations", "催化剂与市场预期",
               "识别未来已知事件、预期差和事件风险窗口。",
               ("events",), "P1"),
)

DIMENSIONS = (
    DimensionSpec("price", "价格趋势", "共享基础行情、收益、趋势、区间和回撤。",
                  ("sector_style",), "shared_input", "P0"),
    DimensionSpec("breadth", "真实股票市场广度", "上涨/下跌家数、成交广度、均线广度和新高新低。",
                  ("breadth_structure",), "market_input", "P0"),
    DimensionSpec("volatility", "波动结构", "实现波动、下行波动、VIX 家族和期限结构。",
                  ("volatility_options",), "market_input", "P0"),
    DimensionSpec("options_pricing", "期权风险定价", "Put/Call、IV、Skew、期限斜率和波动风险溢价。",
                  ("volatility_options",), "market_input", "P1"),
    DimensionSpec("options_positioning", "期权仓位与对冲", "OI 分布、到期集中度、0DTE 和有条件的 Gamma 情景。",
                  ("volatility_options",), "market_input", "P2"),
    DimensionSpec("microstructure", "市场微观结构", "报价价差、盘口深度、订单失衡和价格冲击。",
                  ("liquidity_flows",), "market_input", "P2"),
    DimensionSpec("correlation", "相关性与离散度", "个股/行业相关性、收益离散度和同步下跌。",
                  ("breadth_structure", "sector_style"), "shared_input", "P0"),
    DimensionSpec("cross_asset", "跨资产风险传导", "国债、实际利率、美元、信用、商品和加密资产。",
                  ("macro_cross_asset",), "market_input", "P1"),
    DimensionSpec("positioning", "资金与拥挤", "ETF 申赎、CFTC 持仓、Short Interest 与 Short Volume。",
                  ("liquidity_flows",), "market_input", "P1/P2"),
    DimensionSpec("events", "宏观事件与催化剂", "经济数据日程、已发布实际值/预期差和财报事件。",
                  ("catalysts_expectations",), "market_input", "P1"),
    DimensionSpec("funding", "融资与金融条件", "SOFR/EFFR、回购、信用融资和金融压力。",
                  ("liquidity_flows", "macro_cross_asset"), "shared_input", "P1/P2"),
    DimensionSpec("path", "未来价格路径与尾部结果", "H1/H3/H5 收益、MFE/MAE 和先触及事件。",
                  (), "outcome_validation_not_input", "P0"),
)

# key, dimension, name, unit, cadence, sources, history_days, priority,
# implementation, access, PIT requirement.
_FEATURE_ROWS = (
    ("security_return_1","price","单只证券单日收益","%","daily",("alpaca_bars",),1260,"P0","PARTIAL","credentialed","bar_available_at"),
    ("security_return_5","price","单只证券五日收益","%","daily",("alpaca_bars",),1260,"P0","PARTIAL","credentialed","bar_available_at"),
    ("security_return_20","price","单只证券二十日收益","%","daily",("alpaca_bars",),1260,"P0","PARTIAL","credentialed","bar_available_at"),
    ("security_return_60","price","单只证券六十日收益","%","daily",("alpaca_bars",),1260,"P1","PARTIAL","credentialed","bar_available_at"),
    ("sector_relative_5","price","行业 ETF 相对 SPY 五日强度","%","daily",("alpaca_bars",),1260,"P0","PARTIAL","credentialed","bar_available_at"),
    ("style_relative_5","price","风格 ETF 相对 SPY 五日强度","%","daily",("alpaca_bars",),1260,"P1","PARTIAL","credentialed","bar_available_at"),
    ("breadth_proxy_rsp_spy_5","breadth","等权 ETF 相对 SPY 五日强度代理","%","daily",("alpaca_bars",),1260,"P1","IMPLEMENTED","credentialed","ETF_PROXY_NOT_FULL_MARKET_PIT"),
    ("sector_up_share_1","breadth","行业 ETF 当日上涨占比代理","%","daily",("alpaca_bars",),1260,"P1","IMPLEMENTED","credentialed","SECTOR_ETF_PROXY_NOT_FULL_MARKET_PIT"),
    ("small_cap_relative_5","price","IWM 相对 SPY 五日强度","%","daily",("alpaca_bars",),1260,"P1","IMPLEMENTED","credentialed","ETF_PROXY_NOT_FULL_MARKET_PIT"),
    ("credit_proxy_hyg_lqd_5","cross_asset","HYG 相对 LQD 五日强度代理","%","daily",("alpaca_bars",),1260,"P1","IMPLEMENTED","credentialed","ETF_PROXY_NOT_FULL_MARKET_PIT"),
    ("overnight","price","SPY 隔夜收益","%","daily",("alpaca_bars",),1260,"P1","IMPLEMENTED","credentialed","bar_available_at"),
    ("intraday","price","SPY 日内收益","%","daily",("alpaca_bars",),1260,"P1","IMPLEMENTED","credentialed","bar_available_at"),
    ("close_location","price","SPY 收盘位置","ratio","daily",("alpaca_bars",),1260,"P2","IMPLEMENTED","credentialed","bar_available_at"),
    ("sector_dispersion_1","correlation","行业 ETF 单日收益离散度","%","daily",("alpaca_bars",),1260,"P1","IMPLEMENTED","credentialed","ETF_PROXY_NOT_FULL_MARKET_PIT"),
    ("duration_proxy_5","cross_asset","TLT 相对 SHY 五日强度","%","daily",("alpaca_bars",),1260,"P1","IMPLEMENTED","credentialed","ETF_PROXY_NOT_FULL_MARKET_PIT"),
    ("spy_level1_spread_bps","microstructure","SPY Level-1 报价买卖价差","bps","intraday",("alpaca_snapshots",),252,"P2","PARTIAL","credentialed","LEVEL1_QUOTE_NOT_FULL_DEPTH"),
    ("vol_ratio","volatility","RV5 / RV20 波动比率","ratio","daily",("alpaca_bars",),1260,"P1","IMPLEMENTED","credentialed","bar_available_at"),
    ("momentum_z","price","动量标准分","z","daily",("alpaca_bars",),1260,"P2","PARTIAL","credentialed","DERIVED_RESEARCH_FEATURE"),
    ("pressure_z","volatility","卖压标准分","z","daily",("alpaca_bars",),1260,"P2","PARTIAL","credentialed","DERIVED_RESEARCH_FEATURE"),
    ("decay_z","volatility","卖压衰减标准分","z","daily",("alpaca_bars",),1260,"P2","PARTIAL","credentialed","DERIVED_RESEARCH_FEATURE"),
    ("spy_return_1","price","SPY 单日收益","%","daily",("alpaca_bars",),1260,"P0","IMPLEMENTED","credentialed","bar_available_at"),
    ("spy_return_5","price","SPY 五日收益","%","daily",("alpaca_bars",),1260,"P0","IMPLEMENTED","credentialed","bar_available_at"),
    ("spy_return_20","price","SPY 二十日收益","%","daily",("alpaca_bars",),1260,"P0","IMPLEMENTED","credentialed","bar_available_at"),
    ("spy_return_60","price","SPY 六十日收益","%","daily",("alpaca_bars",),1260,"P1","IMPLEMENTED","credentialed","bar_available_at"),
    ("atr14_pct","price","ATR14 / 收盘价","%","daily",("alpaca_bars",),1260,"P1","PARTIAL","credentialed","bar_available_at"),
    ("drawdown20","price","20 日滚动回撤","%","daily",("alpaca_bars",),1260,"P0","IMPLEMENTED","credentialed","bar_available_at"),
    ("advance_share","breadth","活跃可交易证券上涨占比","%","intraday/daily",("alpaca_assets","alpaca_snapshots"),252,"P0","PARTIAL","credentialed","CURRENT_ACTIVE_UNIVERSE_NOT_HISTORICAL_PIT"),
    ("unchanged","breadth","平盘证券家数","只","intraday/daily",("alpaca_assets","alpaca_snapshots"),252,"P1","PARTIAL","credentialed","CURRENT_ACTIVE_UNIVERSE_NOT_HISTORICAL_PIT"),
    ("market_snapshot_coverage_pct","breadth","市场快照覆盖率","%","intraday/daily",("alpaca_assets","alpaca_snapshots"),252,"P0","PARTIAL","credentialed","CURRENT_ACTIVE_UNIVERSE_NOT_HISTORICAL_PIT"),
    ("advances","breadth","上涨股票家数","只","daily",("alpaca_assets","alpaca_snapshots"),1260,"P0","PARTIAL","credentialed","CURRENT_ACTIVE_UNIVERSE_NOT_HISTORICAL_PIT"),
    ("declines","breadth","下跌股票家数","只","daily",("alpaca_assets","alpaca_snapshots"),1260,"P0","PARTIAL","credentialed","CURRENT_ACTIVE_UNIVERSE_NOT_HISTORICAL_PIT"),
    ("ad_line","breadth","Advance / Decline Line","累计只数","daily",("pit_universe","alpaca_bars"),1260,"P0","PARTIAL","credentialed","pit_membership_and_bars"),
    ("up_volume_share","breadth","上涨成交量占比","%","daily",("alpaca_assets","alpaca_snapshots"),1260,"P0","PARTIAL","credentialed","CURRENT_ACTIVE_UNIVERSE_NOT_HISTORICAL_PIT"),
    ("pct_above_ma20","breadth","站上 MA20 股票比例","%","daily",("pit_universe","alpaca_bars"),1260,"P0","PARTIAL","credentialed","pit_membership_and_bars"),
    ("pct_above_ma50","breadth","站上 MA50 股票比例","%","daily",("pit_universe","alpaca_bars"),1260,"P0","PARTIAL","credentialed","pit_membership_and_bars"),
    ("pct_above_ma200","breadth","站上 MA200 股票比例","%","daily",("pit_universe","alpaca_bars"),1260,"P0","PARTIAL","credentialed","pit_membership_and_bars"),
    ("new_high_52w","breadth","52 周新高家数","只","daily",("pit_universe","alpaca_bars"),1260,"P1","PARTIAL","credentialed","pit_membership_and_bars"),
    ("new_low_52w","breadth","52 周新低家数","只","daily",("pit_universe","alpaca_bars"),1260,"P1","PARTIAL","credentialed","pit_membership_and_bars"),
    ("trin","breadth","TRIN / Arms Index","倍","daily",("pit_universe","alpaca_bars"),1260,"P1","PARTIAL","credentialed","pit_membership_and_bars"),
    ("rv5","volatility","5 日实现波动率","%","daily",("alpaca_bars",),1260,"P0","IMPLEMENTED","credentialed","bar_available_at"),
    ("rv20","volatility","20 日实现波动率","%","daily",("alpaca_bars",),1260,"P0","IMPLEMENTED","credentialed","bar_available_at"),
    ("rv60","volatility","60 日实现波动率","%","daily",("alpaca_bars",),1260,"P1","PLANNED","credentialed","bar_available_at"),
    ("downside_rv20","volatility","20 日下行实现波动率","%","daily",("alpaca_bars",),1260,"P0","IMPLEMENTED","credentialed","bar_available_at"),
    ("vix_close","volatility","VIX 收盘","点","daily",("cboe_vix",),1260,"P0","IMPLEMENTED","public","published_at"),
    ("vix9d","volatility","VIX9D","点","daily",("cboe_indices",),1260,"P1","PLANNED","public_or_licensed","published_at"),
    ("vix3m","volatility","VIX3M","点","daily",("cboe_indices",),1260,"P1","PLANNED","public_or_licensed","published_at"),
    ("vvix","volatility","VVIX","点","daily",("cboe_indices",),1260,"P1","PARTIAL","public_or_licensed","published_at"),
    ("vix_skew","volatility","Cboe SKEW Index","点","daily",("cboe_indices",),1260,"P1","PLANNED","public_or_licensed","published_at"),
    ("put_call_volume_ratio","options_pricing","全市场期权 Put/Call 成交比","倍","daily",("cboe_daily_options",),1260,"P1","IMPLEMENTED","public_summary","published_at"),
    ("etp_put_call_ratio","options_pricing","ETF/ETP 期权 Put/Call 成交比","倍","daily",("cboe_daily_options",),1260,"P1","IMPLEMENTED","public_summary","published_at"),
    ("index_put_call_ratio","options_pricing","指数期权 Put/Call 成交比","倍","daily",("cboe_daily_options",),1260,"P1","IMPLEMENTED","public_summary","published_at"),
    ("equity_put_call_ratio","options_pricing","个股期权 Put/Call 成交比","倍","daily",("cboe_daily_options",),1260,"P1","IMPLEMENTED","public_summary","published_at"),
    ("put_25d_skew","options_pricing","25 Delta Put/Call IV Skew","vol pts","daily",("licensed_option_surface",),1260,"P1","PLANNED","license_required","option_quote_available_at"),
    ("vrp_30d","options_pricing","30 日波动风险溢价","vol pts","daily",("licensed_option_surface","alpaca_bars"),1260,"P1","PLANNED","license_required","option_quote_available_at"),
    ("options_oi_put_call","options_positioning","SPX 系列 OI Put/Call","倍","daily",("cboe_daily_options",),1260,"P2","IMPLEMENTED","public_summary","published_at"),
    ("oi_strike_concentration","options_positioning","行权价 OI 集中度","%","daily",("licensed_option_chain",),1260,"P2","PLANNED","license_required","option_quote_available_at"),
    ("oi_expiry_concentration","options_positioning","到期日 OI 集中度","%","daily",("licensed_option_chain",),1260,"P2","PLANNED","license_required","option_quote_available_at"),
    ("dealer_gamma_scenario","options_positioning","Dealer Gamma 情景估计","美元","daily",("licensed_signed_positions",),1260,"P2","PLANNED","license_required","signed_position_and_quote_time"),
    ("quoted_spread_bps","microstructure","有效买卖价差","bps","intraday/daily",("licensed_quotes",),252,"P2","PARTIAL","license_required","quote_timestamp"),
    ("book_imbalance","microstructure","盘口深度失衡","ratio","intraday",("licensed_order_book",),252,"P2","PLANNED","license_required","order_book_timestamp"),
    ("price_impact_bps","microstructure","单位成交额价格冲击","bps","intraday/daily",("licensed_trades",),252,"P2","PLANNED","license_required","trade_timestamp"),
    ("trf_notional_share","microstructure","TRF 场外报告成交额占比","%","daily",("cboe_market_volume",),1260,"P2","IMPLEMENTED","public_summary","published_at"),
    ("finra_spy_short_volume_pct","microstructure","FINRA SPY 报告卖空成交占比","%","daily",("finra_short_volume",),1260,"P2","IMPLEMENTED","public","published_at"),
    ("finra_qqq_short_volume_pct","microstructure","FINRA QQQ 报告卖空成交占比","%","daily",("finra_short_volume",),1260,"P2","IMPLEMENTED","public","published_at"),
    ("finra_iwm_short_volume_pct","microstructure","FINRA IWM 报告卖空成交占比","%","daily",("finra_short_volume",),1260,"P2","IMPLEMENTED","public","published_at"),
    ("sector_dispersion_5","correlation","行业 ETF 五日收益离散度","%","daily",("alpaca_bars",),1260,"P0","IMPLEMENTED","credentialed","bar_available_at"),
    ("sector_corr_20","correlation","行业 ETF 20 日平均相关性","corr","daily",("alpaca_bars",),1260,"P0","PARTIAL","credentialed","bar_available_at"),
    ("stock_dispersion_1","correlation","个股单日收益离散度","%","daily",("alpaca_assets","alpaca_snapshots"),1260,"P1","PARTIAL","credentialed","CURRENT_ACTIVE_UNIVERSE_NOT_HISTORICAL_PIT"),
    ("downside_sync_share","correlation","同步下跌股票占比","%","daily",("alpaca_assets","alpaca_snapshots"),1260,"P1","PARTIAL","credentialed","CURRENT_ACTIVE_UNIVERSE_NOT_HISTORICAL_PIT"),
    ("treasury_2y_pct","cross_asset","美国国债 2 年收益率","%","daily",("treasury",),1260,"P1","IMPLEMENTED","public","published_at"),
    ("treasury_10y_pct","cross_asset","美国国债 10 年收益率","%","daily",("treasury",),1260,"P1","IMPLEMENTED","public","published_at"),
    ("treasury_2s10s_bp","cross_asset","美国国债 10Y−2Y 期限利差","bps","daily",("treasury",),1260,"P1","IMPLEMENTED","public","published_at"),
    ("real_yield_10y","cross_asset","10 年实际利率","%","daily",("fred_alfred",),1260,"P1","PLANNED","api_key","release_vintage"),
    ("breakeven_10y","cross_asset","10 年通胀盈亏平衡","%","daily",("fred_alfred",),1260,"P1","PLANNED","api_key","release_vintage"),
    ("dxy_return_5","cross_asset","美元指数五日收益","%","daily",("licensed_fx_or_fred",),1260,"P1","PLANNED","public_or_licensed","published_at"),
    ("gold_return_5","cross_asset","黄金五日收益","%","daily",("alpaca_or_market_data",),1260,"P1","PARTIAL","credentialed","bar_available_at"),
    ("oil_return_5","cross_asset","WTI 五日收益","%","daily",("alpaca_or_market_data",),1260,"P1","PARTIAL","credentialed","bar_available_at"),
    ("btc_return_5","cross_asset","Bitcoin 五日收益","%","daily",("crypto_market_data",),1260,"P1","PLANNED","public_or_licensed","bar_available_at"),
    ("hy_oas","cross_asset","高收益债 OAS","bps","daily",("fred_alfred",),1260,"P1","PARTIAL","api_key","release_vintage"),
    ("move_level","cross_asset","MOVE 指数","点","daily",("licensed_rates_vol",),1260,"P2","PLANNED","license_required","published_at"),
    ("etf_flow_pct_aum","positioning","ETF 净流量 / AUM","%","daily/weekly",("licensed_etf_flows",),1260,"P1","PLANNED","license_required","published_at"),
    ("cftc_nasdaq_net_pct_oi","positioning","Nasdaq-100 杠杆基金净仓 / OI","%","weekly",("cftc",),520,"P2","IMPLEMENTED","public","published_at"),
    ("cftc_sp500_net_pct_oi","positioning","E-mini S&P 杠杆基金净仓 / OI","%","weekly",("cftc",),520,"P2","IMPLEMENTED","public","published_at"),
    ("cftc_gold_net_pct_oi","positioning","黄金管理资金净仓 / OI","%","weekly",("cftc",),520,"P2","IMPLEMENTED","public","published_at"),
    ("cftc_wti_net_pct_oi","positioning","WTI 管理资金净仓 / OI","%","weekly",("cftc",),520,"P2","IMPLEMENTED","public","published_at"),
    ("short_interest_pct_float","positioning","真实 Short Interest / Float","%","biweekly",("finra_short_interest",),520,"P2","PLANNED","licensed_or_regulatory","published_at"),
    ("finra_short_volume_pct","positioning","FINRA 报告卖空成交占比","%","daily",("finra_short_volume",),1260,"P2","IMPLEMENTED","public","published_at"),
    ("ici_weekly_etf_net_issuance_bn_usd","positioning","ICI ETF 周度净发行估算","USD bn","weekly",("ici_etf",),520,"P2","IMPLEMENTED","public_summary","published_at"),
    ("days_to_cpi","events","距离下一次 CPI 发布天数","days","event",("bls_calendar",),520,"P1","PARTIAL","public_calendar","schedule_known_at"),
    ("days_to_nfp","events","距离下一次就业报告天数","days","event",("bls_calendar",),520,"P1","PARTIAL","public_calendar","schedule_known_at"),
    ("bls_scheduled_next_7d","events","未来 7 天 BLS 已排程经济发布数","count","daily",("bls_calendar",),520,"P1","IMPLEMENTED","public_calendar","schedule_known_at"),
    ("stock_sample_advance_share","breadth","30 只大盘股样本上涨占比","%","daily",("alpaca_bars",),1260,"P2","IMPLEMENTED","credentialed","FIXED_SAMPLE_NOT_FULL_MARKET_PIT"),
    ("stock_sample_above_ma20_share","breadth","30 只大盘股样本站上 MA20 占比","%","daily",("alpaca_bars",),1260,"P2","IMPLEMENTED","credentialed","FIXED_SAMPLE_NOT_FULL_MARKET_PIT"),
    ("stock_sample_new_high20_count","breadth","30 只大盘股样本 20 日新高家数","只","daily",("alpaca_bars",),1260,"P2","IMPLEMENTED","credentialed","FIXED_SAMPLE_NOT_FULL_MARKET_PIT"),
    ("stock_sample_new_low20_count","breadth","30 只大盘股样本 20 日新低家数","只","daily",("alpaca_bars",),1260,"P2","IMPLEMENTED","credentialed","FIXED_SAMPLE_NOT_FULL_MARKET_PIT"),
    ("days_to_fomc","events","距离下一次 FOMC 天数","days","event",("fed_calendar",),520,"P1","PARTIAL","public_calendar","published_schedule_known_at_not_historical_vintage"),
    ("macro_surprise","events","宏观数据实际值减一致预期","native units","event",("macro_consensus_history",),520,"P1","PLANNED","license_required","consensus_known_at_and_release_at"),
    ("earnings_count_next_5d","events","未来五个交易日财报数量","count","event",("licensed_earnings_calendar",),520,"P1","PLANNED","license_required","schedule_known_at"),
    ("sofr_pct","funding","SOFR","%","daily",("nyfed",),1260,"P1","IMPLEMENTED","public","published_at"),
    ("effr_pct","funding","EFFR","%","daily",("nyfed",),1260,"P1","IMPLEMENTED","public","published_at"),
    ("sofr_effr_spread_bp","funding","SOFR-EFFR 利差","bps","daily",("nyfed",),1260,"P1","IMPLEMENTED","public","published_at"),
    ("ofr_fsi","funding","OFR 金融压力指数","index","daily",("ofr_fsi",),1260,"P1","IMPLEMENTED","public","published_at"),
    ("repo_stress_proxy","funding","回购融资压力代理","bps","daily",("fred_alfred",),1260,"P2","PLANNED","api_key","release_vintage"),
    ("fwd_return_h1","path","未来 H1 开盘至收盘收益","%","per-session",("alpaca_bars",),1260,"P0","PARTIAL","credentialed","strict_future_label"),
    ("fwd_return_h3","path","未来 H3 开盘至收盘收益","%","per-session",("alpaca_bars",),1260,"P0","PARTIAL","credentialed","strict_future_label"),
    ("fwd_return_h5","path","未来 H5 开盘至收盘收益","%","per-session",("alpaca_bars",),1260,"P0","PARTIAL","credentialed","strict_future_label"),
    ("mfe_h5","path","未来 H5 最大有利波动","%","per-session",("alpaca_bars",),1260,"P1","PLANNED","credentialed","strict_future_label"),
    ("mae_h5","path","未来 H5 最大不利波动","%","per-session",("alpaca_bars",),1260,"P1","PLANNED","credentialed","strict_future_label"),
    ("first_touch_h5","path","未来 H5 先触及上下界事件","class","per-session",("alpaca_bars",),1260,"P1","PLANNED","credentialed","strict_future_label"),
)

FEATURES = tuple(FeatureSpec(*row) for row in _FEATURE_ROWS)
FEATURE_BY_KEY = {x.key: x for x in FEATURES}
DIMENSION_BY_KEY = {x.key: x for x in DIMENSIONS}
SYSTEM_BY_KEY = {x.key: x for x in SYSTEMS}

SOURCES = (
    SourceSpec("alpaca_bars","Alpaca 历史股票 Bars","market_data_vendor",("1Day OHLCV","ETF/股票快照"),"daily","当前代码 19 只 ETF；股票扩展受批次/行数/授权约束","credentialed","IMPLEMENTED_PARTIAL","NOT_HISTORICAL_PIT_ATTESTED","历史 SIP/IEX 权限需本机账户验证；symbol 映射不等于永久证券身份。"),
    SourceSpec("alpaca_assets","Alpaca US Equity Assets","broker_asset_directory",("当前资产目录",),"daily","当前供应商资产响应，含 ETF，不是历史成分表","credentialed","IMPLEMENTED","CURRENT_SNAPSHOT_ONLY","现有资产快照明确不具备历史 PIT 或股票/ETF 分类证明。"),
    SourceSpec("alpaca_snapshots","Alpaca US Equity Snapshots","market_data_vendor",("dailyBar","prevDailyBar","latestTrade","latestQuote"),"intraday/daily","当前活跃可交易 US equity 资产批量快照；覆盖取决于权限和返回完整度","credentialed","IMPLEMENTED_PARTIAL","CURRENT_SNAPSHOT_ONLY","可计算当前活跃资产的盘中/最近日线广度；不是历史 PIT、不是完整盘口深度。"),
    SourceSpec("cboe_vix","Cboe VIX 历史","exchange_public",("VIX close",),"daily","VIX 单一指数历史序列","public","IMPLEMENTED_PARTIAL","CURRENT_VINTAGE","现有适配器不提供 VIX 期限结构、VVIX 全家族及历史 vintage。"),
    SourceSpec("cboe_daily_options","Cboe Daily Options Statistics","exchange_public",("汇总 PCR","SPX 汇总 OI PCR"),"daily","交易所汇总统计，不是完整全市场期权链","public_summary","IMPLEMENTED_PARTIAL","PUBLISHED_SUMMARY_ONLY","不含完整逐合约 IV surface、dealer signed positions 或历史链。"),
    SourceSpec("treasury","US Treasury","official_public",("2Y/10Y par yield curve",),"daily","官方日频国债收益率","public","IMPLEMENTED_PARTIAL","PUBLISHED_VALUE_NOT_VINTAGE_STORE","现有接口取月度 XML 中的日值，需扩展历史回补及发布版本保存。"),
    SourceSpec("nyfed","Federal Reserve Bank of New York","official_public",("SOFR","EFFR"),"daily","官方参考利率","public","IMPLEMENTED_PARTIAL","PUBLISHED_VALUE_NOT_HISTORICAL_PIT","当前适配器只取最近十个值。"),
    SourceSpec("fred_alfred","FRED / ALFRED","official_public",("宏观与信用时间序列","vintage dates"),"daily/weekly/monthly","依 series 而定","api_key","IMPLEMENTED_PARTIAL","CURRENT_VINTAGE_UNLESS_REALTIME_FIELDS_USED","现有请求使用当前 vintage，不是完整 vintage archive。"),
    SourceSpec("cftc","CFTC Commitments of Traders","official_public",("TFF","Disaggregated COT"),"weekly","周二持仓、通常周五发布","public","IMPLEMENTED_PARTIAL","PUBLICATION_LAG_ENFORCED","周频报告不代表实时交易仓位。"),
    SourceSpec("ofr_fsi","Office of Financial Research","official_public",("Financial Stress Index",),"daily","综合金融压力指数，发布滞后","public","IMPLEMENTED_PARTIAL","CURRENT_VINTAGE","不是单项信用/融资盘中报价。"),
    SourceSpec("bls_calendar","BLS release calendar","official_public",("未来已排程发布时间",),"event","公开发布日程","public","IMPLEMENTED_PARTIAL","CURRENT_PUBLISHED_SCHEDULE","不含一致预期、实际意外值及历史日程 vintage。"),
    SourceSpec("fed_calendar","Federal Reserve FOMC meeting calendar","official_public",("scheduled FOMC meeting dates","page update date"),"event","公开的 2021–2027 会议日程及页面更新时间","public","IMPLEMENTED_PARTIAL","CURRENT_PUBLISHED_SCHEDULE_NOT_HISTORICAL_PIT","页面最后更新时间作为 schedule_known_at；不恢复历史日程修订版本或临时会议历史。"),
    SourceSpec("ici_etf","Investment Company Institute","industry_public",("ETF weekly net issuance estimate",),"weekly","全美 ETF 周度净发行估算","public_summary","IMPLEMENTED_PARTIAL","PUBLISHED_WEEKLY_ESTIMATE","不是逐日二级市场净买入或 ETF AUM 全量数据。"),
    SourceSpec("finra_short_volume","FINRA Reg SHO daily files","regulatory_public",("报告设施 Short Volume",),"daily","报告设施覆盖范围","public","IMPLEMENTED_PARTIAL","PUBLISHED_DAILY_NOT_SHORT_INTEREST","Short Volume 不是 Short Interest；并非全市场完整卖空成交。"),
    SourceSpec("cboe_market_volume","Cboe historical market volume","exchange_public",("TRF notional share",),"daily","公开市场成交额汇总","public_summary","IMPLEMENTED_PARTIAL","PUBLISHED_SUMMARY_ONLY","TRF 份额不是主动买卖方向或订单失衡。"),
    SourceSpec("pit_universe","历史证券身份与成分数据","security_master_vendor",("历史上市/退市","历史指数成分","历史证券映射"),"daily","必须覆盖历史成分变化、退市和身份变更","license_or_research","BLOCKED","NOT_AVAILABLE_IN_CURRENT_PIPELINE","当前资产目录只有前向观测；固定 30 股样本不能替代 PIT 全市场股票池。"),
    SourceSpec("licensed_option_surface","历史期权链与 IV Surface","options_vendor",("逐合约报价","IV/skew/term structure"),"intraday/daily","SPX/QQQ/IWM 及成分股历史期权","license_required","PLANNED","LICENSE_AND_OPTION_TIMESTAMP_REQUIRED","需比较历史覆盖、报价时点、OPRA/交易所许可和保存/再分发权。"),
    SourceSpec("licensed_order_book","历史盘口/逐笔","market_data_vendor",("NBBO","L2 depth","trades"),"intraday","全市场或明确交易所覆盖","license_required","PLANNED","LICENSE_AND_EXCHANGE_SCOPE_REQUIRED","日线数据不能重建盘口、订单失衡或冲击成本。"),
    SourceSpec("macro_consensus_history","宏观一致预期历史","economic_data_vendor",("预期值","实际值","修订值"),"event","按事件与首次发布时间保存","license_required","PLANNED","CONSENSUS_VINTAGE_REQUIRED","没有当时可得的一致预期，不能计算无前视 macro surprise。"),
    SourceSpec("licensed_etf_flows","ETF 申赎与 AUM","fund_flow_vendor",("ETF primary flow","AUM"),"daily/weekly","按 ETF、申赎口径和发布日期","license_required","PLANNED","LICENSE_AND_PUBLICATION_TIME_REQUIRED","价格成交量不能推导一级市场申赎。"),
    SourceSpec("licensed_earnings_calendar","财报与预期数据","fundamental_vendor",("earnings calendar","consensus estimates"),"event","按证券及历史发布日期","license_required","PLANNED","CONSENSUS_VINTAGE_REQUIRED","免费日历不足以恢复历史一致预期及指引版本。"),
)

SOURCE_BY_KEY = {x.key: x for x in SOURCES}


def _dict(value):
    result = asdict(value)
    for key, item in tuple(result.items()):
        if isinstance(item, tuple):
            result[key] = list(item)
    return result


def catalog_payload() -> dict:
    return {
        "schema": "qdr.l1.market_data_catalog.v1",
        "systems": [_dict(x) for x in SYSTEMS],
        "dimensions": [_dict(x) for x in DIMENSIONS],
        "features": [_dict(x) for x in FEATURES],
        "sources": [_dict(x) for x in SOURCES],
        "counts": {"systems": len(SYSTEMS), "dimensions": len(DIMENSIONS),
                   "features": len(FEATURES), "sources": len(SOURCES)},
        "policy": {"live_verified": False, "historical_pit_verified": False,
                   "forecast_eligible": False, "trade_eligible": False,
                   "path_is_outcome_not_input": True, "proxy_must_be_labelled": True},
    }


def coverage_matrix(observations: Iterable[dict] = (), *,
                    source_health: dict | None = None, asof: str | None = None) -> dict:
    """Build coverage from actual stored observations; registry alone is not coverage."""
    rows = list(observations)
    health = source_health or {}
    latest_rows = {}
    for row in rows:
        key = row.get("feature_id") or row.get("id")
        day = str(row.get("session_date") or row.get("observed_date") or "")
        if asof and day and day > asof:
            continue
        if key not in FEATURE_BY_KEY:
            continue
        def sort_stamp(value):
            if value is None:
                return ""
            return value.isoformat() if hasattr(value, "isoformat") else str(value)
        rank = (day, sort_stamp(row.get("available_at") or row.get("fetched_at")),
                sort_stamp(row.get("ingested_at")), str(row.get("provider") or ""),
                str(row.get("receipt_sha256") or ""))
        previous = latest_rows.get(key)
        if previous is None or rank > previous["rank"]:
            latest_rows[key] = {"date": day, "row": row, "rank": rank}
    # A newer MISSING/NULL observation supersedes an older valid value for the
    # same feature. Otherwise a failed latest scan can leave stale values looking current.
    feature_rows = {
        key: item for key, item in latest_rows.items()
        if item["row"].get("status", item["row"].get("quality_status", "OBSERVED"))
           in ("OBSERVED", "PARTIAL")
        and item["row"].get("value") is not None
    }
    dimensions = []
    for dimension in DIMENSIONS:
        specs = [x for x in FEATURES if x.dimension == dimension.key]
        observed = [x for x in specs if x.key in feature_rows]
        blocked_sources = []
        for feature in specs:
            for source in feature.sources:
                state = health.get(source, {})
                source_spec = SOURCE_BY_KEY.get(source)
                if (state.get("status") in ("BLOCKED", "MISSING", "ERROR") or
                    (source_spec is not None and source_spec.code_status == "BLOCKED")):
                    blocked_sources.append(source)
        count, total = len(observed), len(specs)
        latest_quality = [
            str(feature_rows[x.key]["row"].get(
                "status", feature_rows[x.key]["row"].get("quality_status", "OBSERVED")))
            for x in observed
        ]
        status = ("OBSERVED" if total and count == total and
                  all(x == "OBSERVED" for x in latest_quality) and not blocked_sources
                  else "PARTIAL" if count else "BLOCKED" if blocked_sources else "MISSING")
        rows_for_pit = [feature_rows[x.key]["row"] for x in observed]
        pit = bool(rows_for_pit) and len(observed) == total and all(
            x.get("pit_status") == "PIT_VERIFIED" and x.get("pit_attestation_id")
            for x in rows_for_pit)
        dimensions.append({
            "id": dimension.key, "name": dimension.name, "role": dimension.role,
            "status": status, "coverage": {"available": count, "registered": total},
            "observed_features": [x.key for x in observed],
            "missing_features": [x.key for x in specs if x.key not in feature_rows],
            "blocked_sources": sorted(set(blocked_sources)),
            "historical_pit_verified": pit,
            "model_eligible": pit and status == "OBSERVED",
            "forecast_eligible": False,
        })
    systems = []
    by_dimension = {x["id"]: x for x in dimensions}
    for system in SYSTEMS:
        parts = [by_dimension[key] for key in system.dimensions]
        available = sum(x["coverage"]["available"] for x in parts)
        registered = sum(x["coverage"]["registered"] for x in parts)
        system_status = ("OBSERVED" if parts and all(x["status"] == "OBSERVED" for x in parts)
                         else "PARTIAL" if available
                         else "BLOCKED" if any(x["status"] == "BLOCKED" for x in parts)
                         else "MISSING")
        systems.append({
            "id": system.key, "name": system.name,
            "status": system_status,
            "coverage": {"available": available, "registered": registered},
            "dimensions": list(system.dimensions),
            "historical_pit_verified": bool(parts) and all(x["historical_pit_verified"] for x in parts),
            "model_eligible": False,
        })
    return {
        "schema": "qdr.l1.market_data_coverage.v1",
        "asof": asof,
        "systems": systems,
        "dimensions": dimensions,
        "summary": {"systems": len(systems), "dimensions": len(dimensions),
                    "features_registered": len(FEATURES), "features_observed": len(feature_rows),
                    "historical_pit_verified": False, "forecast_eligible": False,
                    "trade_eligible": False},
    }


if len(SYSTEMS) != 6 or len(DIMENSIONS) != 12:
    raise RuntimeError("QDR L1 market-data catalogue must contain six systems and twelve dimensions")
if len(FEATURE_BY_KEY) != len(FEATURES):
    raise RuntimeError("Duplicate QDR L1 feature key")
if any(x.dimension not in DIMENSION_BY_KEY for x in FEATURES):
    raise RuntimeError("Feature references an unknown dimension")
if any(set(x.dimensions) - set(DIMENSION_BY_KEY) for x in SYSTEMS):
    raise RuntimeError("System references an unknown dimension")
