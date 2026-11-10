# 日常数据维护手册

日常优先使用分类台账和维护入口。数据更新不会自动训练、产生预测、回测成交或真实下单。当前主行情是显式20ETF观察名单，不是历史股票池，也不是全市场个股库。

## 先看哪里

- 网页：`http://127.0.0.1:8766/data`，查看“分类数据台账”，可下载CSV；“日常维护：行情与公司行为”执行真实数据更新。
- 分类入口：`data/managed/`。每个类别的`dataset.json`记载真实来源、权威库路径、用途、状态和缺失原因。
- 最新目录指针：`data/catalog/latest.json`，指向不可变快照目录；目录内有`datasets.csv`、`cache_index.csv`、`excluded_stores.csv`、`catalog.json`。
- 每次维护日志：`outputs/maintenance/<run_id>/manifest.json`，查看每个源的状态、插入数、范围、错误代码。单个源失败不会抹掉其他源的结果。
- 经典因子监测：网页`/styles`；报告在`outputs/styles/<run_id>/`，最新观察指针`data/managed/classic_factors/monitor_latest_observation.json`，最新研究指针`monitor_latest_research.json`。
- 因子实验：网页`/factors`；使用及备份方法见`docs/FACTOR_LAB_GUIDE.md`。版本、冻结配置和计算结果独立保存，按需运行。
- 市场滚动研究在网页 `/market` 按需运行。Yahoo 探索价格为输入，历史方向与下行风险研究产物存入 `outputs/market_research/<run_id>/`。按运行目录备份，完整范围及复现命令见 `docs/G4_market_research_acceptance.md`。

分类目录是入口索引和独立数据存储的组合。原始行情库继续保留现有路径；不复制出第二个“主行情库”，避免日后两份不一致。源原文继续共享内容寻址缓存，分类索引记录每份原文归属。

## 数据分类与当前范围

| 类别 | 权威位置 | 当前实际范围 | 更新/用途 |
|---|---|---|---|
| 行情原价 | `data/real_v21.duckdb` | 20ETF，2017-01-03至2026-11-06，49,520个证券日 | 每日；ALPACA SIP raw，观察及经准入的后续计算 |
| 公司行为 | `data/managed/corporate_actions/events.duckdb` | 1,042条，含拆股及现金分红；源版本保留 | 每日；事件证据，不等于已验收现金账本 |
| SEC申报索引 | `data/g3_evidence.duckdb`的`filing_index_versions` | AAPL/MSFT，2017–2024，共1,953条 | 每周；申报索引证据 |
| SEC财务候选 | 同库`financial_candidates` | 941条候选，可用于历史决策的条数为0 | 每周；禁止作为已验证PIT基本面 |
| 经典因子 | `data/managed/classic_factors/factors.duckdb` | 148,212个因子日数值，FF5/RF、动量、短反转 | 每周；仅归因/当前版本描述，不假设当日已发布 |
| 历史证券与股票池 | `data/managed/historical_securities/dataset.json` | BLOCKED，无合格历史名册/退市/永久ID | 依赖真实历史证券主档 |
| PIT财务与行业 | `data/managed/pit_fundamentals/dataset.json` | BLOCKED | 依赖原稿数值、发布时间、身份及历史行业 |
| 合格模型与预测 | `data/managed/eligible_models/dataset.json` | BLOCKED | 数据准入后训练、样本外验证并冻结 |
| 前向模拟账本 | `data/managed/paper_ledger/dataset.json` | BLOCKED | 从合格真实开始日逐日记录 |
| Yahoo探索价格 | `data/research.duckdb`中的源筛选子集 | 20ETF，2017–2024，40,240个证券日 | 按需；split-adjusted，仅当前版本回溯探索 |
| 因子定义与研究实验 | `data/managed/factor_lab/registry.sqlite3` | 不可变版本与冻结实验；结果在`outputs/factor_lab/` | 按需；不等于合格模型或模拟账本 |
| 开盘前冻结行情观察 | `data/managed/close_snapshots/observations.sqlite3` | 首份 2026-11-06，20 只 ETF 原价及抓取回执 | 按需；前向观察证据 |
| 策略草稿与冻结版本 | `data/managed/strategies/registry.sqlite3` | 因子依赖、策略版本、冻结时间、配置哈希 | 按需；准入结果在 `outputs/strategy_preflight` |
| 每日行情观察报告 | `outputs/daily_observations/<run_id>/` | 真正冻结的 SIP 日线和独立日期的 French 风格 | 更新并冻结后生成；候选资格单列 |

经典因子当前缓存的最早日期为1926-01-26、最晚2026-09-30，各因子起始日期不同。这是缓存覆盖情况，不表示所有因子从1926年开始，也不保证已更新至最近交易日；周更会获取新源版本，缺失日期不得填零。

当前台账共14类。数据库物理行包含不同抓取/修订版本，例如主行情现有99,040物理行对应49,520个证券日。不能把物理行数当训练样本数；正式读取按知识截止筛选版本。旧`fixture`及旧验收库在excluded_stores.csv列明，不删除，也不作为正式输入。`research.duckdb`是历史混合库，仅明确筛选并逐源核验的 YAHOO/yahoo_split_adjusted、2017–2024 子集登记为探索输入，其他记录不因此获得准入。

## 每日操作

可使用一条命令按实际 XNYS 窗口串联日更、冻结、日报与台账。失败保留退出码 4，成功复用同日已有冻结与日报。只用已缓存真实数据演练时加 `-Offline`。

```powershell
.\scripts\run_daily.ps1
```

在项目根目录的PowerShell运行：

```powershell
.\scripts\maintain_data.ps1 --env-file .env
```

