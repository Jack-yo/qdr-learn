# QDR Quant Studio 本地验收报告

验收时点：2026-11-12 约 09:24 UTC（美东盘前）。本报告只记录本机实际执行的检查。`outputs/local_acceptance/` 保存详细日志、SQL 汇总 JSON 和真实 Chromium 截图；该目录被 Git 忽略，原始供应商响应、凭证和账户资料没有提交。复核时应从仓库根目录运行文末命令，并阅读相应产物。

## A. 环境、仓库及复现命令

| 项目 | 实测值 |
| --- | --- |
| 操作系统 | Windows 11，10.0.26200，x64 |
| Python / uv | 3.13.15 / 0.13.7；系统 `python` 别名不可用，使用 `.venv/Scripts/python.exe` |
| 核心依赖 | DuckDB 1.4.1、PyArrow 22.0.0、Pandas 2.3.3、NumPy 2.3.4、scikit-learn 1.7.2、pytest 8.4.2 |
| 浏览器 | Node 24.22.1；Playwright Python 1.65.1；Chromium 158.0.8127.18 (v1254)。`npm` 不在 PATH |
| Git | 初始 `main` 为 `22948b756e7ac0972ee35e6c6a610c6452a51700` 且工作区干净；`git fetch origin main` 成功，本地与远端当时 0/0 分叉。代码修复提交 `caa75005cc74e85a81d41c4ec6b24618da2f71b8`，测试修复提交 `e1cb4bc325b66b7bb4ec10aa19cf4a02975811cd`。报告提交 SHA 见 `git log -1`，不能自含其 SHA |
| 凭证 | 本机 `.env` 存在，进程环境中最初未设置 Alpaca 两个变量；仅通过仓库既有 `--env-file .env` 数据命令加载。未读取或输出凭证值。未使用券商下单接口 |

`uv sync --locked` 初次受沙箱默认缓存目录权限阻断；设置 `UV_CACHE_DIR` 为仓库内被忽略的 `.uv-cache` 后成功。Windows 虚拟环境原本无法导入 DuckDB/MSVC 扩展，独立于沙箱权限；在被忽略的 `.venv/Lib/site-packages/sitecustomize.py` 中加入 `os.add_dll_directory(os.path.join(sys.prefix, "Scripts"))` 并保持返回的 handle 后，全部核心包可导入。全新虚拟环境复核时需重做这一环境修复；它未改变锁文件。Playwright 与 Chromium 安装在被忽略的本机环境，未加入锁定开发依赖。

实际执行的主要命令（PowerShell，所有 `uv run` 均设置上述 `UV_CACHE_DIR`；浏览器命令另设置 `PLAYWRIGHT_BROWSERS_PATH` 为 `.playwright-browsers`）：

```powershell
git status --short --branch
git fetch origin main
.\.venv\Scripts\uv.exe sync --locked
.\.venv\Scripts\uv.exe run --locked pytest -q
node --check src/quant_research/assets/studio.js
.\.venv\Scripts\python.exe scripts/local_acceptance_audit.py
.\.venv\Scripts\uv.exe run --locked python -m quant_research.cli maintain-data --groups prices --end auto --env-file .env
.\.venv\Scripts\uv.exe run --locked python -m quant_research.cli maintain-data --groups actions,french --end auto --env-file .env
.\.venv\Scripts\uv.exe run --locked python -m quant_research.cli close-snapshot --asof 2026-11-11
.\.venv\Scripts\uv.exe run --locked python -m quant_research.cli daily-observation --asof 2026-11-11
.\.venv\Scripts\uv.exe run --locked python -m quant_research.workflow.v4_data_diagnostics --db data/real_v21.duckdb --asof 2026-11-11 --symbols 'SPY,IWM,IWD,IWF,MTUM,QUAL'
.\.venv\Scripts\uv.exe run --locked python -m quant_research.cli research-readiness --asof 2026-11-11
.\.venv\Scripts\uv.exe run --locked python -m quant_research.workflow.v4_ops --root . --date 2026-11-11
.\.venv\Scripts\uv.exe run --locked python -m quant_research.cli feature-price-audit --refresh-source-responses --env-file .env --db data/real_v21.duckdb --asof 2026-11-06 --action-end 2026-11-06 --output outputs/feature_prices
.\.venv\Scripts\python.exe scripts/local_acceptance_browser.py --widths 1440,1920
.\.venv\Scripts\python.exe scripts/local_acceptance_browser.py --widths 375
```

