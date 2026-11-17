# QDR L1 六大数据体系 / 十二维市场数据基础设施

版本：2026-11-17。此文档描述正式工程范围和当前代码能力，不表示所有来源已经取得权限、所有数据已经抓取或模型已经具备预测资格。

## 1. 统一层级

- 六大数据体系：一级业务/研究模块。
- 十二个市场数据维度：二级数据分类。
- Feature Registry：每个指标的单位、频率、来源候选、历史目标、优先级、接入状态、访问要求和 PIT 时点要求。
- Data Store：原始回执、日频 bars、每日 universe、标准化观测、事件 vintage。
- Feature Engine：六大体系的历史计算。
- Quality/PIT：覆盖、时效、缺失、来源回执和首次可得时点。
- L1 forecast：只接收经过独立历史验证的特征；path 是未来结果标签，不是输入。

## 2. 六大体系与十二维映射

| 一级体系 | 二级维度 | 主要输出 |
|---|---|---|
| 全市场广度与行业结构 | 02 breadth、07 correlation | A/D、上涨/下跌成交广度、均线广度、新高新低、同步下跌 |
| 波动率与期权风险定价 | 03 volatility、04 options_pricing、05 options_positioning | RV、VIX 家族、期限结构、IV skew、VRP、OI 集中度 |
| 行业轮动与风格因子 | 01 price、07 correlation | 行业/风格相对强度、离散度、相关性、动量 |
| 市场流动性与资金流 | 06 microstructure、09 positioning、11 funding | spread、depth、ETF flows、COT、short interest、融资利差 |
| 宏观与跨资产风险传导 | 08 cross_asset、11 funding | 国债、实际利率、美元、信用、商品、融资压力 |
| 催化剂与市场预期 | 10 events | 已知事件日历、发布时间、当时一致预期、实际意外值 |
| 交叉验证层（不属于第七个输入体系） | 12 path | H1/H3/H5 未来收益、MFE/MAE、先触及事件标签 |

01 价格趋势是共享基础数据；07 相关性、11 融资条件跨体系复用；12 价格路径是 outcome/label，不能成为预测输入。

## 3. 当前代码审计基线（main）

已有：
- Alpaca 1Day bars 适配器，ETF 默认池为 19 个 symbol；单次请求限制 50 个 symbols、分页最多 15 页、累计行数上限 150,000。当前扩展股票样本仍固定 30 只大盘股。
- Cboe VIX 历史、Cboe 每日汇总 Put/Call 与 SPX 汇总 OI。
- Treasury 2Y/10Y、NY Fed SOFR/EFFR、CFTC 周度持仓、FRED（需 API key）。
- OFR FSI、BLS 已排程日历、Federal Reserve FOMC 会议日历、ICI ETF 周度净发行估算、FINRA 报告设施 short volume、Cboe TRF notional share。
- l1_observatory.py / l1_features.py 已有 12 维研究注册和部分历史计算。

关键缺口：
- 现有 30 股固定样本不是真实全市场广度。
- Alpaca 当前资产目录是当前时点快照，不是历史 PIT 成分/退市证券数据库。
- 当前 Cboe 汇总 PCR / OI 不是逐合约 IV surface、dealer signed position 或完整 Gamma。
- FINRA Short Volume 不是 Short Interest。
- ICI 周度净发行估算不是逐日二级市场资金净流入。
- 当前宏观适配器没有完整 ALFRED vintage 与一致预期历史。
- 盘口深度、订单失衡、完整历史期权链、ETF primary flows 和宏观共识历史需要单独数据授权或合格来源。
- 当前公开扩展特征明确 not_in_model_scores=true；不得因为展示出来就视为已进入 V3。

## 4. 数据标准

所有历史数据记录必须包含：
- session_date：交易所交易日，不以 UTC 日历日代替。
- security_id：永久/供应商身份；仅 symbol 的数据标为 SYMBOL_ONLY_UNVERIFIED。
- provider、price_basis、source、receipt_sha256。
- available_at：该数据实际可用于决策的时点，必须带时区。
- pit_status：默认 PIT_UNVERIFIED。抓取时间或 SHA256 不能单独证明历史 PIT。
- 观察值、发布值、修订值分开保存；不以当前修订版本回填历史。
- 原始供应商响应可按 SHA256 内容寻址存储，禁止保存 API key、secret 或认证 header。

数据存储采用本地 DuckDB + 不可变原始对象；单写进程。先保存日频 OHLCV 和宏观/期权汇总，不默认收集庞大的逐笔或 L2 数据。

## 5. 当前已落地的基础能力

- quant_research.data.l1_market_catalog：六大体系、十二维度、feature/source registry 和实际观测覆盖矩阵。
- quant_research.data.l1_market_store：DuckDB append-only 表、回执 SHA 校验、原始响应对象存储、bars/universe/observations/events。
- quant_research.workflow.l1_market_data：catalog/init/status/import-bars 命令。
- 所有 registry 记录默认 forecast_eligible=false / trade_eligible=false。
- 这是数据基础设施第一阶段；尚不等于全部 provider adapters、全市场 PIT universe 或六大体系实时接入已经完成。

### 5.1 2026-11-17 数据链路与质量审计增量修复

