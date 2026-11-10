# P0 数据契约与后续表设计

P1 更新：当前已实现 schema 以 `src/quant_research/data/schema.py` 和 `data/store.py` 为准。已建表 securities、prices_daily、price_observations、factor_returns、sec_snapshots、filings、runs，以及空的 corporate_actions、universe_daily、fundamentals_pit。下方“后续表”是 P0 初始设计，未实施表仍保持计划状态。

P1 prices_daily 主键为 security_id/date/source/feed/adjustment_basis/raw_sha256；price_observations 在此基础上加 available_at。Factor 主键 date/factor_name/source/version；SEC 快照主键 cik/kind/raw_sha256；filings 主键 cik/accession/source_version。available_at 为首次观测时间，不能为空；SEC accepted_at 和 period_end 可空，不反推发布时间。不同 feed 和 raw/复权不可混存。所有价格版本保留，as-of 先筛时间再选版本。

Yahoo 更新（schema v2）：prices_daily 新增 nullable adj_close DOUBLE；Yahoo 的 adjustment_basis 只能为 yahoo_split_adjusted、source=YAHOO、feed=yahoo、availability_basis=first_observed。不能声明 raw。corporate_actions 已有真实 Yahoo 事件，新增 quality_flag/currency；announced_at=null，available_at 为抓取时刻，factor_or_cash 为供应商所给比率/金额，现金基准未核验，不直接做现金记账。universe_daily/fundamentals_pit 仍为空。

P2 schema v3：features_daily 主键 run_id/date/security_id/feature_name，value 可空；available_at 为声明依赖的最大时间，未知可空；signal_time 必需，research_mode/decision_eligible/missing_reason/version 必需。labels 主键 run_id/date/security_id/horizon，entry/exit 日期时间必需；available_at/forward_return/benchmark_return/proxy_forward_return/proxy_benchmark_return/net_return 可空。Yahoo 只写 proxy 收益，正式 raw/net 列为空。source、输入/代码/配置哈希和样本模式由同 run_id 的 runs/manifest 追溯。其余后续模型/交易表仍未实施。

P3–P6/schema v4：predictions 主键 run_id/date/security_id/horizon/variant，p_up/expected_return/expected_excess_return/downside_quantile/uncertainty 可空；model_version/available_at/decision_eligible/research_mode 必需，无法估计的uncertainty保持null。orders/fills 主键 run_id/experiment_key/sequence；fills数量、价格、UTC时间、成本必需。positions/equity_curve 主键分别为 run_id/experiment_key/date/security_id 和 run_id/experiment_key/date；数量/现金/权益等必需，附完整record_json。开盘持仓另存Parquet/CSV，收盘positions不代表H1日内没有头寸。

纸面SQLite：accounts(account,config_hash,state_json)，days(account,date,input_hash,snapshot_json)，events(account,event_id,date,kind,cash_change,body_json)。未知事件金额不得伪造，重复日期输入变化拒绝覆盖，事务内核对现金后提交。

## 已实现契约

所有时间要求 timezone-aware，比较时转换为 UTC；序列化 UTC 来源使用 `+00:00`。不接受 naive 时间。所有已实现字段不可省略，除显式默认值；不自动填补缺失值或删除异常值。

| 契约 | 主键/身份 | 字段及规则 |
|---|---|---|
| DailyBar | security_id,date | date 为交易所 session 日期；open/high/low/close 为有限正数，high/low 必须包络 open/close；volume 非负整数；adjustment_basis 仅 raw；event_time=当日交易所收盘；event_time ≤ available_at ≤ ingested_at；source=SYNTHETIC_FIXTURE |
| Observation | security_id,name,event_time,version | value 必须有限；source/version 为来源版本；event_time ≤ available_at；决策时 event_time 与 available_at 均 ≤ data_cutoff_utc ≤ signal_time |
| TradeWindow | signal session,horizon | signal_time 为 T close+15min；entry_time 为 T+1 open；exit_time 为 T+H close；H 只允许 1/3/5 |
| Run JSON | run_id UUID | asof_timestamp_utc/data_cutoff_utc、universe_version、model_version、created_at_utc、config/data/result_sha256、runtime_versions；performance=null |

DailyBar 批量校验拒绝重复主键、不递增日期、非交易日或 event_time 与日期不一致。证券 ID 使用 `SYNTH-<ETF名称>`，不代表真实稳定证券 ID。P0 无拆分/分红，不能用其证明企业行为处理正确。

## 后续持久化表的设计约定（未实施）

以下只是 P1 起采用的初始设计，不宣称已经建表。数据字典和迁移会在各表实际实现时细化。时间规则沿用上述 as-of 规则，外键均指向稳定 security_id；必需键不可空，缺失业务事实显式为 null 并附 quality_flag。

| 表 | 计划主键 | 主要字段/空值与时间规则 |
|---|---|---|
| securities | security_id | symbol/exchange/asset_type/source 必需；first_seen 必需，last_seen 可空，不推断退市 |
| prices_daily | security_id,date,source,adjustment_basis | OHLCV 必需；vwap 可空；记录 available_at/ingested_at；执行只用 raw |
| corporate_actions | security_id,ex_date,action_type,source,event_id | factor_or_cash 必需；announced_at 未知为空，不能作为已知特征 |
| universe_daily | date,security_id,universe_version | is_eligible/reason/source/quality_flag/available_at 必需；无法获得 PIT 时明确缺失 |
| filings | security_id,accession | cik/form/period_end/accepted_at/available_at 必需；amended_at 可空；修订不覆盖旧版本 |
| fundamentals_pit | security_id,feature,period_end,source_accession | value 可空；available_at 必需；按披露版本保存 |
| factor_returns | date,factor_name,source,version | value_decimal 可空；available_at 未知则不得进入决策 |
| features_daily | date,security_id,feature_name,version | value 可空；available_at 和输入谱系必需 |
| labels | date,security_id,horizon,label_version | entry/exit 日期与时间必需；forward_return/benchmark_return 数据不足时为空；禁止进入特征 |
| predictions | date,security_id,horizon,model_version,run_id | p_up/expected_return/downside_quantile 无有效估计时为空 |
| orders | run_id,order_id | paper only；signal/计划入场时点、数量、状态必需 |
| fills | run_id,fill_id | order_id、原始成交价、数量、成交时间和成本必需 |
| positions | run_id,date,security_id | 数量、成本、估值与 quality_flag 必需 |
| equity_curve | run_id,date | cash/equity/costs 必需，无法估值不得静默补造 |
| runs | run_id | asof/cutoff、数据/配置版本和哈希、模型/股票池版本、状态必需 |
