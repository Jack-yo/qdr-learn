# 卡点清单与网上解决路径

核查日期：2026-11-07（Asia/Shanghai）。本轮读取实际代码并查询官方文档；没有开通账户、购买订阅、获取新数据权限，也没有修改交易规则。供应商页面可用不等于账户实际可访问；样本覆盖不等于全市场覆盖。本轮仅做诊断与方案整理，不新增测试通过声明。

现有证据：20只真实ETF、49520条最新日线、109自动化测试通过；P3/P4当前版本回溯、P5真实执行阻断、P6观察日报无建议。完整个股系统尚未真实验收。

## 全部主要卡点

| # | 卡点与阶段 | 目前实际状态 | 可行解决路径 | 解除条件 |
|---|---|---|---|---|
| 1 | Alpaca账户权限，P1 | 本地适配器需要环境变量，20证券长历史未实测；连接器曾只验证短区间 | 免费Basic账户历史SIP，明确feed=sip、adjustment=raw、end早于现在15分钟；按月分页缓存 | 账户实际成功返回20证券2017至今日线，缓存重放/幂等/覆盖审计 |
| 2 | raw行情与信号价格口径，P1/P2/P5 | Yahoo OHLC为拆股调整，Adj Close单独存；不能充当raw成交 | Alpaca raw；备选Norgate unadjusted、Massive adjusted=false；Sharadar须按官方公式重建raw OHLC | 对拆股前后、早收盘、零成交、缺日样本逐项比对，复权、成交、标签分层 |
| 3 | 历史股票池与退市，P1/P4/P5 | 只有当代20 ETF列表，非全市场PIT | 免费可从今天起存逐日名册和资格；历史可评估Norgate Platinum、Sharadar成分变更/退市主表、Massive按date查询 | 得到有生效日期/可用时间/退市覆盖的名册；历史指数成分不等于全市场股票池 |
| 4 | 稳定ID、换代码和代码复用，P1 | SYMBOL-UNVERIFIED身份；ticker不能唯一代表跨期证券 | Sharadar permaticker + actions；Norgate asset ID；有机构权限可用CRSP PERMNO；建立有效期映射 | 改名、代码复用、多股类、并购映射测试通过；CIK只能辅助，不能独自区分股类 |
| 5 | 公司行为、退市最终结算，P1/P5 | Yahoo行动未经交叉核验，现金支付/换股/分拆缺真实事件流水 | Alpaca corporate-actions、Sharadar actions、发行人公告；FINRA补OTC事件；CRSP可核验部分退市收益 | 区分公告/生效/除权/支付日；登记应收股息、支付现金、换股、碎股及无法核验事件阻断 |
| 6 | 历史信息可用时间，P1–P4 | 抓取时才首次观测；历史数据strict均不可用；当前版本不证明历史已知 | 保留ingested_at；新增有凭据的source_published_at/重建策略与版本；原始SEC申报按accession回溯；前向持续存档 | 明确原始历史归档、事后重建、当前版本三类；禁止把历史available_at直接改成close |
| 7 | 行业分类和两项行业因子，P2/P4/P5 | 行业全部UNKNOWN；行业残差/相对强弱缺真实输入，行业限额保守合并 | SEC按期as-filed SIC，或Sharadar sicchangefrom/sicchangeto；固定SIC到行业ETF映射并版本化 | 历史有效期、首次可用时间和未知分类测试通过；SIC代理不能称为GICS |
| 8 | PIT基本面和历史市值，P1/P2 | SEC只试取两公司当前聚合快照；size/quality禁用 | 免费SEC FSDS/as-filed原文件+accession/accepted时间；Sharadar ARQ/ART/ARY，禁止MR数据回填 | 处理修订、单位、期间、股数口径、披露时点；仅在启用这些因子时才是必需依赖 |
| 9 | 模型/回测/纸面入口接线，P3–P6 | load_panel只支持fixture/yahoo；backtest、daily、PaperLedger显式只允许fixture | 抽象受验收的DatasetBundle/能力矩阵，把raw/PIT/identity/action/time逐项证据接入；扩展源白名单和端到端测试 | 合格数据能贯通；不合格数据仍拒绝；不能简单删除fixture判断。此项是工程欠账，不是购买数据就自动解决 |
| 10 | 日报时钟与供应商延迟，P6 | 固定close+15min；稍晚抓取就无信号；现有数据源可能17:30或更晚更新 | 记录真实决策时刻、数据截止时刻、首次观测时间；冻结发布策略，决策晚于到达且早于下一open；仍只使用协议允许的T收盘信息 | DST/早收盘/迟到/修订/断网/错过open测试通过；规则变更先冻结，不倒填时间 |
| 11 | 成交成本和开收盘语义，P5 | 5/10/20/50bps是情景，不是实测成本；日线open不保证实际成交 | 用小样本历史SIP报价/成交核验买卖价差、开收盘/拍卖口径、冲击；保留保守敏感性 | 真实现金与持仓对账、停牌/缺bar无假成交、成本参数有证据或明确仍为假设 |
| 12 | 模型效果/校准，P3/P4 | 市场H1/H3/H5 Brier未稳定优于常数概率；不确定性为空 | 继续固定基线、按时间验证、配对块bootstrap；校准器仅过去样本拟合；没有增量则保留状态报告 | 无优势也可完成研究流程；不能以调参到赚钱作为验收条件，不能承诺性能 |
| 13 | 独立最终测试，P3–P5 | 2025起封存，未作策略最终评价 | 先冻结合格数据、目标、成本、参数、准入标准，再一次解封；反复使用后必须重新声明非独立 | 保存冻结hash、一次运行记录和负面结果，不能把解封本身算作策略成功 |
| 14 | 真实前向模拟，P6 | 只有合成跨日账户续记；真实数据仅观察 | 固定当前ETF/股票池用于从现在起的前向研究，存真实每日版本，在raw/时钟/公司行为/账本资格通过后开始纸面记账 | 连续真实交易日运行、周末/节假日/公司行为/重启/重复运行/失败恢复验收；不能伪造已过多日 |
| 15 | 本地运行与运维验收，P6 | 页面可用；调度仅示例，未注册；CI其他平台未实跑 | 单写任务队列/进程锁、数据库备份恢复、实际调度日志、离线重跑、Windows/Linux CI | 本机运行证据和远端实际结果分别记录；109本地测试不代表生产或多平台验收 |

