# v2.1 REAL_ONLY（优先于下方历史记录）

以 docs/codex_handoff_v2_1/AGENTS.md 及01_统一规范为执行规格，用户当前指令优先。
正式CLI/API/研究/报告/模拟账本禁止合成行情，缺数据返回结构化BLOCKED。旧生成器与市场测试只在archive/pre_real_only留档，不可执行或作验收证据。数学常量单测允许；市场集成只用有来源/哈希的真实缓存，无数据标BLOCKED。禁止购买、注册账户、实盘交易、解封最终测试。G0→G5分阶段验收，不沿用109旧测试为新证据。
以下为历史约束，涉及fixture/demo或P0–P6完成的声明全部失效，仅保留供迁移参考。

# 工程约束

以用户当前指令和 `docs/Codex_美股多层量化研究系统_开发任务书.md` 为项目规格。P0–P6 工程实现及离线合成验收已完成，100 测试通过；真实研究/交易就绪仍 NOT_READY。原 Alpaca/原始成交价/PIT/退市等缺口保留，真实最终测试未开放。详见 docs/final_acceptance.md、docs/system_guide.md。

- 计算代码放 src，核心流程可 CLI 调用。新增供应商遵守统一 provider 协议。
- 交易协议唯一：T 收盘后计算；T+1 原始开盘价入场；T+H 收盘退出（H=1/3/5）。日历使用 XNYS 和美东时区规则，存储 UTC aware 时间。
- event_time、available_at、ingested_at 不可混淆。available_at 超过信号或数据截止时间时拒绝；禁止最新财报、市值、当代成分股回填历史。
- 合成、探索性和不完整数据必须显式标记。不得虚构历史、退市、绩效、胜率、测试结果或置信度。
- Yahoo OHLC 标记 yahoo_split_adjusted，Adj Close 分开保存。不得因 auto_adjust=False 就标为 raw；企业行为现金口径未核验，不能自动用于成交/现金记账。available_at 仍为首次观测，不回填历史。
- P2 默认 strict；retrospective 仅当前版本回溯描述，decision_eligible 一律 false，正式 raw 标签为空。P4/P5 不得将其当历史可交易特征/成交标签。2025 起最终测试期在价格读入前隔离；训练末尾 gap 至少 5 session，标签跨边界需 purge。
- 新 Factor 需声明真实回望及依赖、保持日历轴，补公式/未来扰动测试；不能靠插件抽查宣称任意代码已获无泄漏证明。
- P3–P6 用 stream fixture v2（按证券独立随机流），P0–P2 老版本仍保留；扩展 end 不能改历史。模型变换仅训练内拟合，季度重训，1260-session窗口/至少252-session、实际label purge+5-session gap，固定参数，不因亏损自动改规则。
- 执行/纸面入口目前只接受合成 raw/strict。Yahoo retrospective不能进成交引擎；纸面SQLite配置冻结、单写、逐session、重复日期幂等，不得静默改旧流水或跳过交易日。
- live日报训练标签最多到2024，后续forecast行不得读取实际未来收益；真实final-test仍封存。日频上限漂移只能下一可交易事件调整，不能倒造收盘成交。不可定价头寸冻结新入场，不伪造结算。
- 不实现真实交易；凭证仅通过环境变量注入，禁止提交 .env 或日志泄密。
- 模型训练和归一化仅用过去数据；目标、时间划分、purge/embargo、成本、阈值和启停规则必须先冻结。
- 每阶段运行 pytest 和离线 demo，汇报 DONE/TESTS/DATA/RESULTS/RISKS/NEXT。没有当前阶段测试证据不宣称通过。

## 用户长期模型分工

- 主代理默认 gpt-6-astra，负责方案、关键业务规则、复杂推理、最终代码审阅和验收。
- 边界明确且确有帮助的搜索、代码定位、常规编码和验证优先交给 gpt-5.6-luna；显式指定 medium，fork_turns=none，提供最小必要背景。
- 分派明确目标、文件、可修改范围、约束、输出和验收，不覆盖未提交改动；独立任务才并行。
- 主代理核验重要来源和实际改动，投资目标、时间切分、风险阈值及策略启停由主代理决定。
- 指定型号不可用时告知用户并由主代理接手，不静默换用其他昂贵模型。子代理不得自行继续分派。
