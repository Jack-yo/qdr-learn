# P1 数据管道

当前状态：**用户授权 Yahoo 替代来源，P1 探索性验收通过**。20 ETF 已取得 49,500 行实际日线，缺失为 0，禁网重放价格和事件新增均为 0。French、SEC 也已实测；Alpaca 专项和原始价/PIT 缺口保留。没有推进 P2，详见 p1_yahoo_acceptance.md。

## 运行

首次更新依赖：`uv sync --locked`。本机 uv 位于 `.venv/Scripts/uv.exe`，可按 README 使用完整相对命令。

```powershell
# 无网络：20 个合成证券写入 DuckDB，重复运行应新增 0 条价格版本
uv run --locked python -m quant_research.cli ingest --source fixture --offline --start 2024-11-01 --end 2024-12-06
uv run --locked python -m quant_research.cli data-audit --source fixture --offline --start 2024-11-01 --end 2024-12-06

# 真实免费因子及两公司 SEC 快照
uv run --locked python -m quant_research.cli ingest-french
# 先在当前进程设置 SEC_USER_AGENT：项目名称/版本 + 本人联系邮箱
uv run --locked python -m quant_research.cli ingest-sec --ciks 320193,789019

# 已成功下载后，断网重放不需要密钥或 SEC 联系信息
uv run --locked python -m quant_research.cli ingest-french --offline
uv run --locked python -m quant_research.cli ingest-sec --offline

# 用户授权的 Yahoo 替代来源：无需 API Key
uv run --locked python -m quant_research.cli ingest --source yahoo --start 2017-01-01 --end 2026-11-05
uv run --locked python -m quant_research.cli ingest --source yahoo --start 2017-01-01 --end 2026-11-05 --offline
uv run --locked python -m quant_research.cli data-audit --source yahoo --start 2017-01-01 --end 2026-11-05 --offline

# Alpaca：先在本机环境配置 ALPACA_API_KEY / ALPACA_SECRET_KEY
uv run --locked python -m quant_research.cli ingest --source alpaca --feed iex --start 2017-01-01 --end 2026-11-05
uv run --locked python -m quant_research.cli ingest --source alpaca --feed iex --start 2017-01-01 --end 2026-11-05 --offline
uv run --locked python -m quant_research.cli data-audit --source alpaca --feed iex --start 2017-01-01 --end 2026-11-05
```

每个命令支持 `--help`。P1 共同参数：`--db`、`--data-dir`、`--output`、`--sources-config`、`--offline`、`--refresh`。source 配置中的限速参数实际应用；enabled/status 是部署状态记录，不是 CLI 调用的权限开关。数据源由显式子命令选择。

成功 exit 0；参数校验 exit 2；来源或解析失败 exit 3；价格覆盖有缺口 exit 4。失败也写 manifest，已经完成的月份和原始页保留供重启。`data-audit` 的审计执行成功不表示数据达到研究级。

`--refresh` 明确重新下载一个新观测，保留旧对象与抓取收据。默认优先复用相同查询的缓存；更新 end 日期会请求新的未缓存范围。按月分页、按主键入库可增量重启。`--repair-gaps` 在联网模式对缺失交易日各重试一次；无法获得的日期仍列为缺口，不填价格。

`data-audit --asof YYYY-MM-DD` 使用该交易日信号时间作截止；真实历史行情今天才首次抓取时，不会出现在过去 asof 视图。默认审计截止为当前 UTC。结束日需是已结束且数据足够完整的区间，本次示例截止 2026-11-05。

## 存储与版本

- `data/raw/objects/<sha256>`：原始响应字节，内容寻址，读取时校验哈希。
- `data/raw/requests/<request_key>.json`：查询参数、最新对象引用、抓取时间；不保存 API 请求头、密钥或联系邮箱。
- `data/raw/receipts/*.json`：每次成功抓取的不可变收据；`--refresh` 不删除旧对象。
- `data/research.duckdb`：规范化数据、版本、观测记录和 runs。
- `data/silver/<source>/<feed>/*.parquet`：原始价的最新已观测版本导出；French 单独存放。
- `outputs/ingestion/<run_id>/manifest.json`：状态、数据/参数/代码哈希、版本、计数；`run.log` 为 UTC。
- 价格管道及审计另有 `audit.json`、`audit.html`。原始异常不静默删除。

`prices_daily` 保存每个响应版本；`price_observations` 保留该版本再次被观察到的时间。因此能处理“修订后又恢复原值”。as-of 查询先按观测时间过滤，再选择当时最近的版本，不能先取最新再回填过去。离线重放相同 raw 和抓取时间不会重复插入。

当前为单写进程，DuckDB 文件锁防止并发写同一数据库。SEC 客户端在同进程跨实例统一限速，默认不到 5 req/s；总请求限制还包含用户其他进程/机器，运行时需避免并行 SEC 抓取任务。单次重试最多四次，429/5xx 指数退避，超过 60 秒的 Retry-After 停止而非持续阻塞。

## 来源约束

Alpaca 请求显式指定 raw、feed、asof='-'、分页，禁用默认当代代码映射。IEX 是单交易所来源，不是全市场成交量，不能据此验证容量或官方开盘可成交价。尚未实现稳定证券 ID/改名/退市映射，因此仅使用 SYMBOL-UNVERIFIED 身份并固定探索性、存活偏差和不完整标签。

真实价格的 available_at/ingested_at 使用首次抓取观测时间；不把历史日期假定为已知时间。P0 合成数据的历史可用时间仍明确为 synthetic。

French 百分比以 Decimal 转成十进制；-99.99/-999 标为 null；每份下载保留版本，严格 ATTRIBUTION_ONLY。当前文件不是历史 vintage，不用于历史当日决策；不得混淆 FF5 的 SMB 与 FF3 的 SMB。

SEC submissions 仅提取 recent 数组，保留 accepted_at 和当前 available_at；未拉取全部历史分片。companyfacts 只存当前原始快照，不填 fundamentals_pit。不能将这些聚合事实当作完整历史 PIT。

corporate_actions 现保存 947 条 Yahoo 事件，公布时间未知、现金金额口径未核验；universe_daily、fundamentals_pit 仍为空，不填入伪造记录。特征、标签、模型、回测和成交表在 P2–P6 实施。

Yahoo 使用按证券整段历史请求（不是 Alpaca 的按月方式），保存原始 chart JSON。OHLC 为 yahoo_split_adjusted，另有 adj_close；事件和原始价口径没有核验到可以仿真成交的程度。保持 EXPLORATORY / DATA_INCOMPLETE / NOT_READY，raw_execution_prices_available=false。原始响应缓存位于 raw/objects，查询和抓取收据位于 raw/yahoo/requests 与 receipts；yfinance 自身的内部会话缓存仅是辅助，不用于离线重放。

## 官方参考（2026-11-06 核验）

- [Alpaca 数据方案](https://docs.alpaca.markets/us/docs/about-market-data-api)
- [Alpaca bars 参数、分页和复权](https://docs.alpaca.markets/us/reference/stockbars)
- [French 数据库及历史格式变化](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html)
- [SEC API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [SEC Fair Access](https://www.sec.gov/about/developer-resources)
