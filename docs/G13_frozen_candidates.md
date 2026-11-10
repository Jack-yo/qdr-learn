# G13 · 冻结决策逐项核验与每日候选只读入口

## 本轮工程交付

- 新增 `workflow/frozen_decisions.py`：只读查询真实 DuckDB `model_attestations` 与 `decision_attestations`，不创建决策、不抓取历史、不给模型注入 PASS 标志。
- SHA256 逐字校验 `data/managed/models/` 及 `data/managed/decisions/` 范围内的存档文件；审核训练、特征、信号与冻结时间，校验明确的证券 ID/代码、行业、波动与流动性字段，以及 H1/H3/H5 退出日历。拒绝已实现盈亏、未来标签、回溯获知结果进入前向决策。
- 对冻结文件中明确提供的概率/仓位原样展示；没有提供就保持 `null`，不推算或伪造。
- 对真实已收到的 Alpaca SIP raw 数据执行现有 `DatasetBundle.require('forward_shadow')`，并强制要求整套 `source_snapshot_sha256` 与实际截止时点的行情完全一致。缺任一项就阻断。
- CLI `frozen-candidates --session YYYY-MM-DD`、GET `/api/v1/signals/frozen?session=YYYY-MM-DD`、每日信号页冻结候选核验及研究就绪矩阵接线。
- **最高状态仅为 `ATTESTED_FORWARD_DECISION_RESEARCH_ONLY`**，`real_orders_enabled=false`、`execution_ready=false`、`historical_pit_eligible=false`；它证明当时有经核验的研究决策档案，不证明预测优势、成交或正收益。

## 使用方式

```powershell
# 没有真实冻结决策时返回 BLOCKED，CLI 退出码 4
.\.venv\Scripts\python.exe -m quant_research.cli frozen-candidates
.\.venv\Scripts\python.exe -m quant_research.cli frozen-candidates --session 2026-11-06

# 原有就绪矩阵同时新增 frozen_decision 环节
.\.venv\Scripts\python.exe -m quant_research.cli research-readiness

# 单元测试及全仓库回归
uv run --locked pytest -q tests/test_frozen_decisions.py
uv run --locked pytest -q
```

页面：`http://127.0.0.1:8766/signals` →「冻结候选与来源校验」。观察日报继续展示真实 ETF 观察而不冒充预测候选。

## 验收边界与后续必需条件

- 无本机真实 DuckDB、原始 SIP/回执、永久证券身份、真实训练模型和决策 attestation，**无法进行正向端到端验收**；单元测试中的协议标识不能作为行情或者正式信号。
- 当前只读核验不负责训练或冻结正式 Alpha 模型，不会自动输出候选；正式历史个股回测还需独立历史 PIT 数据、完整公司行为和外部结算证据。
- 客户端展示的 `p_up` 仅为有来源的文件原字段，尚未证明预测概率已校准；缺少值时界面明确标记未提供。
- 历史 PIT 数据、个股正式 OOS 模型训练、真实多日前向 shadow 和系统全量回归仍未被自动补全；交付声明必须保持 `NOT_READY` 直到全部来源与业务验收通过。