## 官方来源与新发现

1. [Alpaca Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)：无实时SIP订阅的历史查询end须至少15分钟前；IEX是单一交易所；OTC另有特殊权限。因此日频方案不应直接假设必须购买实时SIP。还说明ticker asof映射及行情聚合条件。
2. [Alpaca方案](https://docs.alpaca.markets/us/docs/about-market-data-api)：Basic免费、历史从2016、200请求/分钟；Algo Trader Plus公开价99美元/月。实际账户资格和覆盖待实测。
3. [Alpaca历史bars](https://docs.alpaca.markets/us/reference/stockbars)：raw/split等调整参数、全页总条数限制与分页规则。[公司行为](https://docs.alpaca.markets/us/reference/corporateactions-1)明确不保证创建/到达时间；process_date不能自动作为历史公告时间。
4. [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)：免费，无API Key；历史submissions有附加分页文件；companyfacts是聚合，bulk夜间重建。[SEC FSDS](https://www.sec.gov/dera/data/financial-statement-data-sets.html)提供as-filed结构化财务和SIC，可用于按原申报重建；季度数据包发布日期不等于原文件发布日期，仍需accession连接与时点核验。
5. [Sharadar官网](https://sharadar.com/)宣布免费入门样本含30只道指公司基本面和行情，AAPL有公开测试示例；这不是历史道指成分或全市场数据。网页工具访问测试API未成功，本轮未验证实际拉取或免费历史深度。
6. [Sharadar基本面](https://sharadar.com/docs/fundamentals)：ARQ/ARY/ART为as-reported/PIT方向，MRQ/MRY/MRT为最新版本；日期只有日级时应保守滞后，不能假定收盘前已发布。[股票价格](https://sharadar.com/docs/stocks)：默认OHLC拆股调整，closeunadj只直接提供未调整收盘，完整raw OHLC须按官方说明重建且验证精度/舍入。不能将原open字段标raw。
7. [Sharadar FAQ](https://sharadar.com/docs/faqs)：permaticker、并购现金/换股、历史SIC变更；并购对价约99%是供应商自己的覆盖估计，不是本项目实测。[历史标普成分](https://sharadar.com/docs/sp500)含增删生效日及历史季度快照，仍需重建每日资格及公告可用时点。
8. [Sharadar公开价格](https://sharadar.com/subscribe)，个人用途许可：10年Prices 19美元/月、199美元/年；10年Bundle 49美元/月、399美元/年；Full History Bundle 69美元/月、499美元/年。29美元/月Bundle仅5年，不覆盖本项目完整2017起训练期。10年窗口会随时间移动，长期复现需核对授权和本地保留条款。价格截至核查日，未购买。
9. [Norgate套餐](https://norgatedata.com/stockmarketpackages.php)：Platinum含历史指数成分和部分类型退市证券，1990起，346.50美元/6月或630美元/年；Gold不含这两项。标注的是Current Fundamentals，不能据此宣称获得PIT财务。[数据FAQ](https://norgatedata.com/data-package-faq.php)列出raw等复权方式及三周试用；试用不是长期免费许可证。[覆盖说明](https://norgatedata.com/data-content-tables.php)有退市类型限制。
10. [Massive证券主表说明](https://massive.com/knowledge-base/article/does-massive-have-a-downloadable-security-master)：可按日期重建名册，但无跨所有变更绝对永久ID，Basic参考数据仅两年，其他档历史更深。不能承诺免费覆盖2017起。[原始价格口径](https://massive.com/knowledge-base/categories/stocks)和[flat-file到达时间](https://massive.com/knowledge-base/article/what-time-are-massives-flat-files-ready-each-day)：raw与到达时点必须分别核验，某些文件次日才到，不适用T晚决策。
11. [FINRA Daily List](https://otce.finra.org/otce/dailyList?viewType=Symbol%2FName+Change)：可补OTC新增、删除、改名和公司行为，不能替代所有上市交易所历史名册。
12. [CRSP官方股票库指南](https://www.crsp.org/crsp_pdf/crsp-us-stock-indexes-databases-guide-flat-file-format-1-0/)：永久标识及退市记录/收益字段。若已有学校/机构授权可考虑；本项目未有权限，未核验报价。

## 建议顺序（保留仅用免费的当前偏好）

1. 先实际验证Alpaca Basic历史SIP raw权限、数据覆盖、单日到达时间，不先购买实时行情；Sharadar免费样本仅做PIT/证券映射接口试验。
2. 完成能力化准入和模型/回测接线、原始价/事件账本/时间策略。把观察、当前版本回溯、前向纸面、严谨历史回测分开，全部保留真实状态，不把一个能力缺口扩大成所有功能不可做。
3. 用SEC历史原申报补SIC与可选基础财务，不必等待全量PIT财务才推进无基本面模型。
4. 合格后从固定日期开始前向纸面，明确研究模型尚未验证；历史全市场退市PIT不足继续阻断严谨历史回测。
5. 若以后愿意付费，优先小样本检验Sharadar或Norgate，而不是先买昂贵实时行情。供应商数据仍须验证；任何方案都不自动解决代码接线、历史版本、时钟、模型无优势和持续模拟观察。

此前把剩余工作概括为外部数据不足不完整；代码接线、能力门槛、事件记账语义、时钟、运维与前向验收也是剩余工作。109测试代表已有实现的已覆盖行为，不代表这些新增需求已完成。
