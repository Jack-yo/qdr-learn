# G14 · 只读模拟账本逐日核对与观察页面适配

## 已实现

- `workflow/paper_timeline.py` 只读真实本地 `data/paper.sqlite3`，先调用既有 `account_summary` 内部账本核对，随后独立检查全部已记录 XNYS 会话是否连续、输入与冻结决策/数据 SHA256 是否齐全、逐日 `snapshot_json` 中现金/权益是否有限、事件 ID 是否符合持久化顺序、`body_json.cash_change` 是否与数据库一致、每天资金是否等于初始现金加累计实际记录事件，以及快照 `new_fills` 是否与事件数量一致。
- `GET /api/v1/paper/timeline?limit=20` 和 CLI `paper-timeline --limit 20`。查询不会创建账户、写入交易、调用外部行情或补历史月份。无账本直接返回 `BLOCKED` 和空交易日列表。
- `/paper` 页面增加逐日现金、估值权益、持仓数量、当天模型成交笔数及对应真实冻结决策哈希；修复原来前向观察页面错误读取 `inventory.records` 的问题，并显示真实观察缺失日。
- `/overview` 就绪矩阵新增 `paper_timeline`，用 `OBSERVATION_ONLY` 与 `BLOCKED` 区分真实记录和缺证据，不因账本内部平衡而放开实盘执行。
- 追加本地无来源保护、CLI 不产生虚构结果、参数及前端接口静态合同检查。

## 运行

```powershell
.\.venv\Scripts\python.exe -m quant_research.cli paper-timeline --limit 20
.\.venv\Scripts\python.exe -m quant_research.cli research-readiness
uv run --locked pytest -q tests/test_frozen_decisions.py tests/test_paper_timeline.py
uv run --locked pytest -q
```

在 `http://127.0.0.1:8766/paper` 查看。这里的数字仅来自已有数据库，没有演示资产曲线。

## 明确的验证级别

通过状态只证明**内部模拟事件、现金和会话连续性**，并非券商成交回执；本模块**不会重新核验每个来源行情对象的全链**（该项在已有严格数据接入和决策资格流程检查），也不证明预测优势或行业分类。没有真实模型、PIT 身份和连续多日档案，**正向完整闭环仍是 `NOT_READY`**。