数据命令对已有库作版本化增量写入；审计脚本只读。`assets-sync --endpoint paper --env-file .env` 也实际执行，返回 `ASSET_IDENTITY_AMBIGUOUS`，没有形成可验收的资产目录。没有执行付费订阅、破坏性迁移或真实交易。

## B. 数据仓库、质量与资格

SQL 查询、列模式、空值/重复/OHLC 检查、来源分组和哈希核验的机器可读原始结果见 `outputs/local_acceptance/database_audit.json`。这里的“物理行”包含保留的抓取版本；训练样本不能直接按物理行计算。

| 数据集与来源 | 实际表、物理行、证券/区间 | 质量和原始证据 | 用途及 PIT 资格 |
| --- | --- | --- | --- |
| Alpaca SIP raw，`data/real_v21.duckdb` | `prices_daily` 与 `price_observations` 各 99,200 行；20 ETF，49,580 个不同证券日，2017-01-03 至 2026-11-11，共 2,479 个 XNYS 日；最新入库 2026-11-12 08:46:58 UTC | 本次补 160 物理行，20 证券在最新日均有记录，配置范围内缺证券日率 0；OHLC/成交量空值 0、非正成交量 0、OHLC 逻辑错误 0；按证券日有 49,520 组保留多版本，按 SHA/证券日/来源精确重复 0。239 个不同原文 SHA 对象全部存在并校验一致。99,180 行首次可用日期晚于其交易日；全库质量标记为 `EXPLORATORY|SURVIVORSHIP_BIASED|IDENTITY_UNVERIFIED|DATA_INCOMPLETE` | **A 当前 ETF 观察**。非历史 PIT；`securities` 20 行 `asset_type=UNKNOWN`，ID 仍为 `SYMBOL-UNVERIFIED:*`。不能充当个股 Alpha、历史原价成交权益或合格训练包 |
| Yahoo split-adjusted 与合成夹具，`data/research.duckdb` | `prices_daily`：Yahoo 99,020 行、20 ETF、2017-01-03 至 2026-11-06；另有 500 行 `SYNTHETIC_FIXTURE`。正式登记的探索子集为 2017–2024 共 40,240 证券日 | 全表价格空值、非正量、OHLC 错误均 0；Yahoo 49,500 个证券日有多个版本，不能按物理行训练。原文对象存在，但调整价与原价不可混用。2026-11-06 的最新缓存另有 `SOURCE_INCOMPLETE_OHLCV:SPY` 测试跳过 | **B 历史探索**，必须按 YAHOO/source/feed/basis/年份筛选；合成夹具不得参与真实指标。非原价执行、非 PIT |
| Yahoo 历史特征/代理标签，同库 | `features_daily` 2,394,756 行，2017–2024，全部 `decision_eligible=false`；`labels` 513,060 行，2017–2024，全部 `EXPLORATORY_PRICE_PROXY_NOT_FILL`，正式 `forward_return` 非空 0、代理收益非空 512,295；`predictions` 102,408 行，2023–2024 | 标签口径是 `yahoo_split_adjusted` 价格代理；当年可用时间及证券池未认证 | **B 历史探索**。不能称为总交易收益或当前预测 |
| Ken French，`data/managed/classic_factors/factors.duckdb` | `factor_returns` 148,212 行，因子各自起始不同；全库 1926-01-26 至 **2026-09-30**；本次重新获取官方当前版本，插入 0 行 | 发布/本机首次可用时间保留；最新记录的 `available_at` 2026-11-06。更新后 `style-report` 只有描述性观察 | **A/B 归因与历史风格观察**；`ATTRIBUTION_ONLY`，不能把 9 月因子值当作 11 月 11 日已知当日因子或风格预测 |
| Alpaca 公司行为，`data/managed/corporate_actions/events.duckdb` | `corporate_event_versions` 1,042 行、20 ETF：1,034 现金分红、8 拆股；本次重新取源两页，插入 0 行 | 新原始页 SHA 与回执保留；事件表最早/最近原观察仍是 2026-11-07。事件出现不证明逐证券逐日“没有其他事件”或分红账本权益 | 事件审计证据，**非**完整历史行动覆盖；`action_coverage_daily` 0 行 |
| SEC，`data/g3_evidence.duckdb` | `filing_index_versions` 1,953 行，`financial_candidates` 941 行，`decision_eligible=true` 为 0 | 两家公司的索引/候选；缺完整有效时间和全市场身份 | 历史事实候选，非 PIT 财务特征 |
| V4 合格输入 | `data/managed/v4_inputs/` 不存在；`factors.parquet`、`labels.parquet`、`market_style.parquet`、`candidate_meta.parquet`、`manifest.json` 均不存在 | `real_v21` 的 `features_daily`、`labels`、`universe_daily`、`action_coverage_daily` 均 0 行，`sector_classification_pit` 0 行且缺 `source_sha256`；`fundamentals_pit` 0 行 | **C 历史 PIT：无；D 合格前向预测输入：无**。仓库无法自动形成合格 V4 包，现有 `v4_data_diagnostics` 为只读拒绝清单 |

