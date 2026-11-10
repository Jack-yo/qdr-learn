# P1 Yahoo 替代来源验收 — 2026-11-06

**用户已授权采用 Yahoo/yfinance 替代来源。P1 的探索性行情覆盖、缓存重放与幂等验收通过。原 Alpaca 专项验收仍未完成；数据不属于 RESEARCH_GRADE，也不具备原始价格成交仿真资格。未开始 P2。**

## DONE

新增 YahooProvider，通过 yfinance 0.2.66 取得 Yahoo chart 响应；仅保存原始 chart 字节和不含 cookie/crumb/请求头的查询元信息。显式关闭 auto_adjust、back_adjust、repair，原始响应直接规范化，不将 yfinance 处理后的 DataFrame 冒充原始响应。

OHLC 保守标记 `yahoo_split_adjusted`，另存 `adj_close`。没有因 auto_adjust=False 就将 Yahoo OHLC 标为 raw。企业行为保留当前提供的 split/dividend 值，announced_at=null、available_at=本次首次观测；现金金额口径仍需核验，不自动用于现金记账。

DuckDB schema 版本 2 增加 adj_close、企业行为质量标识及币种。已有 500 行 fixture、148,212 条 French 因子、4 份 SEC 快照和 2,010 条申报均保留，未覆盖旧数据。

## TESTS

最终实测：**71 passed in 13.93s，无 warning**。

```powershell
.\.venv\Scripts\uv.exe sync --locked --cache-dir .uv-cache
.\.venv\Scripts\uv.exe run --offline --locked --cache-dir .uv-cache pytest -q --junitxml=outputs/p1-yahoo-pytest.xml

# 真实拉取；默认是此前约定的 20 个 ETF
.\.venv\Scripts\python.exe -m quant_research.cli ingest --source yahoo --start 2017-01-01 --end 2026-11-05

# 完全从项目缓存重放；同一请求应新增 0 条价格与企业行为
.\.venv\Scripts\python.exe -m quant_research.cli ingest --source yahoo --start 2017-01-01 --end 2026-11-05 --offline
.\.venv\Scripts\python.exe -m quant_research.cli data-audit --source yahoo --start 2017-01-01 --end 2026-11-05 --offline
.\.venv\Scripts\python.exe -m quant_research.cli demo --fixture
```

本次真实缓存重放还将 socket.socket.connect 与 socket.create_connection 改为立即抛错后调用 CLI，成功 exit 0。没有依赖 yfinance 自身联网缓存。

新增测试覆盖：Yahoo OHLC 与 Adj Close 分离、非 raw 成交阻断、未来数据不可回填、企业行为事件/未知公布时间、USD/日频/交易所时区核验、数组对齐、缺失价格和重复时间拒绝、哈希损坏拒绝、离线缺缓存失败、重试、刷新保留旧原始响应、CLI 和 Parquet 往返、价格及企业行为幂等。首轮 SyntaxWarning 已修正，最终未屏蔽 warning。

## DATA / RESULTS

| 项目 | 实际结果 |
|---|---:|
| 证券数量 | 20 |
| 实际交易日区间 | 2017-01-03 — 2026-11-05 |
| 每证券交易日数 | 2,475 |
| 价格记录 | 49,500 |
| Adj Close 非空记录 | 49,500 |
| 预期证券/交易日缺口 | 0 |
| 分红事件 | 939 |
| 拆股事件 | 8 |
| 离线重放新增价格/事件 | 0 / 0 |
| 已实现审计规则报出的异常 | 0 |

证券：SPY、RSP、IWM、IWD、IWF、MTUM、QUAL、USMV、HYG、LQD、XLK、XLF、XLE、XLV、XLI、XLP、XLY、XLU、XLB、XLRE。

本次“无异常”仅指已实现的日历/契约校验、零成交量及相邻收盘变动超过 40% 检查；没有完成跨供应商或逐项企业行为核对，不能解读为供应商数据已全面认证。

最终数据引用哈希（整个仓库来源版本和观测时间）：`ce9f869edea112e38d930aacb09072a605cfa3fe31e4dc96fb7a6c34ac9ce92b`。真实拉取与禁网重放该哈希一致。原始对象读取逐个验证 SHA-256。

产物：

- 真实下载：`outputs/ingestion/56b1fc08-ef98-400f-a0e1-a3e5fe63c0e7/manifest.json`
- 禁网重放：`outputs/ingestion/c04ad4c2-d145-468b-b04c-0a9f1de6425a/manifest.json`
- 审计 JSON/HTML：`outputs/ingestion/6744b2e6-2a69-4529-bea7-4dc0a9353eca/audit.json`、`audit.html`
- 断言验证摘要：`outputs/p1_yahoo_verification.json`
- pytest XML：`outputs/p1-yahoo-pytest.xml`
- Parquet：`data/silver/yahoo/yahoo/f5040b4e4f96df802cf33eef555f75d4a310243ceb8c7984aa42806640193ff6.parquet`
- 数据库：`data/research.duckdb`
- P0 demo：`outputs/experiments/4cd2878a-a49d-4f62-aea1-9a818c693a4a/report.json`

## RISKS

- `raw_execution_prices_available=false`、`research_grade=false`。Yahoo 价格不是经核验的历史原始可成交价，不用于真实或模拟成交；原有 require_entry 对该复权口径拒绝。
- 当前下载版本不是历史 PIT 快照。available_at 按首次观测保存，历史 as-of 不会因日线日期被回填；Adj Close 也不是当时已知的绝对价格。
- 股票池是今天选定的 ETF 列表，仍标记 EXPLORATORY / SURVIVORSHIP_BIASED / DATA_INCOMPLETE / NOT_READY。
- 公司行为未核验完整性、历史名义现金金额和拆股调整口径；没有由事件反推并伪造 raw OHLC。未取得退市、稳定证券 ID、历史股票池、全量 PIT 财务、成交价差或冲击成本证据。
- Yahoo 按证券整段请求，避免把不同日期抓取的拆股重写口径拼成一条声称 raw 的历史。默认优先复用项目缓存，更新 end 日期或显式 --refresh 才下载新的来源版本。
- 原 Alpaca 直接接口与连接器长历史验收仍未通过。替代来源通过不等于这些缺口已经消失。
- 没有计算策略收益、预测准确率或投资建议，远端 CI 未执行。

## NEXT

可在探索性范围开始 P2 的 Factor 接口、因子公式、窗口/缺失规则及单因子研究框架；先冻结实验规格。历史标签须显式说明价格口径，不能把 Yahoo split-adjusted 开收盘宣称为原始价成交收益。严格成交回测和 PIT 决策继续受上述数据缺口阻断，不得为推进阶段放松原交易协议。

## 文件清单

- 新增：`src/quant_research/data/providers/yahoo.py`、`tests/unit/test_yahoo.py`、`tests/integration/test_yahoo_pipeline.py`、本验收文档。
- 修改：`src/quant_research/data/schema.py`、`store.py`、`pipeline.py`、`quality.py`、`src/quant_research/cli.py`。
- 更新依赖/配置：`pyproject.toml`、`uv.lock`、`configs/sources.yaml`。
- 同步：README、AGENTS、架构、数据字典、数据限制、里程碑、决策与 P1 管道文档；原 P1 首次验收记录保留并标注本次更新。

参考：[yfinance download 参数](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)、[yfinance history 实现](https://github.com/ranaroussi/yfinance/blob/main/yfinance/scrapers/history.py)。
