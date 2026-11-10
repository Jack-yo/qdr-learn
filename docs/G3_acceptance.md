# G2身份关系补证与G3 SEC索引/候选隔离验收

日期：2026-11-07（Asia/Shanghai）；现有仓库无HEAD，commit_sha=null。不采购、不开户、不交易、不解封最终测试。

## DONE / 修改文件

- `data/providers/sec.py`：新增历史申报索引，取全接口公布的附加页、核验页条数/数组长度/重复accession/安全路径；筛选2017–2024。保留源时间字符串，不默认相信Z后缀即可证明正确UTC。空原稿/元数据不填补。
- `data/filing_candidates.py`：按CIK及accession关联五类财务候选；保留概念、单位、期间、财政期、源数组行索引及两个来源hash。候选全部decision_eligible=false、历史available_at=NULL；原稿类型/hash/核验时间缺失时拒绝。
- `data/filing_store.py`：单独候选库、外键、唯一键、事务/幂等；逐条检查缓存SHA及原始行，拒绝来源数字变化和手工资格提升。没有写入正式fundamentals_pit。
- `workflow/sec_audit.py`、`cli.py`：新增sec-audit，支持真实缓存禁网重放、来源证据报告与文件hash。
- `data/identity_evidence.py`、`workflow/g2.py`：把已核验的FB→META关系保存为独立候选证据，保留有效日期、观测时间及双方文档hash。关系证据ID不是全局security_id，不能凭一个改名案例生成历史股票池。
- `tests/test_g3.py`：6项真实SEC/改名缓存回归；源行一致、全索引页、重复键、封存期隔离、跨发行人误关联、候选存储、时间/资格及改名关系不可回填。

## DATA / 实际数量

| 公司 | 读取索引页 | 2017–2024窗口索引 | 财务候选 | 当前SIC |
|---|---:|---:|---:|---|
| Apple CIK320193 | 2 | 686 | 474 | 3571 |
| Microsoft CIK789019 | 3 | 1267 | 467 | 7372 |
| 合计 | 5 | 1953 | 941 | 仅当前快照 |

“页取全”指已处理提供商所公布的所有索引页，不是独立证明所有历史申报/撤回均无缺漏。941条是当前companyfacts聚合版本中的accession关联候选，不是已验证as-filed数值或PIT因子。各单位与财政期不擅自合并、去重或计算ROA；来源行索引保持可追溯。

首次只用缓存时，微软缺附加页被准确阻断；随后通过data.sec.gov只读接口实际补齐，无替代数据。联网运行：`outputs/g3/7dc2aa79-ff7a-42c0-a290-78ddff40eb5f`。首次入库：`outputs/g3/5ad3b319-c909-438f-8292-3ffb4ed64b0d`，1953+941条。离线复验：`outputs/g3/4981c582-a862-4737-9873-9edebcfbe617`，两表新增0、输入文件hash一致。最后代码重跑路径见本目录最新manifest。

库：`data/g3_evidence.duckdb`，只含filing_index_versions和financial_candidates，后者CHECK(decision_eligible=false)，不能冒充生产PIT财务。历史SIC没有原稿证据，当前3571/7372均不向过去填充。

G2改名关系报告：`outputs/g2/1b6458ca-9d8b-4af4-bcfa-c899c4b06bd8/identity_candidates.json`；1条FB→META关系，effective_date=2022-06-09。首次观测为实际2026下载时间，published_at_verified=NULL，tradability_eligible=false。GE重复权益与META原始bar异常保持阻断，没有静默修补。

## TESTS / 命令

```powershell
.\.venv\Scripts\python.exe -m quant_research.cli sec-audit --offline
.\.venv\Scripts\python.exe -m pytest -q -rs --junitxml=outputs/g3/tests.xml
.\.venv\Scripts\python.exe -m pytest tests/test_g3.py -q -rs
```

全量43 passed、1 skipped；6项G3专项通过。跳过仍为Yahoo 2026-11-06真实缓存空OHLCV，不计通过；旧20文件测试依旧待真实迁移。sec-audit总退出4准确表示PIT_PUBLICATION_BLOCKED，不能因为取到941条候选而标记G3完成。第一次全套启动遇自动审核超时，未执行；一次重试成功，无隐藏失败。

## 原稿访问真实阻断

初次限时诊断HTTP403，未获取接受时间头；随后带此前获授权的合规联系信息作一次15秒请求，结果Timeout。证据`outputs/g3/original_access_proof.json`，未发送Alpaca凭证，没有绕过、代理、变换身份或把拒绝页当申报正文缓存。不能由此判断所有网络/所有SEC文件均不可访问，但本机该原稿请求仍BLOCKED。

此前submissions里的accepted_at不经此审计自动提升可信度；G3新索引专门保留candidate文本及NULL核验时间。缺原稿/时区证据时，财季截止日、filed日、Z字符串和当前抓取日都不能替代历史可用时点。

## RISKS / NEXT

G2整体与G3 PIT部分未验收：永久证券主表、历史名册、GE重复CUSIP权益判定、完整退市结算、SEC原稿/接受时间、历史行业变化、as-filed数值核验仍缺。当前关系和候选索引只推进可核验的数据链路，不生成预测、收益或历史交易。

后续独立推进G4 DatasetBundle与能力注册、读取现有真实SIP/观察报告的接线；历史执行、前向委托等能力继续逐项要求证据，不能靠手工字段放行。完整九页交互及持续前向观察未完成。最终测试继续封存。

最后代码离线运行：`outputs\g3\b48f7f0c-8598-4b6c-81b2-1f0a990b2de0`，输入hash与首次入库一致、两表新增0。机器验收记录outputs/g3/phase_acceptance.json；源码/文档/测试/G3日志未发现凭证值。
