# P1–P6 免费真实数据复验

日期：2026-11-07（Asia/Shanghai）。本轮继续完成免费条件下可验证的工作，不能把缺失的数据宣布补齐。

## DONE

- 新增 `src/quant_research/real_acceptance.py`，CLI `real-acceptance`：复制真实仓库、拒绝未checkpoint WAL/缺库/纯合成库，顺序运行P1–P6，保存逐阶段命令/日志/退出码/manifest及文件hash。离线运行，无网络下载，无合成回退；源库不写派生结果，复制库用于计算。
- 新增 `src/quant_research/research/increment.py`：逐日等权配对Brier改善，对比常数概率及Alpha-only A；20交易日块bootstrap、500次、固定种子42；拒绝重复键、不同标签与非法概率。小样本区间留空。
- 更新 `workflow/market.py`、`workflow/train.py`：保存配对增量CSV/Parquet，报告展示区间；真实Alpha研究标明CURRENT_ETF_PROXIES_NOT_INDIVIDUAL_STOCK_ALPHA。
- 更新 `cli.py`、`web.py`、`web.html`：市场模型、ETF A–D消融与完整离线验收均可页面启动。
- 新增 `tests/test_real_acceptance.py`、`tests/test_probability_increment.py`，扩展 `tests/test_web.py`。

## TESTS

```powershell
.\.venv\Scripts\python.exe -m pytest -q --junitxml=outputs/real/p1-p6-final-tests.xml
.\.venv\Scripts\python.exe -m quant_research.cli real-acceptance
```

全套 **109 passed in 247.94s**。HTTP测试需允许本机回环连接。验收命令总退出码4，明确表示真实研究/执行数据阻断；不能将其解释为所有阶段通过。测试通过验证实现，不验证盈利。

## DATA / RESULTS

最终真实快照验收目录：`outputs/real_acceptance/2026563b-4bba-424e-8ee6-169b7399687e`。报告 `report.html`，机器证据 `acceptance.json`。数据来源Yahoo，20只当代ETF代理、2017-01-03至2026-11-06最新版本49520条，历史最终测试从2025起封存。

| 阶段 | 本轮实际结果 | 证据子目录（stages下） |
|---|---|---|
| P1 | 真实数据覆盖审计通过，研究级数据仍缺 | 1d2c83e1-2025-40cf-853b-599a749c7111 |
| P2 | 真实代理标签的回溯因子诊断通过 | 69df3d8c-e529-45aa-a001-350a4056c9f5 |
| P3 | 1506行市场模型输出，真实历史可交易性未验收 | b28db300-d9f7-4872-8dbd-a65e186e9e8c |
| P4 | 102408行ETF A–D预测，非完整个股Alpha | b9117915-fd9a-4d5c-bc8e-a1f2dd8552c2 |
| P5 | BLOCKED_RAW_PRICE_AND_PIT_REQUIRED，无真实成交/净值 | cc7b84cf-619d-42fb-b681-4ab847905675 |
| P6 | 最新真实观察日报生成，NO_NEW_TRADING_ADVICE，无真实模拟成交 | 88cdef54-3193-486b-a3fb-43286aafd873 |

市场模型相对常数概率的逐日Brier改善（正值才是改善）：H1 -0.00057990，H3 -0.00204663，H5 -0.00762534。20日块bootstrap95%区间分别[-0.00428120,0.00269321]、[-0.00709717,0.00294438]、[-0.01622123,-0.00012807]。未显示稳定增量，继续只报告状态；不调整阈值以追求好结果。这些是当前版本回溯的描述统计，不是PIT可部署证据。

## RISKS / NEXT

尚未取得：历史PIT个股股票池与退市历史、稳定证券身份映射、可核验原始价格和公司行为现金记账、历史PIT基本面。免费版不能据此生成完整个股净值或真实可执行候选。规模/质量缺失保持明确标记，最终测试仍封存，无真实券商接口。

下一步必须先补有来源、可验证的历史数据，再进行P1质量验收、P2–P4严格as-of重算、P5真实成本/现金对账、P6跨多日真实模拟成交验证。用户目前选择仅使用免费数据，因此不购买订阅、不要求发送密钥、不放宽门槛。持续真实模拟验证也不能在一个会话内伪装成已完成多日实测。
