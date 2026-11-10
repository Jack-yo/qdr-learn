# G4.9 每日观察与前向组合准入

每日信号页可从已冻结的 SIP 记录生成报告，按美东日期查阅，下载 HTML、CSV 和 JSON。后台读取并核验同一个真实快照，保存抓取截止、冻结时点、来源哈希和运行时间。归档报告保留原交易日。默认生成使用最近已就绪的 XNYS 交易日，缺少该日冻结记录时返回阻断。

## 实际日报

网页后台任务生成 `429222a3-0fcc-48d3-a3ae-192e5d4fee25`，退出 0。美东 **2026-11-06** 的 20 条 SIP raw 日线来自同一开盘前冻结记录。SPY 在供应商同一根日线内的开收变化约 **+0.064%**，名单内 ETF 16 上行、4 下行。变化按该根日线的收盘价除以开盘价减一，统计范围为当前显式 ETF 观察名单。

French 风格报告在冻结时点的知识截止下读取 8 个序列。源数据最近日期为 **2026-09-30**，作为独立观察与归因展示。本次候选状态为 `BLOCKED_NO_ELIGIBLE_MODEL`。

验证包括真实后台任务、报告及三类文件读取、缺失日期 HTTP 409、非法日期 HTTP 400、无写入令牌 HTTP 403。日志和接口证据保存在 `outputs/daily_observations/http-acceptance.json`。

全套回归 **111 通过、1 跳过**，耗时 200.19 秒。跳过项为 Yahoo SPY 的 2026-11-06 缓存缺 OHLCV。最后收紧报告读取及台账规则后的专项回归 **15 通过**，与全套重叠。JUnit 文件为 `outputs/daily_observations/tests.xml` 和 `final-focused-tests.xml`。JavaScript 通过语法检查。

## 前向组合

模拟组合页只读显示实际归档的开盘前观察，核验并展示最近最多 20 个记录，实际已有 **1 个交易日**。缺失日期检查仅覆盖展示区间首尾之间的 XNYS 交易日。一日记录无法验收跨日连续性。

模拟账户状态仍为 BLOCKED。现金、净值、持仓、成交均为 N/A。实测 `paper-step` 退出 4，缺前向股票池、已验收身份与公司行为、冻结合格模型及实际入场前决策。验证用账本路径未创建。API 只读取行情归档，不打开账户 SQLite。2025 起的最终策略测试保持封存。

## 复现与维护

```powershell
.\scripts\start_console.ps1 --port 8766
# 日常行情更新并冻结后，生成最近就绪交易日。
.\.venv\Scripts\python.exe -m quant_research.cli daily-observation
# 从已有真实冻结记录重建指定归档日报。
.\.venv\Scripts\python.exe -m quant_research.cli daily-observation --asof 2026-11-06
.\.venv\Scripts\python.exe -m quant_research.cli paper-status
.\.venv\Scripts\python.exe -m quant_research.cli data-catalog
.\.venv\Scripts\python.exe -m pytest -q -rs --junitxml=outputs/daily_observations/tests.xml
```

使用 `/signals` 生成与查阅日报，使用 `/paper` 看前向证据和账户缺项。结果在 `outputs/daily_observations/<run_id>/`，台账共 14 类。备份同时保留日报、`data/managed/close_snapshots/observations.sqlite3`、French 因子库和各自原文与回执。重建日报只增加报告运行记录，观察天数按冻结归档交易日计算。未注册自动运行任务。

## 实际改动

- `workflow/daily_observation.py` 与 `data/close_snapshot.py` 提供准确的 XNYS 日期、日报生成及哈希复核。
- `workflow/forward_observations.py` 与 `workflow/daily.py` 提供观察归档读取及模拟入口拒绝。
- `daily_observation.html`、`web.py`、`cli.py`、`data/catalog.py` 接入正常页面、查询、命令和分类。
- `tests/test_daily_observation.py`、`tests/test_forward_observations.py`、`tests/test_web.py` 覆盖真实归档重放、证据篡改、缺失状态、禁用账户及本机 API。

浏览器视觉验收尚未执行。剩余主干为备份恢复演练、运行调度验证和积累真实前向观察。正式个股模型、严格回测及模拟成交仍受历史时点、身份和结算证据阻断。
