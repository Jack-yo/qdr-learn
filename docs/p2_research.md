# P2 因子与探索性研究协议

P2 是因子计算、标签与诊断框架，不是训练模型或策略回测。2025 年起的最终测试数据继续封存。当前仅有 ETF 代理面板，不能声称已验证个股 Alpha。

## 命令

```powershell
# 完整无密钥、无网络合成演示，覆盖 252 日回望
.\.venv\Scripts\python.exe -m quant_research.cli factor-report --source fixture --mode strict --db data/p2_fixture.duckdb

# 真实 Yahoo 当前版本的回溯描述；明确不是历史 PIT 决策
.\.venv\Scripts\python.exe -m quant_research.cli factor-report --source yahoo --mode retrospective

# 严格历史信息约束：本项目 Yahoo 数据于 2026 年首次观测，故历史日期应被阻断并返回 4
.\.venv\Scripts\python.exe -m quant_research.cli features --source yahoo --asof 2024-12-31

# 封存期请求应在读取价格前返回 2
.\.venv\Scripts\python.exe -m quant_research.cli factor-report --source yahoo --mode retrospective --end 2025-01-02

.\.venv\Scripts\uv.exe run --offline --locked --cache-dir .uv-cache pytest -q
```

共同参数：`--experiment`、`--db`、`--output`、`--source fixture|yahoo`、`--mode strict|retrospective`、`--start`、`--end`；features 要求 `--asof`。`--horizons` 仅接受冻结的 `1,3,5`。不会静默从 strict 切换到 retrospective。

返回 0 表示工程计算完成，不表示策略可用；2 表示配置/日期/因子因果性等参数约束失败；4 表示没有在该历史信号时点可用的有效特征。运行产物写在 `outputs/research/<run_id>`。DuckDB 为单写进程，不要并行运行多个写同一数据库的命令。

## 冻结的实验范围

`configs/experiments/p2_factors.yaml`：2017–2022 训练描述，2023–2024 验证描述；2025 起封存。SQL 在价格读入前即限制日期，不能通过 --end 或修改 sealed_test_start 开放最终测试。

训练统计末尾额外保留 5 个交易日 gap；每个分区还剔除退出跨出该分区的标签。最终训练 IC 日期不晚于 2022-12-22。验证期只展示结果，不据此翻转因子方向、选窗口或选择成功阈值。本阶段成功标准仅为工程与公式验证。

SPY 为基准；HYG/LQD 是信用代理，排除出横截面研究；SPY 自身也不作为预测对象。因此真实样本有 17 个 ETF 目标，而非 200–500 只个股。ETF 成分重叠，不能把这些目标当作独立股票样本。

## 因子接口

`Factor` 声明 name、version、lookback、dependency、missing_reason 和 compute(context)。返回与输入严格同轴的日期×证券矩阵。引擎负责日历对齐、完整窗口、可用时间、缺失原因和输出。

可向 `compute_features(..., factors=[...])` 或 `research.pipeline.execute(args, factors=[...])` 传入新插件，无需改研究引擎；可与 builtin_factors() 合并。新增插件必须声明真实依赖，补公式和未来数据扰动测试，不得隐瞒外部输入。

| 名称 | 公式与规则 |
|---|---|
| reversal_1d/5d/10d | -(close[t]/close[t-k]-1)，固定三个窗口 |
| momentum_12_1 | close[t-21]/close[t-252]-1；需完整 253 个价格点 |
| sector_residual_5d | -(stock_ret5-beta_sector60*sector_ret5)，Beta 仅用截至 t 的 60 个收益；无 timestamped 分类则缺失 |
| realized_vol_20 | 最近 20 个日收益的样本标准差 × sqrt(252) |
| vol_ratio_5_20 | 样本 std(ret,5)/std(ret,20)，分母 0 则缺失 |
| adv20 | mean(close*volume,20)；Yahoo 值仍是供应商复权与成交量口径 |
| amihud20 | mean(abs(ret)/(close*volume),20)，不额外缩放，单位 USD^-1；零成交金额则缺失 |
| close_location | (close-low)/(high-low)，high=low 则缺失 |
| rel_strength_sector_5d | stock_ret5-sector_ret5，缺 PIT 分类则缺失 |
| beta_60 | cov(stock_ret,SPY_ret,60)/var(SPY_ret,60)，需 61 个价格点 |
| size_pit / quality_pit | 当前仅提供缺失状态，尚未接入 PIT 市值/盈利事实；不使用当前值回填 |

