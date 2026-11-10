# G4.7 开盘前观察与历史时间覆盖验收

系统可以冻结一批实际看到的 SIP 原始日线，并为后续研究保留本机何时看到该版本的证据。每个交易日只写入一次。重复运行重新核验快照、源原文和抓取回执，返回原记录。正式历史模型、回测和前向账本仍各自受准入控制。

## 实际观察

首批是美东 2026-11-06 的 20 只 ETF。快照于北京时间 **2026-11-09 11:22:45** 写入，下一开盘是当日 **22:30:00**。源原文及回执逐行核验通过，数据的精确时点保留 UTC。快照摘要为 `ace60bfc9496b72282a22cdd02b31d2c10354f81a40c5328b59b4a28746f8405`。

写入窗口从 XNYS 收盘后 20 分钟到下一开盘之前，处理假日和提前收盘。采用此间隔是为了给延迟 SIP 历史接口留出时间。Alpaca 说明其无实时权限的历史 SIP 查询的结束参数需至少早于当前时间 15 分钟。[Alpaca Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)

入库前核验行情实际回执时间与所选版本一一对应，并要求行情事件时间 ≤ 首次观测时间 ≤ 入库记录时间 ≤ 数据截止。快照另存本次核验开始、冻结和下一开盘时间。供应商发布时间仍为空。证券身份状态为 UNVERIFIED，决策资格为 false。

## 历史数据阻断

对 2017-01-03 至 2024-12-31 的 20 ETF 所选 SIP 版本完成逐行核验。**40,240 行、96 份源响应**。固定收盘后信号时间前有回执的行数为 **0**，下一开盘前有回执的行数为 **0**。40,240 行均只有未核验的临时代码身份。统计限于所选本地版本。

日期与报表证据在 `outputs/close_snapshots/historical-audit/af43083c-4c7f-4de0-a6cb-a932535c4982/`，逐标的可查 `timing_coverage.csv`。Nasdaq 与 Alpaca 核验的 FB→META 是已有独立案例，覆盖一次换码，无法支持当前 20 ETF 的历史身份连续性。SEC 的 SPY 原申报可作为特定时期的代码与份额身份线索，仍需原文与回执核验，以及能覆盖所需日期的身份映射。[SEC 2018 SPY 申报](https://www.sec.gov/Archives/edgar/data/884394/000119312518014611/d469252d497.htm) · [SEC 2024 SPY 申报](https://www.sec.gov/Archives/edgar/data/884394/000119312524016958/d109104d497.htm)

本机通过 SEC 公开原稿路径实测下载这两份申报，均返回 `DATA_SOURCE_BLOCKED`，没有可入库的原文字节或抓取回执。历史身份门槛继续阻断。下一步优先获取有真实来源的历史版本及有效期身份映射，同时在实际交易日积累开盘前观察。

## 运行与维护

```powershell
# 在开盘前窗口内先运行现有日常更新，再冻结。
.\scripts\maintain_data.ps1 --env-file .env
.\.venv\Scripts\python.exe -m quant_research.cli close-snapshot
.\.venv\Scripts\python.exe -m quant_research.cli data-catalog

# 查看已有指定日期记录。若该日已过窗口且从未记录，退出 4。
.\.venv\Scripts\python.exe -m quant_research.cli close-snapshot --asof 2026-11-06

# 复核开发期的真实版本时点。
.\.venv\Scripts\python.exe -m quant_research.cli bundle-audit --source alpaca --db data/real_v21.duckdb --asof 2024-12-31 --output outputs/close_snapshots/historical-audit

.\.venv\Scripts\python.exe -m pytest -q -rs --junitxml=outputs/close_snapshots/final-tests.xml
```

网页 `/data` 提供冻结操作和最近快照链接。`GET /api/v1/data/close-snapshots?asof=2026-11-06` 可按美东交易日读取。已实测启动 HTTP 202、任务退出 0、重放同一哈希，缺失日期 HTTP 409、非法日期 HTTP 400。实际记录见 `outputs/close_snapshots/http-acceptance.json`。浏览器视觉验收未执行。

分类台账增为 12 类。日常备份保留 `data/managed/close_snapshots/observations.sqlite3` 和对应 `data/raw` 原文及回执。SQLite 按交易日主键追加，读取核验快照哈希。禁止补写已过开盘的未记录日期。实际观察天数目前为 1。

最终全套回归 **102 通过、1 跳过**，耗时 163.05 秒。跳过项为 2026-11-06 的 Yahoo SPY 缓存缺 OHLCV。首轮回归发现代理特征价格传入原价核验时错误类型不正确，修复校验顺序后，恢复了结构化拒绝并通过全套复测。

## 修改文件

- `src/quant_research/data/close_snapshot.py`、`data/bundle.py`、`data/catalog.py` 实现快照、精确回执校验与分类。
- `src/quant_research/workflow/bundle_audit.py` 增加可用时间与临时代码覆盖报告。
- `src/quant_research/cli.py`、`web.py`、`web.html` 接入命令、任务及查询。
- `tests/test_close_snapshot.py`、`tests/test_web.py` 验证真实快照时点、哈希、过期拒绝、重放、精确回执和接口错误。
