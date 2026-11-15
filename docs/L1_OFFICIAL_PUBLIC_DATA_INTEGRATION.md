# L1 官方公开数据扩充 · 按需独立加载

更新：2026-11-15。此交付采用“官方来源独立请求 → 有限缓存 → 12 维证据区”模式，不改变 E01/E02/E03 模型、预测分数或既有 Alpaca 扫描。

## 新增的只读接口

- `GET /api/v1/l1/v2/official`
- `GET /api/v1/l1/v2/official?refresh=1` 强制绕过官方数据原始缓存，仍受前端 GET 暂存约束。

响应 `schema=qdr.l1.official.v1`，字段含 `asof_session`、`features`、`source_health`、`status`、`historical_pit_verified=false`、`not_in_model_scores=true`。数据源独立报错，单源失败不阻塞其他源或整个工作区。无观测返回 `NO_AVAILABLE_PUBLIC_FEED`，不是 0 或假数据。

## 新增官方来源

| 来源 | 官方地址 | 按需数据与口径 | 维度 |
| --- | --- | --- | --- |
| 美国财政部 | https://home.treasury.gov/treasury-daily-interest-rate-xml-feed | 当月每日 2Y、10Y 收益率与 10Y−2Y 期限利差（% / bps） | 跨资产 |
| 纽约联储 | https://markets.newyorkfed.org/static/docs/markets-api.html | SOFR、EFFR 的最近 10 条公布值及同日利差（% / bps） | 融资条件 |
| CFTC TFF futures-only | https://publicreporting.cftc.gov/resource/gpe5-46if.json | **仅** E-mini S&P 500，CFTC 合约代码 13874A，杠杆基金 (long − short) / OI，周频，星期二持仓，星期五发布 | 持仓拥挤 |

以上接口不需要新 FRED Key；但用户仍须遵守提供方条款和限流。旧 FRED 信用利差、Cboe VIX 与 Alpaca ETF 接口不受影响。

## 使用边界

- **这些观测不会直接进入当前上涨动能/卖压/衰减模型**。目前依然由已实现的 ETF 价格和实现波动构成；来源数据只有取得真实样本外增量后才可纳入预测模型。
- 最新公开数据不等于历史 PIT。返回 `fetched_at` 与 `observed_date`，不推断“该数值在历史决策时点已可获知”。
- CFTC 数据是单一金融期货市场的杠杆基金持仓净额，不是整个市场交易商 Gamma，也不是 ETF 实际资金净申赎。星期五保守按 22:00 UTC 之后才允许显示当周星期二的报告；遇节假日延期只能依赖实际源响应，无法提前假定已发布。
- 纽约联储、财政部最近有效日期超 7 个日历日返回 `STALE_OBSERVATION`；CFTC 超 21 日返回过期，均不倒填最新日期。
- 新增数据走原有 `BoundedCache`：原始响应 32 MB 总上限、32 条上限，财政部 TTL 6 小时、纽约联储 1 小时、CFTC 4 小时。没有建设全市场长期历史数据库。
- API 抓取失败代码在 `source_health` 可见（例如 HTTP_403、HTTP_429、PROVIDER_UNAVAILABLE、TREASURY_INVALID_XML、CFTC_TARGET_CONTRACT_MISSING）。前端无权限不会隐藏已有 Alpaca 数据。

## 尚未接入 / 没有宣称完成

完整 Cboe Put/Call 日频自动化、OFR FSI 可验证的官方下载地址、全部市场股票广度、深度订单簿、期权交易商 Gamma、真实 ETF 申赎、宏观事件发布时间：当前**未接通**。尽管页面有 12 维，这不是 12 维完全覆盖。

## 验证口径

- 新增 `tests/test_l1_official_sources.py` 使用离线构造的官方协议响应测试解析、单位、保守 CFTC 发布时点、数据独立失败及缓存限制。
- 更新 `tests/test_l1_information_architecture.py`：主扫描 + 新官方扫描是两条**独立**请求，未展开的 E01/E02/E03 仍不发起。
- 开发环境若无法访问官方域名，**不可声称实际在线联调成功**。请在用户本机运行 `pytest tests/test_l1_official_sources.py tests/test_l1_information_architecture.py -q` 并在系统 Network 检查 `/api/v1/l1/v2/official` 的 `source_health`；需要现场网络/权限验收。

## 继续演进

下一批优先补 Cboe 期权成交统计、OFR FSI 稳定下载、CFTC 更多相关市场，但必须为每个来源保留身份、发布时间、时效和数值校验，不能把“接口已有”误称为“实测已拿到”。
