# QDR V4 · 代码改造进度与剩余验收（2026-11-11）

> 本文记录真实已提交的工程改动；并不宣称四层量化系统已在真实 PIT 全市场数据上完整运行。开发仓库：Jack-yo/qdr-learn / main。

## 目标

四层架构为 L1 市场状态预测、L2 经典因子与风格轮动、L3 自定义因子/多因子选股/个股 Alpha、L4 持仓与风险。每日决策横向使用其研究结论，执行 T 收盘冻结、T+1 原价模拟入场、T+H 收盘或预设条件退出、真实交易日连续跟踪。

## 本次已实现

| 模块 | 代码位置 | 已落地的功能及限制 |
| --- | --- | --- |
| 自定义因子 DSL | features/expression.py | 白名单 AST，不执行任意 Python；OHLCV、daily_return、lag/ret/mean/std/sum/abs/rank/zscore；lookback 自动推导、递归上限、禁止负窗口/未来读取；只计算传入的市场数据 |
| 因子版本及实验接入 | research/factor_lab.py、assets/studio.js | 增加 template=custom，公式随不可变版本保存、预览、实验；窗口必须覆盖依赖；无真实数据时仍然阻断 |
| 横截面时点约束 | features/engine.py | rank/zscore 因子新增 cross_section 依赖；检查全部输入证券窗口及最新发布时间，防止迟到的其他证券数据修改已冻结截面 |
| 多因子诊断 | research/factor_diagnostics.py、research/composite.py | 同一日期的 Spearman 相关性中位数、有效交易日数、≥0.85 的冗余提示；最新候选展示各因子分位和加权贡献；仅历史探索，非可交易信号 |
| 收益目标修正 | models/walk_forward.py | 个股未来总交易收益使用单独 Ridge 模型预测，超额收益使用另一个模型；不再将训练期平均基准收益机械叠加到超额预测后冒充总收益 |
| 持仓风控与风险数学 | risk/portfolio.py | 独立计算协方差收缩组合波动率、历史 VaR/ES、市场 beta、个股/行业/组合仓位风险；输入缺失或含未来数据时拒绝；无来源证明时研究性质 |
| 账本集中度实时检查 | backtest/paper.py、web.py、assets/studio.js | 经内部对账的模拟账本增加可审阅原价估值、/api/v1/paper/risk 只读接口、前端集中度预警；缺少历史收益时 VaR/ES 明确为 N/A |
| 信息架构 | app_shell.html、assets/studio.css | 总览 + 四层研究导航 + 数据中心，L3 因子/选股/回测为子页面，L4 组合风险为子页面 |

## 第二轮：已提交的研究模型与日终编排工程

| 研究能力 | 本轮新增代码 | 实际完成的边界 |
| --- | --- | --- |
| 市场 H1/H3/H5 | workflow/v4_market.py、models/v4_oos.py | 真实标签协议、训练/校准/测试分期、市场上涨/显著下跌概率的独立输出、常数基线；只有拿到合格输入才可得到数值 |
| 风格领先性 | research/v4_style_rotation.py | 经典 ETF 风格代理的因果特征、5日动量变化、滚动持续性、未来相对收益的滚动预测与 OOS 误差基线 |
| 个股 Alpha | models/v4_panel.py、workflow/v4_alpha.py | 禁止回溯代理标签填补真实收益；严格拼接市场/风格/个股特征；A/B/C/D 同样本 Ridge + Logistic 滚动预测 |
| 统计检验 | research/v4_increment.py、v4_alpha_ranks.py | 按交易日配对概率误差及收益 MSE 增量、区块 Bootstrap 区间、Rank IC、分组超额收益；不等于成本后可交易净值 |
| 历史股票池结构 | data/v4_universe.py | 每日完整快照与采集时间、代码冲突、缺失交易日检测；不替代数据提供商真实 PIT 身份/退市证据 |
| 候选→研究计划 | workflow/v4_decision.py | 上涨与下跌概率、预计净优势、成本/流动性/仓位和已有持仓约束；输出研究计划，非已经准入的模拟订单 |
| 研究结果存档 | research/v4_artifacts.py | 不可覆盖的哈希归档、只读验证、API 与策略回测页的样本外指标查看；哈希不证明源数据真实时点 |
| 日终四层编排 | workflow/v4_daily.py、v4_ops.py | 源观察→市场→风格→Alpha→风险→冻结的结构化分阶段记录，失败不伪造数据，独立研究层可继续；源模型尚未全部接入正式自动信号与模拟账本 |
| 新版研究协议 | configs/experiments/v4_research.yaml | 不改动旧 2017–2024 封存研究的原配置；未来新研究可滚动使用实际可获得的最新数据 |

