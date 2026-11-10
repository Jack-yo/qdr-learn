# v2.1 G0整改与G1初步验证

日期：2026-11-07。目录为现有qt_test；git无HEAD，commit_before/after均为null，没有重建仓库或提交。规格完整存档docs/codex_handoff_v2_1，10项SHA256清单匹配。旧验收与本轮结果不得混用。

## G0实际变更

- 新增policy.py，真实来源、记录SHA、非真实标识、缺数据和执行证据错误；无可配置绕过开关。
- CLI删除demo与fixture选项，正式默认改真实来源；从正式包迁出fixture.py、stream_fixture.py、normalize.py、旧config.py/base.yaml至archive/pre_real_only。旧市场测试20个文件与人工行情留档，不执行、不计通过。
- data/schema.py、store.py、features/context.py、workflow/common.py增加REAL_ONLY边界，研究、模型和数据管线移除生成器导入；data/pipeline.py补明确source。
- workflow/backtest.py和backtest/simulation.py撤除合成成交路径；backtest/paper.py、workflow/daily.py明确暂停执行，保留风险/成本/现金引擎，不用删风控解锁。
- web.py阻断无manifest/真实source/hash不匹配的旧报告；九个导航可访问，未完成功能页明确BLOCKED/N/A；不是完整React/九页产品验收。真实总览/数据查询保留。
- yahoo.py发现真实缓存空OHLCV时输出证券/日期错误，无插值、补值、静默替换。
- CI移除演示命令；README/AGENTS按v2.1优先，旧资料仅历史参考。

## 实际审计发现与未完成项

旧CLI默认fixture、随机生成器、执行fixture白名单、旧合成报告暴露均为实际代码问题，不只是数据授权问题。模块清点与hash证据在outputs/g0/source_audit.json。审计中残留synthetic/fixture文字主要是拒绝规则与部分失效状态分支，仍需G4能力接线时清理；正式生成器已不在包内。

统计bootstrap的随机种子用于真实样本重抽样，不是行情生成器，不为REAL_ONLY而删除。数学风控/成本函数保留。完整的历史时间、证券身份、公司行为账本和深层模型正确性审计继续由G1–G5完成，不能据G0守卫测试宣称全部可信。

## TESTS / EVIDENCE

```powershell
.\.venv\Scripts\python.exe -m pytest -q -rs --junitxml=outputs/g0/tests.xml
.\.venv\Scripts\python.exe -m compileall -q src
.\.venv\Scripts\python.exe -m quant_research.cli market-report --source yahoo --mode retrospective --output outputs/g0/real_replay
```

本轮回归26 passed、1 skipped（单列BLOCKED，不计通过）；旧109不沿用。26包括交易时钟、元数据守卫、拒绝旧CLI、仓库缺数据、九路由HTTP、路径/令牌/Host、真实缓存与凭证缺失探针。真实市场测试读取已有Yahoo原始缓存：2475条SPY记录截至2026-11-05的解析/hash通过；全区间至2026-11-06缓存解析失败，最新日缺OHLCV，完整回放验收BLOCKED。首次运行曾1 failed，已将缺字段明确化，没有替代数据或把该市场回放算作通过。

XML日志outputs/g0/tests.xml；Chrome实际无库市场页截图outputs/g0/empty-market.png，空状态API证据outputs/g0/empty-status.json。HTTP九路由测试通过；完整Playwright九页任务链仍待G4，不宣称已完成。浏览器仅实际人工截图复核，非伪造自动化成功。

有效真实市场报告仍能生成：outputs/g0/real_replay/021d87b5-b2b3-4a58-b059-4d8efb27295c/report.html，DESCRIPTIVE_CURRENT_VINTAGE_ONLY；无真实执行资格。

## G1实际验证

新增data/probe.py、provider-probe命令，http.py保留HTTP类别；缺凭证零网络请求，证明不依据供应商宣传。API Key未保存到仓库或日志。

- Alpaca：进程、User和Machine环境均无对应凭证。outputs/g1/alpaca_provider_proof.json为MISSING_CREDENTIALS、真实记录0、plan_verified=false，未调用其API，不能声称SIP/raw/分页/行动权限通过。按用户最新指示正在查找本地其他目录的配置，仅报告路径，不输出凭证。
- SEC：实际联网读取CIK320193的submissions与companyfacts，两个响应hash保存在outputs/g1/sec_provider_proof.json；离线回放hash一致，见outputs/g1/offline。均CURRENT_SNAPSHOT_NOT_PIT。
- SEC扩展：历史submissions一页成功，1271条，hash c01f4199ed2a19c8ccb302597f996ac4050c13f315258301d1164b924458c502；原始10-K的www.sec.gov请求在四次尝试后网络失败，未伪造原稿，未验证accepted时区/PIT。见outputs/g1/extended/sec_provider_proof.json。证明中的2是当前主快照数量，历史页1271条另列evidence，不当作已解析财务事实。

