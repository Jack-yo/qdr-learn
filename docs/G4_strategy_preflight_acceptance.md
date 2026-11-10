# G4.8 策略冻结、严格回测准入与 ETF 对照验收

策略工作台支持选择已完成的真实因子实验、保存草稿、校验、冻结及复制。第一版采用单因子值降序的配置，保留 T+1 开盘、H1/H3/H5 退出以及 ATR 止损规则。单标的、总仓位、行业上限、最低 ADV20 和止损倍数受服务端约束。市场与风格条件、多因子组合及模型选股未接入该策略。

配置记录绑定因子版本、实验、结果和数据快照哈希。校验及冻结重新核验研究依赖，复制生成新版本。冻结保存配置及时间，历史决策资格由回测准入独立判断。预设成本场景每侧 5/10/20/50 bps，属于冻结的参数假设。

## 实际策略与回测准入

- 网页接口冻结 v1 `cfafe5f2-1f3e-418f-89da-b1e451259f5f`，复制 v2 草稿 `f9eb7c8c-9760-484e-b052-74a712014cb2`。v2 将总仓位上限配置为 45% 以检验版本隔离。v1 哈希未变。
- 越界单标的上限返回 HTTP 400，未冻结版本检查返回 409，缺少写入令牌返回 403。重复冻结返回原记录。
- 准入运行 `69fd803d-5323-430a-ba74-5160b38cc02d` 核验了 2017–2024 年的 40,240 条 Alpaca SIP 原价，原价和覆盖通过。历史股票池与退市覆盖、永久身份、时点、公司行为结算和可交易策略信号缺项，实际结果为 BACKTEST_BLOCKED。
- 页面显示缺项，支持回看最新准入证据并下载 HTML 与 JSON。收益、回撤、实际交易成本及成交均显示 N/A，封存最终测试仍未使用。

## ETF A–D 验证

通过策略工作台的后台任务实际运行 `d41ab97b-5925-4265-9e7a-c0d5d73873e2`，退出 0。使用 40,240 条经来源回执核验的 Yahoo 2017–2024 日线，SPY 为基准，17 只 ETF 进入横截面。初始训练至 2022 年底，2023–2024 季度滚动，执行训练期内变换、5 个交易日间隔与标签退出时点剔除。

共有 101,796 个可评价预测行，四个变体按相同日期、标的和期限比较。H1、H3、H5 每个变体分别有 8,517、8,483、8,449 行。12 组超额收益排序的平均 Rank IC 均为负，结果不足以支持按这些模型排序选股。原始概率、配对 Brier、单因子对照、分组和可靠性表均在报告中保留。结果仅限当前版本 ETF 回溯，历史决策合格行数为 0。

## 复现与日常维护

```powershell
.\scripts\start_console.ps1 --port 8766
.\.venv\Scripts\python.exe -m quant_research.cli strategy-preflight --strategy-version cfafe5f2-1f3e-418f-89da-b1e451259f5f
.\.venv\Scripts\python.exe -m quant_research.cli train --source yahoo --mode retrospective --db data/research.duckdb --output outputs/alpha_research
.\.venv\Scripts\python.exe -m quant_research.cli data-catalog
.\.venv\Scripts\python.exe -m pytest -q -rs --junitxml=outputs/strategy_preflight/tests.xml
```

在 `/strategies` 保存与冻结，在 `/backtests` 查看资格。当前准入命令退出 4，同时保存真实证据报告。策略登记保存在 `data/managed/strategies/registry.sqlite3`，结果按运行归档在 `outputs/strategy_preflight` 和 `outputs/alpha_research`。分类台账 13 类。备份时连同所引用的因子实验、来源原文与回执一起保存。

全套实际 **106 通过、1 跳过**，耗时 250.34 秒。跳过项为 2026-11-06 Yahoo SPY 缓存缺 OHLCV。最终准入报告回看及台账改动后，专项回归 **11 通过**，与全套重叠。两次 JUnit 分别为 `outputs/strategy_preflight/tests.xml` 与 `final-focused-tests.xml`。JavaScript 语法检查通过。服务重启后，已实测重新读取同一份准入证据和 ETF 报告。

## 修改文件与剩余工作

- `src/quant_research/research/strategy.py` 与 `workflow/strategy_preflight.py` 实现版本及准入。
- `src/quant_research/workflow/train.py`、`models/walk_forward.py` 明确历史样本、精确标签截止及只读来源。
- `src/quant_research/workflow/factor_lab.py` 补齐依赖报告哈希校验。
- `src/quant_research/strategies.html`、`web.py`、`cli.py`、`data/catalog.py` 接入网页、接口、命令和台账。
- `tests/test_strategy.py`、`tests/test_alpha_research.py` 验证真实依赖、冻结复制、源缺失、哈希缺失、标签截止和 A–D 配对样本。

下一主干为每日观察与前向账本的证据接线。正式个股 Alpha、严格回测和模型模拟成交仍需历史证券、可用时点及结算数据通过验收。完整浏览器视觉验收尚未执行。
