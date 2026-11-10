# 美股多层量化研究与交易决策系统 —— Codex 开发任务书（v1.0）

> 日期：2026-11-06  
> 用途：直接交付 Codex 执行、逐阶段验收。  
> 定位：**研究系统 + 历史回测 + 每日信号报告 + 模拟交易记录**，不是已验证盈利策略，也不自动提交实盘订单。

## 0. 项目目标与不可妥协约束

### 核心目标
使用美股日频数据，为未来 **1、3、5 个交易日**构建可复现的研究与决策流程：

1. **市场模型**：估计 SPY 未来收益方向概率、下行风险及市场状态。
2. **经典因子/风格模型**：追踪市场、小盘、价值、质量、动量、低波动风格的近期表现及状态转换；判断其是否对未来收益有增量预测价值。
3. **个股 Alpha 模型**：构建反转、动量、波动率、流动性、行业残差等股票特征，预测短期收益分布与超额收益。
4. **风控/组合模型**：以确定性风险预算为第一版，根据预期净收益、尾部风险、相关性及流动性确定候选持仓和退出规则。
5. **统一回测**：所有模型使用同一交易时钟、股票池、成本假设和 walk-forward 测试方式。
6. **每日输出**：市场报告、风格报告、Top N 候选股、进出场规则、风险预算、模型有效性提示。

### 非目标（v1 不做）
- 不接入真实下单和券商账户读写；只提供 paper-trading CSV/数据库流水。
- 不实现毫秒/分钟/逐笔订单流、实时报价、复杂 Gamma 估算。
- 不宣称有稳定收益、预测胜率或实盘可交易 Alpha；先检验数据和方法。
- 不在 MVP 内做复杂的深度学习、强化学习或云部署。

### 交易协议（唯一权威）
- 市场：美国上市普通股及美国 ETF；默认只做多。
- 频率：**收盘后**计算信号。交易日 T 的所有特征仅使用截至 T 收盘时**已经可用**的信息。
- 买入：T+1 交易日开盘，模拟开盘可成交价及滑点。
- 退出：分别建立 1、3、5 交易日独立实验；例如 3 日持仓在 T+3 收盘退出，或先触发止损 / 其他事先固定条件。
- 不能混用 T 日已知收盘因子与 T 日收盘成交价；不能把事后披露或回填数据用于历史决策。
- 对无明确公布时间的外部因子文件采用保守滞后策略或只用于事后历史风格解释，**不假设在 T 收盘后立即可用**。
- 每次运行存储 `asof_timestamp_utc`、`data_cutoff_utc`、`universe_version`、`model_version` 和 `run_id`。

## 1. 技术架构与目录结构

**推荐：** Python 3.11+、pandas、numpy、DuckDB、Parquet、pyarrow、scipy、statsmodels、scikit-learn、pydantic、pyyaml、pytest、matplotlib/plotly、Streamlit（最后加入）。使用 `uv` 或 `pyproject.toml` 管理依赖，版本锁定。Windows/macOS/Linux 均可本地运行。

```text
quant-research/
├── README.md
├── AGENTS.md                    # Codex 长期工程约束
├── pyproject.toml
├── uv.lock
├── .env.example                 # 无任何真实密钥
├── .gitignore
├── configs/
│   ├── base.yaml                # 时间、因子、模型、风险参数
│   ├── sources.yaml             # 数据源配置、限速和字段映射
│   └── experiments/             # 固化每次研究假设
├── data/                        # gitignore：原始及衍生数据
│   ├── raw/
│   ├── bronze/
│   ├── silver/
│   └── gold/
├── src/quant_research/
│   ├── cli.py
│   ├── data/providers/         # alpaca, french, sec, fixture
│   ├── data/normalize.py
│   ├── data/quality.py
│   ├── data/universe.py
│   ├── features/               # market, style, equity, fundamentals
│   ├── research/               # IC、分组、衰减、稳健性
│   ├── models/                 # market, style, alpha
│   ├── validation/             # 时间切分、purge、embargo
│   ├── backtest/               # event loop, fills, costs, portfolio
│   ├── risk/                   # limits、ATR、exposure、kill-switch
│   ├── reports/                # HTML / CSV / JSON
│   └── app/                    # Streamlit（可选）
├── tests/
│   ├── fixtures/
│   ├── unit/
│   ├── integration/
│   └── leakage/
├── notebooks/                   # 解释性探索，不承载唯一的生产代码
├── outputs/
│   ├── experiments/
│   ├── reports/
│   └── paper/
└── docs/
    ├── architecture.md
    ├── data_dictionary.md
    ├── data_limitations.md
    ├── research_protocol.md
    ├── milestones.md
    └── decisions.md
```