`data/raw/` 本次审计有 344 个对象、321 份回执、305 个请求指针；价格 239 个不同 SHA 的实际对象哈希全匹配。原文 SHA 只证明对象完整，不能替代有效期证券身份、行业、退市、完整公司行为或模型优势。`data/managed/close_snapshots/observations.sqlite3` 已在 2026-11-12 08:48 UTC 冻结 2026-11-11 的 20 条真实 ETF 观察，`capture_sha256=6d59ecdf...`，状态 `OBSERVATION_FROZEN`、`decision_eligible=false`。`data/managed/factor_lab/registry.sqlite3` 有实际不可变因子版本/实验；本轮新增一个验收版本与实验，见下文。其他旧 fixture/验收库未删除，仍由分类目录排除。

严格的拆股参考对账首次用旧参考响应时出现 11 条成交量差异（最大 217,501），原因是原价已更新而参考缓存未同批刷新。新增 `--refresh-source-responses` 后重新向 Alpaca 获取并保留新旧回执；同一 49,520 行比较的成交量差异降至 **0**。收盘价仍有 11,149 行差异、最大 0.005，预设 `price_atol=0.0001` 未修改，结果保持 `BLOCKED`。详见 `outputs/local_acceptance/feature_price_audit.txt`、`feature_price_refresh.txt` 及 `outputs/feature_prices/037b8632-b194-4055-97d8-9b82589b42f0/comparison.json`。

### 统一时点与逐模块新鲜度

实测美东 2026-11-12 盘前，XNYS 最新完成交易日是 2026-11-11，统一研究截止为当日 21:15 UTC。20 ETF 的完整日线直到 **2026-11-12 08:46:58 UTC** 才在本机可用：虽在次日开盘前，仍晚于事先固定的 T 日信号截止，不能倒填为 11 月 11 日的事前模型输入。`/api/v1/v4/freshness` 和 `outputs/local_acceptance/freshness.json` 分别记录 UTC/美东时钟、`asof_session`、`source_data_asof`、`knowledge_cutoff_utc`、`generated_at_utc`、`model_version`、状态及阻断原因；`CURRENT` 在行情栏仅指当前**观察日覆盖**，不授予模型准入。

| 模块 | 数据来源 | 实际截止交易日 | 最新可获得交易日 | 预测生成时间 | 时效状态 | 阻断原因 |
| --- | --- | --- | --- | --- | --- | --- |
| 市场数据观察 | Alpaca SIP 20 ETF | 2026-11-11 | 2026-11-11 | 无 | CURRENT（观察） | 当日数据晚于 21:15 UTC 决策截止；`known_by_decision_cutoff=false` |
| L1 市场预测 | SPY 原价 + V4 市场模型 | 2026-11-11 行情 | 2026-11-11 行情 | 无 | BLOCKED | `NO_APPROVED_CURRENT_MARKET_FORECAST; PRICE_ARRIVED_AFTER_DECISION_CUTOFF` |
| L2 风格预测 | French + ETF 代理 | French 2026-09-30；ETF 2026-11-11 | ETF 2026-11-11 | 无 | HISTORICAL_ONLY | 官方 French 当前缓存有公布延迟；无已准入风格预测 |
| L3 个股 Alpha | 需要 PIT 股票池/因子/标签 | 无合格股票数据 | 无 | 无 | BLOCKED | `NO_PIT_STOCK_UNIVERSE_OR_CURRENT_FROZEN_ALPHA` |
| L4 当前持仓风控 | 需要已对账持仓/现金和估值 | 无 | 无 | 无 | BLOCKED | `NO_RECONCILED_CURRENT_HOLDINGS_AND_CASH` |
| 总览同批四层 | 上述四层同一批次 | 无完整批次 | — | 无 | BLOCKED | `FOUR_LAYER_BATCH_NOT_ADMITTED` |

