# QDR L3 · 个股 Alpha 重构方案与当前实现

- 更新日期：2026-11-20
- L3 原始定位：**自定义因子研究 → 因子验证 → 多因子组合 → 每日横截面选股 → 条件 Alpha 预测 → 前向复盘**。
- L3 不等于固定“超跌/卖压衰竭/重新转强”扫描器。反转、动量、波动、量价、行业相对强度或用户 DSL 只是可选因子族。
- L3 回答“具体研究哪只股票”；L4 独立回答“是否做、做多少、如何退出”。
- Alpha Score 与收益预测严格分开：**组合分位不等于预期收益率**。

## 1. 产品闭环

    创建/复制因子
       ↓
    冻结定义并运行历史实验
       ↓
    查看 H1/H3/H5 Rank IC、覆盖率、稳定性
       ↓
    选择 2–8 个完成实验 + 权重
       ↓
    保存并冻结 Alpha Strategy
       ↓
    显式启用一个当前组合
       ↓
    T 日收盘后计算真实当前因子
       ↓
    冻结 AlphaDailyRun
       ↓
    今日候选（Alpha Score / 因子贡献）
       ↓
    若存在严格匹配的 OOS/forward 模型：
    Alpha-only / +L1 / +L2 / Full
       ↓
    H1/H3/H5 expected excess return / P(up) / P(down)
       ↓
    L4 风控
       ↓
    T+H 后真实结果复盘

没有匹配的收益模型时，L3 **仍允许展示真实冻结的 Alpha-only 排名**；收益、概率字段保持空，不填示意数据。

## 2. 页面结构

一级导航仍为 **③ 个股 Alpha**，默认进入“今日选股”。

二级：
1. **今日选股**：当前组合、股票池/完整因子数量、候选、H1/H3/H5、因子贡献；匹配到条件模型时再显示收益与概率。
2. **因子组合**：有效因子库、2–8 因子权重、保存新版本、冻结、显式启用、历史版本。
3. **因子实验室**：创建/复制因子、显式股票池、真实历史实验、因子证据。
4. **验证与回测**：组合 Rank IC/相关性、A/B/C/D 样本外增量、冻结结果复盘。

旧的“组 A=超跌、组 B=卖压衰竭、组 C=重新转强”硬编码已从 L3 选股工作台删除。

## 3. Alpha Score

当前组合使用可解释的日横截面百分位：

    每个因子 T 日真实值
            ↓
    同一股票池横截面 rank(pct)
            ↓
    只保留全部启用因子均有值的股票
            ↓
    Alpha Score = Σ(weight_i × factor_percentile_i)
            ↓
    再次计算横截面 Alpha percentile

规则：
- 因子权重合计必须为 100%。
- 不填补缺失因子。
- 因子必须在 T 日 cutoff 前实际可得。
- 当前候选默认取 Alpha percentile ≥ 80%，可以自然得到 0 个候选。
- 每只候选保留逐因子贡献，便于解释。

## 4. H1/H3/H5 条件模型

保留现有四组模型：

- A = 用户 Alpha 因子
- B = Alpha + L1 市场
- C = Alpha + L2 风格
- D = Alpha + L1 + L2

D 不会因为“四层完整”自动启用。只有与 A 在相同 OOS 样本上配对比较，并同时满足预设的概率质量与收益误差增量证据时，当前产品层才允许选用 D；否则默认 A。

前向预测与每日 Alpha 排名必须同时匹配：
- session
- source snapshot
- factor set
- frozen strategy version

不匹配时只显示 Alpha Score，不拼接旧模型的收益/概率。

## 5. 两条每日运行路径

### 5.1 Alpha-only 当前排名

目的：即使历史 PIT 模型尚未完成，也能从今天开始积累真实 forward Alpha 记录。

输入要求：
- 已完成的 feature-price audit；
- Alpaca SIP raw 源；
- split-adjusted feature price；
- vendor reference comparison = PASS；
- 知识 cutoff 在 T 日收盘信号之后、T+1 开盘之前；
- 当前启用的冻结多因子组合；
- 所有组合因子在 T 日可计算。

产物：
- outputs/l3_factor_snapshots/<session>/<identity>/
- outputs/l3_daily/<session>/<identity>/

所有产物哈希化、只写一次，不产生收益预测或交易资格。

### 5.2 严格条件预测路径