**原则：** 计算代码必须在 `src/` 可调用，Notebook 只是展示；核心流程必须 CLI 可运行，所有评估输出必须带数据版本和参数指纹。允许无网络 fixture 模式完整演示。

## 2. 数据层：先把数据正确性做到可审计

### 数据源与用途

| 数据类别 | 首选 | 备用 / 限制 |
|---|---|---|
| 股票/ETF 历史 OHLCV | Alpaca Historical Bars（SIP 历史可用范围以账户权限为准） | yfinance 仅用于原型对照，不能默认满足完整研究质量 |
| 经典因子收益 | Kenneth French Data Library 日频因子 | 注意各序列的构建定义、单位、更新滞后及版本调整 |
| 公司财务与披露时点 | SEC EDGAR submissions + XBRL | companyfacts 的现存聚合记录不得直接当作历史 PIT 快照 |
| 市场/行业 ETF 代理 | SPY、RSP、IWM、IWD、IWF、MTUM、QUAL、USMV、HYG、LQD、行业 ETF | ETF 只是代理，**不等于**纯 Fama-French 因子 |
| 风险无关基准 | SPY、等权或行业中性基准 | 统一复权口径和交易日历 |

SEC 请求需配置合规 User-Agent（带联系邮箱）、缓存、429 退避以及总速率不超过 10 req/s；Alpaca 凭证通过环境变量注入，禁止写入仓库。数据拉取可重试、幂等、分页、断点续传，保留原始响应的 hash 和抓取时间。

### 必须的数据库表（至少）

- `securities(symbol, security_id, exchange, asset_type, first_seen, last_seen, source)`：尽量用稳定 ID 关联改名、换代码等。
- `prices_daily(security_id,date,open,high,low,close,volume,vwap,adjustment_basis,source,ingested_at)`：价格和事件时点需分离记录；**成交仿真使用原始可成交价格**，收益评估需正确处理拆股和分红。
- `corporate_actions(security_id, ex_date, action_type, factor_or_cash, announced_at, source)`。
- `universe_daily(date,security_id,is_eligible,reason,source,quality_flag)`：历史可交易股票池，不得使用今天的成分股充当过去市场股票池。
- `filings(security_id,cik,accession,form,period_end,accepted_at,available_at,amended_at)`。
- `fundamentals_pit(security_id,feature,value,period_end,available_at,source_accession)`。
- `factor_returns(date,factor_name,value_decimal,source,available_at,version)`。
- `features_daily(date,security_id,feature_name,value,available_at,version)`。
- `labels(date,security_id,horizon,entry_date,exit_date,forward_return,benchmark_return)`。
- `predictions(date,security_id,horizon,p_up,expected_return,downside_quantile,model_version)`。
- `orders/fills/positions/equity_curve/runs`：模拟执行、净值和完整复盘。

所有表必须有明确主键、字段数据字典、空值与时间戳规则。任何 `available_at > signal_time` 的数据严禁出现在决策特征中。

### 股票池与历史数据限制（阻断项）

- **开发测试：** `fixture` 中的合成历史数据 + 20–50 只 ETF/液体股票，确保代码全流程能运行。
- **探索性研究：** 约 200–500 只流动性好的股票，但如采用今天仍上市的股票名单，所有报告必须打 `SURVIVORSHIP_BIASED / EXPLORATORY` 标签，不能宣称是全市场有效性结果。
- **严谨历史回测：** 需要历史 PIT 股票池、退市证券、历史行动/换代码映射；免费来源若无法获得则置 `DATA_INCOMPLETE`，阻止标记为 `RESEARCH_GRADE`。
- 不要伪造退市历史、股票池覆盖或历史总市值。找不到合法数据则显式缺失，并在报告注明研究不能支持的结论。

### 数据质量检验
主键唯一、时间递增、价格合理、非负成交量、split/dividend 异常、日历错位、不同供应商采样差异、财报发布时间、证券代码变更、缺失率、重复记录、极端值解释。提供 `data-audit` CLI 和 HTML/JSON 报告。对异常值不能默认删除导致选择偏差。

