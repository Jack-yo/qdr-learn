# Codex 本地接力：L1 V3 实际数据及自动任务验收

请在项目最新 GitHub main 本地工作副本执行以下验证；目标是验证已提交的模型持久化、增量预测、到期核验和调度脚本，并仅在发现真实问题时提交最小修复。**不要改写模型原理、删其他页面、虚构任何概率、启动实盘交易或将 API 密钥写入 Git。**

1. 更新仓库并安装 pyproject.toml 规定的环境。保留现有本机环境变量、凭据及文件，不向日志打印敏感信息。
2. 执行离线测试：
   python -m pytest -q tests/test_l1_v3_alpaca_history.py tests/test_l1_v3_pipeline.py tests/test_l1_v3_probability.py tests/test_l1_v3_outcomes.py tests/test_l1_v3_http.py tests/test_l1_v3_ui.py tests/test_l1_v3_shell_integration.py
   报告通过数量、任何失败测试的完整栈与原因；修复由本轮改动导致的问题，必要时回归旧版 L1 及 L2/L3/L4。
3. 检查本地 read-only Alpaca 数据密钥是否配置。检查 QDR_L1_HISTORY_FEED=sip 或 iex，以及快照 QDR_L1_FEED=delayed_sip；不得静默回退为另一个 Feed。执行 python -m quant_research.workflow.l1_v3_verify --root . --live。若 403/429/数据缺失，请准确记录请求参数（脱敏）、响应代码、配额/权限说明，不要捏造成功数据。
4. 核对 outputs/l1_v3_models 的 SHA JSON 结构与真实三模型计算：七项输入值、标准化值、Logit、温度校准，三类之和 1；历史滚动样本外评分必须与输出一致，资格仍然 RESEARCH_ONLY。
5. 连续两次运行 python -m quant_research.workflow.l1_v3_pipeline --root . daily，应第二次 ALREADY_FROZEN，且不重新训练多年行情、不改写首个预测；必要时在另一个完成的交易日重复，确认 420 日行情路径重用模型。
6. 启动原 Web server，并请求 GET /api/v1/l1/v3/latest、/status、/outcomes、/history、/overview；验证所有 GET 纯读，不触发自动训练或网络任务；访问 /studio#market 完整操作 H1/H3/H5，检查暗色体系、数值计算明细、原始指标第二段滚动、公开数据欠缺及旧版研究入口。桌面/移动宽度检查无布局溢出。
7. 按用户操作系统安装自动任务（Windows scripts/install_l1_v3_windows.ps1、Linux scripts/install_l1_v3_linux.sh），检查计划状态、日志及用户账户读取凭据的能力。不得把启动软件一次视为连续调度完成，至少观察一次新的 NYSE 交易日收盘后实际任务运行。
8. 用真实已完成日期验证 H1/H3/H5 到期结果只在截止后写入，前向评分真实来源可追溯且报告不以历史 PIT 认证冒充。若新交易日尚未到期，请保持 PENDING，而不是伪造后验标签。
9. 交付一份简洁的报告：测试通过/失败、真实 Alpaca 取数覆盖、历史日线源、模型保存及加载、每日新旧两轮性能（秒）、前向归档数量、Brier/LogLoss、HTTP 响应、系统调度状态、未能完成的验证项。不要宣称正式概率发布资格已通过。

核心实现文件：src/quant_research/data/l1_light_sources.py；
src/quant_research/workflow/l1_v3_persist.py；
src/quant_research/workflow/l1_v3_pipeline.py；
src/quant_research/workflow/l1_v3_scorecard.py；
src/quant_research/assets/v4_ui_market_v3.js。

真实依赖凭据/网络/系统调度无法在 ChatGPT 环境直接完成；请基于用户本机验证结果准确反馈，不要用合成行情替代真实验收。
