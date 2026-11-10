# P2 验收记录 — 2026-11-06

**P2 工程与探索性诊断验收通过，未开始 P3。尚不能宣称完成严谨个股 Alpha 研究或历史原始价回测。**

## DONE

实现扩展 Factor 协议、14 个固定因子/缺失状态、日历对齐与时间守卫、H1/H3/H5 标签、分区 purge 与 5 session gap、Rank IC/ICIR/块 bootstrap、五分组、衰减 SVG、因子相关性、缺失/覆盖、成员换手与固定市场条件描述。SQL 在读入前隔离 2025 起最终测试期。DuckDB schema v3 与 Parquet 保存特征和标签。

真实 ETF 面板可计算其中 10 个因子；两个行业因子已实现且有公式测试，但无 PIT 行业映射，实际输出为空；size/quality 暂为明确缺失状态，没有用当前财报或市值替代。

## TESTS

实际最终命令：

```powershell
.\.venv\Scripts\uv.exe run --offline --locked --cache-dir .uv-cache pytest -q --junitxml=outputs/p2-pytest.xml
.\.venv\Scripts\python.exe -m quant_research.cli factor-report --source fixture --mode strict --db data/p2_fixture.duckdb
.\.venv\Scripts\python.exe -m quant_research.cli factor-report --source yahoo --mode retrospective
.\.venv\Scripts\python.exe -m quant_research.cli features --source yahoo --asof 2024-12-31
```

最终 pytest：**83 passed in 22.09s，无 warning**。前两类报告命令成功；严格历史 as-of 按预期返回 4，因 Yahoo available_at 晚于 2024 年信号，不能伪造当时可用特征。2025-01-02 的报告请求按预期返回 2，且在读取价格前被拒绝。

新增验证：独立公式对照（含 Beta=2 的构造样本及行业残差）、完整窗口与零分母、节假日 T+1 与 H3/H5、尾部和中间缺失标签、同日收盘不能当入场价、Yahoo 只能写代理标签、常数/ties IC、五分组与成员换手、块 bootstrap 确定性和小样本缺失。

未来泄漏故障注入：未来 shift 插件和全样本均值标准化被前缀检查拒绝；改动未来价格/可用时间不改变内建因子的过去输出；迟到分类不能成为 strict 特征。新建 external_plugin，无需修改研究引擎即可完整生成报告，两次统计哈希一致。

两次真实 Yahoo 研究均禁用 socket 连接后串行运行，配置/输入/代码/统计哈希一致。实际单写验证曾因并行操作同一 DuckDB 触发文件锁，已串行重跑；没有绕过数据库锁或修改数据。

训练末尾固定 5 session gap 在验收核对时补齐；初始草稿仅做标签边界 purge。最终报告和两次重放均使用完整规则，最后训练 IC 日期为 2022-12-22。没有按收益结果调参或读取最终测试。

浏览器已渲染并检查 HTML 与 SVG 布局；最终截图 outputs/p2-report-final.png。远端 CI 仅配置，未执行。

## DATA / RESULTS

- 输入仅 2017-01-03 至 2024-12-31：40,240 行、20 ETF；排除 SPY/HYG/LQD 后研究 17 个 ETF。
- 14 个因子/状态，共 478,856 条特征，其中 335,121 条为非空回溯数值；真实历史决策资格为 0。
- 102,612 条 H1/H3/H5 标签记录，102,459 条非空价格收益代理；正式 raw 收益字段为 0 条非空，净收益为空。
- 84 条汇总（14 因子 × 3 horizon × 2 分区），附逐日 IC/分组、分布、相关性、条件统计与缺失记录。
- sealed_test_used=false；输入和有效标签退出日期均不超过 2024-12-31。
- 所有结果固定 EXPLORATORY / ETF_PROXY_NOT_EQUITY_ALPHA / DATA_INCOMPLETE / NOT_READY。

最终真实报告目录：`outputs/research/f375cdf7-8a37-40ef-a4ca-1d6355a6affb/`。

- report.html：报告与衰减图。
- manifest.json、config.json、run.log：完整版本与元信息。
- features.parquet、labels.parquet：实际计算结果。
- summary.csv/parquet、daily_ic.parquet、daily_groups.parquet、conditional_ic.csv/parquet、factor_correlations.csv/parquet。
- 禁网重复目录：`outputs/research/ac47884e-5f3b-48ad-9d1a-1f3795ccaed6/`。
- 合成完整报告：`outputs/research/babd2493-8bf9-4d8d-aadf-c95ef7328413/report.html`。
- 复核断言：`outputs/p2-verification.json`；阻断证据：`outputs/p2-strict-asof-check.txt`、`p2-sealed-period-check.txt`；pytest XML：`outputs/p2-pytest.xml`。

输入哈希：`2b65b88da88d111b6abd9143d02cf42bff063f99d3443e10e6ca120498033477`。

最终统计哈希：`92b078c66118a7fe16eadf38f90b9b8318c2f3225ecbaf5f5f215b1396cf0ebe`。

## RISKS

Yahoo 当前下载版本无法证明历史当时已知，故只允许明确 retrospective 描述模式；没有把 available_at 回填为价格日期。价格仍为 split-adjusted，不能用于原始价成交仿真；企业行为现金口径未核验。P4/P5 不得将这些特征/代理标签直接当作严格 PIT 训练和交易记录。

样本是成分重叠的 17 ETF，不是股票横截面；缺乏历史股票池、退市、行业分类、PIT 市值/财务、报价和成本数据。置信区间仅是预设块方法的工程统计，不保证真实 Alpha，也未做多重检验后优势判断。行业/市值/风格暴露对应缺口明确保留。

前缀抽查和已覆盖扰动测试不构成任意外部插件的形式化证明。新插件必须附依赖声明、公式与未来扰动测试。

## NEXT

P3 先实现可追溯的市场/ETF 风格状态与历史归因，阈值仅训练期估计并冻结；French 保持发布日期/当前版本限制。只有在具备合法训练输入与时间验证后才运行方向模型基线，不能直接将 Yahoo 回溯描述包装成历史可交易预测。原始价与 PIT 数据缺口继续保留。

## 文件清单

新增：

- configs/experiments/p2_factors.yaml
- src/quant_research/features/context.py、factors.py、engine.py
- src/quant_research/research/experiment.py、labels.py、statistics.py、evaluate.py、pipeline.py
- src/quant_research/reports/factors.py
- tests/unit/test_p2_factors.py、test_p2_labels_stats.py
- tests/integration/test_p2_research.py
- docs/p2_research.md、docs/p2_acceptance.md

修改：src/quant_research/cli.py、data/store.py、.github/workflows/tests.yml，以及 README、AGENTS、架构/数据字典/限制/协议/里程碑/决策文档。没有增加新依赖、训练模型、下单接口或 P3–P6 业务实现。