## 3. 第一层：市场预测模型（Market）

### V1 特征（尽量免费日频）
- SPY：过去 1/5/20 日收益；5/20 日实现波动率与比率。
- RSP/SPY：5/20 日相对收益（市场集中度代理）。
- HYG/LQD：5/20 日相对收益（信用风险代理，而非官方信用利差）。
- 市场广度：PIT 股票池中收益正数占比、收盘高于 20 日均线占比；PIT 不可用时替换为 ETF 代理并注明。
- 行业分化：主要行业 ETF 5 日收益分散度、同行业之间平均相关性。
- 美国 10 年期利率的近 5 日变化（可选，必须记录发布时间与更新频率）。

### 输出与算法
- 目标一：未来 1/3/5 日 SPY T+1 开盘至目标退出价收益是否 >0。
- 目标二：同期收益是否低于训练集预先确定的风险阈值（比如 -2%，不可事后调）。
- 起步：只以固定规则描述市场状态；然后用 LogisticRegression 做分类基线，输出 Brier、LogLoss、概率校准、与常数概率基线的对比。
- 如无显著样本外增量，市场模块仅报告状态，不直接决定买卖。

## 4. 第二层：经典因子 / 风格模型（Style）

### 核心数据
- French 日频：Mkt-RF、SMB、HML、RMW、CMA、Mom、ST Rev；若数据单位是百分数，**转换为十进制收益**并校验。
- ETF 风格代理：小盘 IWM/SPY、价值 IWD/IWF、动量 MTUM/SPY、质量 QUAL/SPY、低波动 USMV/SPY。
- **区别：** Fama-French 因子用于历史归因、统计研究；ETF 代理用于能确证时间上可获得的每日风格观察。不得把滞后发布的第三方因子收益当成当日收盘实时已知。

### 每个风格输出
- `relative_return_5d`、`relative_return_20d`、`relative_acceleration`（短期与中期增长率之差）、`positive_days_10`、`relative_volatility_20d`。
- 四态标签：强势加速 / 强势减速 / 弱势改善 / 弱势恶化。阈值只在训练期估计并冻结到验证段。
- 下一步研究因子收益持续性、风格变化与市场/Alpha 收益的条件关系；如不增加样本外表现只报告不交易。

## 5. 第三层：个股 Alpha 模型

### 第一版因子仓库
| 名称 | 公式/定义 | 备注 |
|---|---|---|
| reversal_5d | `-(P_t/P_(t-5)-1)` | 另测 1/10 日，不随意无止境调窗 |
| momentum_12_1 | `P_(t-21)/P_(t-252)-1` | 股票上市不足样本窗口时为空 |
| sector_residual_5d | `stock_5d_return - beta_sector * sector_5d_return`，再取负 | Beta 仅用截至 t 的历史训练窗口估计 |
| realized_vol_20 | `std(daily_return,20)*sqrt(252)` | 下行波动另设特征 |
| vol_ratio_5_20 | `std(ret,5)/std(ret,20)` | 分母为零则缺失 |
| adv20 | 过去20日日均成交金额 | 用于流动性过滤与特征 |
| amihud20 | `mean(abs(ret)/dollar_volume,20)` | 明确缩放与缺失处理 |
| close_location | `(close-low)/(high-low)` | high == low 则缺失 |
| rel_strength_sector_5d | `stock_5d_return-sector_5d_return` | 无行业分类则标记缺失 |
| beta_60 | 60日个股对市场收益回归系数 | 需要足量历史日 |

规模与质量：若 `market_cap` 和 `fundamentals_pit` 真正具有历史 as-of 数据，追加 `-log(market_cap)`、`ROA/ROE/ROIC`；否则 **不准用今日市值、最新财报倒灌历史**，V1 缺失可接受。

### 个股标签（统一）
- 收盘 T 的信号；T+1 开盘建仓，T+H 收盘退出（H ∈ {1,3,5}），计算 **成本前原始收益**、相对 SPY/行业基准收益、净收益。
- 同一时刻跨股票横截面 ranking；Rank IC 按日计算后聚合，记录覆盖股票数。
- 先建立线性回归/岭回归 + 逻辑回归，要求优于简单基线后才准引入 LightGBM。
- 输出 `predicted_return`、`P(up)`、`expected_excess_return`、`uncertainty`（无法估计时必须为空而不是虚构置信度）。

