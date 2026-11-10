# G4.5 因子实验主流程增量验收

本次验收范围：真实来源预览、参数模板、不可变版本、冻结实验、后台计算、结果核验与比较。整体 G4/G5 尚未完成，research_grade、execution_ready、real_orders_enabled 均为 false。

## 实际修改

新增 `src/quant_research/research/factor_lab.py`、`workflow/factor_lab.py`、`factor_lab.html`、`configs/factors/reversal5.json`、`tests/test_factor_lab.py`；修改 `cli.py`、`web.py`、`web.html`、`data/catalog.py`、`reports/factors.py` 和 `tests/test_maintenance.py`。维护说明、任务清单和 README 同步更新。完整带哈希文件清单见 `outputs/factor_lab/phase_acceptance.json`。

复用已有因子引擎、标签和评价模块，未重写策略或降低风控。模板仅反转、动量和波动率；无用户代码执行能力。版本复制保留父版本，不变更旧记录。新实验冻结 20ETF 名单、来源、知识截止、因子哈希、训练/验证协议；读取完成结果逐文件校验 SHA256。

## 真实数据与执行证据

- Yahoo 历史受筛选输入 40,240 行、20 个真实响应对象，范围 2017-01-03 至 2024-12-31。逐行来源、回执和源原文核验；快照 SHA256：`ab04e464b921c4e9409a93a3ebbed5173c4b453496c532d069e94cc6d2e9f640`。
- 反转 5 日实例 `5955920c-7cb0-4814-92d6-a77f231fc03b`：34,204 个因子行、34,119 个非空值；102,612 个标签行，其中 102,459 个非空代理标签、正式 raw 标签 0。训练/验证 × H1/3/5 共 6 行评价。
- 已真实完成 5/10/20 日版本的创建、预览、实验与比较，没有宣称任一版本盈利。HTTP 创建/复制、CSRF、实际子进程、轮询、报告读取均实测。
- 最终含冻结名单的 API 实验：`a8d9f6fb-8c65-4105-9d68-3c2cbbcea065`，后台状态 COMPLETED、实际退出码 0；结果见同名目录及 `outputs/factor_lab/final-api-result.json`。与 5 日实验比较生成 6 行同源同协议结果。
- Alpaca 实验 `a6cd3d7d-4544-4e6a-8011-7f10b7a4e144` 实际 BLOCKED；未生成替代标签或收益，未自动切至 Yahoo。API 的 Alpaca 预览返回能力阻断。
- 分类目录现有 11 类，349 回执、源对象哈希异常 0；因子登记为独立元数据类别。`research.duckdb` 只登记 YAHOO 历史探索子集，未接受整个混合库。

## 测试与复现

```powershell
.\.venv\Scripts\python.exe -m pytest -q -rs --junitxml=outputs/factor_lab/tests.xml
.\.venv\Scripts\python.exe -m pytest tests/test_factor_lab.py tests/test_maintenance.py -q -rs --junitxml=outputs/factor_lab/final-maintenance-tests.xml
.\.venv\Scripts\python.exe -m quant_research.cli data-catalog
.\scripts\start_console.ps1 --port 8766
```

实际全套：97 passed、1 skipped，142.30 秒。之后冻结名单及分类目录变更的最终针对性回归：20 passed，35.04 秒；这 20 项与全套重叠，不能相加。跳过项为最新 Yahoo 真实缓存缺 OHLCV，不生成行情替代。实验测试使用有来源的真实本机缓存；没有缓存时保留阻断。

覆盖参数拒绝、版本不可变、实验幂等、训练尾部隔离、跨期标签剔除、真实覆盖率、截止/名单/协议冻结、产物篡改、来源准入、API 请求校验及目录用途不升级。页面 JavaScript 通过 Node 语法检查。此轮未执行浏览器视觉验收，可用浏览器技能文件未找到；HTTP 与任务成功不能等同完整视觉/交互验收。

## 限制与下一主干

Yahoo 当前版本 ETF 探索不是 PIT 个股 Alpha，也不是历史可交易特征；正式收益、净收益和成交未验收。参数比较没有多重检验校正；行业/市值暴露不可用。最终测试未解封。

仍待完成市场/个股真实预测与滚动样本外证据、策略版本与合格回测、前向模拟账本和完整九页交互。Alpaca 特征价格严格对账、历史证券/退市结算、PIT 财务依赖继续分别阻断对应功能；不因本阶段通过而升级系统状态。下一步优先打通不绕过准入的市场研究/预测主流程，再推进策略、回测与前向账本。