已落地的工程修复：
- 全市场当前资产目录与快照批次分别记录健康状态；资产目录成功而快照失败时，不再把资产目录误报为缺失。
- 快照覆盖率低于 98% 时保留非零观测并标记 PARTIAL；快照日期落后于目标交易日时标记 STALE_SNAPSHOT / PARTIAL。
- 市场广度健康记录引用实际 Alpaca 快照批次回执；广度派生回执不再冒充底层快照回执。
- DuckDB append-only bars、universe、security features 在读取时按稳定身份选取最新版本，避免重复导入后历史计算因重复 session/symbol 失败。
- Coverage Matrix 按交易日、available_at、ingested_at 选择最新观测；最新 MISSING 记录会覆盖同一指标的旧 OBSERVED 值；全部为 PARTIAL 的维度不会被升级为 OBSERVED。
- 修复 SourceSpec 状态字段引用错误，并使 PIT 阻断在覆盖矩阵中可见。
- 新增 Federal Reserve 官方 FOMC 日历解析与 `days_to_fomc` 观测；事件保留页面最后更新时间作为 `schedule_known_at`，并明确标记为当前已发布日程而非历史 PIT。
- 当前 registry：109 个特征（47 IMPLEMENTED / 38 PARTIAL / 24 PLANNED），21 个数据源（1 IMPLEMENTED / 14 IMPLEMENTED_PARTIAL / 1 BLOCKED / 5 PLANNED）。

验收边界：
- 已提交确定性回归测试，覆盖快照批次全失败、低覆盖、回执归属、append-only 修订去重、最新缺失观测，以及 FOMC 日历解析和 schedule-known-at 防前视。
- 这些测试尚未在本机依赖环境执行；GitHub 当前没有返回对应提交的 workflow run。不得将“测试已编写”表述为“测试通过”。
- Alpaca 真实账户的资产目录、快照批次和历史 Bars 权限仍需在用户本机运行 `scan-live` / 历史回补任务验收。
- 当前快照只代表 Alpaca 当前 active/tradable universe，不构成历史 PIT 股票池，也不具备模型或交易资格。

## 6. 本地使用

\`\`\`bash
python -m quant_research.workflow.l1_market_data catalog
python -m quant_research.workflow.l1_market_data init --root .
python -m quant_research.workflow.l1_market_data status --root .
python -m quant_research.workflow.l1_market_data import-bars --root . --input path/to/bars.parquet --provider alpaca --price-basis raw --available-at 2026-11-17T22:00:00Z
\`\`\`

输入文件必须包含 date 或 session_date、symbol、OHLCV。若没有 security_id，系统显式使用 SYMBOL:<ticker> 并标记 SYMBOL_ONLY_UNVERIFIED，不会伪造永久身份。available_at 必须由操作者提供真实时点，不使用本机当前时间替代。

## 7. 开发顺序与验收门槛

### A. 基础设施（本阶段）
- [x] 六大体系和十二维统一注册
- [x] Feature/Source Registry 与当前状态分离
- [x] DuckDB append-only schema 和来源回执
- [x] 本地导入入口
- [ ] 本机依赖环境中执行全部新测试

### B. 真实行情和股票池
- 扩展 Alpaca 多批次历史 bars 下载与断点续传。
- 引入交易所/合格证券主数据并审计 common stock / ETF / ADR / preferred / warrant 类型。
- 对当前股票池可先做前向观察；没有历史 PIT membership 时不回填历史全市场广度。
- 建立 5 年历史目标的实际供应商覆盖报告，不把目标写成既有能力。

### C. 六大体系数据接入
- 扩展公开官方数据源的历史回补、首次可得时间和原始响应存档。
- 期权 IV/Skew、盘口、ETF primary flows、宏观 consensus 等单独进行授权与供应商评估。
- 对每个来源记录覆盖、历史长度、发布频率、延迟、许可和 PIT 资格。

### D. 特征计算与模型验证
- 每个可用维度输出 long-form observations 和质量审计。
- breadth 必须有完整当时成分与退市证券数据；当前成分只能作为 current snapshot。
- 未来路径标签与预测输入隔离。
- 先保留 V3 ETF7 基准，再逐组做 walk-forward / purged OOS 消融；不合格特征不进入预测模型。

### E. 页面与持续运行
- 新增数据覆盖工作区：六体系、十二维、feature/source、覆盖/时效/PIT/权限。
- 每日增量任务和可恢复失败队列。
- 目标机真实 provider 验收、运行报告和连续前向验证。

## 8. 外部数据限制

- Alpaca 历史 Bars 分页的 limit 是每页数据点数而不是每 symbol；必须持续读取 next_page_token。实际可获取范围仍受 feed/订阅、请求速率、symbol 批次和历史授权约束。
- Nasdaq Trader Symbol Directory 可提供当前上市符号及部分 ETF 标记；它是当前目录，不可当作历史 PIT universe 或永久证券身份。
- Cboe 免费公开统计主要是汇总成交量/PCR；详细历史期权链和定制波动数据需要评估其数据产品和许可。
- Databento、Polygon、ORATS、OptionMetrics 等仅作为候选供应商，采购前必须核对产品 schema、历史起始日、退市/成分覆盖、PIT、许可和成本。

## 9. 安全与资格

本项目只读研究，不创建订单。真实行情缺失时保留 MISSING/BLOCKED；代理数据必须在标签上写明 proxy；当前观察不等于历史 PIT；模型研究资格不等于交易资格。未通过真实数据、PIT 和样本外证据验证，不开放交易。
