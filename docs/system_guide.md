# P0–P6 本地研究系统使用指南

P0–P6 的工程功能已实现。严格历史研究、实盘可交易性和盈利优势**未验收通过**：真实数据只有当前版本 ETF 面板，缺少原始价/PIT/退市等证据。Yahoo 永远不会进入当前成交或模拟账户路径。没有券商账户、真实订单或云端服务。

## 从零运行

需要 Python 3.11–3.13、uv 0.13.7。首次安装依赖需联网；安装后合成全流程不需要网络或 API Key。

```powershell
uv sync --locked
uv run --locked pytest -q

# 原 P0 快速演示
uv run --locked python -m quant_research.cli demo --fixture

# P3→P6 完整工程演示，独立数据库和模拟账户
uv run --locked python -m quant_research.cli run-all --source fixture --db data/demo-system.duckdb --state-db data/demo-paper.sqlite3
```

本机 uv 位于虚拟环境，可用 `.\.venv\Scripts\uv.exe` 替代 uv；Python 可用 `.\.venv\Scripts\python.exe`。命令均在项目根目录执行。

## 各阶段命令

```powershell
# P3：状态、方向概率和固定下行事件基线
.\.venv\Scripts\python.exe -m quant_research.cli market-report --source yahoo --mode retrospective --asof 2024-12-31
.\.venv\Scripts\python.exe -m quant_research.cli train-market --source fixture --db data/market-demo.duckdb

# P4：A–D 按季度滚动训练，禁用随机切分和全样本变换
.\.venv\Scripts\python.exe -m quant_research.cli train --source fixture --db data/model-demo.duckdb
# 如需当前版本真实 ETF 模型研究，必须显式 retrospective；结果禁止成交
.\.venv\Scripts\python.exe -m quant_research.cli train --source yahoo --mode retrospective

# P5：默认会先生成训练运行；也可 --training-run outputs/system/<训练run_id> 复用
.\.venv\Scripts\python.exe -m quant_research.cli backtest --source fixture --db data/execution-demo.duckdb
# Yahoo 必须返回 4，产生明确阻断报告
.\.venv\Scripts\python.exe -m quant_research.cli backtest --source yahoo --mode retrospective

# P6：完整概率/风格/候选计划，允许没有交易
.\.venv\Scripts\python.exe -m quant_research.cli daily-report --source fixture --asof 2024-12-31 --db data/paper-demo.duckdb
.\.venv\Scripts\python.exe -m quant_research.cli paper-replay --source fixture --asof 2024-12-31 --db data/paper-demo.duckdb --state-db data/paper-demo.sqlite3
.\.venv\Scripts\python.exe -m quant_research.cli paper-step --source fixture --asof 2025-01-02 --db data/paper-demo.duckdb --state-db data/paper-demo.sqlite3
.\.venv\Scripts\python.exe -m quant_research.cli paper-step --source fixture --asof 2025-01-03 --db data/paper-demo.duckdb --state-db data/paper-demo.sqlite3

# 调度入口：只在显式调用时刷新数据；失败不发新建议、不推进纸面账户
.\.venv\Scripts\python.exe -m quant_research.cli scheduled-run --source yahoo --mode strict --asof auto
```

全部命令支持 --help。P3–P6 默认配置为 `configs/experiments/baseline.yaml`，可指定 --experiment、--db、--output、--mode、--source；纸面账户另有 --state-db。

成功返回 0 只代表工程计算完成；2 是输入/契约错误；4 是数据不足/不符合严格模式，不能理解为建议做空或强制清仓；未知运行错误返回非零并保留异常。数据库为单写，不要并发写同一 DuckDB 或同时运行两个每日作业。

## 冻结的研究窗口与学习协议

- 开发价格 2017–2024，2023–2024 为样本外验证展示；真实 2025 起最终结果不用于训练评估和择优。
- 按季度重训，最长 1,260 过去 session，最少 252 session；以标签实际退出时间 purge，并额外隔离至少 5 session。
- SimpleImputer/StandardScaler 只拟合训练段。Ridge alpha=1、Logistic C=1、seed=42，无参数搜索。
- 市场 H1/H3/H5 方向和收益低于 -2% 的概率，与各训练段常数概率比较 Brier/LogLoss，另存校准分箱。单类别训练只能回退常数，并明确状态。
- Alpha 预测超额收益、P(up)、预期原始价毛收益；未估计预测不确定性时为 null，未做校准时保留 UNCALIBRATED 标记。
- A=Alpha；B=Alpha+市场观测；C=Alpha+ETF 风格代理；D=全部+因果交互。使用同一窗口/目标，不能把不同层分数直接相加。
- 5% 下行分位是训练样本的无条件历史分位，不是校准的个股 VaR 或组合尾部保证。市场/风格预测没有经验证的增量时只报告，不直接控制交易。
- 真实 Yahoo 的 retrospective 是当前版本模型研究，不是历史可交易预测；所有决策资格为 false。

## 市场与风格

SPY 收益/波动、RSP/SPY 集中度代理、HYG/LQD 信用代理、行业 ETF 分散度/相关性、ETF MA20 广度代理均保留可用时间。广度不是历史股票 PIT 广度，信用代理不是官方利差；10 年利率输入未接入，标记缺失。

