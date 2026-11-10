# G4第一步：真实DatasetBundle、能力门槛与观察链路

后续增量：独立公司行为特征价格层已实现并实测，严格参考精度仍BLOCKED；详见[G4_feature_prices_acceptance.md](G4_feature_prices_acceptance.md)。本页的53项通过是第一步历史结果，新增后的最终测试以outputs/feature_prices/phase_acceptance.json为准。未因此解锁原有模型/执行能力。

日期：2026-11-07（Asia/Shanghai）；原仓库无HEAD，commit_sha=null。仅推进受证据支持的能力，不宣称G4或九页工作台已完成。

## DONE / 实际修改

- `data/bundle.py`：只读查询真实源，先按知识截止筛版本再选最新；观测日期与knowledge_cutoff分开。逐行OHLCV核对原始响应及SHA，核验来源/feed/raw参数的抓取凭据及可用时间，不因供应商名直接放行。对外返回数据和能力副本，价格变更/源缺失/无凭据拒绝。
- 8项能力：observation、raw_prices、exploratory_price_factors、historical_model、industry_factors、pit_fundamentals、historical_backtest、forward_shadow。缺证据逐项列出；raw不能自动变成拆股一致的因子价格，当前PIT候选不能变成可用财务。
- `models/dataset.py`、`research/pipeline.py`：统一从bundle读取指定来源。修复因子路径原先写死Yahoo的接线，拒绝“请求Alpaca、实际读Yahoo”。严格模型入口要求历史时间/身份能力；回溯模式仍明确当前版本探索。
- `workflow/train.py`、`market.py`、`daily.py`、`backtest.py`：将对应入口绑定模型/历史执行/前向证据，不删除风控、成本或时间约束。实际交易和paper仍未放行。
- `workflow/bundle_audit.py`、`cli.py`：新增bundle-audit，真实观察报告含20条最新报价、全部49,520条源核验计数、能力表、快照/代码/文件hash。无预测/模拟成交/策略收益。凭证显式加载复用到ingest，仅本地.env，不记录值。
- `web.py`、`web.html`：默认读取独立SIP raw库；版本化system/status、data/quality、market观察API；来源/口径/时间/能力实际显示。刷新按钮与当前源一致；raw观察/能力按钮实际调用bundle-audit；缺公司行为序列时模型按钮禁用且后端也拒绝。去掉旧“拆股调整”假标签；raw跨期收益不计算，显示N/A。排除pytest-tmp报告，当前日志走专用API。
- `workflow/common.py`：移除旧fixture版本分支，raw标识依据数据口径，避免对raw误贴NOT_RAW。
- `tests/test_g4.py`：真实本地SIP及回执/响应测试，篡改/缺失/口径/时间/按钮源一致/严格入口回归。未生成市场记录。

## DATA / 实际证据

独立`data/real_v21.duckdb`：显式当前20ETF观察样本，最新日2026-11-06，2017起49,520条最新版本价格；119份原始响应逐行匹配。snapshot_sha256=5f652f593eab28e4689a3f5dd6e5d4145ad911fc0191c232a441b9c6bfdcaa38。不把显式当前名单称为历史PIT名册。

真实报告：`outputs/g4/eb88dbda-588f-4620-9fd6-84746f3bd286/report.html`。按钮实际生成：`outputs/g4/dbde564c-3e7e-4da9-b105-bdaee39fb7f6/report.html`；任务COMPLETED、exit_codes=[0]，并非只验证启动。按钮开始/结束证据：outputs/g4/button-start.json、button-finish.json。该按钮本轮改为明确的观察报告，不宣称已有完整预测日报。

API真实返回：ALPACA、49,520条逐行已核验，observation/raw_prices PASS、historical_backtest BLOCKED。证据outputs/g4/api-verification.json。

Yahoo原有描述研究仍能真实重跑：`outputs/g4/yahoo_regression/d75dabbb-3023-4ed2-90fc-9b3303c54dc1`，DESCRIPTIVE_CURRENT_VINTAGE_ONLY。没有拿Yahoo替代SIP，更没有用合成数据补缺。

## TESTS / 运行命令

```powershell
.\.venv\Scripts\python.exe -m quant_research.cli bundle-audit
.\.venv\Scripts\python.exe -m quant_research.cli factor-report --source alpaca --db data/real_v21.duckdb
.\.venv\Scripts\python.exe -m quant_research.cli market-report --source yahoo --mode retrospective --output outputs/g4/yahoo_regression
.\.venv\Scripts\python.exe -m pytest -q -rs --junitxml=outputs/g4/tests.xml
```

第二条正确返回结构化CAPABILITY_BLOCKED：缺corporate-action-consistent feature price series，不读另一源、不生成虚构因子。首次接线遇只读/写连接配置冲突，已把bundle读取移至写连接之前修复；失败真实保留，没有降低检查。

中间全套52通过、1项BLOCKED跳过，最后新增严格模型入口回归后结果以outputs/g4/tests.xml和phase_acceptance.json为准。跳过仍是Yahoo最新真实缓存缺字段；旧20文件市场测试待迁移，不计通过。

## 实际浏览器检查

后台Chrome截图任务未结束，已仅清理本轮独立profile进程，不将其计作成功。改用浏览器控制工具实际打开/data，检查DOM和截图：ALPACA / sip / raw / 2026-11-06、20条报价、raw收益全部N/A、四个模型/因子按钮disabled。导航/backtests显示BLOCKED/N/A，无收益曲线或假概率。实际截图在本次工具输出；未生成虚构UI样本。完整自动化Playwright九页研究流程未验收。

## RISKS / NEXT

目前只有行情观察和原始价格证据通过。原始价格具备不等于历史回测具备；尚缺公司行为一致的特征价格序列、永久身份、历史股票池与退市、接受的事件账本、PIT原稿/行业、冻结合格模型和决策快照。前向需要从真实开始日登记的股票池与模型/事件资格；不强行要求全市场历史才做观察，也不因此放松前向规则。

Registry当前未为缺失证据提供手动PASS开关；未来应通过真实证据注册实现相应能力，而不是编辑布尔值。正式模拟账本尚未接入新事件算术模块；React完整九页、任务取消/版本管理/因子DSL等仍未实现。下一步补公司行为一致特征价格与证据接线，再迁移模型/实验交互。成本和仓位参数未变，最终测试仍封存。

最终全量结果：53 passed、1 skipped（Yahoo最新缓存BLOCKED），见outputs/g4/tests.xml。G4新增10项测试。最后代码观察报告：`outputs\g4\294c14ea-d832-49f6-8641-9cef6d76c35d\report.html`。机器记录outputs/g4/phase_acceptance.json；凭证扫描未发现值写入源码/文档/测试/G4日志。