### 因子研究报告
每个候选因子、H ∈ {1,3,5} 输出：分组未来收益、Rank IC 均值/分布、ICIR（说明定义）、IC 衰减、覆盖率、缺失率、行业和市值暴露、风格相关性、交易换手、不同市场状态条件结果。重叠标签的显著性需使用合适的块 bootstrap 或 HAC，不能把逐日重叠观测视为完全独立。

## 6. 第四层：风控 / 组合管理

### 第一版规则（配置化，全部为待验证初始值）
- 只做多；单股票权重 ≤10%；单笔计划权益风险 ≤0.3%；总目标仓位 ≤50%；单行业权重 ≤25%。
- 交易流动性：ADV20 ≥ $20M；有效价格 ≥ $5；报价/滑点数据不充分时采用保守成本并做敏感性分析。
- 起始止损：`2*ATR(20)`；仓位风险预算 `min(10%, 0.3% / stop_distance_pct)`。
- 预估成本：双边手续费（可配置）+ 买卖滑点 + 冲击成本（由参与成交金额比例决定的保守模型）；测试 5/10/20/50 bps **每侧**情景，标明不是实际券商成本。
- 回测 **跳空低开穿越止损**：卖出价不可理想化为原止损价，应按可获得的更差开盘价及成本处理。
- 日线同一根K线触及止盈和止损而路径未知时采用保守顺序；需要精准路径则升级分钟数据。
- 不允许超额杠杆、空仓也属于合法结果；无需每天必须产生交易。
- 股票相关性和行业聚集风险需要在组合风险报告中显示，不能把单票风险简单相加当成组合尾部风险。

### 决策逻辑
- 市场/风格预测作为状态特征或风险上限参考，**不直接与 Alpha 分数相加**。
- 先从 Alpha 候选预测收益中扣除交易成本，并与下行风险评估；再用优化前明确的风险约束分配权重。
- 比较实验：A 只用 Alpha；B Alpha+市场；C Alpha+风格；D 三者；E 三者+风控。相同样本、相同执行和成本，输出增量贡献。
- 模型预测只是研究信号，不应自动转化为真实订单。

## 7. 验证协议：必须严格执行

1. **严格时间顺序：** 不随机打乱训练/测试日期。固定隔离最终测试期，首次定义好研究窗口、目标收益、成本参数与成功标准。
2. **示范划分：** 2017–2022 训练；2023–2024 调参/验证；2025–2026-11-05 封存为最终测试（若数据实际较短，缩短但明确披露）。只在研发决策冻结后做一次最终测试；测试结果反复调参则不再独立。
3. **滚动训练：** expanding / rolling walk-forward：模型在每个回测预测时点只能用过去数据拟合标准化、缺失填充、参数及模型。
4. **Purge / Embargo：** 对 1/3/5 日重叠预测标签，按实际 label `entry_time` 和 `exit_time` 移除跨越测试边界的训练样本；另保守设置不低于最大持有期的 gap。注意特征回望窗口与标签窗处理不是同一件事。
5. **逐步基线：** SPY Buy&Hold、现金、等权股票篮子、单因子简单排序、Alpha-only、多层模型。所有收益与风险比较以同一净值/持仓记账口径输出。
6. **报告：** 净年化收益、日收益 Sharpe、最大回撤、Calmar（可用时）、收益波动、最差 1/5 日、净换手、交易次数、平均/中位持仓期、成本占毛收益比例、分年度/分市场状态表现、资金利用率、参数敏感性。
7. **负面结果：** 无统计优势、成本后为负、样本太小、数据偏差过大都必须明确判定 `NOT_READY`；禁止自动修改标准直到测试通过。
8. **禁止泄漏测试：** 构造会把未来财务事实写入过去日期、会把未来 close 写入特征、会把调仓日收盘价当成交价、会把当代成分股当历史成分股的故障测试，保证至少各有一项自动失败。
9. **交易日历：** 用美股实际交易日和美东时区处理 DST、半日市、休市；T+1 是下一个有效交易日，不是自然日。
10. **现实化执行：** 对无交易、涨跌停样式异常/停牌、退市结算、拆股和企业行为做明确规则；无法处理时给风险标识而不是静默忽略。

