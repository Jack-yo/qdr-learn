# QDR Quant Studio · 当前开发规范（V4）

本文件定义**当前代码开发的业务优先级**。历史 G0–G14、v2.1 的阶段协议保留在 docs 中供追溯，但不再作为 V4 的全局产品架构。具体改动与限制见 docs/V4_DEVELOPMENT_STATUS.md。

## 1. 产品目标

每个完成的美股交易日，在 T 收盘后、必要数据真实到达时，研究未来 H=1/3/5 交易日市场状态和个股条件收益；通过多因子候选发现、四层模型预测和组合风险约束，形成可冻结、可检验的模拟交易研究计划。预测结果必须持续与实际后续行情核对。

四层研究架构：
1. L1 市场状态：上涨/下跌概率、收益分布、显著下跌风险、状态识别与模型校准。
2. L2 经典因子：French 历史因子观察、ETF 风格代理、轮动、变化率、领先性样本外研究。
3. L3 个股 Alpha：自定义因子、因子组合、历史排序检验、A/B/C/D 条件收益预测和严格回测。
4. L4 持仓风控：已有持仓、相关性、风险预算、集中度、流动性、退出与风险预警。

总览整合四层研究事实，数据中心是底层支撑。多因子选股负责**发现研究候选**，四层决策负责**预测与风险判断**，不能将各层简单加权成为“买入评分”。

## 2. 时间与标签

- 使用 XNYS 日历和 UTC aware 时间。T 日收盘后冻结可用特征，最早 T+1 原始开盘价模拟入场，T+H 收盘退出或按事先冻结规则提前退出。
- 个股总交易收益、行业/市场超额收益、上涨概率、下跌事件概率分别建模；不得将超额收益直接当作扣成本前的总交易收益。
- 历史身份、行业、市值、财报、复权、公司行为必须有真实当时可用时间；当前存活股票和最新修订历史不能倒填。
- 训练、校准、验证、前向样本严格时间分离。五个交易日 embargo 是初始最低约束，仍须按实际标签可用时间排除重叠信息。
- 原 configs/experiments/baseline.yaml 的 2017–2024 / 2025+ 封存，只约束原实验版本。新研究配置使用 configs/experiments/v4_research.yaml，可使用最新实际可得数据；已经反复检查的年份不能再次称为独立最终测试。

## 3. 数据和模型证据

- 正式数据、概率、收益、回测、风险、模拟持仓不得使用虚构行情。数学单测可使用可控数字样本，但不能当作实际市场绩效。
- 区分描述性观察、探索性排序、时间外预测、历史成交模拟和已冻结前向模拟。任何一项不能自动冒充后一项。
- 缺少真实来源、PIT 历史证券池、公司行为权益或模型校准时，应明确报告缺失，保持不交易；不能为了填满页面伪造推荐。
- 概率校准必须使用时间上晚于模型拟合、早于测试期的独立校准样本；稀有事件不足时返回不可校准，而非精确概率。
- 比较 A/B/C/D 时必须匹配同一股票、同一交易日和标签；研究记录、多重检验次数和样本外对照必须可追溯。
- 研究档案哈希仅证明文件未被修改，不能独立证明证券身份、数据时点或统计预测优势。
- 实际券商下单始终关闭；不得添加购买数据、账户注册、密钥提交或自动开启实盘操作。

## 4. 当前 V4 源码入口

| 领域 | 代码 |
| --- | --- |
| 真实数据与来源 | src/quant_research/data/ |
| 历史股票池结构 | src/quant_research/data/v4_universe.py |
| 自定义因子 | src/quant_research/features/expression.py |
| 多因子研究 | src/quant_research/research/composite.py、factor_diagnostics.py |
| 市场预测基线 | src/quant_research/workflow/v4_market.py |
| 风格领先研究 | src/quant_research/research/v4_style_rotation.py |
| 条件 Alpha | src/quant_research/models/v4_panel.py、v4_oos.py、workflow/v4_alpha.py |
| 样本外增量/IC | src/quant_research/research/v4_increment.py、v4_alpha_ranks.py |
| 模型结果归档 | src/quant_research/research/v4_artifacts.py |
| 交易研究计划 | src/quant_research/workflow/v4_decision.py |
| 日终流程 | src/quant_research/workflow/v4_daily.py、v4_ops.py |
| 风控与模拟账本 | src/quant_research/risk/、backtest/ |
| Web UI/API | src/quant_research/web.py、assets/studio.js、app_shell.html |

不要把独立数学函数的完成说成已取得真实的市场预测优势，或将当前 v4_ops 描述为已接入生产模型和连续前向成交的完整调度。

## 5. 工程要求与验收

- 使用仓库已有 Python/uv/pytest/DuckDB/SQLite/Parquet 技术栈，优先扩展现有代码；新来源遵循 provider 协议。
- 新输入、产物和版本都应具备明确数据契约、拒绝重复/未来数据的测试、错误状态和可追溯版本。
- 禁止任意用户 Python eval/exec；自定义因子只允许经过审查的受限 DSL。
- 每次提交说明 DONE / TESTS / DATA / RISKS / NEXT；只有实际执行的测试可以宣称通过。
- 具备环境后运行：uv sync --locked；uv run --locked pytest -q；node --check src/quant_research/assets/studio.js。真实 PIT 研究和连续前向模拟需单独验收。
