# G4.6 市场滚动研究验收

市场分析页 `http://127.0.0.1:8766/market` 支持启动 Yahoo 回溯研究、选择 H1/H3/H5 与历史日期、查看状态和方向及下行概率、核对常数基线、下载逐日结果和训练窗口。市场状态日期和最后一个有完整标签的预测日期分别显示。正式历史模型状态仍为 BLOCKED。

## 样本与切分

- 读取 2017-01-03 至 2024-12-31 的 Yahoo 拆股调整价格。20 只显式 ETF 共 40,240 个证券日，经 20 份真实响应及抓取回执核验。实际运行记录保留源快照哈希、数据知识截止、代码及配置哈希。
- SPY 目标单独构建，每个信号日与期限仅一个标签。T 收盘后计算特征，按 T+1 开盘至 T+H 收盘计算价格代理收益。缺少完整特征或标签的日期不参加评价。带 `--asof` 的运行从数据库读取时即限制行情和标签范围。
- 初始训练截至 2022 年底，2023–2024 年按季度滚动。每折使用最多 1,260 个训练交易日且至少 252 日，先留 5 个交易日间隔，再剔除退出时间触及拟合边界的标签。预处理仅在训练段拟合。数据截止为 2023-06-30 的复跑与完整运行在共有信号日的输出一致。
- 沿用冻结配置的 Ridge 和 Logistic 基线，下行事件阈值为 −2%。模型概率未经额外校准，可靠性分箱用于评价。市场状态阈值在初始训练段估计，应用于后续验证段。French 归因由单独的风格监控提供，市场研究只读行情库。

## 实际结果

页面接口生成运行 `ddb850b5-6a8c-4589-8534-dac2ce60f721`，后台退出码 0。3 个期限、8 个季度共 24 个拟合窗口。方向概率的验证指标如下。

| 期限 | 可评价样本 | 模型 Brier | 常数 Brier | 基线减模型及 95% 区间 |
|---|---:|---:|---:|---|
| H1 | 501 | 0.247383 | 0.246803 | −0.000580 [−0.004281, 0.002693] |
| H3 | 499 | 0.243994 | 0.241948 | −0.002047 [−0.007097, 0.002944] |
| H5 | 497 | 0.242983 | 0.235358 | −0.007625 [−0.016221, −0.000128] |

三个期限方向模型的 Brier 和 Log loss 均高于常数基线。配对区间采用 20 交易日区块、500 次抽样。下行概率的对照分数、事件频率与方向可靠性分箱保存在报告中。H1 下行事件仅 3 例，三期限均没有独立的下行概率校准验收。

Yahoo 的真实首次可用时间晚于历史信号时间。因此上述验证属于当前版本的时间顺序回溯，历史决策资格为 false。实测 Alpaca 严格入口返回 `CAPABILITY_BLOCKED`、退出 4，缺历史发布时间和证券身份证据。2025 年起的最终测试仍封存。

## 复现及日常维护

```powershell
.\.venv\Scripts\python.exe -m quant_research.cli train-market --source yahoo --mode retrospective --db data/research.duckdb --output outputs/market_research
.\.venv\Scripts\python.exe -m pytest -q -rs --junitxml=outputs/market_research/tests.xml
.\.venv\Scripts\python.exe -m quant_research.cli data-catalog
.\scripts\start_console.ps1 --port 8766
```

输入继续登记在 11 类台账中的 `yahoo_research_prices`。研究产物独立保存在 `outputs/market_research/<run_id>/`，包括 manifest、参数、逐日状态与预测、训练窗口、方向和下行评分、可靠性分箱及报告。页面通过 `/api/v1/market/research` 读取最新完成且文件哈希匹配的研究。日期查询只切换历史样本，页面的整体验证指标仍对应运行全段。任务完成后可备份整个运行目录和数据原文。

全套回归实际为 **99 通过、1 跳过**，耗时 176.15 秒，JUnit 保存在 `outputs/market_research/tests.xml`。跳过项为 2026-11-06 的 Yahoo SPY 缓存缺 OHLCV。首次针对性测试有一项因沙箱阻止回环连接失败，随后全套在可访问本机回环的环境通过了该项。

实际 HTTP 验收记录在 `outputs/market_research/http-acceptance.json`，覆盖启动、任务状态、三个期限、12 月 31 日无完整 H5 标签的空态、报告下载和 2025 日期拒绝。已核对运行的 17 个产物哈希和 JavaScript 语法。Windows Computer Use 的浏览器输入授权等待超时，视觉验收尚未完成。

下一阶段优先补历史可用时点和身份的证据接线，再验收严格模型。个股 Alpha、合格策略回测和前向账本保留各自的数据准入门槛。

代码改动见 `models/dataset.py`、`models/walk_forward.py`、`workflow/market.py`、`workflow/common.py`、`web.py`、`market.html`、`data/catalog.py`（均在 `src/quant_research/` 内）。回归覆盖见 `tests/test_market_research.py` 与 `tests/test_web.py`。严格阻断输出见 `outputs/market_research/strict-blocked.log`。