默认自动选择已经收盘至少20分钟的XNYS交易日。只读访问Alpaca数据域；凭证只保留在本机`.env`，不上传到网页、报告或聊天。

行情按每只证券真实最新日期选择增量起点，并重取最近5个交易日以容纳迟到修订。公司行为重取配置范围、按事件ID及源版本保留。返回0表示所选维护任务完成，仍不代表研究/交易资格通过。

网页也可点击“日常维护：行情与公司行为”。维护期间页面与其他工作流返回维护中，完成后恢复；不并发读写同一DuckDB文件。

更新结束后，在收盘 20 分钟后至下一开盘前，可在 `/data` 点击“冻结本期 SIP 观察”，或运行 `.\.venv\Scripts\python.exe -m quant_research.cli close-snapshot`。冻结保存本期原价及精确回执，一日一次。需要刷新分类台账时运行 `data-catalog`。参见 `docs/G4_close_snapshot_acceptance.md`。

冻结后在 `/signals` 点击“生成本期观察日报”，或运行 `.\.venv\Scripts\python.exe -m quant_research.cli daily-observation`。日报与原始快照独立保存。使用 `/paper` 核对前向观察日期及账户准入，备份时保留 `outputs/daily_observations` 和相应快照及回执。参见 `docs/G4_daily_observation_acceptance.md`。

## 每周操作

SEC在线请求需要在本机进程设置合规`SEC_USER_AGENT`，内容为项目名和你的真实联系邮箱；不要把值提交到仓库或发送聊天。Alpaca仍从本地`.env`读取。

```powershell
.\scripts\maintain_data.ps1 --cadence weekly --env-file .env
```

周更默认只跑French与SEC。SEC当前仅支持已验证的AAPL/MSFT候选范围，不能把这两个样本称为美股财务全库。French保留发布版本及首次观测时间；不能把下载日期倒填成历史公布日期。

French维护结束后自动核验源ZIP并生成最新风格观察报告，在任务manifest中记录style_monitor_status。也可单独运行`.\.venv\Scripts\python.exe -m quant_research.cli style-report`；`--mode research`限制至2024年底。页面支持5/20/60日窗口、日期、知识截止、来源检查及摘要导出；观察状态不是交易预测。

## 检查、重跑和历史回补

```powershell
# 仅重建台账、校验现有原文哈希，不联网、不修改源价格。
.\.venv\Scripts\python.exe -m quant_research.cli data-catalog

# 仅重试特定类别。
.\scripts\maintain_data.ps1 --groups french,sec --env-file .env

# 回放本机真实缓存。下例是已实测区间；缺缓存会明确失败。
.\scripts\maintain_data.ps1 --offline --full --groups prices,actions,french,sec --end 2026-11-06

# 需要联网补齐配置中的整段历史时使用；不会购买数据。
.\scripts\maintain_data.ps1 --full --env-file .env
```

维护配置在`configs/data_maintenance.yaml`：每日/每周分类、ETF名单、历史起点、重叠会话数、French数据集及SEC样本。改变当前名单不会自动产生历史PIT股票池。

数据任务顺序执行，逐项记入manifest。真实源失败不会生成替代值；全任务成功为MAINTAINED，部分失败为PARTIAL_BLOCKED（退出码4）。失败后先看该组code，再用`--groups`重试，不必重跑所有类别。

| 错误或状态 | 处理 |
|---|---|
| MISSING_CREDENTIALS | 检查本机Alpaca环境变量或显式`--env-file .env` |
| MISSING_SEC_USER_AGENT | 为本机研究进程设置合规SEC项目名与联系邮箱 |
| HTTP_401 / HTTP_403 | 检查凭证、数据权限或供应商拒绝；不自动开通付费套餐 |
| Offline cache miss | 该精确查询没有缓存，允许联网后重跑相应组；不补造行情 |
| missing_sessions > 0 | 检查缺失日期，必要时`--full --groups prices`回补；缺口未修复前不开放相关研究 |
| MAINTENANCE_LOCKED / DAILY_OPS_LOCKED | 活动进程持锁时等待其结束。本版本在进程退出后可核对并恢复遗留标记。旧格式或损坏标记需人工确认 |
| CATALOG_HASH_MISMATCH | 保留损坏证据，恢复原文件或重新执行data-catalog；不手改状态为PASS |
| NOT_HISTORICAL_PIT / ATTRIBUTION_ONLY | 数据用途限制，不是“采集失败”；禁止用作不符合资格的历史预测 |

## 保存与备份

在维护及实验结束后运行 `ops-backup`。恢复使用 `ops-restore --backup-id <备份UUID>`，输出到新的隔离目录，核验实际来源与报告依赖。Windows 失败重试与恢复日志见 `docs/G5_operations_acceptance.md`。

策略版本按需保存和冻结。备份时保留策略登记、引用的因子实验和 `outputs/strategy_preflight`。ETF A–D 结果独立存于 `outputs/alpha_research`，使用相同 Yahoo 探索输入分类。参见 `docs/G4_strategy_preflight_acceptance.md`。

保留`data/raw/objects`、`data/raw/receipts`、`data/raw/requests`、Yahoo对应回执、上述权威数据库、`data/managed`、`data/catalog`、维护配置以及`outputs/maintenance`、`outputs/factor_lab`、`outputs/market_research`。备份在维护和实验任务结束、数据库写连接关闭后进行。恢复后先运行data-catalog与离线回放核验，不靠文件存在就声明完整。

不要删除原文/回执来“节约空间”，不要覆盖旧预测、成交或账本，也不要手工编辑源价格或用当前名单填充过去。没有注册自动计划任务、购买服务或启用真实交易。