回答强制时效问题：① **20 ETF 市场观察已更新到最新完成交易日**，股票历史池没有；② 四层模型**未**基于最新合格数据运行；③ 当前候选排名**不是**最新冻结研究批次，页面历史排名必须继续标为探索；④ 四层没有形成同一决策时点的合格输入；⑤ 市场旧研究、Yahoo 因子实验与 Alpha 旧归档仍以 2024 年及以前为研究终点；⑥ French 截止 9 月且发布滞后，Alpaca 缺永久 PIT 身份/完整公司行为覆盖，Yahoo 是调整价代理，SEC 财务候选 0 条决策合格。价格最新日期并不构成预测更新。

## C. 四层模型运行验收

本轮没有用旧历史预测冒充 2026-11-11 的概率。`configs/experiments/v4_research.yaml` 的**协议参数**为 H1/H3/H5、训练至少 252 交易日、校准 126 日、5 日 embargo、每类校准样本至少 8、Ridge alpha 1、Logistic C 1、显著下跌阈值 -2%。它们不是本轮拟合出的标准化均值、回归系数或 Platt 参数；当前模型版本、系数和概率均为空。

| 层 | 代码与实际操作 | 输入/产物/样本及结论 | 日终联动 / 前向资格 |
| --- | --- | --- | --- |
| L1 市场 | `workflow/v4_market.py`、`models/v4_oos.py`；执行最新仓库预检与 `v4_ops` | **BLOCKED**，最新真实原价标签 0、市场当前已准入模型 0。历史只读档案 `outputs/market_research/7237566e-363d-48bb-a2d8-77f4a77da197/` 是 2024-12-31 Yahoo 回溯，H1/H3/H5 Brier 0.247383/0.243994/0.242983，朴素基准 0.246803/0.241948/0.235358，三者均未胜出；历史样本数 501/499/497，归档状态 `NOT_READY`。不能外推到当前 | `v4_ops` 市场阶段 `NO_APPROVED_V4_MARKET_PREDICTIONS`；无正式前向概率，训练系数和校准参数本轮 **NOT RUN** |
| L2 风格 | `research/v4_style_rotation.py`、`workflow/styles.py`；实际运行 `maintain-data --groups actions,french` 及自动 `style-report` | 描述性风格报告 `outputs/styles/b323690d-8b71-48c8-8792-96120fa16c94/`，French 截止 2026-09-30，状态 `DESCRIPTIVE_CURRENT_VINTAGE_ONLY`。没有 `VERIFIED_RAW_RELATIVE_RETURN` 标签或本轮滚动 OOS 风格预测；ETF 代理行情虽到 11-11，未和可用时点合格标签形成领先性验证 | `v4_ops` 风格阶段 `PolicyError`；无 L2→L3 当前预测增量，**BLOCKED / UNVERIFIED** |
| L3 个股 Alpha | `features/expression.py`、`models/v4_panel.py`、`v4_oos.py`、`v4_forward.py`、`workflow/v4_alpha.py`；本轮实际创建/运行因子实验 `525060a0-9fb9-46ff-abe8-5581f09a4f2f` | `outputs/factor_lab/525060a0-9fb9-46ff-abe8-5581f09a4f2f/` 只用 Yahoo 2017–2024：40,240 输入行、34,204 特征行、102,612 标签行，其中 102,459 有代理收益、正式原价标签 0、决策合格特征 0，`RETROSPECTIVE_EXPLORATORY_ONLY`。旧 `outputs/alpha_research/d41ab97b-5925-4265-9e7a-c0d5d73873e2/` 有 A/B/C/D 的 101,796 行历史 ETF 代理研究预测、96 folds、0 合格决策行，**不是个股 Alpha**；未证明 D 优于 A | `v4_ops` Alpha 阶段 `NO_DATED_V4_ALPHA_PREDICTION`；当前候选/参数归档/校准概率 **BLOCKED** |
| L4 持仓风控 | `risk/portfolio.py`、`workflow/v4_decision.py`、`backtest/paper.py`、`workflow/v4_plan_outcomes.py`；运行 readiness 与 `v4_ops` | `NO_ACCEPTED_PAPER_LEDGER`；无可核对的当前持仓/现金、当日估值、冻结风险计划或 H3 成熟结果。成本、止损、仓位和现金逻辑有单元测试，但本轮无真实账户或连续真实模拟样本可执行 | 决策/冻结/后续评价 **BLOCKED**；没有交易订单 |

