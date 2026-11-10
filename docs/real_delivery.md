# 免费真实数据改造交付

## 修改文件

- `src/quant_research/web.py`：本地HTTP服务、真实数据库概览、受限报告文件访问、串行后台任务、来源与执行门槛。
- `src/quant_research/web.html`：中文操作页面、真实行情表、运行按钮、日志与报告入口。
- `scripts/start_console.ps1`、`start_console.cmd`：命令行/双击启动入口。
- `tests/test_web.py`：命令白名单、真实来源、禁止执行、空库、并发写保护、HTTP令牌、Host及目录穿越验证。
- `docs/real_console.md`、`README.md`：运行方式与免费数据边界。

## 实际数据与运行证据

真实联网刷新运行：`outputs/real/694f3fd0-a75b-401f-8c79-f872b06f0b1b/manifest.json`。20只ETF，2017-01-03至2026-11-06，每只2476个交易日，共49520条最新版本日线；coverage_complete=true，947条来源公司行为记录仍未核验现金记账口径。数据库保留旧版本，物理行数不等同最新日线数。

市场风格报告：`outputs/real/e717782d-6a62-4619-b545-47c2e0eb1aaa/report.html`，当前版本回溯描述。

刷新后因子报告：`outputs/real/34599b20-5839-4dfa-8ac8-0df40f9086ab/report.html`，RETROSPECTIVE_EXPLORATORY_ONLY。

从HTTP按钮实际生成的最新日报：`outputs/real/37ac4e6b-b025-4e86-bf9c-297481925ebb/report.html`，NO_NEW_TRADING_ADVICE，退出码4。保留first-observed及raw/PIT门槛，无模拟成交与券商下单。

浏览器截图：`outputs/real/console.png`，1440×1200，真实数据已显示。实际HTTP状态接口返回20只真实ETF、execution_enabled=false。网页操作成功启动CLI并生成上述日报。

HTTP测试需要允许本机回环连接；受限沙箱整套结果为102通过、1项因WinError10013失败；允许回环后完整复测 **103 passed in 245.82s**，证据 `outputs/real/pytest-verified.xml`。

## 仍未完成的真实研究验收

全历史个股股票池与退市覆盖、稳定证券身份、可核验raw价格和公司行为、PIT基本面；基于这些数据的真实历史成交回测、滚动样本外和模拟盘验收。工程能力保留，不能以免费ETF回溯代替。真实最终测试尚未开放。此次交付是可使用的免费真实数据研究界面，不宣称已达到完整买方个股系统数据条件。
