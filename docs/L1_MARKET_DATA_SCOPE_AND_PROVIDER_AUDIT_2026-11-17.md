# QDR L1 市场数据范围与 Provider 审计（2026-11-17）

> 本文是对 `L1_SIX_SYSTEMS_12_DIMENSIONS_IMPLEMENTATION.md` 的范围收敛与执行补充。若旧文档中仍有“全市场历史股票库 / PIT 股票池”作为 L1 必做项，以本文的 L1 边界为准。本文不改变六大数据体系、12 个市场维度的研究框架。

## 1. 决策：L1 不建设全市场个股历史数据库

L1 的产品目标是实时监测并预测美股整体市场状态，而不是对所有个股做 Alpha 选股。因此：

### L1 保留
- 当前市场快照：大盘 ETF、行业 ETF、风险资产 ETF、跨资产代理，以及可取得的市场广度汇总。
- 精简历史基准：核心 ETF / 指数代理、VIX、利率、信用、宏观与跨资产序列。
- 六大体系、12 个维度的实时/最新可用观测、数据来源、发布时间、延迟、质量状态与历史变化。
- 日终增量更新、短期缓存、原始来源回执与可复算特征。

### L1 暂不建设
- 全市场数万只股票的多年 OHLCV 历史数据库。
- 完整历史退市证券主数据、历史指数成分及全市场逐日 PIT 股票池。
- 全市场逐只个股因子历史、全市场逐笔 / L2 order book。
- 完整逐合约历史期权链与 Dealer signed gamma 仓位。

这些能力属于未来 L3 个股 Alpha、专门的微观结构研究或付费数据项目，不作为 L1 实时市场状态监测的前置条件。

### 重要边界
- 当前 Alpaca active assets + snapshots 可用于“当前可观测活跃资产”的广度统计，但必须显示分母、成功批次数、返回覆盖率、交易所/资产过滤规则与 feed。不能称为完整历史 PIT 市场广度。
- 若历史 A/D、52 周新高低、TRIN 等没有可信的历史汇总数据，必须标记 unavailable / proxy，不得用当前股票池倒推历史。
- IEX、delayed SIP、实时 SIP 必须明确区分；HTTP 200 不是“实时”证明。
- 价格代理、ETF 资金流、Short Volume、Short Interest、期权 OI、Dealer Gamma 必须分别命名，不能互相冒充。

## 2. 当前 main 代码审计快照

审计基线：`main`，代码目录 `src/quant_research/data/l1_market_catalog.py`、`l1_official_sources.py`、`l1_public_extended.py`、`l1_light_sources.py`、`workflow/l1_market_data.py`。

### Registry 计数
- Feature Registry：109 项；IMPLEMENTED 47、PARTIAL 41、PLANNED 21。
- Source Registry：21 项（此前口头称 20 项，按当前 main 实际代码计数应更正为 21 项）；IMPLEMENTED 1、IMPLEMENTED_PARTIAL 14、BLOCKED 1、PLANNED 5。
- 以上是代码注册状态，不是本机实际运行成功率、数据覆盖率或预测资格。

### 核心行情调用链的实际范围（静态代码核对）
- `LiveSources.ETF_SYMBOLS` 当前包含 28 个核心指数、行业、风格和风险 ETF；历史 Bars 默认使用这 28 个 symbol。
- main 中 `LiveSources.snapshots()` 默认只请求 SPY、QQQ、IWM、RSP、HYG、LQD 六个 symbol。因而旧版 `current_l1_v2()` 的实时 latestTrade/latestQuote 只有六个标的，而不是完整 28 ETF 核心篮子。
- `market_breadth()` 是另一条独立链路：读取当前 active/tradable/non-OTC 资产目录，再按 200 个 symbol 分批拉快照，计算当前 universe 的上涨/下跌、上涨成交量和覆盖率；它不是历史 PIT。
- `scan-live` 会持久化官方/扩展扫描和市场广度结果；但这不等于这些所有数据已统一进入 L1 预测输入。
- 后续核心实时篮子修复应把默认 snapshots 从 6 个扩展到现有 28 个 ETF，并保留显式传入小集合的能力；不得扩大为全市场个股历史行情下载。

### 21 个数据源审计