现有 V4 preflight、OOS、forward、L2→L3 binding 继续保留。只有严格 V4 bundle 通过原有 source/time/cohort preflight，才能冻结对应收益模型结果。

严格路径失败不会篡改 Alpha-only 当前排名；Alpha-only 路径成功也不会降低严格模型的资格标准。

## 6. 自定义股票池

Factor Lab 已支持实验显式传入 5–1000 个不重复代码，必须包含 SPY 作为基准。

现在区分：
- 默认基础研究池：EXPLICIT_CURRENT_ETF_LIST_NOT_PIT
- 自定义证券列表：EXPLICIT_CUSTOM_SECURITY_LIST_NOT_HISTORICAL_PIT

自定义股票池不会再被错误标记为 ETF proxy，但它仍然是 **current-vintage explicit list，不是历史 PIT 股票池**。

当前前向 Alpha 路径会做最低价格与 ADV20 过滤，但现有资产观察接口仍不能独立证明 stock vs ETF 类型，因此当前系统**不会宣称已完成全市场普通股类型资格验证**。要做严格历史个股回测，仍需历史 membership、退市、公司行为和 raw execution price 证据。

## 7. 主要代码

| 能力 | 文件 |
|---|---|
| 当前启用组合 | workflow/l3_strategy_activation.py |
| 当前真实因子快照 | workflow/l3_current_factors.py |
| 不可变 AlphaDailyRun | workflow/l3_daily.py |
| L3 聚合产品 API | workflow/l3_overview.py |
| 因子实验 | research/factor_lab.py / workflow/factor_lab.py |
| 多因子策略 | research/strategy.py / research/composite.py |
| OOS / Forward | models/v4_oos.py / models/v4_forward.py |
| 条件模型 A/B/C/D | workflow/v4_alpha.py |
| L2→L3 绑定 | workflow/l2_l3_binding.py |
| L3 UI | assets/v4_ui_l3.js / assets/v4_ui_l3.css |

## 8. API

- GET /api/v1/l3/overview?horizon=3&limit=20
- GET /api/v1/l3/active-strategy
- POST /api/v1/l3/active-strategy

Factor Lab preview 允许可选 symbols；网页实验室也可直接填写显式股票池。

## 9. CLI

    # 启用一个已经冻结的多因子策略
    .\.venv\Scripts\python.exe -m quant_research.cli l3-activate --strategy-version <UUID>

    # 对显式股票池做 split-only feature-price audit
    .\.venv\Scripts\python.exe -m quant_research.cli feature-price-audit --symbols SPY,AAPL,MSFT,NVDA,AMZN,META,GOOGL,AVGO,AMD --asof 2026-11-20 --action-end 2026-11-20

    # 用已审计特征价格冻结当前因子 + Alpha 排名
    .\.venv\Scripts\python.exe -m quant_research.cli l3-current --date 2026-11-20

    # 只读产品聚合，不重新计算排名
    .\.venv\Scripts\python.exe -m quant_research.cli l3-overview --horizon 3

如果本地已有多个 feature-price audit，可用 l3-current --feature-price-run <run-id> 显式指定。

## 10. 当前完成与未完成

### 已完成代码
- L3 默认入口改为结果优先的每日选股工作台。
- 旧 A/B/C 固定语义选股页删除。
- 因子组合保存、冻结、显式启用。
- 自定义股票池历史因子实验。
- Alpha-only 当前因子快照与不可变每日排名。
- Alpha-only 与严格收益预测解耦。
- 精确匹配的 H1/H3/H5 forecast joining。
- A/B/C/D OOS 增量门。
- 四层总览区分“Alpha 排名已冻结”和“收益模型已匹配”。
- 页面/API/归档均保持 research-only / no real orders。
- 新增 L3 单元/静态 UI/浏览器回归测试代码。

### 尚需真实本地环境验收
- 实际执行完整 pytest / 浏览器回归。
- 对目标 100–300 只美股完成真实 Alpaca 数据导入与 feature-price audit。
- 跑出首个真实 l3-current T 日归档。
- 历史 PIT 股票池、退市、完整公司行为、raw execution price 仍未满足，因此严格历史个股 Alpha 回测和可交易资格仍是 BLOCKED。
- 条件预测只有在已有模型与当前日、来源快照、因子集合完全一致时才显示。

**本文件描述当前代码结构，不代表历史 PIT、模型盈利能力或实盘执行已经验收。**