`v4_ops --date 2026-11-11` 的真实产物是 `outputs/v4_daily/2026-11-11/42ce30feca25e4a7/manifest.json`：数据阶段 `RESEARCH_ONLY`，随后 L1/L2/L3/L4 均 `BLOCKED`，整体 `RESEARCH_UPDATED_NO_TRADE`。再次运行返回同一 `identity` 与 `content_sha256`，没有覆盖。由于没有五件套 V4 包和 PIT/行动证据，不执行带 `--bundle-id` 的冻结 CLI，避免创建不合格“当前预测”。不可变哈希只校验本地归档字节，不能证明历史数据资格。

## D. 自动化、API 与真实浏览器

初次在套接字受限沙箱执行的全量 pytest 为 **351 PASS / 11 FAIL / 7 SKIP**，HTTP 回环权限与缺 Playwright 是部分原因；解除回环限制并安装匹配 Chromium 后又暴露 Windows 路径/默认编码、DST 固定 UTC 夹具、异步 UI 断言、过时硬编码数据行数和实际数据参考版本不一致。没有删除失败测试或降低原价对账容差。最终在真实数据更新和修复后，`uv run --locked pytest -q --tb=short` 为 **371 PASS / 0 FAIL / 3 SKIP**（172.55 秒），完整结果 `outputs/local_acceptance/pytest_final.txt`。三项跳过分别是两条缺已归档真实 Alpaca 资产目录、以及 SPY 2026-11-06 旧缓存 OHLCV 不完整；它们不是通过跳过掩盖的模型通过。

Playwright 仓库交互测试 `tests/test_v4_ui_browser.py` 最终 **4 PASS**，覆盖子 Tab/键盘、历史校准显示、候选主从联动、因子比较和风险空态；其 API stub 仅验证 UI 契约。真实后端另外使用 `scripts/local_acceptance_browser.py` 启动实际 `ThreadingHTTPServer`，分别在 1440、1920、375 px Chromium 访问 `/studio` 六个工作区及数据中心：**21/21 路由渲染，0 横向溢出**；市场 4、风格 5、因子实验 4、选股 4、风控 5 个子 Tab 均实际存在。`/factors`、`/strategies`、`/backtests`、`/signals`、`/paper`、`/data` 高级工具入口均 HTTP 200。`/api/v1/v4/freshness`、`/daily`、`/plans` 均 HTTP 200。选股页请求无合格资产目录时返回 409，浏览器控制台相应记录 1 次/视口；这是实际后端阻断，不是 JS 异常或伪造数据。桌面/手机汇总见 `outputs/local_acceptance/browser/summary_1440-1920.json` 与 `summary.json`，实际运行截图见同目录 `overview_*.png`、`market_*.png`、`risk_*.png`、`data_*.png`。没有把 UI stub 的数字或静态样稿当作模型绩效。真实浏览器**尚未**逐项完成弹窗/因子 POST→实验→版本比较及移动端全部操作反馈，故六页完整交互结论仍为 PARTIAL。

## E. 真实链路逐步结果