不填补日历缺口，不把上市不足窗口填为 0；不全样本标准化、缩尾或填充。原始因子方向固定，高值进入高分组，不能看结果后改正负号。

## 时间与防泄漏

strict 模式：每条特征 available_at 是声明依赖窗口的最大原始可用时间（包括 SPY/行业代理和分类时间）；只有 available_at ≤ T close+15min 才保留数值与决策资格。

retrospective 模式：允许描述当前下载版本中的历史价格形态，但不修改输入 available_at，所有 decision_eligible=false。后续模型/风控不得将这类行视为历史可交易特征。

插件会在样本中点、尾部前 5 日做前缀重算一致性检查，拒绝常见负向 shift、全样本均值等行为。内建因子另有完整未来价格/可用时间扰动测试。抽查不能作为任意第三方代码已获形式化无泄漏证明；插件依赖声明仍需审查。

## 标签

严格交易时钟：T+1 open 到 T+H close，H=1/3/5；使用实际 XNYS session。窗口内任何缺失交易日均使标签缺失，不将下一行误当下一交易日。末尾不完整标签保持 null。

fixture 只有合成 raw 价格，forward_return 为合成成本前原始价收益。Yahoo 的 forward_return/benchmark_return 均为 null，只写 proxy_forward_return/proxy_benchmark_return；它们是 split-adjusted OHLC 的价格收益代理，不代表可成交原始收益、含分红总收益或策略绩效。net_return 始终为空，成本在 P5 实施。

标签 available_at 取未来持仓窗口与基准输入的最大可用时间。标签与特征分开存储，不能进入特征计算。对最终数据边界外的退出时间只保留计划时钟，不读取封存期价格或生成收益。

## 诊断定义

- 每日横截面 Spearman Rank IC：成对非空样本的平均秩 Pearson 相关；最少 10 个目标，常数秩为 null。
- ICIR：日 IC 均值 / 日 IC 样本标准差，不年化；零标准差为 null。输出 IC 分位数及逐日 Parquet。
- 均值区间：20 session 循环块 bootstrap，500 次、seed=42、95% percentile CI；保留日历位置和缺失。少于两块的有效样本不输出区间。块长为预设值，不能据此保证覆盖率或宣称独立 Alpha；不提供 iid t-test、p 值或多重检验后优势结论。
- 五分组：每日平均秩映射到固定五组，保留 ties，不人为排序相同值；不足 5 个不同值不分组，空组不造数。先按日取组均值，再时间平均，避免覆盖多的日期获额外权重。
- 换手仅是最高分组等权成员的 0.5*L1 权重变化，遇缺口重置；不是实际持仓、成本或组合交易换手。
- 相对 SPY 的 Rank IC 同时给出；同日减去共同基准不改变股票横截面秩，两者相同不代表新增预测信息。
- 因子相关性为每日横截面秩相关的时间均值。行业/市值暴露无 PIT 输入时为空，风格相关性明确等待 P3。
- 市场条件是预设描述规则：SPY 过去 20 日价格收益 >0 / ≤0；不是预测状态或交易开关。条件均值仅为描述统计，不做逐日独立显著性检验。

## 产物与持久化

DuckDB schema v3：features_daily 和 labels 按 run_id 保存，保留 research_mode、available_at、decision_eligible、缺失原因和标签价格类型。后续消费者必须显式按 run_id、mode 和资格过滤。

每次研究输出配置/数据/代码哈希、源版本、universe_version/model_version、运行时库版本、UTC 截止时间和 run_id。summary.csv/parquet、daily_ic.parquet、daily_groups.parquet、conditional_ic.csv/parquet、factor_correlations.csv/parquet、features.parquet、labels.parquet、HTML 与日志一同保存。

参考：[Spearman 定义与常数输入](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.spearmanr.html)、[循环块 bootstrap](https://arch.readthedocs.io/en/latest/bootstrap/timeseries-bootstraps.html)。实现未引入 scipy/arch 依赖，采用独立公式和测试对照。
