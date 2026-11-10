# G12 · 严格冻结预测逐行审计与端到端就绪矩阵（2026-11-10）

> 范围：只增强已存在的 REAL_ONLY 准入与可解释性，不提供真实券商订单、虚构个股信号、模拟市场收益或自动放开封存样本。

## 本轮工程交付

- `validation/frozen_predictions.py`：在 G10 严格 P5 回测模拟前，独立审核冻结预测 Parquet 的**每一行**。原本仅靠文件 SHA256 与 manifest 的状态标志不足以证明行内时点、证券身份或交易规则有效。现检查字段、重复键、真实价格中的 `(date, security_id, symbol)`、原始收盘锚点、模型拟合和特征到达时间、T 收盘后信号、T+1 正式开盘与 T+H 收盘、交易所日历、H1/H3/H5、有限数值及行业身份。实际未来收益标签进入决策文件、源内含 retrospective、2025 年起的封存测试数据、未通过的信号均拒绝。
- `workflow/backtest.py`：执行严格模拟前调用上述审核；通过后把行审计摘要写入本次回测 manifest。缺任何条件就返回结构化 BLOCKED，不发生原价模拟。
- `workflow/research_readiness.py`：整合现有只读来源数据能力、证券目录、冻结策略版本、真实前向观察、已通过的回测产物、内部对账模拟账本；按环节显示 `PASS / OBSERVATION_ONLY / BLOCKED` 和具体修复方向。文件存在或当前来源观察不等于历史 PIT 验证。
- CLI：`quant_research.cli research-readiness [--asof YYYY-MM-DD] [--db data/real_v21.duckdb]`。检查仍缺完整证据时结果为 `NOT_READY`，退出码 4。
- Web：`GET /api/v1/research/readiness[?asof=YYYY-MM-DD]`。研究总览页面增加面向用户的业务就绪矩阵。无数据仍返回不含假行情的阻断信息。

## 验证

- 当前隔离环境：`tests/test_frozen_prediction_protocol.py` 和 `tests/test_research_readiness.py` **24 passed**；其中时钟、价格和证券数值是协议断言使用的固定数学占位，绝不导出生产行情/研究结果。
- `python -m compileall` 相关源文件及 `node --check src/quant_research/assets/studio.js` 通过。
- 本环境**不具备**用户真实 DuckDB/Parquet 数据及 `duckdb`、`pyarrow`，没有执行严格 P5 回测或全仓库测试，更没有宣称模型存在预测优势。
- 所有交易执行开关仍为 `real_orders_enabled=false`；不能因冻结策略存在或来源页面哈希验证而自动变成资格 PASS。

## 在本机验收

```powershell
# 更新代码后，检查实际数据、模型和模拟账本缺口
.\.venv\Scripts\python.exe -m quant_research.cli research-readiness

# 检查某历史日期当时的证券来源可用性
.\.venv\Scripts\python.exe -m quant_research.cli research-readiness --asof 2024-12-31

# 运行新增纯规则测试（无需从外部伪造任何市场记录）
uv run --locked pytest -q tests/test_frozen_prediction_protocol.py tests/test_research_readiness.py

# 真实环境回归（需要本地安装和真实数据；未获证据时应有明确阻断）
uv run --locked pytest -q
```

在浏览器打开 `/overview` 查阅所有模块的就绪矩阵；`/backtests` 仍只读取来源和哈希验收通过的 P5 历史模拟结果。

## 尚未通过的外部及业务验收

1. PIT 历史股票池、退市/改名生效和来源发布时间、独立确认的公司行为权益及现金结算。
2. 完整真实样本训练和模型快照：独立 OOS 预测能力、概率校准、成本后正向贡献、冻结模型与推理运行档案。
3. 可进入严格 P5 的实际 PIT 预测 Parquet、持续每日真实候选/冻结、实际 T+1 模拟续记和跨日对账。
4. 使用本机真实 API 和缓存完成全仓库测试、UI 浏览器交互、定时任务与独立恢复测试。

**结论**：此批改造交付的是业务准入保护与可执行的缺口定位工具。整个项目状态仍为 `NOT_READY`；不能把单元测试完成与真实投资研究验收混为一谈。
