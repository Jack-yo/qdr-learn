# G4 独立特征价格层验收记录

后续G4.2已补精确诊断、发行人原稿7/8与页面接线；最新全套68通过、1跳过，严格精度仍BLOCKED。见[G4_split_evidence_acceptance.md](G4_split_evidence_acceptance.md)。下述62项通过保留为G4.1历史结果。

2026-11-07；本轮范围是拆股一致性、来源与时间隔离，不是整个 G4 验收。保留现有 raw 库、模型规则、仓位/成本/止损约束及最终测试封存。

## 任务与依赖

| 任务 | 依赖 | 当前结论 |
|---|---|---|
| 获取20ETF完整公司行为分页 | G1只读凭证和缓存 | 实际2页，1,042条事件 |
| 独立拆股特征层 | 已验证raw、事件原文及不可变回执 | 已实现；仅当前版本价格代理 |
| 全量供应商split口径对账 | 单独参考读取器、真实5页响应 | 已执行；严格价格精度BLOCKED |
| 截止日、原始价格不变与缺失证据测试 | 真实缓存 | 测试结果见下 |
| 代理标签/正式标签隔离 | 截至2024真实样本 | 已实现；缺账本的raw标签拒绝 |
| 因子/模型正式接线 | 特征层验收、能力注册 | 尚未放行，不用编辑PASS开关绕过 |

## 实际文件

- `src/quant_research/data/feature_prices.py`：单独的split_adjusted_price_proxy口径、锚定日、事件完整分页、源回执、版本/快照hash与OHLCV对账。
- `src/quant_research/workflow/feature_price_audit.py`：可复现CLI审计，输出Parquet、比较JSON及manifest。失败也保留证据。
- `src/quant_research/cli.py`：feature-price-audit命令，凭证仍只从本地显式文件/环境读入。
- `src/quant_research/research/labels.py`：拒绝仅凭raw生成正式收益标签；移除旧SYNTHETIC_RAW_GROSS标识；拆股代理不填forward_return/benchmark_return/net_return。
- `tests/test_feature_prices.py`：9项真实缓存集成和故障注入测试，不生成市场行情。

## 数据契约与方法

源是Alpaca SIP、raw价格以及/v1/corporate-actions当前返回的事件。价格来源逐行核验沿用DatasetBundle；事件查询重新从内容寻址原文解析并要求不可变抓取回执。查询日期是process_date，不冒充ex_date筛选或历史公告时间。全量请求2016-01-01至2026-11-06，价格2017-01-03至2026-11-06。

锚定日为观察asof；只对早于拆股ex_date的行情累计old_rate/new_rate调整OHLC及VWAP，成交量除以同一乘数。锚定日之后的拆股不参与计算。分红不进行价格调整或现金记账。输出明确为价格收益代理，不是总收益、可成交价或历史当时已知序列。

特征available_at至少等于价格与全部事件分页首次观测时间的最大值，不能早于当前事件证据；显式knowledge_cutoff不因下载而后移。原始价格ingested_at另存raw_price_ingested_at，避免将原价格入库时间当特征生成时间。知识截止在manifest中记录，验收记录生成时间另存phase_acceptance.json；Parquet不写入raw价格表。

重复同证券/日期拆股、未支持的有效公司行为、缺失字段、错误比例、缺回执、缺行情或截止之后的证据会拒绝；不丢掉问题证券来换取通过。永久身份与完整历史名册仍未验证。

## 实际计算结果

原始价格49,520行，119份真实响应逐行核验。公司行为1,042条：1,034现金分红、8正向拆股；独立split参考5页、49,520行。当前锚定下18,510行受拆股调整，31,010行不变；close×volume最大绝对差0。

| 字段 | 超出预定阈值行数 | 最大绝对差 |
|---|---:|---:|
| open | 11,025 | 0.005美元（浮点末位误差除外） |
| high | 12,255 | 0.005美元（同上） |
| low | 12,085 | 0.005美元（同上） |
| close | 11,149 | 0.005美元（同上） |
| volume | 0 | 0股 |

