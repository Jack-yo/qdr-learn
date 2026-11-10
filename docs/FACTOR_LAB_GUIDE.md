# 因子实验室使用与维护

入口：`http://127.0.0.1:8766/factors`。本模块用于真实历史价格的探索检验，尚未提供合格个股 Alpha、预测或可交易策略。

## 网页操作

1. 创建因子，选择反转、动量或波动率模板，填写窗口、方向和研究假设。模板只接受参数，不执行用户 Python 或表达式。
2. 主动选择数据源，再预览真实样本、公式、来源及快照哈希。Yahoo 为历史回溯探索；Alpaca 仍须通过独立特征价格准入。失败会返回阻断原因，不自动切换供应商。
3. 创建实验。系统冻结因子版本、当前显式 ETF 名单、知识截止、数据源及完整研究协议，然后点击运行。
4. 查看实际任务状态、H1/3/5 的 IC、覆盖率、区间估计和分组报告。COMPLETED 只表示计算完成，不代表研究或交易资格通过。
5. 修改参数时复制为新版本；旧定义、实验及结果不覆盖。比较两个已完成实验时，数据源、快照、价格口径及评价协议必须一致。

当前真实 Yahoo 样本为 2017-01-03 至 2024-12-31 的 20ETF、40,240 个证券日。SPY 为基准，SPY/HYG/LQD 不进入候选横截面，因而因子目标为 17ETF。该名单不是历史 PIT 股票池；Yahoo 数据为当前版本拆股调整价格，其首次观测时间不能冒充历史可用时间。

研究协议固定为 2017–2022 训练描述、2023–2024 验证描述；标签按 T+1 开盘至 T+H 收盘计算，H=1/3/5。使用 5 交易日隔离和跨边界标签剔除，最小横截面 10，五分组，20 日区块 bootstrap、500 次、种子 42。这里没有拟合预测模型，不能把分区指标称作模型滚动样本外验收。

所有标签均为探索代理标签，正式 raw 标签与扣费收益保持空值。没有模拟成交、策略净值、手续费或滑点绩效。多版本比较未做多重检验校正；历史行业、市值与风格暴露连接也未验收。2025 年起最终测试期保持封存。

最新 Yahoo 缓存的 2026-11-06 缺字段仍单列阻断；本模块独立逐行核验 2017–2024 范围，不拿完整最新行情作保证。Alpaca 行情观察可用，但公司行为特征价格严格精度准入尚未通过，不能绕过它启动本实验。

## 命令行

在项目根目录运行：

```powershell
# 首次创建。名称必须唯一；已有名称请通过页面复制版本，或提供含 parent_version_id 的定义文件。
.\.venv\Scripts\python.exe -m quant_research.cli factor-lab-create --definition configs/factors/reversal5.json --source yahoo

# 将上一步真实返回的实验 UUID 填入，禁止直接照抄占位符。
.\.venv\Scripts\python.exe -m quant_research.cli factor-lab-run --experiment-id <实验UUID>

# 刷新分类目录，包含版本数和实际实验状态；不联网。
.\.venv\Scripts\python.exe -m quant_research.cli data-catalog
```

运行成功退出 0，BLOCKED/FAILED 退出 4。已结束实验再次运行返回原状态，不覆盖文件。数据修复后新建实验以冻结新的知识截止和输入；不要手改旧 JSON、数据库状态或哈希。

## 存放与备份

| 内容 | 位置 | 日常维护 |
|---|---|---|
| 因子版本和冻结实验 | `data/managed/factor_lab/registry.sqlite3` | 按需新建，不手改旧记录 |
| Yahoo 历史探索输入 | `data/research.duckdb` 中受源和范围筛选的价格 | 仅 YAHOO/yahoo_split_adjusted、2017–2024；不接受整个混合库 |
| 来源原文、回执 | `data/raw/` | 与数据库一起保留，不删除哈希对象 |
| 每次计算结果 | `outputs/factor_lab/<实验UUID>/` | config、manifest、特征/标签、评价表、HTML；读取时校验文件 SHA256 |
| 后台日志 | `outputs/factor_lab/jobs/<实验UUID>.log` | 查看实际退出与失败原因 |
| 分类入口 | `data/managed/factor_lab/dataset.json`、`data/catalog/latest.json` | 新增实验后运行 data-catalog 刷新快照 |

在维护和实验任务均结束、写连接关闭后备份。恢复时保留原始文件，重新核验来源与产物哈希；单有 HTML 文件不构成验收证据。维护锁存在时实验拒绝启动，不抢占写库任务。