| 步骤 | 状态 | 可复核证据 |
| --- | --- | --- |
| Git 同步和锁定依赖 | PASS | `git fetch` 0/0 分叉；`uv sync --locked` 成功，本机 MSVC 路径修复见 A |
| 最新 ETF 行情和行动/French 更新 | PASS（仅观察） | `outputs/maintenance/9676f698-de3c-4476-9aea-e86bdefabb1b/`、`92cd1d81-128f-40c4-a702-c71eed6651e3/`；20 ETF 到 11-11、French 到 9-30 |
| 来源/质量与 V4 合同预检 | BLOCKED | `outputs/local_acceptance/database_audit.json`、`v4_diagnostics.json`：8 项中 6 项阻断；`readiness.json` 历史模型/回测/前向均 BLOCKED |
| 当前因子生成、市场/风格特征、H1/H3/H5 原价标签、候选元数据及五件套 | BLOCKED | `real_v21` 对应表空、`v4_inputs` 不存在；历史 Yahoo 因子实验虽 PASS（计算）但非当前合格因子 |
| L1→L2→L3→L4 预测与风险决策 | BLOCKED | `outputs/local_acceptance/v4_daily.json` 的逐阶段代码；无批准模型、PIT 个股和账本 |
| 11-11 真实 ETF 观察与研究日志冻结 | PASS（观察） | `outputs/daily_observations/0b9e9f20-f868-4fc5-b43e-95ce94897c2f/`、`outputs/v4_daily/2026-11-11/42ce30feca25e4a7/manifest.json`；`v4_daily_repeat.json` 哈希相同 |
| 合格预测/交易计划冻结 | BLOCKED | 行情到达晚于信号截止，模型与 V4 包缺失；无经批准候选，不触发真实或模拟订单 |
| H1/H3/H5 后续实际结果及前向评分 | NOT TESTED | 本轮无合格事前冻结预测且期限未成熟；不得回填历史作为前向胜率 |

## F. 本轮修改、验证及兼容性

| Commit | 文件和修复 | 验证 / 风险 |
| --- | --- | --- |
| `caa75005cc74e85a81d41c4ec6b24618da2f71b8` | `workflow/v4_freshness.py`、`web.py`、V4 core/pages、`cli.py`、`workflow/feature_price_audit.py`、`models/v4_forward.py`、`data/capability_checks.py`、`.gitignore`：增加只读 XNYS 决策时点与逐模块状态/API/UI；显示 French 实际截止日；显式刷新原始参考版本且保留回执；前向标签泄漏报精确拒绝原因；旧 baseline 封存说明纠偏。对应 `tests/test_v4_freshness.py`、`test_feature_prices.py` | 全量 pytest、JS 解析、真实浏览器。新 API 只读；刷新选项显式使用，旧默认缓存行为不变。时效状态仅是观察时点，不授予数据/模型资格 |
| `e1cb4bc325b66b7bb4ec10aa19cf4a02975811cd` | 9 个测试文件：修复 Windows `src` 路径、UTF-8、路径括号、DST 夹具、异步等待、同一阶段互相矛盾的索引、独立仓库篮子夹具；把动态真实行数按日历验证 | 不删除测试、不放宽价格阈值。测试数据断言仍要求完整回执和原价对账；更新真实源后全量通过 |
| 本报告提交 | `scripts/local_acceptance_audit.py`、`scripts/local_acceptance_browser.py`、本报告与 JSON 摘要 | 审计脚本只读，浏览器脚本只启动本机回环；日志和截图在 Git 忽略的 `outputs/`。报告自引用的最终提交 SHA 由 `git log -1` 复核 |

已完整修复的 P0 两项：本机锁定依赖的 DLL 导入阻断；新旧真实来源版本不一致造成的 11 条成交量参考差异。统一时点状态和页面标注已落地，但四层全部接入同一合格批次仍是剩余 P0，不能计入完成。

## G. 剩余缺口及复核方式

### P0：本地工程仍可继续解决

1. `workflow/v4_ops.py` 的默认适配器仍为观察模式，`workflow/v4_market.py`、`research/v4_style_rotation.py` 与 `workflow/v4_alpha.py` 未作为已准入生产模型连续衔接；需要在真实数据准入后做同日批次 ID、模型参数与来源归档，并跑 `v4_ops --preflight-only` 与不可变重复运行检查。
2. `workflow/v4_bundle_contract.py` 有严格消费者/拒绝逻辑，但尚无从合格仓库**自动**生成五件套及 Manifest 的正式生产器。应以独立来源、PIT 身份、行动权益及可用时间为输入，测试重复行、未来因子/标签、原价/代理混用；在数据未齐时只能输出阻断清单。
3. `workflow/v4_freshness.py` 与数据中心已展示统一 XNYS 时钟，旧模块还未全部以同一 `asof_session`/`knowledge_cutoff_utc` 驱动实际训练、预测与 UI。需在四层模型调用和冻结记录中传播同一批次上下文，增加来源各自发布节奏配置及跨日期拼接拒绝测试。
4. `data/assets.py` 本轮在线当前资产同步返回 `ASSET_IDENTITY_AMBIGUOUS`。需审查保存的原始响应中歧义字段、修复身份规范化或明确拒绝异常条目，再次运行 `assets-sync`；不得把当前目录倒填历史。
5. 真实 UI 交互 E2E 还缺逐项因子创建/预览/提交、策略权重保存、错误反馈及高级工具功能流程；在 `tests/test_v4_ui_browser.py` 与实际服务脚本上补同源 API 断言。重型 `/api/status`/readiness 并发请求在先前移动端巡检曾引发超时，本轮去掉顶部重复请求后通过，但仍需独立性能验收。

