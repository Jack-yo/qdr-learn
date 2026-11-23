# L3 当前前向特征价格准入拆分（2026-11-23）

## 结论

L3 当前日 Alpha-only 前向观察，不再依赖 G4 的“本地 raw + corporate actions 复算 split-adjusted 价格必须逐字段完全复刻供应商”作为唯一准入门。

两个证据任务拆开：

1. **G4 normalization-audit**：验证本地 raw → split-adjusted 重建是否严格匹配供应商 split 参考。已有 0.005 美元级价格精度差异时继续保持 `BLOCKED`，不得放宽阈值、不得改 PASS。
2. **L3 forward feature admission**：直接使用 Alpaca SIP 原生 `adjustment=split` bars 作为研究特征价格，逐页要求 content-addressed 原文、immutable receipt、明确 feed/adjustment/asof、完整当日覆盖和 knowledge cutoff。该路径只允许 `research_only`，不证明历史 PIT、总收益、交易价或执行资格。

因此“本地重建公式没有逐分钱复刻供应商”仍是 G4 质量问题，但不再错误地阻断供应商原生数据本身用于当前前向因子计算。

## CLI

严格 G4 审计保持原语义：

```powershell
uv run --locked python -m quant_research.cli feature-price-audit ^
  --purpose normalization-audit ^
  --symbols "SPY,..." ^
  --asof YYYY-MM-DD ^
  --action-end YYYY-MM-DD
```

L3 前向研究：

```powershell
uv run --locked python -m quant_research.cli feature-price-audit ^
  --purpose l3-forward ^
  --symbols "SPY,..." ^
  --asof YYYY-MM-DD ^
  --start YYYY-MM-DD

uv run --locked python -m quant_research.cli l3-current --date YYYY-MM-DD
```

`l3-forward` 不查询/重建 corporate-action adjustment，不使用本地复算结果；直接读取同一 Alpaca SIP bars API 的 `adjustment=split` 响应。

## L3 forward 必须满足

- source = `ALPACA`
- feed = `sip`
- provider request = `timeframe=1Day, adjustment=split, asof=-`
- 每一页 response SHA256 对应真实 cache object
- 每一页存在匹配 immutable receipt
- 当前 anchor session 对所有显式请求 symbols 完整覆盖
- 每个 vendor symbol 可映射回当前已观察 raw bundle 的唯一 security_id
- source observation 不晚于 knowledge cutoff
- L3 freeze 时仍必须满足 close signal <= cutoff < next-session entry
- 输出固定：
  - `research_only=true`
  - `execution_ready=false`
  - `real_orders_enabled=false`
  - `historical_decision_eligible=false`

## 明确不证明

该路径不证明：

- 历史 PIT 股票池
- 普通股 / ETF / ADR 的独立分类
- 永久证券身份
- 公司行为历史完整性
- total return
- 可成交执行价
- H1/H3/H5 预测有效性
- 实盘或模拟交易资格

这些继续由各自的数据/模型/风控证据链验收。

## L3 准入状态

L3 当前因子快照允许两种 feature artifact：

- `NORMALIZATION_VERIFIED_CURRENT_VINTAGE`：原有严格 G4 normalization PASS；
- `FORWARD_VENDOR_SPLIT_FEATURES_VERIFIED_CURRENT_VINTAGE`：新增供应商原生 split-adjusted、只读前向研究路径。

后者不会把 `reference_comparison=BLOCKED` 改成 PASS；因为它根本不声称“本地 normalization 已验证”。manifest 中明确记录：

- `purpose=l3-forward`
- `reference_comparison.status=NOT_APPLICABLE_DIRECT_VENDOR_SOURCE`
- `strict_normalization_audit_status=NOT_RUN`

## 当前剩余阻断

即使 forward feature price 打通，L3 仍要求：

1. 一个真实冻结的 2–8 因子 Alpha 策略；
2. 至少 5 个证券通过当前价格、ADV20 和完整因子门槛；
3. 第一天真实 freeze 后，跨日 Alpha 状态仍应为 `HISTORY_UNAVAILABLE`；
4. 只有第二个连续 XNYS 交易日、同一 strategy/config 的真实归档出现后，才计算 Alpha Δ / Rank Δ / Signal Age。

历史 PIT 继续阻断严格历史个股回测，但不阻断上述当前 forward Alpha 观察。
