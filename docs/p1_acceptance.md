# P1 验收记录 — 2026-11-06

后续更新：用户授权 Yahoo 替代来源后，20 ETF 的 49,500 行日线已下载、零缺口审计及禁网重放通过；最终 71 项测试通过。见 [替代来源验收](p1_yahoo_acceptance.md)。下文保留首次 P1 验收时的真实状态，Alpaca 专项缺口仍然存在。

**结论：P1 工程部分完成，真实行情覆盖验收未通过；不进入 P2。**

## DONE

实现统一规范化 PriceProvider/PriceRecord、DuckDB 和 Parquet、原始响应 SHA-256 缓存、不可变抓取收据、分页续传、按月增量、显式刷新、限速/429/5xx 退避、价格版本/观测时间、French 单位转换和事后归因限制、SEC 两公司接口与近期申报、HTML/JSON 数据审计、CLI 与完整运行清单。

没有填入伪造的公司行为、股票池或财务 PIT 数据；相应表保持为空。模型、因子、回测、交易功能仍未开始。

## TESTS

实际环境 Windows、Python 3.13.15，uv.lock 锁定依赖；完整测试最终结果：**60 passed in 9.46s**，无 warning。保留 P0 全部测试。

```powershell
.\.venv\Scripts\uv.exe run --offline --locked --cache-dir .uv-cache pytest -q --junitxml=outputs/p1-pytest.xml
.\.venv\Scripts\python.exe -m quant_research.cli ingest-french --offline
.\.venv\Scripts\python.exe -m quant_research.cli ingest-sec --offline
.\.venv\Scripts\python.exe -m quant_research.cli ingest --source fixture --offline --start 2024-11-01 --end 2024-12-06
.\.venv\Scripts\python.exe -m quant_research.cli demo --fixture
```

覆盖：HTTP 重试/限速、只读 allowlist、请求头不入缓存、哈希损坏拒绝、分页/循环 token、失败后复用已完成页、无密钥离线重放、百分比和缺失码、SEC 时间/快照限制、幂等批量入库、Parquet 读回、IEX/SIP 隔离、历史时点先过滤再取版本、修订后恢复旧值、缺口审计、失败运行不伪装成功、配置和 P0 泄漏阻断。

测试使用明确合成响应，不冒充外部实测。真实下载和离线重放另列在下面。CI 已更新但远端未运行。

首次加载 DuckDB 遇到 Windows 缺 MSVC DLL；已在虚拟环境安装锁定的 msvc-runtime 并注册该环境 DLL 目录，未更改系统运行库。

## DATA / RESULTS

| 来源 | 实际结果 | 边界 |
|---|---|---|
| French FF5、Mom、ST Rev | 148,212 条日因子；FF5/含 RF 每序列 15,918 行，Mom 26,237，ST Rev 26,467 | 最新数据日均为 2026-09-30；仅事后归因 |
| SEC Apple / Microsoft | 4 份真实快照；2,010 条 recent 申报 | companyfacts 当前聚合，不是历史 PIT；未遍历全部旧申报分片 |
| fixture | 20 个合成证券，500 行，2024-11-01 至 2024-12-06 | 仅工程验证 |
| Alpaca 仓库 | 0 行真实行情 | 无本地凭证，长历史连接器传输失败/超时 |

French 和 SEC 的真实下载已经成功，随后离线重放新增行数均为 0。fixture 重复入库新增价格版本也为 0。
French FF5 起始 1963-07-01，Mom 1926-11-03，ST Rev 1926-01-26；这些是当前下载文件的历史序列，不是当时保存的 vintage。

Alpaca 短期 SPY 工具探测曾返回 4 行，仅作连通性检查，未当作已覆盖 20 证券或可成交行情入库。完整请求随后失败；本机直接适配器实测明确返回缺少 ALPACA_API_KEY / ALPACA_SECRET_KEY，写 FAILED 清单，无价格补造。

真实行情审计：2017-01-01 至 2026-11-05 的默认 20 证券，0 行，49,500 个预期证券/交易日观测缺失。缺口未填补。

### 产物

- 测试 XML：`outputs/p1-pytest.xml`
- P0 demo：`outputs/experiments/fabe343f-6931-4e5e-aaf8-37204b57d546/report.json`
- 数据库：`data/research.duckdb`
- french：`outputs/ingestion/d66f9049-860c-4a85-83a4-cd17df1986a3/manifest.json`
- sec：`outputs/ingestion/1199a5fd-acb2-4e6a-b055-3ee7a022aa1b/manifest.json`
- fixture：`outputs/ingestion/8dc4e6c4-4d1d-46f8-a39c-397507c332e0/manifest.json`
- alpaca_failed：`outputs/ingestion/21d997fb-0037-40dd-b79b-17c87108b1f6/manifest.json`
- alpaca_audit：`outputs/ingestion/31d5ef42-fd8d-4241-8b6a-d094074f97f9/audit.json`

## RISKS

- P1 的 20 证券 2017 至今真实价格拉取、断网行情缓存重放验收尚未完成。分页和缓存的合成测试不能替代它。
- 无 PIT 股票池/退市/改名、公司行为、跨供应商核验、全市场成交量及可交易开盘价证据。IEX 不能代表 SIP 全市场。
- 真实历史数据可用时间采用首次观测；今天下载的历史行情不能直接被宣称为历史时点可得快照。
- SEC 联系邮箱只在请求头使用，没有存入仓库、manifest 或原始缓存元数据。密钥也不入仓库。
- P1 默认读取相同查询缓存；获取供应商修订需要显式 --refresh。SEC 单进程统一限速，避免与其他 SEC 下载任务并发。
- 本阶段没有计算或宣称策略收益、胜率、显著性和实盘可用性。所有报告 research_grade=false。

## NEXT

继续完成 P1：在本机配置 Alpaca 只读市场数据凭证或恢复可用连接器，然后执行 20 证券 2017 至最近已结束交易日的 ingest、相同请求离线重放、重复运行和数据审计。确认实际覆盖与 feed 限制，无法获得的历史保留 DATA_INCOMPLETE。此项通过后再制定 P2 因子协议和标签实现。

## 文件变更清单

新增源码：

- src/quant_research/data/http.py
- src/quant_research/data/schema.py
- src/quant_research/data/normalize.py
- src/quant_research/data/store.py
- src/quant_research/data/quality.py
- src/quant_research/data/pipeline.py
- src/quant_research/data/providers/alpaca.py
- src/quant_research/data/providers/french.py
- src/quant_research/data/providers/sec.py

修改源码：src/quant_research/cli.py、data/providers/base.py、data/providers/fixture.py。

新增测试：tests/unit/test_http_cache.py、test_p1_providers.py、tests/integration/test_p1_pipeline.py、test_p1_resume.py；更新 tests/unit/test_fixture.py。

修改配置/文档：pyproject.toml、uv.lock、configs/sources.yaml、.env.example、.github/workflows/tests.yml、AGENTS.md、README.md、docs/architecture.md、data_dictionary.md、data_limitations.md、decisions.md、milestones.md。

新增文档：docs/p1_data_pipeline.md、docs/p1_acceptance.md。真实原始数据、数据库、Parquet、报告和测试产物保存在被 Git 忽略的 data/ 与 outputs/ 中。
