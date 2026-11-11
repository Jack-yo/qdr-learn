# QDR V4 · 代码改造进度与剩余验收（2026-11-11）

> 本文记录真实已提交的工程改动；并不宣称四层量化系统已在真实 PIT 全市场数据上完整运行。开发仓库：Jack-yo/qdr-learn / main。

## 目标

四层架构为 L1 市场状态预测、L2 经典因子与风格轮动、L3 自定义因子/多因子选股/个股 Alpha、L4 持仓与风险。每日决策横向使用其研究结论，执行 T 收盘冻结、T+1 原价模拟入场、T+H 收盘或预设条件退出、真实交易日连续跟踪。

## 本次已实现

| 模块 | 代码位置 | 已落地的功能及限制 |
| --- | --- | --- |
| 自定义因子 DSL | features/expression.py | 白名单 AST，不执行任意 Python；OHLCV、daily_return、lag/ret/mean/std/sum/abs/rank/zscore；lookback 自动推导、递归上限、禁止负窗口/未来读取；只计算传入的市场数据 |
| 因子版本及实验接入 | research/factor_lab.py、assets/studio.js | 增加 template=custom，公式随不可变版本保存、预览、实验；窗口必须覆盖依赖；无真实数据时仍然阻断 |
| 横截面时点约束 | features/engine.py | rank/zscore 因子新增 cross_section 依赖；检查全部输入证券窗口及最新发布时间，防止迟到的其他证券数据修改已冻结截面 |
| 多因子诊断 | research/factor_diagnostics.py、research/composite.py | 同一日期的 Spearman 相关性中位数、有效交易日数、≥0.85 的冗余提示；最新候选展示各因子分位和加权贡献；仅历史探索，非可交易信号 |
| 收益目标修正 | models/walk_forward.py | 个股未来总交易收益使用单独 Ridge 模型预测，超额收益使用另一个模型；不再将训练期平均基准收益机械叠加到超额预测后冒充总收益 |
| 持仓风控与风险数学 | risk/portfolio.py | 独立计算协方差收缩组合波动率、历史 VaR/ES、市场 beta、个股/行业/组合仓位风险；输入缺失或含未来数据时拒绝；无来源证明时研究性质 |
| 账本集中度实时检查 | backtest/paper.py、web.py、assets/studio.js | 经内部对账的模拟账本增加可审阅原价估值、/api/v1/paper/risk 只读接口、前端集中度预警；缺少历史收益时 VaR/ES 明确为 N/A |
| 信息架构 | app_shell.html、assets/studio.css | 总览 + 四层研究导航 + 数据中心，L3 因子/选股/回测为子页面，L4 组合风险为子页面 |

## 测试证据

- 在独立工作目录对新增 DSL、横截面因子冗余和组合风险数学运行了 24 项本地单元测试，全部通过；主要测试文件：tests/test_factor_expression_v4.py、tests/test_factor_diagnostics_v4.py、tests/test_portfolio_risk_v4.py。
- 修改前版本 UI JavaScript 已通过 node --check；最新修改后完整 UI/HTTP/数据库集成和所有历史 pytest 尚未在本地完整运行。
- 未运行持证的全市场 PIT 回测、实际 Alpaca SIP 前向实盘历史连续验证，也没有生成可交易的真实预测收益。

## 仍然没有完成（不能以页面/接口代替）

1. **PIT 历史证券池**：全市场普通股身份、上市/退市、当时行业和成分覆盖、公司行为及合法来源；当前 G7/G8 前向目录不能替代历史 PIT。
2. **可执行个股 Alpha**：前瞻 1/3/5 日真实标签、市场/风格的同样本 A/B/C/D 增量、样本外校准、训练/验证及不确定区间，且不对旧测试期重复择模。
3. **历史严格回测**：原始可成交价格、拆股分红/退市权益、公司行为现金流水、真实成本及成交条件资格；现存 Yahoo 回溯结果仍为价格代理研究。
4. **完整日终调度**：数据→市场→风格→Alpha→净优势→定仓→决策冻结→次日模拟→逐日验证的自动有资格链路（现有 daily_ops 不具备全部步骤）。
5. **模型有效性**：目前无足够合格真实数据可证明超过基准的 OOS 预测优势、正净收益或连续前向表现。
6. **完整集成验收**：使用最新 main 在具备合规真实数据和依赖的开发环境运行全部 pytest、web smoke、SIP/数据回执审计及每日连续模拟。

## 研究协议重要纠偏

- 旧 baseline.yaml 的 2025+ 封存仅约束**旧实验自身**；新 V4 可按真实数据与新滚动研究协议纳入最新交易日，但不得重写旧证据，也不得把已见过的 2025–2026 历史伪装成独立测试。
- 概率必须显式区分未校准 Logistic 与样本外经过验证的已校准概率。
- 单个因子 IC、风格延续状态或多因子排名都不是完整成本后交易优势。
- 没有满足准入的候选时应输出“无交易计划”，严禁为了让 UI 有内容编造信号。

## 可在具备本地完整仓库时运行

\`\`\`powershell
uv sync --locked
uv run --locked pytest -q tests/test_factor_expression_v4.py tests/test_factor_diagnostics_v4.py tests/test_portfolio_risk_v4.py
uv run --locked pytest -q
node --check src/quant_research/assets/studio.js
.\scripts\start_console.ps1 --port 8766
\`\`\`

此文档可作为后续开发和 code review 的持续验收清单；对未完成项必须保留明确的外部数据/验证依赖，不能标为完成。
