# QDR L1 市场预测新版界面 · Codex 数据接入契约

版本：`qdr.l1.market.v1`。本阶段是前端交付。**不包含真实预测和真实数据接入**，不要将缺失值渲染为 0 或假概率。

## 1. 路由与使用位置

现有 `/#market`（`/studio#market`）保留。先加载 `v4_ui_core.js`、`v4_ui_pages_a/b/c.js`、`v4_ui_fidelity.js`，**最后**加载 `v4_ui_market_v2.js`（覆盖 `pages.market`，不影响 L2/L3/L4）。同时加载 CSS `v4_ui_market_v2.css`，服务端资产白名单放行两文件。

## 2. 数据请求

已有旧端点：`GET /api/v1/v4/freshness`、`GET /api/status`、`GET /api/v1/market/research?horizon=3`。旧历史研究端点仅用于标记为历史的验证结果，**不可作为当前预测**。

已实现的端点：`GET /api/v1/l1/market/overview?horizon=1|3|5`（附加可选 asof）、`/api/v1/l1/observations`、`/api/v1/l1/anomalies`、`/api/v1/l1/validation`、`/api/v1/l1/replay`。无研究归档返回 409；有可信度分级的历史观察数据时返回 `OBSERVATION_ONLY`，不填假概率；只有真实冻结数据才返回研究级 forecast。不得使用 L3 个股预测替代 L1。

### 成功响应示例（结构样板；非预测示例数据）

```json
{
  "schema": "qdr.l1.market.v1",
  "status": "FROZEN_FORWARD_RESEARCH_ONLY",
  "asof_session": "YYYY-MM-DD",
  "knowledge_cutoff_utc": "ISO-8601 timestamp",
  "entry_at_utc": "ISO-8601 timestamp",
  "frozen_at_utc": "ISO-8601 timestamp",
  "source_snapshot_sha256": "64 lowercase hex characters",
  "model_version": "nonempty immutable model version",
  "forecast": {
    "horizon": 3,
    "expected_return": null,
    "p_up": null,
    "p_downside": null,
    "quantiles": [null, null, null, null, null],
    "first_passage": null
  },
  "domains": [],
  "drivers": []
}
```

上面是字段说明样板，**并不是合格预测响应**（null 不能展示），只在全部强校验通过时显示预测。

预测成功时：`forecast.quantiles` 固定为收益分布 `[q10, q25, q50, q75, q90]`，小数收益率而非百分号字符串；`expected_return` 同一交易窗口的预期总收益；`p_up` 和 `p_downside` 为 [0,1] 概率，明确下跌事件阈值及是否已校准（应追加到响应证据字段）；`first_passage = {up_first,down_first,neither,up_threshold,down_threshold}`，三事件互斥、穷尽、概率和为 1。首触事件若日线同日无法确定先后，必须按研究协议标记未知，不应强行分配标签。

`status` 仅 `FROZEN_FORWARD_RESEARCH_ONLY` 或 `MODEL_OOS_ADMITTED` 可进入预测绘制逻辑；后者必须在后端有独立验收证明。`asof_session` 必须与最新完成交易日一致，预测冻结在正确时段；data digest、model version、timestamps 缺失时前端不展示预测。

`domains` 为 12 个维度观测，`{id,status,value,unit,label,precision,source_available_at,coverage}`，其中 `status` 为 `OBSERVED | PARTIAL | MISSING | BLOCKED | STALE`。只有 OBSERVED 并具备有效数字时显示数据；PARTIAL 展示覆盖缺口而不伪造完整结论。允许整个维度没有数据。

`drivers` 为 `{label,value,unit,status,delta,oos_increment}` 数组；`oos_increment` 缺失时只能称为观测变化，**不能将其称为预测驱动**。建议后端补充基准模型、特征分组消融、分期指标和不确定性。

12 维 ID：`price, breadth, volatility, options_pricing, options_positioning, microstructure, correlation, cross_asset, positioning, events, funding, path`。

## 3. 正式接入还需补充的字段与保障

- 特征合法性：每条观测和预测输入要有来源、可得时间、当时有效证券身份、公司行为处理，和覆盖分母。
- 历史权益池：PIT 退市/上市/停牌信息不可使用当下幸存股票反推历史广度；ETF 广度必须明确标记代理。
- 模型可信性：训练区间、校准区间、测试区间、模型摘要、预测事件定义、基准误差、CI、校准状态及未见样本数。
- 收益预测一致性：跨期限同一输入时点，分位单调；路径事件和分布估计来自一致的研究协议。
- 数据频率：日频版不能生成实时订单簿/GEX/交易商仓位的准确结论，未接供应商时 MISSING。
- 准入等级：OBSERVATION_ONLY, EXPLORATORY, FROZEN_FORWARD_RESEARCH_ONLY, MODEL_OOS_ADMITTED，绝不能在界面上把历史回溯说成今日模型。
- API 安全：未知字段不渲染为 HTML；前端转义所有 provider 字符串。后端验证数值、时点、schema 和鉴权。

## 4. 前端交互验收

- H1/H3/H5 切换时请求对应期限数据，不能共享旧期限概率。
- 12 维筛选（全部、内部结构、风险、衍生品、流动性、事件、价格）可用。
- 日期错位、来源过期、模型未批准、概率不一致时预测区域显示真实空态。
- 历史 Brier 只有完整真实回溯报告时显示，显著标注历史。
- 旧四层导航、旧高级工具、数据中心保留。
- 移动视口布局不溢出，数值/标签可读。
- 无 JavaScript 异常及 `Math.random` / 演示概率。

## 5. 完成状态

前端源文件、样式和离线预览已完成。后端只读端点、离线研究引擎和实际 T 日冻结的研究接口已写好，均提供严格空态和研究资格标记。**真实供应商数据、历史 PIT 独立证明及真实样本外模型验收仍未完成，交由 Codex 做数据接入和本地实证**。新端点在缺少本地归档时返回结构化 409；有研究归档但没有真正冻结预测时，可返回 `OBSERVATION_ONLY` 和 12 维观测数据，`forecast=null`。本次不声称 H1/H3/H5 已具备实盘预测能力。新增接口细节见 `docs/L1_CODEX_DATA_HANDOFF.md`。
