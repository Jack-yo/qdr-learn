# G4.4 真实经典因子监测与研究接线

2026-11-07。本轮交付可运行的经典因子观察/归因流程，不宣称四层模型、严格历史预测、回测或模拟交易整体验收完成。

## 实际完成

- `data/french_bundle.py`：独立读取分类French库。先按知识截止筛版本再选最新；逐行核对官方ZIP里的因子日期和值、原文SHA及不可变来源回执。返回冻结快照副本；缺源、篡改、时点不符或日期未覆盖时拒绝，不改读ETF/Yahoo。
- `research/style_monitor.py`：8条序列的5/20/60交易日统计、20日年化波动、观察四态、状态变化与60日相关性；完整日历轴，缺失不补零/不前填，窗口来源可用时间取输入并集。RF只作参考。
- `workflow/styles.py`、`cli.py`：style-report命令，观察或研究两种范围；CSV/Parquet/JSON/HTML、源/参数/代码hash及不可变run_id。最新观察与研究指针分开保存。
- `web.py`、`styles.html`：/styles真实页面、日期/知识截止选择、5/20/60窗口、因子选择、滚动曲线、摘要CSV、来源明细；独立API及“生成最新观察报告”后台任务。与Alpaca价格能力分开准入，ETF输入受阻不影响French事后观察。
- `workflow/maintenance.py`：French周更完成且写连接关闭后，在同一维护进程的锁保护下生成观察报告；外部读者仍受维护锁阻断，未删除写锁或风控。
- `data/catalog.py`：经典因子类别增加研究产物位置及最新观察报告指针。日常分类仍9类。
- `tests/test_styles.py`：9项真实缓存、公式、前缀因果性、缺失、原文、知识截止、封存、维护锁及HTTP/CSV验证。

## 数据与真实结果

主源：分类库`data/managed/classic_factors/factors.duckdb`，仅KEN_FRENCH / ATTRIBUTION_ONLY。

观察范围2017-01-03至2026-09-30：2,449交易日×8序列=**19,592**数值，缺失因子会话0。官方FF5/RF 14,694条、Mom 2,449条、ST_Rev 2,449条分别逐行匹配3份原文。最新源数据日明确显示2026-09-30，不冒充最新行情日2026-11-06。

研究模式默认截止2024-12-31：**16,096**数值、8条最新摘要；SQL读入前限制日期，拒绝研究模式进入2025+。2025+只在观察模式展示已发布的因子值和描述统计，没有训练、策略评估或最终测试解封。

最终代码观察报告：`outputs/styles/a15f963f-474e-42b7-9889-2824ae2c4632/report.html`；快照SHA=47f408d1eedd6993c265bbb8c2eb46db2001aa303f7af93cc601bc3dc5bc03f5。

研究范围实测：`outputs/styles/a88d15f2-5cb2-4b9e-83c3-dfc75dc104b0`。API触发的真实报告任务：`outputs/styles/f30d3e24-2494-457c-a8f5-c2b7cba418f3`，COMPLETED、exit_codes=[0]，不是只检查任务启动。开始/完成证据在outputs/styles/api-verification.json、job-finish.json。

周更联动实测：`outputs/maintenance/45bdedd2-9f1d-46e7-93a9-ad5e875671bd`，French入库新增0、style_monitor_status=GENERATED，生成`outputs/styles/7e9abcc2-fb41-44c3-8360-305cc81a97fb`。数据更新与报告生成分别记录，数据采集成功不等于研究资格开放。

## 计算口径

协议固定为`french-descriptive-v1`：

1. W日滚动值为最近W个交易日的每日因子收益**算术和**。这是一种归因描述，不是长短组合复利净值、含成本回测或ETF相对收益。
2. 20日波动为样本标准差（ddof=1）×sqrt(252)。
3. 状态水平=mean(r,20)，加速度=mean(r,5)−mean(r,20)。分别以固定0为界，得到强势加速/强势减速/弱势改善/弱势恶化；不使用全样本拟合阈值。此协议不替换原ETF模型的训练期阈值规则。
4. 任一必要会话缺失，对应窗口为null、状态UNKNOWN；首次建立状态不虚构“状态转折”。RF状态固定REFERENCE_ONLY，不参加四态轮动判断。
5. 查询日距当前会话数按已结束交易日计算。历史查询时描述的是选中日期距当前的间隔，不代表French全库只覆盖到该历史日。
6. 相关性按最近60会话且至少60个有效配对计算；方差为0或配对不足保留null，不填0。

所有decision_eligible=false，model_version=null，prediction_rows=0，research_grade/execution_ready=false。当前ZIP中的历史修订不能当历史当时已知数据。

官方定义参见[French因子库](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html)和[五因子构造说明](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_5_factors_2x3.html)。现存文件的源版本及首次观测时间逐份输出；官方自2025年起使用CIZ格式，不能假设历史发布版本恒定。RMW是盈利因子，不直接等同QUAL ETF；本页没有用ETF伪装纯因子。

## 复现命令

```powershell
# 当前已发布因子观察，不联网。
.\.venv\Scripts\python.exe -m quant_research.cli style-report
# 开发/验证范围，最终策略测试保持封存。
.\.venv\Scripts\python.exe -m quant_research.cli style-report --mode research
# 指定日期和知识截止，仍然是当前版本回看。
.\.venv\Scripts\python.exe -m quant_research.cli style-report --asof 2024-12-31
# 因子维护后自动生成最新观察报告。
.\scripts\maintain_data.ps1 --offline --groups french --end 2026-11-06
# 全量及最终专项。
.\.venv\Scripts\python.exe -m pytest -q -rs --junitxml=outputs/styles/tests.xml
.\.venv\Scripts\python.exe -m pytest tests/test_styles.py -q -rs --junitxml=outputs/styles/final-focused-tests.xml
```

## 测试及限制

全量**84 passed、1 skipped，141.03秒**。唯一跳过仍是Yahoo最新真实缓存缺OHLCV，不计通过。最后补齐通用API data_quality_flags字段后，9项专项重新执行；实际最终结果见outputs/styles/final-focused-tests.xml及phase_acceptance.json，不把专项与全量重复相加。

测试验证：真实滚动结果与源窗口一致；前缀不因后续观测加入而改变；删除一个实际SMB观测后拒绝产生完整窗口；篡改值、缺回执、早于首次观测的截止、无覆盖日期、研究进入封存期分别阻断；维护锁只允许持有锁且已关闭写连接的本进程派生。

本机HTTP实际验证：/styles页面结构、8序列、研究CSV 8行、FRENCH来源与asof、缺日409、封存409，后台报告任务实际完成。浏览器技能在本轮所列安装路径缺失，未将HTTP/JavaScript语法检查当成浏览器视觉或完整Playwright验收。React完整九页仍待实现。

## 下一主干

将真实输入与研究协议继续接到因子实验流程、模型评估及策略工作流。历史可用时点、历史股票池/退市/永久身份、现金事件账本及执行资格保持独立阻断；ETF风格代理和预测增量检验尚未随本次French观察功能一并验收。未新增实盘交易、付费服务、盈利声明或伪造样本。