| Source key | 当前代码能力 / 频率 | 当前限制 | L1 处理建议 |
|---|---|---|---|
| alpaca_bars | 1Day OHLCV；凭证；历史日线 | 默认历史池仍是有限 ETF；SIP/IEX 权限需目标机验证；symbol 不等于永久身份 | 保留，但只拉核心市场篮子 |
| alpaca_assets | 当前 US equity asset directory；日频/按需 | 当前目录，不含历史成员和退市信息 | 保留作当前股票快照的 universe denominator |
| alpaca_snapshots | dailyBar / prevDailyBar / latestTrade / latestQuote；盘中/日频 | 依 feed、权限、批次成功率；非完整 L2 | 保留；必须输出 feed、覆盖率、批次失败和时间戳 |
| cboe_vix | VIX 历史收盘；日频 | 单一 VIX 序列，不含 VIX9D / VIX3M / VVIX / SKEW 家族 | 保留；补历史回补和更新审计 |
| cboe_daily_options | 汇总 PCR、SPX 汇总 OI PCR；日频 | 交易所汇总统计，不是全市场逐合约 IV surface / dealer positions | 保留为“公开汇总代理”，不改名成完整期权风险 |
| treasury | 2Y / 10Y par yield；日频 | 当前实现取月度 XML 的日值；历史 vintage / 回补未完整 | 保留；扩展稳定历史回补与发布日期元数据 |
| nyfed | SOFR / EFFR；日频 | 当前只取最近 10 个值 | 保留；补充历史增量，不称盘中实时 |
| fred_alfred | FRED / ALFRED 宏观与信用序列；按 series 日/周/月频 | API key；当前 session vintage 查询不等于完整逐日历史 vintage archive | 保留；限定核心 series，增量维护 |
| cftc | TFF / Disaggregated COT；周频 | 周二持仓、通常周五发布；必须按发布日期使用 | 保留；作为周频仓位背景，不当作实时资金流 |
| ofr_fsi | OFR Financial Stress Index；日频但发布滞后 | 综合压力指数，不是盘中融资报价 | 保留；显示 source date / publication lag |
| bls_calendar | BLS 官方发布日历；事件频率 | 只有已排程发布时间，没有一致预期、实际 surprise、历史 schedule vintage | 保留；只作事件风险日历 |
| fed_calendar | FOMC 已发布会议日程；事件频率 | 当前页面更新时间，不恢复历史修订和临时会议版本 | 保留；只作当前已公布日程 |
| ici_etf | ICI ETF weekly net issuance estimate；周频 | 周度净发行估算，不是二级市场每日净买入 | 保留为低频辅助，严格命名 |
| finra_short_volume | FINRA Reg SHO 报告设施 Short Volume；日频 | 设施覆盖口径；不是 Short Interest | 保留为辅助观测，标注覆盖边界 |
| cboe_market_volume | Cboe 市场成交量 / TRF notional share；日频 | 汇总成交额份额，不等于主动买卖方向或订单失衡 | 保留为市场结构代理 |
| pit_universe | 历史证券身份 / 历史成分 | 当前 pipeline BLOCKED；需要许可数据 | 从 L1 必做项移出；仅 L3 全市场历史选股或严格历史广度研究再评估 |
| licensed_option_surface | 历史逐合约报价 / IV surface | 许可、OPRA 覆盖、时点与再分发权未确认 | 暂缓；L1 先用 Cboe 公共汇总与可验证的 VIX 家族 |
| licensed_order_book | NBBO / L2 / trades | 许可与交易所范围未确认；对 L1 市场状态不是必需 | 移出 L1 交付范围 |
| macro_consensus_history | 宏观预期 / 实际 / 修订 | 需要一致预期 vintage 供应商 | 第二阶段可选；当前事件日历不伪装成 surprise |
| licensed_etf_flows | ETF primary flow / AUM | 需要基金流量供应商许可 | 第二阶段可选；当前 ICI 周度估算保留但口径清晰 |
| licensed_earnings_calendar | 财报日历 / 一致预期 | 历史预期和指引版本需许可 | 不作为 L1 市场总览前置；以后作为事件风险增强项 |

## 3. 六大体系在 L1 的实际交付边界

| 体系 | L1 必须具备 | 暂不要求 |
|---|---|---|
| 1. 市场广度与行业结构 | 当前市场涨跌分布、广度覆盖率、核心指数/行业 ETF、可用的 A/D 汇总 | 为了历史广度而维护全部退市股票 OHLCV |
| 2. 波动率与期权风险 | VIX、可用的期限/期权公开汇总、RV、历史波动分位 | 完整全市场历史期权链和 Dealer Gamma |
| 3. 行业轮动与风格 | 11 个行业 ETF、核心风格/大小盘代理、相对强弱 | 全市场个股横截面因子库 |
| 4. 流动性与资金流 | 成交量结构、公开 short-volume / TRF / ICI 周度数据及其口径 | 全市场 L2、逐笔和付费逐日 ETF 申赎 |
| 5. 宏观与跨资产 | 国债、SOFR/EFFR、核心 FRED series、信用、美元/商品代理、OFR | 与 L1 无关的全宏观数据仓库 |
| 6. 催化剂与市场预期 | BLS/FOMC 已公布日历、重要宏观事件日期 | 未取得历史一致预期前，不计算历史 surprise |

