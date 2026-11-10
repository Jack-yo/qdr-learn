# P3–P6 最终工程验收

**P0–P6 工程实现与离线合成验收已完成；真实研究与可交易性仍为 NOT_READY。** 本阶段没有接入券商或真实订单，没有把 Yahoo 调整价当原始成交价。最终实测日期与断言见 `outputs/system_verification.json`。

## DONE

| 阶段 | 实施与验收 | 未消失的限制 |
|---|---|---|
| P3 | 市场/5 类 ETF 风格状态、训练阈值冻结、French 事后归因图；H1/H3/H5 Logistic/常数基线、方向和下行 Brier/LogLoss、校准 | ETF 不是纯因子或 PIT 股票广度，利率未接入，概率未校准 |
| P4 | Ridge/Logistic，训练内 impute/scale，按季度 walk-forward，1260 session 窗口、实际 label 时间 purge 和 5 session gap，A–D 消融 | 17 ETF 不是个股股票池；Yahoo 只可当前版本模型研究，禁止成交 |
| P5 | 同一事件/费用引擎的 A–E 和4基准，H1/H3/H5×5/10/20/50bps/侧，共108组；现金/仓位/费用逐笔对平，风险/年度/市场条件报告 | 全部成交验证是合成 raw；真实 raw/PIT/公司行为/报价缺口阻断真实回测 |
| P6 | 日报、空候选保护、市场风险概率、跨日SQLite纸面账本、重放幂等、失败事务回滚、刷新失败空建议、调度脚本与示例、一键工程运行 | 定时任务没有自动安装；真实数据不满足严格条件时只输出无建议报告 |

## TESTS

最终完整执行：

```powershell
.\.venv\Scripts\uv.exe run --offline --locked --cache-dir .uv-cache pytest -q --junitxml=outputs/p3-p6-pytest.xml
```

**100 passed in 147.94s，无 warning。** 测试 XML 保存在 outputs/p3-p6-pytest.xml。新增端到端测试禁用 socket，以短验证窗口完整执行 P3→P6、全部108组合和重复纸面重放；不是只测试占位接口。

覆盖原 P0–P2 全部测试，另覆盖市场/风格公式和冻结、训练内变换、训练 purge/gap/标签可用时间、改变验证期未来标签和特征不改变第一日预测、概率单类别回退、原始快照不匹配拒绝执行、开盘时钟、跳空/同根保守止损、双边成本、仓位/现金/未知行业约束、停牌冻结、kill-switch、拆股/分红/退市政策、非有限金额拒绝、生成器扩展不改历史、SQLite事务与重复日期、API失败无新建议，以及2025之后 live forecast 不读取任何 heldout label outcome。

各阶段先执行针对性测试与命令，再全量运行。开发中修正了 v1 fixture 扩展 end 会改写后续证券历史的问题，新增 v2 而未修改 P0–P2 老报告；修正 H1 只看收盘暴露导致资金利用率为0的问题，另报开盘/收盘/两端观测代理。没有为追求盈利修改标准。

Windows Python3.13.15 本地已验证；Windows/Linux Python3.11–3.13 的 CI 配置保留，但远端未执行。不能宣称其他平台已经通过。

## DATA / RESULTS

### 实际运行证据

- 一键 P3–P6：`outputs/system/66697ab4-18f3-4d4e-9c76-a541ff324f0f/manifest.json`，ENGINEERING_WORKFLOW_COMPLETE。
- 最终 P3 方向/下行基线：`outputs/system/4ee44588-8626-4b0e-9796-07c66937ea10/report.html`。
- 真实 Yahoo/French 状态归因：`outputs/system/e3702a80-7573-410a-8109-f5b02b2776f7/report.html`。
- P4 合成 A–D：`outputs/system/6dfc1f92-8a67-4285-bea5-89b8ba47518b/report.html`；102,408 条样本外合成预测、96 个 alpha fold；P3有1,506条市场预测。
- P4 真实当前版本研究：`outputs/system/e1e96327-ce41-4e33-bc76-beec38e6cf8d/report.html`；所有预测均为不可成交的 retrospective。
- P5 完整108组：`outputs/system/7533f179-999d-4289-966b-c6b415ed2b3a/report.html`，附逐笔/逐日 CSV/Parquet。
- 最新纸面日报：`outputs/system/61e0bed9-0662-458e-892e-bb9949967ded/report.html`；纸面账户跨 2024-12-30、12-31、2025-01-02、01-03 四个 session，新年休市被正确跳过。这里只是合成 forward paper，不是真实最终测试。
- 真实 Yahoo 无建议：`outputs/system/ec1a55a1-028a-4966-8af4-61105896ed18/manifest.json`。
- 真实 Yahoo 回测阻断：`outputs/system/fdc32c0d-481e-48d4-b62e-18ccb54f39a5/manifest.json`。

