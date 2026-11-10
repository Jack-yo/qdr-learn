# G7 · 真实美股资产目录与前向证券身份观察

## 本次实现

- 使用官方 Alpaca **交易资产目录** `GET /v2/assets?asset_class=us_equity`（默认 paper API；live 可明确选择），只发送 GET，绝不下单或创建账户。只从用户本机环境或可选本地 `.env` 读取凭证，不向页面、日志、Git 提交明文密钥。
- `assets-sync` 将真实 HTTP 响应原文按 SHA256 不可变存入 `data/managed/asset_observations/objects`，将查询参数、API 域名、实际接收时刻、来源哈希、上版 ID 存入不可变 manifest。只有原文和 manifest 都持久化完成才更新 `latest.json`。
- `assets-status` 与 `/api/v1/data/assets` 会再次校验原文、manifest、UUID、唯一代码和原始字节哈希。支持证券代码/名称检索、活跃/非活跃、可交易过滤、分页；同一代码不同资产 ID 保留各自记录并告警，前后两次快照差异只标为「观察到变化」，绝不直接推断已退市、已改名。
- v4 `/data` 交互增加真实目录查询、源状态、检索表格与只读同步入口。同步经本地后端任务锁、Web 同源令牌与命令白名单。无数据时显示明确阻断，不补演示证券。
- 本地灾备允许备份新的资产目录原文与 manifest，并包含 CSS/JS 页面资源，减少恢复时 UI 缺失风险。

## 严格不能宣称的能力

1. 当前 `us_equity` API 包括普通股票、ETF 等证券，**不能直接当成已验证的「纯个股池」**；需要另行确认证券类型、ADR 等分类。
2. API 的 `asset.id` 只是**本次实际观察的供应商资产 UUID**；不等于 CRSP PERMNO、永久发行人身份或历史更名链。
3. 今天获得的目录不能改写过去交易日 `universe_daily.available_at`，不能倒填历史 2017–2024 股票池、退市记录或 survivorship-bias-free 成分。
4. 这些观测不改变 `data/capability_checks.py` 既有的严格历史回测、历史模型或前向成交资格；仍需独立的可观察价格、公司行为、证券身份、时点、冻结模型与决策证据。
5. 未在本执行环境取得真实 Alpaca 凭证及真实库；联机结果只在用户本机执行后方能验收。

## 使用

```powershell
# 如凭证在项目根目录 .env 中：仅发生 GET /v2/assets
.\.venv\Scripts\python.exe -m quant_research.cli assets-sync --endpoint paper --env-file .env
# 本地离线复核，不写入新的观察时点
.\.venv\Scripts\python.exe -m quant_research.cli assets-sync --offline
.\.venv\Scripts\python.exe -m quant_research.cli assets-status --q AAPL --status active --limit 10
.\scripts\start_console.ps1 --port 8766
# 在 /data 页面点击「同步真实资产目录（只读）」，再点击查询
```

## 后续关键依赖

- 累积跨交易日快照，审计供应商资产 ID / 代码变化，对不同来源建立证据映射；不将旧 symbol-only 日线盲目重标历史 ID。
- 获取可核验的 PIT 股票池与退市历史来源，建立有效期和 as-of/available_at 台账，才可以研究历史个股 Alpha 和严格回测。
- 分红、拆股、退市、合并的事件完整性和现金记账应由原始响应、分页全覆盖和结算协议单独验收。

参考（Alpaca 官方）：https://docs.alpaca.markets/us/reference/get-v2-assets-1