原文件失败不影响已验证快照，但G1完整历史贯通仍BLOCKED。原始申报、历史分页取全、公司行为、身份与退市测试尚未完成；未解封最终测试、未创建账户、未采购、未实盘。

## 能力与下一步

REAL_ONLY正式路径阻断、真实空态、已缓存观察/描述报告可用；严格历史回测、前向影子成交仍BLOCKED。source_coverage最新完整回放BLOCKED；historical_identity_coverage/delisting_settlement/corporate_action/PIT_publication均BLOCKED；raw_adjusted_separation仅schema守卫有证据、真实交叉核验待G1；time_leakage为局部已有时钟/守卫测试、完整真实研究待G3/G5；ui_real_only为基础HTTP+Chrome空态证据，完整产品E2E待G4。

后续：在用户授权范围查找本地凭证并先确认用途/授权，再做只读Alpaca探测；独立重试SEC原稿网络/核对历史分页；以真实样本迁移旧测试。能力矩阵、动态decision_at、事件应收分红/现金支付、历史ID和九页交互仍是明确工程工作，不以数据缺口掩盖。

## 本地凭证查找补充

经用户明确要求查找本机其他目录，发现C:\Users\liyil\Documents\predict_test\.env含非空ALPACA_API_KEY和ALPACA_API_SECRET。仅检查存在性，不显示或保存值，不修改该文件。当前项目期望ALPACA_SECRET_KEY，名称不一致。User/Machine环境未配置对应变量。尚未读取凭证发起API请求；已请求用户明确授权临时进程只读行情探测，批准前不使用。该文件不纳入源码、测试证据或交付清单。

## 用户授权后的G1更新

用户明确授权将找到的两项Alpaca凭证复制到本项目本地.env。复制前git check-ignore确认.env被忽略；未复制其他配置，未显示值。CLI provider-probe增加显式--env-file参数，只加载两项命名凭证到当前进程，不访问账户/交易域名。

Alpaca本次实际只读探测成功，16条SPY/AAPL SIP raw覆盖2017、2020拆股附近、2024早收盘。最终分页探测为4/3/1页，见outputs/g1/paginated_final/alpaca_provider_proof.json；首轮4/4/1页也保留，不能假定分页数量恒定。公司行为返回一条AAPL四拆一、一条现金分红，原文hash与样本outputs/g1/authorized/corporate_action_samples.json；尚未跨来源核验或记账。

初次20ETF历史拉取入库49420条后HTTP403失败，原因是end设成次日午夜且请求时尚未到达，触发SIP最近15分钟限制。保留ed9d90fc-ac65-4003-afa2-a331f5e9a85a失败manifest。修复为确定性的已收盘会话边界后，第二次运行4f9faedb-51cc-4243-ad97-6a02e302a72e成功：20只ETF、2017-01-03至2026-11-06，每只2476交易日，共49520条、missing=0，feed=sip、adjustment=raw。原文按月缓存，有版本/抓取时间，不倒填历史available_at。独立真实仓库data/real_v21.duckdb保留两次拉取版本；物理98940行不等于最新版本数，未混入旧合成数据。

这证明当前凭证可访问所测历史SIP和行动接口，但未查询账户或套餐，plan_verified仍false。不能据此推断账户必为Basic、OTC/全退市可用。完整股票公司行为/身份/名册与历史PIT仍缺；G1不等于G2/G4执行资格。完整禁网回放/幂等证据另见offline_full_sip运行。

最终回归28 passed、1 skipped（Yahoo最新缓存仍BLOCKED）。新增真实SIP月度缓存和公司行为响应哈希测试；旧市场测试20文件仍待迁移，不计通过。源审计列表需按最后代码hash重生成。

完整禁网重放 d387c3cd-c047-4377-800d-9d2424eca36d：49520条，inserted_rows=0，data_sha/Parquet路径/表计数均一致，证据outputs/g1/replay_verification.json。凭证泄露扫描仅输出命中数量与路径，未打印凭证；本轮源码/文档/测试/G0/G1日志未发现凭证值。阶段机器记录outputs/g0/phase_acceptance.json。