## 8. P0–P6 实施计划、验收条件及工时估算

> 工时为开发 + 验收的粗略估算，网络/API 准入与 PIT 数据补齐可能大幅延长。

### P0：工程骨架与交易时钟（4–8h）
- 建仓库、依赖锁、CI/pytest、配置、`.env.example`、fixture 数据、日志与 `run_id`。
- 定义交易日历、信号 T、T+1 open、T+H close 的数据契约。
- **验收：** 无 API Key 可运行 demo；单元测试绿；可展示未来数据泄漏阻断测试。

### P1：数据管道（12–20h）
- Alpaca 历史数据适配（自动补漏、增量更新、缓存、限速）；French 因子适配（日期/百分比口径）；SEC API 只先做接口与 2–3 家公司的试取（完整 PIT 后置）。
- 建统一 schema、DuckDB/Parquet、质量报告、数据限制标识。
- **验收：** 可拉取并复用至少 20 ETF/股票 2017 至今可得日线数据；断网可从缓存运行；同一天重复跑不重复插入。

### P2：因子引擎与单因子研究（12–18h）
- 计算反转、动量、波动率、流动性、行业残差，添加可选 size/quality gating。
- 批量计算 H1/H3/H5 标签，Rank IC、五分组、衰减图、因子相关性与缺失率。
- **验收：** 任意新增一个按统一 `Factor` 接口写的特征，无需改研究引擎即可生成报告；fixture 对照公式正确。

### P3：市场与经典因子状态（10–16h）
- 市场变量计算；French 因子收益历史可视化；ETF 风格代理及四状态规则。
- 市场方向模型：先 naive 基线 + Logistic Regression；历史风格转折仅做条件分析。
- **验收：** 任何交易日可查询市场/风格状态及使用的各项输入发布日期；有回测图与不确定性披露。

### P4：个股 Alpha 与融合（12–20h）
- 股票超额收益预测基线；归一化/缺失填充仅在训练集拟合；市场/风格状态条件交互。
- 消融实验 A-D；固定训练/调参空间和实验编号。
- **验收：** 输出 1/3/5 日的个股预测、分组检验、基线比较；不能靠样本外数据挑参数。

### P5：回测和风控（14–24h）
- 基于事件时间的组合现金/持仓/手续费/滑点/公司行动、止损缺口处理。
- 单票/行业/总体权重限制；敏感性分析、样本外跑通。
- **验收：** 随机种子固定可复现；净值与逐笔成交汇总一致；异常成本和跳空单测通过；输出完整 A–E 对照。

### P6：自动化、报告、模拟盘（8–14h）
- CLI 一键跑、可选 Streamlit 查看仪表盘；导出 HTML/CSV/JSON；日志、异常告警、模拟订单记账。
- 每日收盘后按时区计划运行（配置 cron/Task Scheduler 示例，**不包含必须开着的云服务器**）。
- **验收：** 无网络时历史重跑与报告仍正常；API 临时失败不会写出假的新交易建议；模拟持仓可跨多日续记。

**总预计：约 72–120 人工小时（并非 Codex 纯运行时间）**。每周 10–15 小时协作，大致 6–10 周研究 MVP。集中开发 25–35 小时/周，大致 3–5 周。更完整的退市股票/PIT 财务、生产运维及持续模拟验证，通常另需数周至数月。

## 9. CLI 交付接口（命名可以调整，能力必须具备）

> 以下日期是截至 2026-11-06 可以完整取得的示范交易日。实际运行时应使用美国东部交易所已经结束且数据已完整到达的最新交易日。

```bash
# 建议使用 uv；也允许标准 venv/pip，README 必须可从零复现
uv sync
uv run pytest -q

# 无网络 fixture 完整演示
uv run python -m quant_research.cli demo --fixture

# 数据刷新、审计
uv run python -m quant_research.cli ingest --start 2017-01-01 --end 2026-11-05
uv run python -m quant_research.cli data-audit

# 因子计算及报告
uv run python -m quant_research.cli features --asof 2026-11-05
uv run python -m quant_research.cli factor-report --horizons 1,3,5

# 模型训练、时间验证、回测、每日信号
uv run python -m quant_research.cli train --experiment configs/experiments/baseline.yaml
uv run python -m quant_research.cli backtest --experiment configs/experiments/baseline.yaml
uv run python -m quant_research.cli daily-report --asof 2026-11-05
```

