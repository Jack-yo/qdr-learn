# G8.1 · 真实证券目录的前向时点查询与变更观察

## 范围

本次增量建立在 G7 的 Alpaca 只读 `GET /v2/assets` 真实原始响应归档之上，**没有**新增市场数据生成器、批量造数或回填历史证券成分。此次交付不是完整的历史 PIT 股票池。

### 新增能力

- `data/forward_universe.py`：沿 `latest.json → immutable snapshot → previous_snapshot_id` 向前核验完整来源响应与 SHA256 链；拒绝环路、缺失快照、未来时间、逆序观察时点。
- **As-of 查询**：提供明确的 UTC 截止时间，仅选中在该时点或此前已经从真实供应商采集的资产响应；如果早于第一份记录，返回 `NO_ASOF_ASSET_EVIDENCE`，不能用今天的股票列表代替旧数据。标记超过 96 小时未更新的目录为 `STALE_OBSERVATION_ONLY`。
- **来源资产 UUID 映射**：从被选中的实际来源响应解析 ticker 对应的 Alpaca asset UUID；代码复用/重复、inactive、不可交易、过期快照分别给出阻断原因；只允许“观察映射”，不得声称发行人永久身份或已核验的可投资股票池。
- **观察变化**：比较相邻实际来源快照中同一个 UUID 是否修改 symbol/status/tradable/exchange，展示新增出现、不再出现与变化数量。它们**不是**正式上市/退市、更名或公司行为的法律证据。
- Web：`/api/v1/data/universe/asof`、`/history`、`/resolve`，参数严格白名单，重复参数拒绝；数据页新增可视查询及观察证据解释。
- CLI：`universe-asof`、`universe-history`、`universe-resolve`。

### 严格禁止

1. 目录来源的 `class=us_equity` 同时包含 ETF，**无法**证明“纯普通股股票池”；不允许给 `stock_vs_etf_verified` 填 `True`。
2. UUID 是供应商资产标识，不等于全球永久证券身份、CIK、CUSIP 或历史代码变更证明。
3. 历史时点已经过去但当时没有采集证据，不得重建“当年系统真实可知”的列表。
4. 新功能不写入 `universe_daily.PIT_VERIFIED`，不覆盖历史行情的 `SYMBOL-UNVERIFIED:*` 标识，不改变 `capability_checks.assess` 的严格准入、不允许产生模拟成交或实盘交易。
5. 时间戳和哈希是**本地证据一致性检查**，本地 SHA256 不等于供应商密码学签名或完整外部审计证明。

## 本机使用

在本地已配置 Alpaca 凭据后先同步 G7 实际目录：

```powershell
.\.venv\Scripts\python.exe -m quant_research.cli assets-sync --endpoint paper --env-file .env
.\.venv\Scripts\python.exe -m quant_research.cli universe-asof --state candidate --limit 30
.\.venv\Scripts\python.exe -m quant_research.cli universe-resolve --symbols AAPL,MSFT
.\.venv\Scripts\python.exe -m quant_research.cli universe-history --limit 15
```

可以通过 `universe-asof --asof 2026-11-10T20:00:00+00:00` 查询当时已采集的来源观察；并非允许事后在旧时点创建观察。Web 访问 `/data`，使用「前向证券池」模块。首次安装没有任何实际快照时，应返回 `NO_REAL_ASSET_OBSERVATION`。

至少同步两次、在不同实际时点获取 Alpaca 响应，才能看到相邻观察之间的变化。只有一个真实快照时，变化列表合理为空。

## 本次验证

- 本地执行 `PYTHONPATH=. pytest -q tests/test_forward_universe_policy.py tests/test_asset_catalog_readonly.py`：**9 passed，2 skipped**。两个 skip 因本执行环境没有真实 Alpaca asset snapshot。测试没有写入合成市场数据或假资产清单。
- Python 编译和 JavaScript `node --check` 通过。
- **未完成**：有真实账户凭据与资产快照的端到端 API、浏览器交互、长期多快照变化验证；完整仓库回归未执行。

## G8.2 及后续需要的外部证据

- 历史**生效日**的上市/退市、证券更名/代码复用以及发行人证券身份链（独立于当前 Alpaca assets）；真实完整历史可投资股票池，不含幸存者偏差；可证明彼时可获得性的成员变更。
- 股票/ETF/ADR/优先股等历史资产类型区分；行业/SIC/财务的 filing accepted_at 与 available_at。
- 公司行为 API 全分页完备性、拆股/分红/退市现金及头寸对账；不能仅凭某个空事件 API 响应认定历史无行动。
- 只在上述数据的质量、时点、哈希和独立回测准入均满足时才评估正式个股 Alpha；不能通过硬编码 PASS、修改日期或复制用户今天的股票池来“解锁”。