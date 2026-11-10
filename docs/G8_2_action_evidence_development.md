# G8.2 公司行为事件来源与历史身份审计（只读增量）

## 本次交付

- 新增 `quant_research/data/action_audit.py`，仅读取本地已有的 G2 / 日常维护 / 研究 DuckDB 公司行为 **版本表**，不创建真实行情、交易、PIT 股票池、历史身份或公司行为结算记录。
- 对每条实际返回的公司行为版本，核对 `corporate_event_versions` 关系字段与 `record_json`、保存的 Alpaca 原始响应字节 SHA256、事件 ID/类型/原文内容、来源 URL、真实抓取时间，以及不可变抓取回执的参数和请求哈希。
- 仅包含单个 API 响应的来源核对不证明全历史分页或无事件；出现分页指针明确标注 `SOURCE_PAGE_CHAIN_UNPROVEN`；如回执或源文件缺失，则状态为 `BLOCKED_SOURCE_EVIDENCE`。
- 支持按 **实际可用 UTC 时点** 筛选：事件响应晚于指定时点时不进入结果。事件 `ex_date` 或 `process_date` 不能被当作历史新闻发布时间。
- 若 G7/G8 实际资产快照存在，可显示查询时点的来源资产 UUID 映射；不能证明历史发行人、法定 share class 或当时股票池资格。
- CLI 新增 `action-evidence`，Web 新增只读 `GET /api/v1/data/actions/audit`，数据页新增公司行为与身份来源的查看/筛选。
- 不修改 `capability_checks.py` 准入门槛，不写 `PIT_VERIFIED`，不更新当前模型、回测或前向模拟资格。

## 体验方式

在拥有真实 `data/g2_evidence.duckdb` 或 `data/real_v21.duckdb` 与 `data/raw/{objects,receipts}` 的本地项目中：

```powershell
.\.venv\Scripts\python.exe -m quant_research.cli action-evidence --symbol AAPL --database all --limit 30
.\.venv\Scripts\python.exe -m quant_research.cli action-evidence --asof 2026-11-10T20:00:00Z --limit 10
.\scripts\start_console.ps1 --port 8766
```

访问 `/data` →「公司行为与历史身份证据」。纯 GET，不需要在页面输入 API 密钥，也不触发交易。无真实归档时 CLI 返回 `NO_CORPORATE_EVENT_ARCHIVE`（退出码 4），HTTP 返回 409，不补假事件。

## 测试范围与剩余限制

- 本地：G8.2、G8.1 和 G7 相关 **25 passed, 2 skipped**；跳过因为无真实 G7 快照。新增真实公司行为正向集成测试也会在没有真实 G2 数据库时跳过；以新一轮运行结果为准。
- Python `compileall`、JS `node --check`、CLI 参数帮助检查通过。本环境没有 DuckDB 运行依赖和用户真实行情库，无法验证真事件来源正向读取、数据库联查及完整 Web 浏览器回归。
- 来源响应 SHA256 + 本地回执匹配只证明本地归档的一致性，供应商数据未提供不可伪造的外部数字签名；不等于正式公布时间、全分页无遗漏或事件现金权益结果。
- **G8.2 全量目标仍未完成**：按期间与证券的完整事件覆盖、退市/改名跨证券身份、发行人原稿发布时间、分红权益/支付/碎股对账、独立数据来源交叉验证等仍须补真实数据及端到端验收。
- 后续合理任务：补充历史公司行为全分页的请求链核验，才可能对特定区间形成来源覆盖声明；再与 PIT 证券主数据及现金结算独立联验。不得以这一只读审计器直接解除严格回测或 Paper 资格。
