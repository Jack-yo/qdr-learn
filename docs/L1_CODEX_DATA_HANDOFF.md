# QDR L1 数据接入交付契约（Codex 仅负责真实数据与本地验收）

日期：2026-11-14。对应 `feat/l1-observatory-phase-a` 的 E01/E02/E03 研究和 12 维观测。

## 本轮代码已有的能力

- `research/l1_observatory.py`：日频 OHLCV、广度及 7 个以上基础市场代理，时间戳/覆盖检查。
- `research/l1_features.py`：12 维、57 个指标注册，基础派生量、行业相关、12 维资格状态；缺失为 null。
- `research/l1_derived_sources.py`：来源原始值的隐含/实现方差差、偏斜、期权未平仓集中度、盘口价差、订单簿不平衡、ETF flow/AUM、SOFR-IORB 等计算；交易商 Gamma 仅允许有明确净仓位假设的情景计算，不能用公开 OI 当真实仓位。
- `research/l1_models.py`：E01 未来 RV（基准、EWMA 对照、Ridge）、E02 先反弹/先下跌/未触及与校准不足阻断、E03 条件收益分布（基准、Ridge+条件尺度）、净化日历间隔、样本外按期限评分。
- `workflow/l1_runtime.py`：完整离线数据研究任务、不可覆盖归档、异常、样本外结果、模型指标、观察 API 和历史回放。
- `workflow/l1_forward.py`：只允许真实 T 日冻结的研究模型、签名归档、时间窗与当日数据检查，提供 CLI。
- `web.py` 预留 GET `/api/v1/l1/{market/overview,observations,anomalies,validation,replay}`；`assets/v4_ui_market_v2.js/css` 已对接单一 L1 市场展望页。

这些模块不等于市场预测已证明有效；历史代理价格回报也不等于经过公司行为核验的实际交易总收益。

## 必须由 Codex 接入的真实数据

### 1. `bars.csv` / `bars.parquet`

字段：`date,security_id,symbol,open,high,low,close,volume,available_at`。每个交易日完整 SPY，不可缺 OHLC；历史研究需尽量覆盖 ETF 与 PIT 股票池。保证同一证券身份及公司行为调整口径稳定，提供真实供应商回执，不允许把后来采集的数据回填为当时已知。

### 2. `cutoffs.csv` / `cutoffs.parquet`

字段：`date,decision_cutoff_utc`。按交易所真实日历生成，UTC 带时区；不得假定每天固定交易时间。数据 `available_at` 必须早于等于当天信号截止。

### 3. `universe.csv` / `universe.parquet`（如需完整广度）

字段：`date,security_id,is_member,available_at`。包含当时实际股票池、上市/退市和停牌处理，需有 PIT 独立凭证。不给该文件时，模型必须如实显示真实广度 MISSING，而非“零”。

### 4. `optional.csv` / `optional.parquet`（可选）

字段：`feature_id,date,value,available_at,source,source_snapshot_sha256,source_attested`。使用 `l1_features.py` 中注册的 optional `feature_id`，`source_attested` 标记由供应商证据核实，不代表仓库自行完成了独立核验。

也可以提供更原始的 `raw-measurements.csv`：`date,metric_name,value,available_at,source,source_snapshot_sha256,source_attested`。例如 `vix_30d,vix_90d,put_25_delta_iv,call_25_delta_iv,put_option_volume,call_option_volume,quoted_bid,quoted_ask,book_bid_size,book_ask_size,etf_net_flow,etf_aum,sofr,iorb`。数学转换由 `l1_derived_sources.py` 完成，不需 Codex 重写模型。

**期权、GEX、订单簿、借贷资金、仓位等未购买或无合格历史的来源必须显示缺失；不得伪造。** COT/金融条件等周频/修订源须保留实际发布时点。

## 运行入口

完整历史观测及 OOS：

```bash
python -m quant_research.workflow.l1_runtime \
  --bars /path/bars.parquet --cutoffs /path/cutoffs.parquet \
  --universe /path/universe.parquet --raw-measurements /path/raw-measurements.parquet \
  --output outputs/l1_research/unique_run_id \
  --evaluation-start 2023-01-03
```

在**真实当前时点**、本交易日收盘后、次日开盘前冻结研究预测：

```bash
python -m quant_research.workflow.l1_forward \
  --bars /path/bars.parquet --cutoffs /path/cutoffs.parquet \
  --root . --asof YYYY-MM-DD --source-snapshot-sha256 <64位真实源快照哈希>
```

禁止历史日期冒充真实冻结。不要在研究阶段将 `research_only`、`model_admitted` 或 `real_orders_enabled` 改为 true。

## 前端/API 对接

- `GET /api/v1/l1/market/overview?horizon=1|3|5`：包含 `domains`, `drivers`, `forecast`。只有存在真实冻结且完整的归档才会给出 `forecast`。没有历史研究归档返回结构化 409。
- `GET /api/v1/l1/observations?asof=YYYY-MM-DD`：历史观察及 12 维覆盖度。
- `GET /api/v1/l1/anomalies`：实际已记录异常。
- `GET /api/v1/l1/validation`：E01/E02/E03 相同日期样本外模型/基准误差；样本不足不能报告显著性。
- `GET /api/v1/l1/replay?asof=YYYY-MM-DD&horizon=3`：历史研究日期的预测与真实结果对照，明确是回顾研究，不是当时实盘冻结。

## 最终接入验收

1. 完整 PIT、公司行为、历史发布时点、供应商回执链路独立核验。
2. 真实 OHLCV、历史证券池和真实跨资产/期权数据按口径接入，维度覆盖率报告透明；缺数据清楚阻断。
3. 在用户本机执行项目全量 `pytest`、历史研究任务和浏览器端到端测试；确认 L2/L3/L4 无回归。
4. 研究预测不等于交易策略优势；如未能持续超过基准，保持 `RESEARCH_ONLY` 并在界面显示失败。
5. 如果开发分支合并，使用 PR 评审，不直接覆盖 `main`。