最终模型快照与另一独立训练运行的配置/输入哈希相同，predictions.parquet 字节哈希相同。模型不存在通过随机分割或未来数据拟合变换的路径。

两次独立的108组回测重放，其期末净值、净总收益、费用、回撤和实际关闭lot数量逐组一致（误差不超过1e-9）；断言保存在 system_verification.json。

主工程数据库 `data/system_acceptance.duckdb`：102,408 prediction、70,259 order、54,929 fill、148,818 收盘position记录、54,216 日净值记录。108 个实验均验证“初始现金+成交/事件现金流=期末现金=期末净值”（本次全部已平仓），累计成本与 fills 成本和一致。开盘持仓另导出，以免遗漏 H1 风险。

纸面数据库 `data/system_acceptance_paper.sqlite3`：4 session、6 个现金事件，重复重放没有增加事件；最新持有4个合成头寸。现金与全历史事件和核对一致。快照及实际余额见 system_verification.json，不手写假数。

### 固定默认场景的实际合成结果

验证期2023–2024，H3，每侧10bps加配置冲击；每个实验独立初始 $100,000。这些不是美股真实历史策略收益。

| 变体 | 合成净总收益 | 最大回撤 |
|---|---:|---:|
| A | -3.8706% | -4.2032% |
| B | -1.4916% | -3.5528% |
| C | -1.3810% | -3.6168% |
| D | -0.7161% | -2.9233% |
| E | -0.5331% | -1.7158% |

没有将负结果调成盈利，研究状态保留 NOT_READY。这些合成结果只能证明软件行为，不能推断真实市场优劣。

## 可复现命令

```powershell
.\.venv\Scripts\uv.exe sync --locked --cache-dir .uv-cache
.\.venv\Scripts\python.exe -m quant_research.cli run-all --source fixture --db data/demo-system.duckdb --state-db data/demo-paper.sqlite3
.\.venv\Scripts\python.exe -m quant_research.cli train --source yahoo --mode retrospective
.\.venv\Scripts\python.exe -m quant_research.cli backtest --source yahoo --mode retrospective
.\.venv\Scripts\python.exe -m quant_research.cli daily-report --source yahoo --mode strict --asof 2026-11-05
```

后两条预期返回4，分别为 raw/PIT 阻断、无新交易建议，不应强行改成成功。首次 sync 联网，工程 run-all 安装后完全离线；真实源 ingest/显式 scheduled-run 才联网。

完整命令、规则、表和调度说明见 [system_guide.md](system_guide.md)。交付文件清单见 [project_file_manifest.json](project_file_manifest.json)；包含源码、测试、配置、脚本和文档，不包含虚拟环境、缓存或输出数据库。当前代码未创建 Git 提交或推送。

## RISKS / 后续条件

工程验收不等于真实研究验收：仍缺真实 PIT 股票池、退市/稳定证券身份、PIT 财务/行业/规模、经核验原始开盘价及企业行为、报价/滑点/冲击证据；个股样本仍只是17 ETF。Alpaca 长历史专项未完成。真实最终测试未开放或择优。

资金/行业上限按入场和下一可交易事件实施，价格漂移可能暂时越界，报告显示并在下一开盘减仓；不能以日线实现虚假的连续无漂移控制。相关性只是历史观测，不是组合尾部保证。分红/退市/碎股需验证的输入缺失时会报错，不静默造结算。

模拟账户是本地合成交易记录，绝不是券商 paper API 或实盘。调度示例未注册系统任务。不会自动发送邮件/消息或真实订单。

下一步不再是新开发阶段，而是补齐合格真实数据、冻结真实研究配置并独立验证；条件不足继续 NOT_READY，不自动投入真实资金。
