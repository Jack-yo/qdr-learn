# v2.1 REAL_ONLY整改中

正式运行只接受可追溯真实数据。旧演示入口已撤除，旧合成测试不再作为验收结果。当前工程执行进度见 docs/G0_G5_TASKS.md。无合格数据时BLOCKED；不购买、不实盘、不解封最终测试。

启动：`.\scripts\start_console.ps1`。以下为旧版记录，fixture命令不再支持，阶段完成和测试数量不能作为v2.1验收。

# 美股多层量化研究系统

**免费真实数据操作页面已加入。** 在项目目录运行 `.\scripts\start_console.ps1`，打开 http://127.0.0.1:8765 。支持20只真实ETF行情、刷新、市场风格/因子研究、最新观察日报与报告浏览。使用说明及数据边界见 [真实版操作指南](docs/real_console.md)。保留原始成交价、PIT与退市数据缺口，不生成无法验证的真实策略绩效。

**P0–P6 工程功能与离线合成验收已完成，100 项测试通过。** 已有市场/风格状态、滚动 Ridge/Logistic、A–D 消融、108 组 A–E/基准成本回测、本地可续记模拟盘和日报。真实研究仍为 NOT_READY：Yahoo 当前版本与17 ETF不满足原始成交价/PIT/退市等条件。真实最终测试未开放，没有真实下单功能。

[本次交付报告入口](outputs/final_delivery/index.html) · [最终验收与文件清单](docs/final_acceptance.md) · [完整运行指南](docs/system_guide.md)

完整工程演示（安装依赖后无需网络/密钥）：

```powershell
.\.venv\Scripts\python.exe -m quant_research.cli run-all --source fixture --db data/demo-system.duckdb --state-db data/demo-paper.sqlite3
```

## 从零运行

需要 Python 3.11–3.13 和 uv 0.13.7。首次安装依赖需联网；安装后 demo 无需 API Key 或网络。

```powershell
uv sync --locked
uv run --locked pytest -q
uv run --locked python -m quant_research.cli --help
uv run --locked python -m quant_research.cli demo --fixture
uv run --locked python -m quant_research.cli demo --fixture --asof 2024-11-27
```

本次环境的 `python` 是不可执行的 Windows 应用别名，uv 已装在项目虚拟环境中。当前工作区可直接运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m quant_research.cli demo --fixture
.\.venv\Scripts\uv.exe sync --locked --cache-dir .uv-cache
```

P0 输出为 `outputs/experiments/<run_id>/report.json`、`fixture.json`、`config.json` 和 `run.log`。错误输入 exit code 2，成功为 0。P1 新增 `ingest`、`ingest-french`、`ingest-sec`、`data-audit`，详见 [P1 管道与运行说明](docs/p1_data_pipeline.md)。

pytest 默认在 `outputs/pytest-tmp/` 下创建唯一临时子目录，以适应受限 Windows 环境；可通过 `--basetemp` 显式覆盖。

## P0 范围

- `clock.py`：XNYS 实际交易日，UTC 存储，DST、休市和半日市；T 收盘后 15 分钟信号，T+1 开盘入场，T+H 收盘退出，H=1/3/5。
- `contracts.py`：原始 OHLCV 数据、事件/可用/抓取时间，重复和顺序检查、as-of 严格拒绝、PIT 股票池与成交时点约束。
- `data/providers/`：统一 provider 协议及确定性离线合成数据，20 个 ETF 名称的人工价格序列。
- `config.py`、`cli.py`：配置校验、UUID run_id、UTC 元信息、数据/参数/结果 SHA-256、日志。
- `tests/`：日历、数据质量、四类信息泄漏阻断、禁用网络的重复 demo。

## 可复现性

`uv.lock` 固定直接及传递依赖与分发包哈希。相同 fixture 范围、种子和配置应得到相同数据及结果哈希；run_id 和实际运行时间刻意不同。输出配置和全量合成数据快照便于复核。`asof_timestamp_utc` 是模拟历史决策时间；`created_at_utc` 是实际运行时间。fixture 的历史 available/ingested 时间是人工假设，不能充当真实市场时间证据。

## 文档

- [原始任务书](docs/Codex_美股多层量化研究系统_开发任务书.md)
- [架构](docs/architecture.md)、[数据字典](docs/data_dictionary.md)
- [数据限制](docs/data_limitations.md)、[研究协议](docs/research_protocol.md)
- [里程碑](docs/milestones.md)、[决策记录](docs/decisions.md)
- [P1 验收证据与剩余缺口](docs/p1_acceptance.md)
- [Yahoo 替代来源验收、71 项测试及运行命令](docs/p1_yahoo_acceptance.md)
- [P2 因子协议与命令](docs/p2_research.md)、[P2 验收与产物](docs/p2_acceptance.md)
- [P3–P6 使用、风控、模拟盘与调度](docs/system_guide.md)、[最终验收](docs/final_acceptance.md)

本项目不包含券商账户或下单接口。P0 通过不表示策略有效或数据达到 RESEARCH_GRADE。