CLI 应在不可用交易日、尚未收盘的日期给出合理提示；`--asof` 必须实现信息可用性检查。所有命令须有 `--help`、明确 exit code、可复现的输出位置与源数据摘要。

## 10. 成功标准与最终交付

### 工程成功标准（可以验收）
1. 从空仓库到 `demo`，在无密钥、无网络的 fixture 下能够完整跑完。
2. 历史数据源有版本/抓取日期/可用时间记录，支持新增供应商。
3. 六大因子概念都有对应输入或明确缺失状态；优先实现五大日线/行业信号。
4. 所有报告可重现：相同数据哈希与配置，得到相同结果。
5. 漏泄检测、交易时间、公司行为、同根 K 线止损、成本场景、现金一致性测试通过。
6. 产出 HTML 市场与风格监测、因子评价、策略回测、模拟选股清单。
7. 对数据偏差、预测失效、流动性不足和未校准概率有明显风险提示。

### 研究成功标准（**不能保证**）
- 回归/分类模型对独立数据优于低成本基线，且改进幅度稳定、可解释。
- 成本后策略收益、风险调整收益、回撤和容量达到事先定义的标准。
- 若未达标，交付“无优势/不可投入真实资金”的结论，视为**研究流程成功**而不是硬编盈利结果。

### Codex 每阶段输出格式
- `DONE`：实施了什么（列出修改文件）。
- `TESTS`：实际执行的命令、通过/失败结果。
- `DATA`：使用数据源、覆盖范围、时效、已知缺口。
- `RESULTS`：生成的报告路径、关键数值（只能引用实际计算）。
- `RISKS`：留存问题、偏差与阻断项。
- `NEXT`：下一阶段第一步；没有通过当前验收不擅自宣称下一阶段完成。

## 11. 直接复制给 Codex 的总启动指令

```text
你是有买方量化研究、Python 数据工程和交易回测经验的工程师。请在当前仓库中实现附件《美股多层量化研究与交易决策系统 —— Codex 开发任务书（v1.0）》所定义的系统。

严格按 P0→P6 阶段执行。当前先完成 P0，随后在具备测试证据时逐阶段推进。不要一次性生成没有测试的庞大代码。允许采用最佳工程实践，但不得改变本文件规定的交易时钟、PIT 数据规则、研究/测试隔离、数据来源可追溯和禁止真实下单原则。

每个阶段必须：先检查仓库状态与已有代码；列出可验证的子任务；编写实际可运行代码；补充 pytest 单元测试/泄漏测试；执行测试与 fixture demo；输出改动摘要、报告路径、剩余数据局限、下一步。

不允许编造 API 数据、回测收益、胜率、统计显著性或已完成的测试结果。第三方服务未配置密钥时，使用明确标记的合成 fixture 完成工程验证；阻断阶段时明确说出缺失的凭证/数据，不要绕过验证。使用 .env.example 说明所需凭证，不要向代码或日志写入真实密钥。

请先：1）阅读此任务书，2）生成 README、AGENTS.md、pyproject.toml、目录骨架、configs/base.yaml，3）实现交易日历与 as-of 信息约束，4）实现可离线运行的 demo，5）写出阻止未来函数的测试。执行 pytest 并报告真实结果。
```

## 12. 官方参考（开发时阅读）

- Alpaca 数据方案与历史权限：https://docs.alpaca.markets/us/docs/about-market-data-api
- Kenneth French Data Library：https://mba.tuck.dartmouth.edu/pages/faculty/Ken.French/data_library.html
- SEC EDGAR 数据 API：https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SEC 自动访问政策：https://www.sec.gov/about/developer-resources
- QuantConnect 研究偏差指南：https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/research-guide
- DuckDB Python API：https://duckdb.org/docs/stable/clients/python/overview
- scikit-learn TimeSeriesSplit：https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html

---

**最终原则：** 先用免费数据证明技术流程可运行，再用足够完整的点时数据证明统计研究可信，最后通过成本后样本外结果与持续模拟盘决定是否具有进一步实盘研究价值。任何一环未通过，都不能跳跃推导“策略能赚钱”。
