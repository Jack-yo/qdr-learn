# P0 验收记录 — 2026-11-06

DONE：P0 本地验收通过；未开始 P1。初始目录为空，已初始化 Git，未创建提交或远端。

## TESTS

实际环境：Windows、Python 3.13.15、uv 0.13.7；依赖以 uv.lock 为准。

```powershell
.\.venv\Scripts\uv.exe run --offline --locked --cache-dir .uv-cache pytest -q --junitxml=outputs/p0-pytest.xml
.\.venv\Scripts\uv.exe run --offline --locked --cache-dir .uv-cache python -m quant_research.cli demo --fixture
.\.venv\Scripts\python.exe -m quant_research.cli --help
```

最终 pytest：**35 passed in 4.22s**，exit code 0，无 warning。XML：`outputs/p0-pytest.xml`。
Demo exit code 0。集成测试禁用 socket 连接并重复运行，确认数据/结果哈希一致、run_id 不同。
四类故障注入均被拒绝：未来 close、回填未来财报、T 日收盘成交、当代股票池冒充历史 PIT。
另测 DST、半日市、感恩节/圣诞节/2025-01-09 休市、H1/H3/H5、naive 时间、错误复权、重复键、错误 OHLC、配置与无效 asof。

首轮结果曾为 24 passed、6 errors：沙箱系统临时目录不可写。已将测试临时文件转到工作区唯一子目录，完整重跑通过。发现日历与 NumPy 2.5.4 的弃用警告后，将 NumPy 锁为 2.3.4；未屏蔽警告。
远端 CI 未执行；Windows/Linux、Python 3.11–3.13 矩阵只是已配置。

## DATA / RESULTS

- 数据为 SYNTHETIC_FIXTURE，20 个人工证券，2024-11-01 至 2024-12-06，共 500 行。
- 模拟信号时间 2024-11-27 21:15 UTC，合法可见 380 行。
- T+1 开盘 2024-11-29 14:30 UTC；H1 退出为该日半日市 18:00 UTC；H3/H5 分别为 12-03/12-05 21:00 UTC。
- future_leakage_blocked=true；performance=null；SYNTHETIC/DATA_INCOMPLETE/NOT_READY。

最终 demo 报告：`outputs/experiments/af673f43-ba82-457d-99d8-781edb57c362/report.json`。同目录含 fixture.json、config.json、run.log。

数据 SHA-256：`d8b43127edf57fac528f8bd847addc4fb43f542b33c86daa0b8e0412ce9289ec`

配置 SHA-256：`1ca281568e3f8d753af54e95c09217ce3979521253a9813a8b0220af1fb1f65d`

结果 SHA-256：`c6cdbe230adf8071c9a21fcc40b4cdf030abd88f10869402a2097f3a4bdf353d`

## RISKS

没有真实行情、PIT 股票池、退市数据、公司行为、财务发布时间或交易成本证据；不能推出 Alpha、胜率或盈利结论。所有尚未实现的业务模块仅目录占位。契约测试不能替代后续模型、特征和回测的端到端防泄漏验证。

## NEXT

P1 首步核实 Alpaca 账户数据权限与免费历史覆盖；实现统一持久化 schema、来源元信息与适配器，再加入幂等缓存、French 单位和可用时间、SEC 接口及审计。验收必须证明 20 证券实际可得历史、断网缓存复用与重复运行不重复入库；覆盖不完整必须标记，不补造历史。不在本次交付中推进 P1。

## 文件清单

以下为新增交付文件（含目录占位文件；不包含虚拟环境、缓存和 outputs）：

- `.env.example`
- `.github/workflows/.gitkeep`
- `.github/workflows/tests.yml`
- `.gitignore`
- `AGENTS.md`
- `README.md`
- `configs/base.yaml`
- `configs/experiments/.gitkeep`
- `configs/sources.yaml`
- `docs/.gitkeep`
- `docs/Codex_美股多层量化研究系统_开发任务书.md`
- `docs/architecture.md`
- `docs/data_dictionary.md`
- `docs/data_limitations.md`
- `docs/decisions.md`
- `docs/milestones.md`
- `docs/p0_acceptance.md`
- `docs/research_protocol.md`
- `notebooks/.gitkeep`
- `pyproject.toml`
- `src/quant_research/__init__.py`
- `src/quant_research/app/__init__.py`
- `src/quant_research/backtest/__init__.py`
- `src/quant_research/cli.py`
- `src/quant_research/clock.py`
- `src/quant_research/config.py`
- `src/quant_research/contracts.py`
- `src/quant_research/data/__init__.py`
- `src/quant_research/data/providers/__init__.py`
- `src/quant_research/data/providers/base.py`
- `src/quant_research/data/providers/fixture.py`
- `src/quant_research/features/__init__.py`
- `src/quant_research/models/__init__.py`
- `src/quant_research/reports/__init__.py`
- `src/quant_research/research/__init__.py`
- `src/quant_research/risk/__init__.py`
- `src/quant_research/validation/__init__.py`
- `tests/conftest.py`
- `tests/fixtures/.gitkeep`
- `tests/fixtures/bars_synthetic.json`
- `tests/integration/test_demo.py`
- `tests/leakage/test_guards.py`
- `tests/unit/test_clock.py`
- `tests/unit/test_config.py`
- `tests/unit/test_fixture.py`
- `uv.lock`
