# G4.2 精度诊断、发行人原稿与页面接线

后续G4.3已通过SEC原申报补齐IWF，字段核验8/8，并完成主干数据分类和维护。最新75通过、1跳过；严格精度门槛仍未放行。见[G4_data_maintenance_acceptance.md](G4_data_maintenance_acceptance.md)。下述7/8是本阶段历史结果。

2026-11-07。增量工程及回归通过，不代表G4、模型、历史回测或模拟成交整体验收通过。

## 完成任务

| 任务 | 结果 |
|---|---|
| 从原始JSON十进制数重新计算拆股价格 | 已执行，排除“只是本地浮点误差”的解释 |
| 检验固定量化公式 | 18,510条受调整行的四个价格字段均匹配当前供应商参考；仅实测规律 |
| 下载发行人PDF并保留哈希/不可变回执 | 三份正式检查源成功，另两份被覆盖的候选保留原始缓存 |
| 逐事件关联原稿字段 | 7/8匹配，IWF未核验，未使用搜索摘要替代 |
| 页面与API显示真实证据及阻断 | 已实现并实际检查；不改变能力矩阵 |
| 回归与安全边界 | 68通过、1跳过，0失败/0错误 |

## 修改清单

- `data/split_evidence.py`：精确十进制复算、三个十进制舍入模式和固定浮点公式的诊断；发行人PDF前12页的特定事件核验、事件源原文校验、源回执和知识截止检查。
- `data/http.py`：发行人域名只开放逐条审阅的PDF路径，仍拒绝重定向及向非Alpaca域名发送其凭证。
- `workflow/feature_price_audit.py`、`cli.py`：增加`--issuer-documents`，保留比较/精度/原稿三个独立结果和生成时间。下载发生在默认知识截止确定之前；显式截止不后移。原稿缺失只阻断该核验，不伪造或停止其他独立检查。
- `web.py`、`web.html`：真实快照/锚定日/截止匹配和文件哈希守卫；数据页显示核对行数、原稿进度、IWF缺口与比较下载链接。篡改文件返回BLOCKED，不拿旧文件冒充当前证据。
- `tests/test_split_evidence.py`：6项真实缓存、故障注入和HTTP路径/凭证边界测试。
- `pyproject.toml`、`uv.lock`：锁定pypdf 7.0.0，仅解析公开PDF，无账户/订阅服务。

## 数据与实测结果

最终运行：`outputs/feature_prices/d98f2a58-de5a-4e2e-9f2c-a2224a970238`。三个结果分别为comparison.json、precision.json、issuer_checks.json；manifest记录源响应SHA、事件、代码及产物hash。

原raw快照仍为5f652f593eab28e4689a3f5dd6e5d4145ad911fc0191c232a441b9c6bfdcaa38，49,520条。当前特征快照仍为52fe137217d4f8a46c55e07648110483cabfc0656f0ac1a6fdf69dd34065cb1c，没有改写raw库或特征公式。

受调整的18,510条记录，从原文数字用Decimal和实际old_rate/new_rate计算。HALF_UP与供应商的open/high/low/close分别有449/361/358/401处差异，主要是半分位边界；HALF_EVEN和截断也不匹配。精确最大差均为0.0050美元。

固定浮点假设`floor(binary64_adjusted_price * 100 + 0.5) / 100`在四字段均为0差异。该公式没有改变特征价格、严格阈值或任何能力，只记录为当前样本上的经验解释。未找到供应商正式保证，不能宣称其以后不会变化。原定atol=0.0001、rtol=1e-8仍保留，comparison.status仍BLOCKED。

发行人核验：MTUM/QUAL在iShares SAI第2页，XLB/XLE/XLK/XLU/XLY在State Street公告第1页，比例、ex_date、record_date、payable_date共5字段分别匹配。只核验特定事件，不证明历史证券身份、完整行为名册或历史当时已公布。

| 原稿 | 当前原文SHA256 | 结果 |
|---|---|---|
| [iShares SAI 3-31](https://www.ishares.com/us/literature/sai/sai-ishares-trust-3-31.pdf) | 4aaffd4a73c36b49de818ae72683f85c142edfeacdd6bb1f497dee4a8a59ce0f | MTUM/QUAL匹配 |
| [State Street公告](https://www.ssga.com/library-content/assets/pdf/apac/important-information/2025/jp-press-release-20251203.pdf) | 88ca596a99141174d89b4349d438670e67e9f204a814f05c0c9c3934874837de | 5只行业ETF匹配 |
| [iShares SAI 2-28](https://www.ishares.com/us/literature/sai/sai-ishares-trust-2-28.pdf) | a9d986e47734c63a15222fe76a45703b172933f0afe5e95b01831f8143441fce | 前12页未找到IWF原始字段，BLOCKED |

实际下载的Russell prospectus已是2026-07-31版；完整112页搜索没有三月补充说明。另取SAI 4-30也未在前12页找到；SAI 2-28的276页另作完整只读搜索亦未找到March 27或IWF+April 29。搜索索引含旧补充页不能当当前下载成功。pypdf在IWF候选上提示部分字体需fontTools，相关未匹配不计通过；不得把可能的提取缺口说成发行人从未公告。

## 运行及验证

```powershell
.\.venv\Scripts\uv.exe sync --locked --cache-dir .uv-cache
.\.venv\Scripts\python.exe -m quant_research.cli feature-price-audit --offline --issuer-documents --action-end 2026-11-06
.\.venv\Scripts\python.exe -m pytest tests/test_split_evidence.py -q -rs
.\.venv\Scripts\python.exe -m pytest -q -rs --junitxml=outputs/feature_prices/precision-issuer-tests.xml
```

首次抓取去掉`--offline`；Alpaca使用此前获授权的本地凭证文件`--env-file .env`，发行人PDF请求只含项目User-Agent。对账内部退出码4是预期BLOCKED，不是通过。无缓存明确缺失，不生成替代内容。

全量结果：68 passed、1 skipped，90.91秒。原有测试未删除；新增6项包含原稿截止、实际事件篡改拒绝、HTTP路径/凭证限制以及Web对快照和所有产物hash的检查。跳过仍为Yahoo 2026-11-06真实缓存缺OHLCV，不计通过。

API证据：`outputs/feature_prices/ui-evidence.json`。浏览器实际打开`http://127.0.0.1:8766/data`，DOM显示20条raw报价、收益全部N/A、严格BLOCKED、7/8及IWF缺口、四个模型/因子按钮disabled，证据链接指向本次结果。只有原本本仓库且任务IDLE的进程被更新；新本地服务PID记录在console-pid.txt。完整九页交互尚未验收。

## 剩余与顺序

1. 获取可核验的IWF历史补充原稿，必要时补字体解析工具或SEC原始申报路径；不能靠搜索摘要转为PASS。
2. 为已知供应商精度建立有来源、可版本化的口径契约；当前经验诊断不能取代严格精度检查。
3. 通过适用范围审阅后再接探索因子与模型。历史PIT、身份/退市、完整事件现金账本、前向模型资格与冻结决策快照仍分别阻断。

未新增预测、策略收益或成交；2025+只做行情/行为/精度观察，策略最终测试仍封存。