## 4. 精简历史基准库

建议维护 3–5 年（宏观序列按可用历史长度）的最小历史篮子：

- 大盘：SPY、QQQ、IWM、DIA、RSP。
- 行业：11 个 Select Sector SPDR ETF。
- 风险/风格代理：TLT、SHY、HYG、LQD、GLD、USO（或明确标注的原油基准）、美元指数可用代理。
- 波动率：VIX 历史；其他期限/波动率系列仅在可靠公开源可用时加入。
- 宏观：Treasury 2Y/10Y、SOFR、EFFR、核心 FRED 利率/通胀预期/信用/美元序列、OFR FSI。
- 市场广度：优先使用可追溯的官方/供应商汇总历史；没有则只保存从接入日开始的 current-universe observations，不回填伪历史。

数据存储继续复用 DuckDB、source receipts、SHA256、available_at / publication time 和质量状态。历史初始化只执行一次，之后按数据源频率增量更新；实时快照短期缓存，不作为长期历史主库。

## 5. 当前明确的执行顺序

### A. Provider 审计（本次已完成代码层审计，仍需目标机连通性验收）
1. 将 registry 的 21 个 source key 与 scanner 实际调用逐一对应。
2. 目标机执行 `scan-live --refresh`，记录每个 source 的 status、asof、fetched_at、source date、receipt SHA、错误码。
3. 核实 Alpaca SIP / delayed SIP / IEX 实际可用权限；核实 FRED key；核实公开源是否被网络/缓存/解析器阻断。
4. 形成“代码存在 / 本机可取 / 数据新鲜 / 可用于 L1”的四态报告，不能只看 HTTP 200。

### B. 实时核心篮子与广度
1. 核心 ETF / 行业 ETF / 风险代理统一 snapshot 与历史 bars。
2. 先用官方汇总数据覆盖全市场 A/D / TRIN / new highs-lows；不可得时才用当前活跃股票 snapshots，并标注当前 universe、feed、coverage、batch failures。
3. 不把 IEX 或 delayed SIP 标成实时 SIP。

### C. 精简历史基准库
1. 对核心篮子做一次 3–5 年历史初始化，验证 pagination、日期完整性、重复、OHLC 合法性。
2. 以后按交易日增量更新，支持重试与断点续传；不得为了 L1 拉取全市场股票历史。
3. 宏观 / 官方序列按各自发布频率增量更新并保留发布时间与来源回执。

### D. 六体系 12 维特征质量与 L1 接入
1. 对每个 feature 记录 observed / partial / stale / missing / proxy。
2. 区分当前可用与历史可用；明确代理指标、覆盖率、延迟和质量门槛。
3. 仅将达到新鲜度与覆盖门槛的数据交给模型；缺失不得填 0 或静默回退。

### E. 模型验证和工作台
1. 对新增实时/历史特征做消融和滚动样本外验证。
2. 监测页面展示当前值、source date、feed、delay、coverage、质量状态和关键变化。
3. 前向结算样本不足时保持 RESEARCH_ONLY，不提升交易资格。

## 6. 目标机验收命令

在项目根目录、配置好本机 `.env` 后运行：

```bash
python -m quant_research.workflow.l1_market_data scan-live --root . --refresh
python -m quant_research.workflow.l1_market_data status --root .
```

提交报告时至少保留每个 source 的 status、asof_session、fetched_at、有效观测日期、receipt SHA256、失败原因和 feed。不得上传 API keys 或未经授权的原始供应商数据。

## 7. 本次审计结论

- 已完成：代码层 source registry / scanner 对照、L1 范围收敛、六体系交付边界与精简历史篮子定义。
- 尚未完成：用户目标机真实 Provider 逐源连通性、权限、延迟和覆盖率验收；此项不能由静态代码审计代替。
- 下一步：执行 B 的核心实时篮子和广度设计前，先拿到目标机 `scan-live --refresh` 报告；并修正当前全市场历史 PIT 股票池被误当作 L1 必做项的计划描述。
