# L1 公开数据源完善 · 本轮交付（2026-11-15）

## 目标与架构

不创建全量历史仓库，沿用已有 `LiveSources.request` 的 URL 白名单、大小和条目数受限的本地缓存（默认最多 32MB / 32 条）、数据回执和失败即缺失机制。原有 `/api/v1/l1/v2/overview` 和第一批 `/api/v1/l1/v2/official` 保持不变；新增独立接口：

```
GET /api/v1/l1/v2/extended
GET /api/v1/l1/v2/extended?refresh=1
```

返回 `schema=qdr.l1.extended.v1`、`asof_session`、`features`、`source_health`、`calendar_events`。各来源并行、独立失败；只有真实数值才作为 `OBSERVED`。新增值仅作为当日数据证据，不直接进入市场涨跌概率、E01/E02/E03 或三项综合评分。

## 新增数据源

| 任务键 | 原始源 | 真实观测及维度 | 缓存 |
|---|---|---|---|
| cboe_options | Cboe Daily Options JSON `https://cdn.cboe.com/data/us/options/market_statistics/daily/YYYY-MM-DD_daily_options` | 全市场/指数/个股/ETF 期权成交 Put/Call；SPX 系列汇总 OI Put/Call，分别入期权定价与期权持仓 | 2h |
| ofr_fsi | `https://www.financialresearch.gov/financial-stress-index/data/fsi.csv` | OFR 综合金融压力指数（指数点，约滞后两个工作日） | 6h |
| bls_calendar | `https://www.bls.gov/schedule/news_release/bls.ics` | 未来 7 日已排程 BLS 数据发布数量及未来 14 日精确 UTC 日程 | 4h |
| cftc_nasdaq | CFTC TFF Futures-only `gpe5-46if` | Nasdaq-100 期货杠杆基金净仓 / OI | 4h |
| cftc_gold、cftc_wti | CFTC Disaggregated Futures-only `72hh-3qpy` | 黄金、WTI 管理资金净仓 / OI | 4h |
| cboe_equity_volume | Cboe consolidated historical market volume `market_history_YYYY.csv` | 美国市场 TRF 场外报告成交金额占比（非方向性订单流） | 6h |
| stock_sample | Alpaca 30 只指定流动性较高股票、按需近 55 日行情 | 固定样本上涨占比、MA20 上方占比、20 日新高/低家数 | 15m |

官方来源文档：
- Cboe Options: https://www.cboe.com/markets/us/options/market-statistics/daily
- OFR FSI: https://www.financialresearch.gov/financial-stress-index/
- BLS: https://www.bls.gov/schedule/news_release/bls.ics
- CFTC: https://publicreporting.cftc.gov/resource/gpe5-46if.json 和 https://publicreporting.cftc.gov/resource/72hh-3qpy.json
- Cboe equity volume: https://www.cboe.com/markets/us/equities/market-statistics/historical-market-volume/

## 数据资格与解释

- 每条数据携带 `source`、`observed_date`、`fetched_at`、`pit` 和单位。当前公网下载不是历史 PIT 有效性证明；回放/模型训练不得用当前版本结果倒填历史。
- Cboe 成交 PCR 以官方 Volume 的 put/call 比率复核并设允许四舍五入误差；无成交时不能显示 0 PCR。SPX 汇总 OI 不等于真实 dealer gamma。
- OFR FSI 属于统计构建的压力指数，不是单项信用/融资利差；OFR 官方说明约晚两个工作日，不标为最新秒级市场数据。
- CFTC 合约持仓为周二观察、通常周五发布（节假日可能延期）。采用保守周五 22:00 UTC 之后才能展示当周周二结果，不允许提前看未来。持仓快照不等于交易资金净流入或实时交易意愿。
- Cboe TRF 成交金额占比不是正/负主动订单失衡，不能直接解释为机构买入或卖出。
- 30 只股票样本为人工固定大盘股集合，存在样本偏差及历史成分生存者偏差。仅报告**固定样本广度**，绝不能显示成“全市场真实广度”。
- BLS ICS 是已排程发布日期，不含市场一致预期、实际意外值或未公布事件。读取时使用官方 TZID / UTC，无时区信息的日程不猜测时间。
- 源被封、请求权限不足、文件格式变化、最近观察值超时均返回 `source_health[*].code`，不插值或编数字。
- 本次未新增商业数据授权，未实现在市场层自动交易。

## 前端

L1 同时发起三条独立请求：市场主扫描（原评分和历史研究）、第一批官方源、扩展公开数据。它们在现有 GET 渐进加载缓存下独立完成。已获取数据分入原 12 个维度的可展开证据区；BLS 未来已排程事件按 UTC 显示时间。不改变 L2/L3/L4。

## 测试命令与验收

```bash
python -m pytest tests/test_l1_extended_public.py tests/test_l1_extended_ui.py \
  tests/test_l1_information_architecture.py tests/test_l1_official_ui.py \
  tests/test_l1_official_sources.py -q
```

```
http://127.0.0.1:8766/api/v1/l1/v2/extended
http://127.0.0.1:8766/studio#market
```

在浏览器 Network 查看三条 GET 各自是否 200；在 `source_health` 检查 8 组来源。外部源因网络/WAF/权限可能仍不可用，因此必须在目标机逐源实际验收，不能将离线模拟测试等同于真实联网成功。

## 仍需要授权或更强历史基础的数据

全美股在某一历史时点的 PIT 股票池、全市场 Level 2 盘口、经证实的真实 dealer 净 Gamma、全部 ETF 一二级市场每日申购赎回、所有宏观共识预期等，均不能用目前公开接口完整还原。对这些维度保留明确的缺失原因。没有引入成本较高的复杂机器学习/动态权重。

## 用户本地使用

使用原有 `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` 只读行情权限即可尝试 30 股样本；其他扩展公共源不需要新密钥。按需下载的 CSV/ICS/JSON 不长期入库，只保存在已有容量受限的 TTL 缓存内。受各官方网站使用条款约束。