缺失/额外键0；未发生调整的行各价格字段差异0。预先固定价格atol=0.0001、rtol=1e-8，成交量atol=1股；本轮没有放宽。差异集中于拆股后的小数精度，但供应商具体舍入算法尚未证实。简单Decimal HALF_UP并不能解释全部行，不能宣称已解决。

首次实测保留：`outputs/feature_prices/2fda3df7-6907-49c2-8ade-08ff1720ca9a`。增加分段诊断及独立时间字段后的离线证据：`outputs/feature_prices/43ec417b-04e5-4a22-9d1e-3f9e753270ee`。最终代码版本证据另见本目录phase_acceptance.json。

最终代码版本离线重放：`outputs/feature_prices/274fff48-96c3-4b2a-9fab-c0edcb71c335`。与上一离线版本的特征快照SHA和Parquet文件SHA都相同：feature_snapshot_sha256=52fe137217d4f8a46c55e07648110483cabfc0656f0ac1a6fdf69dd34065cb1c。未写入或改变原始价格表。

## 一手资料核查与访问限制

[Alpaca历史bars规范](https://docs.alpaca.markets/us/reference/stockbars)说明split调整价格和成交量，asof用于证券代码映射；本实现仍显式asof="-"，不自动拼接改名前证券。

[Alpaca公司行为规范](https://docs.alpaca.markets/us/reference/corporateactions-1)明确process_date排序、分页及事件可能延迟入库。当前查询成功不能证明历史公告时点或市场全部事件完备。

[iShares当前SAI原稿](https://www.ishares.com/us/literature/sai/sai-ishares-trust-3-31.pdf)第2页的2026-10-05补充说明MTUM/QUAL的4:1拆股和2026-11-05除权日。[State Street公告](https://www.ssga.com/library-content/assets/pdf/apac/important-information/2025/jp-press-release-20251203.pdf)第1页列示XLB/XLE/XLK/XLU/XLY的2:1及2025-12-05生效。IWF的2026-04-29、4:1在发行人搜索索引中找到，但首个英国链接实际重定向至全球目录，不能算原稿抓取成功。上述网页核查尚未接入本地源回执注册，不能当自动放行证据。原SSGA英文FAQ链接实际404，已保留此限制。

## 可复现命令及测试

```powershell
.\.venv\Scripts\python.exe -m quant_research.cli feature-price-audit --env-file .env --action-end 2026-11-06
.\.venv\Scripts\python.exe -m quant_research.cli feature-price-audit --offline --action-end 2026-11-06
.\.venv\Scripts\python.exe -m pytest tests/test_feature_prices.py -q -rs --junitxml=outputs/feature_prices/focused-tests.xml
.\.venv\Scripts\python.exe -m pytest -q -rs --junitxml=outputs/feature_prices/tests-authorized-loopback.xml
```

对账CLI内部返回4表示BLOCKED，生成证据不代表通过。首次专项9 passed / 79.26s。首次全套61 passed、1 failed、1 skipped / 96.04s；失败是Windows沙箱禁止本地Web测试连接的WinError10013，未删除/降低测试。获批本机端口访问后的最终回归结果见phase_acceptance.json及对应XML。

唯一已知跳过：Yahoo真实最新缓存2026-11-06缺OHLCV字段，仍拒绝替代值，不计通过。市场测试依赖现存真实缓存；缺缓存明确跳过并标BLOCKED。

最终结果：**62 passed、1 skipped，68.81秒，0失败/0错误**；XML含63项，跳过不计通过。新增9项已全部通过，原有测试均保留。代理标签补充测试单独1 passed / 30.56s；全量回归已包含此修改。凭证值扫描覆盖src/tests/docs及本轮输出文本，匹配0，不打印凭证。

## 剩余与下一步

严格价格精度对账仍BLOCKED；当前拆股公式输出已落盘，可检查但未给因子/模型正式入口开放能力。下一步核验供应商调整价格量化规则、缓存发行人原稿并做字段关联，再审阅适用精度契约；保留本次失败证据和原标准，不能因需通过测试而调阈值。

随后才能接探索因子/模型、Web研究交互。历史股票池/永久身份/退市、PIT公告时间、事件现金账本、前向合格模型与冻结决策快照仍是分别验收的外部/实现依赖。无策略收益、预测概率、成交或盈利被本轮伪造；未运行2025+策略最终测试。
