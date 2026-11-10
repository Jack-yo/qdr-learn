# G4.3 主干数据分类与日常维护验收

日期2026-11-07。按用户“优先主干、数据分类便于日常维护”的要求，本轮重心是可运行的分类数据管线与维护入口。G4整体验收、合格模型、历史回测和前向模拟仍未完成。

## 实际实现

- `configs/data_maintenance.yaml`：每日行情/行为、每周French/SEC，显式ETF名单、历史起点与5会话重叠；不是历史股票池配置。
- `data/catalog.py`：9类台账、权威库索引、版本计数、覆盖日期、数据用途、缺失原因；原文349份回执逐文件SHA核验。输出不可变catalog快照、带SHA的latest指针、分类目录dataset.json及CSV导出。旧混合/验收/fixture库只列隔离清单，不作为正式输入。
- `workflow/maintenance.py`：真实来源维护、增量水位/历史回放、逐源结果、独占维护锁、源失败后继续独立组、保留版本、分类归档。明确把“采集完成”和“研究资格”分开。
- `cli.py`、`scripts/maintain_data.ps1`：data-catalog和maintain-data入口；提供日更、周更、分组重试、离线回放和历史回补。
- `policy.py`：修复实际发现的KEN_FRENCH与FRENCH命名不一致。适配器的真实KEN_FRENCH可入库，仍限定ATTRIBUTION_ONLY；没有放宽合成源拒绝或历史时点限制。
- `data/bundle.py`、`web.py`、`web.html`：维护期间阻断并发读写/工作流；9类台账、固定范围CSV下载、日常维护按钮，沿用Host/CSRF和命令白名单。
- `data/split_evidence.py`、`workflow/feature_price_audit.py`：IWF原始SEC 497申报接入，原稿字段核验8/8；在线SEC请求要求本机合规User-Agent。严格价格精度阈值及BLOCKED结果未改变。
- `tests/test_maintenance.py`：7项真实数据、幂等、增量、分类、锁、导出完整性及单源故障继续测试；原有拆股原稿测试更新为真实8项字段匹配，仍禁止PIT/执行放行。

操作手册见[DAILY_DATA_MAINTENANCE.md](DAILY_DATA_MAINTENANCE.md)，包含分类位置、日常/每周操作、失败处理及备份范围。

## 真实维护证据

1. 首次全组离线运行`outputs/maintenance/439dedbc-2104-41bf-bf17-36faf5dc0323`：行情重放0新增；行为入库1042；French被来源命名不一致阻断；SEC成功。PARTIAL_BLOCKED保留，未改写为成功。
2. 修复后全组运行`outputs/maintenance/d8c33918-f6e7-483a-a858-61bb3763b50b`：MAINTAINED。行情49,520证券日/0缺口/0新增；行为1042/0新增；French148,212数值首次进入独立库；SEC1953索引及941候选、历史可用0。
3. **实际联网日常增量**`outputs/maintenance/eb7de453-8b6c-42a3-a3ec-3a4f1e1e481d`：只读Alpaca SIP，2026-11-02至11-06共100行/0缺口，保留100个新响应版本，未覆盖旧数据。
4. **增量离线重放**`outputs/maintenance/a714911f-e221-4051-9c7b-d334f5a03c7e`：行情0新增、公司行为0新增、French0新增。不是只检查退出码，实际记录了各类插入数。
5. 当前目录`data/catalog/snapshots/81b5edb6-77d5-4516-bce2-694b938196bb`：9类、349份回执、哈希异常0。当前行情99,040个保留版本，对应49,520证券日；公司行为1042、French148212、SEC1953+941。French缓存止2026-09-30，不冒称已到最新交易日。

公司行为首次观测时间统一以UTC展示，不把系统本地+08时间误标为UTC。分类台账的COLLECTED_RESTRICTED_USE仅说明已采集且限制用途；不把数据库存在或条数大于0当研究验收。

IWF原始证据来自[SEC Form 497](https://www.sec.gov/Archives/edgar/data/1100663/000119312526129300/d765912d497.htm)，accession 0001193125-26-129300；原文SHA=74356293404bd3b954baeebaea39d4936becae428c5a871e5dbaaf7d45cbb690。通过实际SEC索引定位并下载，未使用搜索摘要作为原稿。首次观测仍是本次抓取，不倒填历史可用时间。

最新拆股证据`outputs/feature_prices/6b037510-575b-48a3-90fc-420b6e602698`：8/8字段匹配、严格价格精度仍BLOCKED。增量后的raw snapshot=e716fad51c7b951bfd7606a88c67abaa0498f30cb0d39162ac22b5c9d6e1e84c。旧快照和报告保留，不能当新版本数据的凭据。

## 测试与复现

```powershell
.\.venv\Scripts\python.exe -m quant_research.cli maintain-data --offline --full --groups prices,actions,french,sec --end 2026-11-06
.\.venv\Scripts\python.exe -m quant_research.cli maintain-data --groups prices --end 2026-11-06 --env-file .env
.\.venv\Scripts\python.exe -m quant_research.cli maintain-data --offline --groups prices,actions,french --end 2026-11-06
.\.venv\Scripts\python.exe -m quant_research.cli data-catalog
.\.venv\Scripts\python.exe -m quant_research.cli feature-price-audit --offline --issuer-documents --action-end 2026-11-06
.\.venv\Scripts\python.exe -m pytest -q -rs --junitxml=outputs/maintenance/tests.xml
```

全套：**75 passed、1 skipped，125.73秒，0失败/0错误**。跳过仍是Yahoo 2026-11-06真实缓存缺OHLCV。新维护及原稿专项先前12通过；增加导出/锁测试后的最终结果以上述全量XML为准。

主库写入时曾并发启动只读审计，实际触发DuckDB文件锁错误；已增加统一维护锁与结构化DATA_MAINTENANCE_RUNNING，未绕过数据库锁。故障测试还验证价格源失败时真实公司行为仍完成，第二次重放新增0，锁释放，catalog落盘。

API及页面结构实际检查`outputs/maintenance/api-verification.json`：9类台账、CSV内容9行、哈希异常0、日常维护入口存在。现有本机研究台确认IDLE后更新，PID保存在outputs/maintenance/console-pid.txt。未把API检查描述为完整九页视觉/端到端验收。

## 主干剩余与顺序

接下来使用已分类的经典因子库完成风格监测和研究任务，再推进因子/模型/策略工作流接线。精度口径、历史PIT、永久身份、退市与完整现金事件账本继续独立阻断相关能力，不让单一缺口阻断全部独立开发，也不以假数据绕过。

尚无合格全市场个股库、完整历史股票池、通过验收的SIP模型/历史回测/前向账本；经典因子不能冒充及时公布的交易信号。无订阅采购、账户创建、计划任务注册、实盘交易或最终测试解封。