小盘、价值、动量、质量、低波动为 ETF 比率代理。相对收益 5/20 日、按日增长差加速度、正收益天数、20 日相对波动率组成描述；四态分界用训练段中位数估计，冻结到验证段。阈值可用时间也进入状态资格，不能把训练期末阈值回填过去。

French 当前版本只用于历史归因图，原始 available_at/version/use_policy 保留；不作为当日实时输入。SEC 当前 companyfacts 不进入 PIT 质量特征。

## 事件执行与风控

实际执行仅接受合成 raw/PIT 工程路径。每个 horizon/variant/cost 是独立账户，初始权益 $100,000。T close 后信号，T+1 open 买入，T+H close 退出；风险约束可在预先定义事件提前退出。

- 单票目标≤10%，总目标≤50%，单行业≤25%；未知行业统一视作一个 UNKNOWN 集群，不伪造分散。
- E 额外用 2×ATR20 起始止损，计划权益风险≤0.3%。先扣成本，要求预期净收益>0，并用预先冻结的无条件下行分位限制筛选。
- ADV20≥$20M、价格≥$5，成交金额≤过去 ADV20 的 1%；不使用当日最终成交量来决定开盘仓位。
- 每侧滑点 5/10/20/50 bps；手续费和冲击另配置。冲击 bps=100×(成交金额/过去ADV20)，是保守假设而非实际券商报价。
- 开盘穿越止损按更差开盘价加成本；同根路径未知保守止损优先。日内触发的精确时刻不可得，以收盘时间记账并留标记，不伪装逐笔时间证据。
- 仓位在成交事件按上限分配；收盘价格漂移超限在下一可交易开盘调整，不倒造当日收盘调仓。风险汇总展示实际超限漂移。
- 不可定价/停牌持仓冻结新入场，保留过期持仓和陈旧估值标识；无法验证的退市结算不虚构价格。支持显式 kill-switch API，状态可持久化。
- 拆股同步调整数量/成本基准/止损和待执行订单；无法处理的碎股/现金替代须报错。分红仅在显式验证生效/付款政策时记现金；真实 Yahoo 事件现金口径仍未验证，不进入成交路径。

现金、SPY Buy&Hold、等权篮子、单因子与 A–E 共用成交/费用/记账引擎。SPY 与等权基准免投资组合权重上限，资金利用率另报，不能把不同仓位差当作模型增量。

指标包括净收益/年化、日 Sharpe、回撤/Calmar、最差1/5日、费用、持有期、换手、年度/市场条件、行业集聚与过去相关性。交易数是实际关闭 lot 切片（含风险减仓）；费用/毛收益仅在毛利润为正时定义。日频资金利用率用开盘与收盘观测暴露较大值的均值，并另列两端暴露，不冒充精确的日内时间加权利用率。H1 收盘空仓不能被误认为全天未投资。

## 模拟账户与失败恢复

SQLite WAL + BEGIN IMMEDIATE，账户配置冻结，account/date 与事件 ID 唯一。相同输入/日期重跑返回原快照，不新增成交；不同输入修订必须显式处理，不能覆盖旧记录。必须逐个有效 session 推进，跨过漏失交易日会失败；paper-replay 演示最后两个 session。

现金=初始现金+所有持久事件现金流，每次提交前核对。订单先存前一日状态，下一 session 才成交；历史 snapshot、成交、持仓与账户状态可续记。数据刷新失败输出 alerts.json 和空候选，不推进账户。Yahoo 因 raw/PIT 或历史可用时间不足，只产生无建议报告。

当前 REAL_ONLY 日常入口为 `scripts/run_daily.ps1`，通过 `daily-ops` 按 XNYS 收盘后 20 分钟至下一开盘窗口更新、冻结并生成观察日报。Windows 和 cron 示例未注册为定时任务。实际恢复演练与退出码见 `docs/G5_operations_acceptance.md`。

live 日报可读取当时已到达的价格特征，但训练标签始终截止 2024；2025 之后仅创建没有实际收益的 forecast 行，不能评估或反向调参。跨年演示的数据完全合成，不是打开真实最终测试。

## 产物与数据表

每次输出 UUID run_id、UTC asof/cutoff、universe/model 版本、数据/配置/代码哈希及文件哈希。HTML/CSV/JSON/Parquet 共同交付。DuckDB schema v4 已有 predictions、orders、fills、positions、equity_curve，附执行 record_json；纸面账户另存 SQLite accounts/days/events。

P3–P6 fixture v2 按证券独立随机流，扩展 end 不改写过去；P0–P2 保留旧版生成器以复现既有报告。不同 fixture 版本不是同一研究样本，不能混合比较。

当前固定状态仍是 NOT_READY：ETF 面板不是股票 Alpha 证据，缺原始成交价/PIT 股票池/退市/行业/市值财务/真实报价与成本。没有部署按钮、真实下单代码或隐含实盘授权。

技术参考：[LogisticRegression](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html)、[时间切分与 gap](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)。实际 purge 还按标签退出/可用时间实施，不仅依赖通用 TimeSeriesSplit。
