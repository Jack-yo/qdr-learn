# G2真实事件与证券身份：本轮验收

日期：2026-11-07（Asia/Shanghai）。在原仓库继续修复；git HEAD仍不存在，commit_sha=null。未购买、开户、访问账户或下单；未解封最终测试。

## DONE / 修改文件

- `data/providers/actions.py`：Alpaca公司行为只读适配，分页、重复ID/循环token阻断、日期校验、首次观测时间及原始响应SHA。区间按process_date查询，不能当作公告日期；不虚构published_at。
- `data/event_store.py`：真实事件版本表、事务/幂等；入库前校验缓存字节SHA及payload与原响应一致。事件ID不当永久证券ID，当前快照不提升PIT。
- `data/event_review.py`：Apple、GE、Nasdaq独立来源特定字段核对；疑似重复股息身份冲突单独列出，不自动合并。
- `backtest/action_accounting.py`：独立事件算术模块，拆股不增加现金；除息日产生应收、支付日转现金，股份归零仍保留应收权益；重复事件幂等，碎股无核验结算则阻断，身份不符、修订及潜在重复股息拒绝自动记账。
- `backtest/engine.py`：关闭旧按当前持仓直接发股息的路径。新模块尚未接入可执行账户，正式成交仍BLOCKED；没有用数学验证状态充当真实历史持仓或交易。
- `data/http.py`：独立公开证据域名白名单；禁止Alpaca凭证头转发到其他域名。
- `workflow/g2.py`、`cli.py`：新增g2-audit，逐案例收集/报告失败原因、来源hash、代码/配置hash、报告文件hash。不放行执行能力。
- `tests/test_g2.py`：9项真实缓存及纯标量算术回归，无生成市场行情或虚构收益。

## DATA / 实际证据

联网采集：`outputs/g2/30f29f16-6f90-4b3d-aa91-234c1a539304`。

最终离线报告：`outputs/g2/95ed8d92-c260-4509-bafd-57789bfc9cf2/report.html`，manifest记录原文、页数、逐项状态、首次观测时间及hash。该次离线重跑7条事件新增0版本、14条有效raw日线新增0行；事件表共7版本，证据`outputs/g2/replay_verification.json`。

| 案例 | 实际结果 | 未解决 |
|---|---|---|
| AAPL 2020 | 一笔分红、一笔四拆一，2页；3条SIP raw日线 | 公告小时级时点、全生命周期覆盖未验收 |
| GE 2021 | 一笔1:8反拆股、两条分红记录，3页；3条raw日线 | 同一分红两个新旧CUSIP/不同ID，疑似重复权益，保持阻断 |
| FB→META 2022 | 一条改名事件；Nasdaq通知支持同一Class A及CUSIP | 原始bar出现META改名前零量/零VWAP记录，价格校验拒绝；不能跨代码直接拼接 |
| ABNB IPO附近 | 真实raw窗口返回4条，观测首日2020-12-10 | 只是查询窗口内观测首日，不能据此构造完整挂牌名册 |
| TWTR 2022收购 | 一条现金并购事件、4条raw日线 | 54.2来源记录尚未核验全部结算条款/时间，不能按最后收盘价或0结算 |

独立原文均实际下载并缓存：

- [Apple 2020年三季报公告](https://www.apple.com/newsroom/2020/07/apple-reports-third-quarter-results/)：支持0.82美元股息、8月13日支付及8月31日四拆一交易口径。
- [GE反拆股公告](https://www.ge.com/news/press-releases/ge-completes-one-for-eight-reverse-stock-split)：支持1:8及2021-08-02交易口径。
- [Nasdaq代码变更通知](https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2022-125)：支持FB→META、2022-06-09及CUSIP30303M102。

7条事件中4条关键字段与独立来源匹配，不能解释为全表字段/PIT或执行验收通过。原始文档hash、事件hash在manifest；HTML字段核对是固定案例验证，不是通用公告抽取器。其余3条未完成独立核验，明示BLOCKED_NOT_RECONCILED。

## TESTS

```powershell
.\.venv\Scripts\python.exe -m quant_research.cli g2-audit --env-file .env
.\.venv\Scripts\python.exe -m quant_research.cli g2-audit --offline
.\.venv\Scripts\python.exe -m pytest -q -rs --junitxml=outputs/g2/tests.xml
```

g2-audit返回4（整个G2未验收），报告不是策略收益。9项G2专项测试实际通过。全套37 passed、1 skipped；跳过项仍为SPY Yahoo 2026-11-06缓存缺字段，未当作通过。旧20文件测试仍待真实数据迁移。数学测试的初始股数/现金仅为字面标量算术，不是声称历史持仓/成交。

新增测试覆盖：拆股股份与现金不变、应收到现金的双向分录、持仓归零后的支付、重复执行、提前支付拒绝、缺权益拒绝、错误证券拒绝、反拆股碎股拒绝、GE跨CUSIP重复权益拒绝、原始payload变更拒绝、真实缓存hash、事件存储幂等、官方字段核对及现金并购未核验时阻断。

## RISKS / NEXT

G2整体仍NOT_ACCEPTED。没有完整永久证券主表、历史PIT股票池、退市/代码复用全覆盖、全部公司行为或结算。GE重复身份不能静默去重；META零量记录不能删除校验后拼接。当前事件源是current_revised_snapshot，published_at=NULL，不将今天抓取当历史已知时间。

事件算术模块尚未与PortfolioEngine/持久化paper ledger完成事务接线和完整回归，这属于G4明确工程工作。旧路径已封堵，未改变仓位/成本/风控参数。下一步需补身份关系与历史有效期证据、实际ticker复用与停牌案例，继续SEC原申报/SIC验证；数据不足保留对应阻断，不购买订阅。前向观察不可倒填。