### P0：必须依赖外部真实数据、权限或额外来源证据

1. `real_v21.duckdb` 的 `universe_daily`、`sector_classification_pit`、`fundamentals_pit`、`action_coverage_daily` 为空，`securities` 缺永久 ID/有效期证券映射，未纳入退市股票；需可核对的 PIT 主档、当时行业/市值和逐证券行动覆盖后，按 `data/capability_checks.py` 复核。没有这些数据不能训练真实个股 Alpha 或做严格历史回测。
2. `labels` 与当前股票因子为空；`research.duckdb` 仅 Yahoo 价格代理，不能充当原价总收益。需原价 T+1 开盘/T+H 收盘、分红拆股/退市权益及实际可用时间，再生成真实 H1/H3/H5 标签。
3. 49,520 行拆股参考仍有 11,149 条最大 0.005 的价格差异，严格 `price_atol=0.0001` 下继续 `BLOCKED`。需供应商原始精度/舍入语义或独立可成交价证据；不能改阈值求 PASS。
4. French 官方当前可取版本只到 2026-09-30，需保留真实发布时间，不可补造 11 月值；风格前向标签还需可核对的 ETF 行动权益。

### P1：需要连续真实前向样本

1. `research/v4_forecast_archive.py`、`workflow/v4_plan_outcomes.py`、`v4_forward_scorecard.py` 需要逐日事前冻结预测、到期原价路径和独立结果复核。当前有效预测/结算会话为 0；积累至少协议定义的配对会话数后才比较 Brier、MSE、成本后收益及区块区间。
2. `backtest/paper.py` 与 `workflow/paper_timeline.py` 需真实开始日、现金/持仓/行动权益和每日估值流水；目前 `NO_ACCEPTED_PAPER_LEDGER`。不能把历史研究预算场景或假设成交称为已运行账户。

### P2：可选增强

1. 将只读 SQL/浏览器脚本接入 CI 的可选本地数据验收作业，保留源数据缺席时的明确 `BLOCKED`，而不是使普通无数据 CI 假绿。
2. 对数据中心新鲜度表在 375px 下增加专门的宽表列提示；本轮已无页面横向溢出，但表格单元格会省略长阻断码。

## H. 最终验收判定

| 问题 | 结论 | 证据 |
| --- | --- | --- |
| 1. 软件可启动并完成基本操作？ | **PASS** | 实际本地 HTTP、21 次真实浏览器工作区渲染、因子实验完成、371 条测试通过；缺数据操作按规则阻断 |
| 2. V4 六个核心页面通过真实浏览器完整验收？ | **PARTIAL** | 三视口六页与数据中心渲染/子 Tab/高级入口通过；尚缺全部真实 POST、弹窗和错误回放路径 |
| 3. 真实数据自动生成合格 V4 输入包？ | **BLOCKED** | `v4_inputs` 五件套均无；PIT/行动/原价标签表缺失，诊断 6 项阻断 |
| 4. L1/L2/L3/L4 自动联动运行？ | **BLOCKED** | 11-11 日志市场/风格/Alpha/风险阶段均阻断，只有来源观察冻结 |
| 5. 模型概率通过可信样本外及前向验证？ | **BLOCKED** | 当前校准概率/系数 0，旧 Yahoo 市场 Brier 未胜朴素基准、正式前向样本 0 |
| 6. 具备持续可复核研究模拟运行能力？ | **BLOCKED** | 无合格连续前向模型、当前持仓/现金/行动权益与逐日模拟账本；不开放真实订单 |

**独立复核重点**：先执行只读审计并核对原始对象哈希、SQL 结果和 11-11 决策截止；再运行锁定测试与浏览器脚本；最后按来源证据检查 `v4_diagnostics.json` 和 `readiness.json` 的每个阻断。不得把历史 Yahoo 实验、真实 ETF 观察、源码中存在的模型函数或测试全绿提升为实时预测能力。
