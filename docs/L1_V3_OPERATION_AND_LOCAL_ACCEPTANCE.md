# QDR L1 V3 — 训练、每日预测、归档和本地验收

本文件以 2026-11-15 版本为基础。用户界面沿用原 QDR 暗蓝设计；本轮仅完善 L1 的运行架构，不修改 L2/L3/L4。

## 交付状态

**代码已具备：** Alpaca 历史 Feed 与快照 Feed 分离、分页与时间窗校验、ETF 核心历史质量门槛、三个期限的 Logistic + 标准化 + 温度校准模型持久化、独立的每日推断、只读快照 API、前向归档/到期结算、跨进程 OS 锁、失败日志、Windows/Linux 定时任务安装入口、离线回归测试、带凭据的本地验收脚本。

**必须在用户机器上完成：** 安装 Python 环境，授权只读 Alpaca 历史行情，完成真实 API 请求和至少一次真实数据模型训练；安装/启用自动任务并持续验证其下一交易日执行。当前 ChatGPT 无法访问本地密钥和进程，不能宣称这些已经实际通过。

## 核心流程

1. 历史训练：Alpaca historical bars 请求 SIP 或 IEX，窗口最多约 2500 自然日；**价格调整固定 split**，不混用 raw；每一页保留 SHA256 来源收据。要求全部 5 个核心 ETF 最近 80 个观测日同步，无非法 OHLC、缺失或重复。
2. 训练：7 项核心 ETF 特征 × H1/H3/H5。严格分开的训练、温度校准与时间向前滚动 OOS。归档 Numeric Brier、LogLoss、ECE 与历史频率基准。模型参数是可审计 JSON（scaler.mean/scale、3×7 系数、截距、温度、训练/校准规模）；使用 SHA256 命名，不用 pickle。
3. 推断：前向任务加载最近一次真实模型（35 日后自动重训），仅向 Alpaca 请求最近约 420 自然日，计算当前因子值并使用 NumPy 重算已保存的 Logit 和三类概率。**不重新跑滚动训练**。
4. 预测冻结：每个已完成交易日只能有一份官方冻结记录，同样截止日不能重新写入不同预测；源收据、输入、模型引用与计算明细一起归档。
5. 到期验证：只读取近期数据并追加不可覆盖的实际 H1/H3/H5 收益、市场情景与 Brier，不修改原预测。
6. 只读 UI：/studio#market 请求 /api/v1/l1/v3/latest 和 /status，**不再通过 HTTP GET 触发多年行情下载、训练或写盘**；官方公开数据和 V2 原始观测依旧按需独立加载。
7. 调度：\`daily\` 可由每 30 分钟触发一次；交易所收盘+15 分钟之前不会猜测当日结果。记录最近最多 90 条任务日志，OS 文件锁保证进程崩溃后自动释放，跨进程不重入。
8. 资格：所有数据当前依然属于 current-vintage ETF 研究。\`admitted_probabilities=null\`，\`historical_pit_verified=false\`，\`execution_eligible=false\`，**禁止将这些研究估计宣称为已认证/有实盘交易优势的概率**。

## 历史数据配置

\`\`\`text
ALPACA_API_KEY=<在用户本地配置，不提交 Git>
ALPACA_SECRET_KEY=<在用户本地配置，不提交 Git>
QDR_L1_HISTORY_FEED=sip       # 历史 bars；无 SIP 权限时显式设置 iex
QDR_L1_FEED=delayed_sip       # snapshot 可使用 delayed_sip
\`\`\`

**不能把 delayed_sip 作为历史 bars 的 feed。** SIP 是合并交易所行情，IEX 是较小的单交易所样本，若 IEX 对部分 ETF/日期缺乏连续日线，模型须阻断，不允许悄悄合并两种 Feed 进行训练。

Alpaca 日线支持 \`raw\`、\`split\`、\`dividend\` 等 adjustment；这版模型使用 \`split\` 解决拆股断层，属于当前数据版本的价格调整，不等于历史 PIT 证明；真实收益的分红/交易成本仍未建模。

## 命令（在项目根目录）

\`\`\`bash
python -m quant_research.workflow.l1_v3_verify --root .
# 首次训练
python -m quant_research.workflow.l1_v3_pipeline --root . train
# 交易日收盘后增量预测 / 冻结 / 到期核验
python -m quant_research.workflow.l1_v3_pipeline --root . daily
# 仅补核验
python -m quant_research.workflow.l1_v3_pipeline --root . settle
# 查看系统状态与最近一次冻结（仅本地文件，无联网）
python -m quant_research.workflow.l1_v3_pipeline --root . status
python -m quant_research.workflow.l1_v3_pipeline --root . latest
# 一次完整真实 API 验收（需要本地凭据）
python -m quant_research.workflow.l1_v3_verify --root . --live
\`\`\`

启动原本的 QDR Web Console 后访问 \`/studio#market\`。

### 任务调度（在用户本地安装）

- Windows：PowerShell 执行 \`.\scripts\install_l1_v3_windows.ps1\`，创建当前用户的 QDR-L1-V3-Daily 任务，每 30 分钟检测一次；运行状态查看 \`Get-ScheduledTask -TaskName QDR-L1-V3-Daily\`。安装器不会写入 API 密钥；需确保调度用户能读取正常环境变量与 Python 环境。当前设置的任务触发最长重复期为 365 天，期满须续设。
- Linux：执行 \`bash scripts/install_l1_v3_linux.sh\`，安装 systemd **用户定时器**；无图形登录的服务器还需显式配置 user lingering，确保服务在退出登录后继续运行。
- 其他平台或临时运行：\`python -m quant_research.workflow.l1_v3_pipeline --root . daemon --interval 900\` 是**前台**循环，需 OS supervisor 才能脱离终端运行。

这些文件只是在本地安装任务的工具，本次 PR 不会也不能直接修改你电脑的任务计划程序。

## 测试与验收

\`\`\`bash
python -m pytest -q tests/test_l1_v3_alpaca_history.py \
  tests/test_l1_v3_pipeline.py tests/test_l1_v3_probability.py \
  tests/test_l1_v3_outcomes.py tests/test_l1_v3_ui.py \
  tests/test_l1_v3_shell_integration.py
\`\`\`

验收必须看到：
- Feed 分离、分页连续、未来数据/重复数据拒绝；
- 首次训练模型文件落地，SHA256 可以验证并且重新加载精确复现原始概率及温度校准结果；
- 同一个交易日二次运行无重复归档，下一交易日仅用近期行情与同一模型推断；
- 预测日期未到不允许写后验结果；到期后结果来自真实 SPY bar；
- 模型数据缺失、滞后/权限不足、校准条件不足、文件篡改或任务并发，均必须失败关闭；
- Web 页面 6 个独立渐进请求，原 QDR 主题和旧研究入口保持不变，V3 GET 无模型训练副作用；
- 本地真实 API 验收输出 LIVE_ACCEPTANCE_PASS 后，仍需至少一个**新的**交易日观察自动任务执行及结果归档。

## 持久化目录

\`\`\`text
outputs/l1_v3_models/YYYY-MM-DD/<full SHA256>.json
outputs/l1_v3_research/YYYY-MM-DD/<SHA256-prefix>.json
outputs/l1_v3_outcomes/YYYY-MM-DD/<SHA256-prefix>_H1|H3|H5.json
outputs/l1_v3_jobs/YYYYMMDD...json
\`\`\`

供应商原始日线仍使用 \`data/cache/l1_on_demand\` 的严格大小/TTL 缓存，不建立历史行情常驻数据库。模型和预测文件是小型不可覆盖研究证据。

## 仍需严格限制的研究结论

当前 **不能证明**：交易前完全可用的历史 PIT 数据、模型可持续的 OOS 优势、市场真实可成交收益、交易成本和滑点、足量的独立前向样本。若后续要申请真正的概率资格，需要按预测当时原始数据来源时点逐步积累真实前向成绩，且有预先写定的通过门槛。其他 12 域公开观测目前只是监控证据，不可自行赋予“概率贡献”。


## 2026-11-17：Alpaca SIP 历史数据 HTTP 403 的安全排查

- L1 每日研究使用历史 `1Day` bars，不是 Snapshot。历史 Feed 由 `QDR_L1_HISTORY_FEED` 控制（默认 `sip`），与 `QDR_L1_FEED` 快照权限分开。
- 历史日线请求的 `end` 现在固定为 XNYS 交易日收盘 + 1 分钟，不再使用下一自然日 00:00。免费 SIP 的最近 15 分钟限制另留缓冲；太早则返回 `HISTORICAL_SIP_EMBARGO_PENDING`，等待下一轮定时任务，不会自动回退 IEX 或发布预测。
- 使用本地合法环境变量运行（密钥仅在 `.env` 时可通过 `uv run --env-file .env` 显式加载），先做回归，再重跑一次每日任务：

```bash
uv run --locked pytest -q tests/test_l1_v3_alpaca_history.py tests/test_l1_v2.py --tb=short
uv run --locked python -m quant_research.workflow.l1_v3_pipeline --root . daily
uv run --locked python -m quant_research.workflow.l1_v3_pipeline --root . status
```

- 若日线截止时间已过、仍出现 `HTTP_403`，检查真实 API key/secret 对应账户及历史行情 Feed 权限（不要发送密钥或带认证的完整请求）。不要静默改成 `iex`：已有模型记录 Feed 身份，SIP/IEX 不能直接混用。
- `/api/v1/l1/v3/latest` HTTP 200 仅说明旧归档可读取，不能证明每日任务成功。旧版 7.2 冻结不能重写；仅在新任务生成 `FROZEN_RESEARCH_ONLY` 且 asof 正确时才代表新增研究预测，且仍必须标记 `RESEARCH_ONLY`。
