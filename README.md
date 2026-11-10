# 美股多层量化研究系统 · v2.1 REAL_ONLY

现有仓库按G0→G5整改，不提供演示或合成行情。缺真实数据/时间/身份/行动证据时返回BLOCKED，不生成收益或候选替代值。禁止实盘、采购、自动创建账户及解封最终测试。

- 规格：docs/codex_handoff_v2_1/README_先看这里.md
- 任务清单：docs/G0_G5_TASKS.md
- 数据策略：docs/REAL_DATA_POLICY.md
- 阶段验收：docs/G0_G1_acceptance.md
- 拆股特征层与未通过项：docs/G4_feature_prices_acceptance.md
- 最新增量验收：docs/G4_split_evidence_acceptance.md
- 日常数据维护与分类目录：docs/DAILY_DATA_MAINTENANCE.md
- 主干数据维护验收：docs/G4_data_maintenance_acceptance.md
- 经典因子监测验收：docs/G4_classic_styles_acceptance.md
- 因子实验室使用说明：docs/FACTOR_LAB_GUIDE.md
- 因子实验主流程验收：docs/G4_factor_lab_acceptance.md
- 市场滚动研究验收见 docs/G4_market_research_acceptance.md
- 开盘前真实观察与时间覆盖验收见 docs/G4_close_snapshot_acceptance.md
- 策略冻结、严格回测准入及 ETF 对照见 docs/G4_strategy_preflight_acceptance.md
- 每日观察与前向组合准入见 docs/G4_daily_observation_acceptance.md
- 本地备份恢复与日常运行见 docs/G5_operations_acceptance.md
- 进程强制中止与恢复见 docs/G5_crash_recovery_acceptance.md

运行（项目根目录）：

```powershell
.\scripts\start_console.ps1 --port 8766
.\.venv\Scripts\python.exe -m pytest -q -rs
.\scripts\maintain_data.ps1 --env-file .env
.\.venv\Scripts\python.exe -m quant_research.cli close-snapshot
.\.venv\Scripts\python.exe -m quant_research.cli daily-observation
.\scripts\run_daily.ps1
.\.venv\Scripts\python.exe -m quant_research.cli ops-backup
.\.venv\Scripts\python.exe -m quant_research.cli data-catalog
.\.venv\Scripts\python.exe -m quant_research.cli style-report
.\.venv\Scripts\python.exe -m quant_research.cli provider-probe --provider alpaca
.\.venv\Scripts\python.exe -m quant_research.cli provider-probe --provider sec --offline
.\.venv\Scripts\python.exe -m quant_research.cli feature-price-audit --offline --action-end 2026-11-06
.\.venv\Scripts\python.exe -m quant_research.cli market-report --source yahoo --mode retrospective
```

页面 http://127.0.0.1:8766 。已提供真实观察、经典因子监测和因子实验主流程；九页导航中的未完成功能显示真实空态，完整交互待G4实现。旧生成器与市场测试已隔离至archive/pre_real_only，不执行、不计通过。旧数据/报告保留，不删除，正式UI拒绝无真实来源/文件哈希凭据的报告。

`/market` 可运行 Yahoo 2017–2024 市场滚动研究，查看 SPY H1/H3/H5 方向、下行风险、常数基线和逐日结果。历史模型资格仍受真实发布时间与身份准入约束。

环境变量只在本地配置，不通过聊天提交密钥。Alpaca未配置时权限探针输出MISSING_CREDENTIALS；SEC需要合规项目名和联系邮箱。历史市场数据缺失/许可或缓存不完整时测试单列BLOCKED，不用虚构行情测试替代。

数据维护已支持每日行情和公司行为、每周 French 和 SEC、14 类台账及带哈希导出。日常更新后在 `/data` 冻结开盘前 SIP 观察，`/signals` 生成日报，`/paper` 查阅归档和模拟账户缺项。策略版本在 `/strategies` 保存与冻结，`/backtests` 显示真实准入证据。
