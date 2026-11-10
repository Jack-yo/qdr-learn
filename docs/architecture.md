# 架构与边界

P0 调用链：CLI → Settings → TradingClock → DailyBarProvider/FixtureProvider → DailyBar + validate_bars → Observation + require_asof → JSON 快照/报告/日志。

信号与历史研究标签严格分离：demo 只展示计划入场/退出时点，不把未来开收盘读入决策特征。fixture 全量快照包含信号日之后的测试数据；决策视图只包含 event_time 与 available_at 均不晚于截止时间的数据。require_asof 对违规输入直接抛错；读取层先选取合法视图。

未来模块目录已预留但尚未实现：features、research、models、validation、backtest、risk、reports、app。新增 Factor 和模型的正式协议在 P2/P4 定义；P0 不制造空壳业务实现。

P0 演示持久化为 JSON。P1 已加入 DuckDB/Parquet、统一 PriceRecord 与 PriceProvider 协议、原始响应缓存、来源版本及观测记录；详见 p1_data_pipeline.md。统计/机器学习依赖到相关阶段再加入。合成数据生成不依赖网络，运行产物排除出 Git。

交易日历来源为 exchange_calendars XNYS，显式覆盖 2016–2027；超范围拒绝。日历不表示供应商完整性，也不能识别个股临时停牌。上游规则与临时休市应在升级时复核。

参考： https://github.com/gerrymanoim/exchange_calendars （2026-11-06 查阅）。

Yahoo 替代路径：CLI → YahooProvider → yfinance/RecordingSession → 保存 chart 原始字节 → parse_chart → PriceRecord/CorporateAction → DuckDB/Parquet/审计。离线只读本项目原始响应缓存；不调用 yfinance、不重建历史可用时间。原始价与 Yahoo 调整价由 schema 限制隔离，成交守卫拒绝后者。已有数据库经 schema v2 增列保留历史记录。

P2 路径：CLI → 冻结 Experiment/日期边界 → Warehouse 日期与可用时间过滤 → FactorContext 日历矩阵 → Factor 插件/因果前缀检查/依赖 available_at → features_daily；独立 labels → 分区 purge/gap → 日 IC/块 bootstrap/分组/条件/相关性 → CSV/Parquet/HTML+SVG。schema v3 保存衍生数据，strict 与 retrospective 隔离。features 模块不导入 labels。

P3–P6：models/settings冻结参数 → features/states因果观测与训练阈值 → validation/walk_forward标签purge与gap → sklearn训练内imputer/scaler/Ridge/Logistic → A–D预测 → backtest/simulation选择已知信号 → PortfolioEngine事件现金/持仓/成本 → 风控、逐笔/净值/条件报告。PaperLedger复用同一step引擎，SQLite事务保存跨日状态。scheduled-run先刷新，失败输出空建议而不推进账本。没有券商客户端。

schema v4 新增 predictions/orders/fills/positions/equity_curve；执行审计附record_json。P3–P6 source fixture为独立随机流v2，模型/成交数据快照哈希必须相同。P0–P2老fixture不变，保留既有可复现性。