**新增只读入口：**
- GET \`/api/v1/v4/research/runs\`：已归档的研究实验列表。
- GET \`/api/v1/v4/research/runs/{run_id}\`：真实存档的 Brier、MSE、配对增量、Rank IC 等研究指标。
- GET \`/api/v1/v4/daily\`：真实记录的最近日终四层阶段日志。
- 命令：\`uv run --locked python -m quant_research.workflow.v4_ops --root . --date YYYY-MM-DD\`。此命令当前执行**已存数据的观察与研究进度编排**，不会自动拟合具备准入的生产预测器，也不会伪造预测或推进模拟成交。

研究数据若尚未提供，相关页面显示无历史归档，不会出现任何演示盈亏与模型预测值。

## 第三轮：正式研究入口与前向预测冻结

已增加可以在合格的本地数据包到位后直接运行的两类 CLI：

- **历史样本外实验**：\`python -m quant_research.workflow.v4_study_cli --root . --bundle-id <DATA_BUNDLE_ID> --run-id <EXPERIMENT_ID> --evaluation-start 2024-01-02 --evaluation-end 2024-12-31\`
- **T 日前向预测与冻结**：\`python -m quant_research.workflow.v4_forward_cli --root . --bundle-id <DATA_BUNDLE_ID> --asof YYYY-MM-DD\`

在真正生成预测之前，输入包必须位于 \`data/managed/v4_inputs/<DATA_BUNDLE_ID>/\` 并具有：

1. \`factors.parquet\`：\`date,security_id,feature_name,value,available_at,decision_eligible\`，全部需是实际时点可用的因子；
2. \`labels.parquet\`：\`date,security_id,horizon,entry_time,exit_time,available_at,gross_return,excess_return,label_kind\`。历史实际标签必须为 \`VERIFIED_RAW_TRADE_TOTAL_RETURN\`；当日尚不可知的未来标签必须明确为空且类型 \`FUTURE_UNOBSERVED\`；严禁以 Yahoo 当前版本代理行情替代；
3. \`market_style.parquet\`：\`date,state_available_at,market_*,style_*\`，需带有真实可用时点和数值特征；
4. \`manifest.json\`：研究包类型 \`V4_STRICT_LABEL_STUDY_INPUT\`、逐文件 SHA256、数据快照 SHA256、\`factor_names\`。

该规范只是**输入契约和文件完整性检验**，**不代表真实供应商 PIT 历史、事件结算和原价成交资格已经被独立验收**。在真实数据不可用时不提供任何模型预测值。

这次新增的具体能力：
- \`models/v4_forward.py\`：T 日未观测收益严格为空，历史数据遵守滚动训练窗口与5-session embargo，模型训练与概率校准按时序隔离，针对未来 H1/H3/H5 分别给出研究预测和版本证据。
- \`research/v4_forecast_archive.py\`：冻结未来预测时，不允许保存任何实际未来收益、成交 ID，采用不可覆盖的独立目录、SHA256 校验，拒绝把研究预测升级为交易结果。
- \`GET /api/v1/v4/forecasts\`、\`GET /api/v1/v4/forecasts/YYYY-MM-DD/<identity>\`：只读查看已归档前向研究预测；总览已接入 H3 候选研究视图，未归档时显示真实空态。
- \`workflow/v4_ops.py\`：只读当日研究阶段记录，可持续观察独立四层结果，但默认**不自动调用完整训练和合格模拟成交**，需要接入真正已经独立验收的数据与模型。
- 新增测试：\`tests/test_v4_forward.py\`、\`tests/test_v4_forecast_archive.py\`，仅数值和防伪造契约测试，**本轮没有运行完整 pytest**。

**开发完成与实际策略有效是不同的两个验收对象。** 现有 V4 模型、CLI 和存档使工程链路具备独立运行入口，但未有外部合格数据、未完成全量运行与评估，不能宣称系统已经能稳定预测或有正收益。

## 测试证据

- 已为自定义因子、市场/Alpha OOS、时间戳标签、统计增量、历史股票池、风格、候选计划、风险、实验归档和日终编排增加独立单元测试文件。**本轮未能在完整最新 main 环境执行这些新增测试或全部 pytest，因此不可宣称通过。**
- 本轮通过连接的源码读取对最新 `studio.js` 进行了 JavaScript 语法解析检查；但 `node --check`、实际浏览器交互、HTTP 集成、DuckDB/Parquet 读写及完整 pytest 尚未在同一个最新 main 本地环境运行。
- 未运行持证的全市场 PIT 回测、实际 Alpaca SIP 前向实盘历史连续验证，也没有生成可交易的真实预测收益。

## 仍然没有完成（不能以页面/接口代替）

1. **PIT 历史证券池**：全市场普通股身份、上市/退市、当时行业和成分覆盖、公司行为及合法来源；当前 G7/G8 前向目录不能替代历史 PIT。
2. **真实样本外 Alpha 验证**：A/B/C/D 预测、滚动校准与统计对比的代码已写入；仍需合格真实 PIT 个股数据、合规总收益/超额收益标签、可量化的预测不确定性、持久化生产模型与未见样本证据。
3. **历史严格回测**：原始可成交价格、拆股分红/退市权益、公司行为现金流水、真实成本及成交条件资格；现存 Yahoo 回溯结果仍为价格代理研究。
4. **真实模型的日终全自动链路**：已经有六阶段 V4 编排和研究日志，但默认适配器目前是只读观察模式；尚需把经过真实数据准入的市场/Alpha 模型训练、实时候选、预测版本冻结、T+1 模拟执行与连续验证接入正式运行。
5. **模型有效性**：目前无足够合格真实数据可证明超过基准的 OOS 预测优势、正净收益或连续前向表现。
6. **完整集成验收**：使用最新 main 在具备合规真实数据和依赖的开发环境运行全部 pytest、web smoke、SIP/数据回执审计及每日连续模拟。

## 研究协议重要纠偏

- 旧 baseline.yaml 的 2025+ 封存仅约束**旧实验自身**；新 V4 可按真实数据与新滚动研究协议纳入最新交易日，但不得重写旧证据，也不得把已见过的 2025–2026 历史伪装成独立测试。
- 概率必须显式区分未校准 Logistic 与样本外经过验证的已校准概率。
- 单个因子 IC、风格延续状态或多因子排名都不是完整成本后交易优势。
- 没有满足准入的候选时应输出“无交易计划”，严禁为了让 UI 有内容编造信号。

## 可在具备本地完整仓库时运行

\`\`\`powershell
uv sync --locked
uv run --locked pytest -q tests/test_factor_expression_v4.py tests/test_factor_diagnostics_v4.py tests/test_portfolio_risk_v4.py
uv run --locked pytest -q
node --check src/quant_research/assets/studio.js
.\scripts\start_console.ps1 --port 8766
\`\`\`

此文档可作为后续开发和 code review 的持续验收清单；对未完成项必须保留明确的外部数据/验证依赖，不能标为完成。
