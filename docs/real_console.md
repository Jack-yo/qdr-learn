# 免费真实数据版本

在项目根目录执行：

也可双击根目录 `start_console.cmd`，保持终端窗口开启。

```powershell
.\scripts\start_console.ps1
```

打开 http://127.0.0.1:8765 。如果端口被占用：

```powershell
.\scripts\start_console.ps1 --port 8766
```

页面读取 `data/research.duckdb` 中真实 Yahoo 数据，没有模拟价格替代逻辑。显示最新日期、首次观测时间、拆股调整收盘价、过去20交易日价格变化、成交量与历史会话数。缺数据库时显示空数据。最新观察不会解除2025起的最终测试封存。

四个按钮分别刷新20只ETF真实数据、运行截至2024的市场风格研究、运行截至2024的因子诊断、生成最新观察日报。按钮任务串行执行，使用白名单命令与固定真实来源；期间暂停读取数据库，日志可从页面查看。CLI和其他控制台进程不要同时写同一数据库；跨进程写冲突将明确报错。页面关闭不终止后台任务；停止服务用启动终端 Ctrl+C。输出保存在 `outputs/real`。

新增“市场方向模型验证”“ETF A–D模型消融”和“P1–P6离线真实验收”按钮。模型训练及研究仍截止2024；ETF代理不称为完整个股Alpha。模型报告附按日配对Brier改善、20日块bootstrap区间；区间不能解除当前版本数据的历史可用性限制。

完整离线真实验收命令：

```powershell
.\.venv\Scripts\python.exe -m quant_research.cli real-acceptance
```

命令先在只读连接保护下复制真实仓库；存在未checkpoint的WAL、空库或只有合成数据时拒绝运行。随后在复制库内逐阶段运行P1审计、P2诊断、P3市场模型、P4消融、P5真实执行门槛检查、P6最新日报，不需要网络或密钥。原仓库不写入这些派生结果。每阶段保存命令、退出码、manifest、日志及文件哈希，入口为 `outputs/real_acceptance/<run_id>/report.html`。总退出码4表示真实研究/执行仍存在明确数据阻断，并非所有P都通过；失败退出码1。其他进程请勿同时写原库。复制库包含原数据库已有的工程记录，阶段命令只选择Yahoo价格，不会回退到合成数据。

研究报告为当前数据版本的回溯描述，不是历史可交易信号。最新日报可能明确显示 `NO_NEW_TRADING_ADVICE`，这是数据门槛的真实结果，不是执行故障。页面报告列表也包含已有合成工程报告，以报告内部 source/mode/status 为准。

免费版可用范围：真实ETF行情观察、市场风格状态、因子诊断、历史模型研究、可审计原始缓存与版本、报告导出。当前ETF列表不是历史股票池；缺退市证券、永久映射、原始成交价格/核验公司行为现金口径和PIT基本面。因此不开放真实数据策略净值、真实模拟成交、仓位建议或实盘下单。French只做事后归因；SEC快照不回填历史。完整个股Alpha与真实执行验收仍需要补齐数据，不把免费ETF探索版本称作买方研究级完整版本。

复现命令：

```powershell
.\.venv\Scripts\python.exe -m quant_research.cli market-report --source yahoo --mode retrospective --output outputs/real
.\.venv\Scripts\python.exe -m quant_research.cli factor-report --source yahoo --mode retrospective --output outputs/real
.\.venv\Scripts\python.exe -m quant_research.cli daily-report --source yahoo --mode retrospective --asof auto --output outputs/real
.\.venv\Scripts\python.exe -m pytest -q
```

无新交易建议的日报返回非零状态；应阅读报告中的原因，不能把它当成可执行信号。网络刷新需要联网；离线时已有数据库和报告可继续读取。服务仅绑定127.0.0.1，不提供远程部署或账户认证。应用无券商订单接口。HTTP写操作有随机令牌与Host校验，文件服务仅限outputs目录。
