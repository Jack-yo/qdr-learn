import type { Horizon } from './endpoints'

export function getDemoOverview(horizon: Horizon) {
  const m = horizon === 'H1' ? 0.45 : horizon === 'H5' ? 1.55 : 1.0
  return {
    trading_date: '2026-11-24',
    bundle_id: 'v4_20261124_close_xnys',
    manifest_sha256: '9f84c2a1e04b7d66c8e21a5f092c17b842e901f3',
    status: 'PASS',
    layers: {
      l1: { status: 'PASS', regime: '温和上行', detail: '上涨 61.4% · 下跌风险 14.2%' },
      l2: { status: 'PASS', summary: '动量 / 质量占优', detail: 'MOM +1.42σ · RMW +0.86σ' },
      l3: { status: 'PASS', summary: '5 只合格候选', detail: '平均期望 +1.32% · 扣费后正期望' },
      l4: { status: 'PASS', summary: '仓位 42% / 80%', detail: '单票最大 12% · 行业最大 26%' },
    },
    ledger_curve: {
      labels: ['11-03', '11-05', '11-09', '11-11', '11-13', '11-17', '11-19', '11-20', '11-23', '11-24'],
      portfolio: [100.0, 100.6, 101.2, 100.9, 101.8, 102.5, 102.9, 103.4, 103.9, 104.3],
      benchmark: [100.0, 100.3, 100.7, 100.2, 100.8, 101.1, 101.4, 101.6, 101.9, 102.1],
    },
    allocation: [
      { name: '半导体', value: 21 },
      { name: '软件服务', value: 11.5 },
      { name: '医疗健康', value: 9.5 },
      { name: '可用现金', value: 58 },
    ],
    ablation: [
      { tier: 'A · 仅个股特征', oos_ic: 0.031, sharpe: 0.96, win_rate: 53.8, delta_ic: 0.0 },
      { tier: 'B · 个股 + L1 市场条件', oos_ic: 0.038, sharpe: 1.18, win_rate: 55.9, delta_ic: 0.007 },
      { tier: 'C · 个股 + L2 风格条件', oos_ic: 0.041, sharpe: 1.26, win_rate: 56.8, delta_ic: 0.010 },
      { tier: 'D · 四层完整条件 + 风控', oos_ic: 0.046, sharpe: 1.42, win_rate: 58.4, delta_ic: 0.015 },
    ],
    scorecard: [
      { date: '2026-11-20', count: 4, pred_ret: 1.18, real_ret: 1.35, hit_rate: 75.0, status: '已结算' },
      { date: '2026-11-19', count: 5, pred_ret: 0.94, real_ret: 0.82, hit_rate: 60.0, status: '已结算' },
      { date: '2026-11-18', count: 3, pred_ret: 0.72, real_ret: -0.24, hit_rate: 33.3, status: '已结算' },
    ],
    candidates: [
      { symbol: 'NVDA', sector: '半导体', status: 'ELIGIBLE', expected_return: +(1.84 * m).toFixed(2), up_probability: 66.2, weight: 12.0, entry_rule: 'T+1 开盘限滑点 15bps', sha256: 'c91a...7e42' },
      { symbol: 'AVGO', sector: '半导体', status: 'ELIGIBLE', expected_return: +(1.52 * m).toFixed(2), up_probability: 63.1, weight: 9.0, entry_rule: 'T+1 开盘原价', sha256: 'f401...9d0c' },
      { symbol: 'MSFT', sector: '软件服务', status: 'ELIGIBLE', expected_return: +(1.26 * m).toFixed(2), up_probability: 64.0, weight: 11.5, entry_rule: 'T+1 开盘原价', sha256: 'a82f...3b19' },
      { symbol: 'LLY', sector: '医疗健康', status: 'ELIGIBLE', expected_return: +(1.08 * m).toFixed(2), up_probability: 61.4, weight: 9.5, entry_rule: 'T+1 开盘原价', sha256: '73bd...21aa' },
      { symbol: 'COST', sector: '必选消费', status: 'ELIGIBLE', expected_return: +(0.89 * m).toFixed(2), up_probability: 59.8, weight: 8.0, entry_rule: 'T+1 开盘原价', sha256: '1e90...88cf' },
      { symbol: 'TSLA', sector: '汽车能源', status: 'WATCH', expected_return: +(0.42 * m).toFixed(2), up_probability: 53.5, weight: 0.0, entry_rule: '波动超单票预算', sha256: '55ab...00e1' },
      { symbol: 'INTC', sector: '半导体', status: 'WATCH', expected_return: +(-0.64 * m).toFixed(2), up_probability: 44.2, weight: 0.0, entry_rule: '负期望剔除', sha256: '81cc...09a1' },
    ],
  }
}

export function getDemoL1(horizon: Horizon) {
  const up = horizon === 'H1' ? 56.2 : horizon === 'H5' ? 64.8 : 61.4
  const down = horizon === 'H1' ? 11.5 : horizon === 'H5' ? 16.9 : 14.2
  return {
    regime: '温和上行 (Low-Vol Uptrend)',
    up_probability: up,
    downside_risk: down,
    expected_return: horizon === 'H1' ? 0.24 : horizon === 'H5' ? 1.32 : 0.78,
    brier_score: horizon === 'H1' ? 0.218 : horizon === 'H5' ? 0.197 : 0.204,
    history: {
      labels: ['11-11', '11-12', '11-13', '11-16', '11-17', '11-18', '11-19', '11-20', '11-23', '11-24'],
      up: [54, 56, 52, 55, 58, 59, 60, 58, 62, up],
      down: [19, 18, 22, 18, 16, 15, 14, 15, 13, down],
    },
    ret_dist: {
      bins: ['<-3%', '-3~-1.5%', '-1.5~0%', '0~1.5%', '1.5~3%', '>3%'],
      probs: [4.2, 10.0, 24.4, 34.8, 19.2, 7.4],
    },
    calibration: {
      bins: ['30%', '40%', '50%', '60%', '70%'],
      predicted: [30, 40, 50, 60, 70],
      observed: [31.5, 38.8, 51.2, 61.4, 68.2],
    },
    dimensions: [
      { system: '价格趋势', name: 'SPY/QQQ 均线斜率', score: 0.82, state: '偏强', source: 'Alpaca', freshness: '21:05 UTC' },
      { system: '波动结构', name: 'VIX / VIX3M 期限', score: 0.45, state: 'Contango', source: 'CBOE', freshness: '21:10 UTC' },
      { system: '市场广度', name: '50日均线以上占比', score: 0.54, state: '62% 健康', source: 'XNYS', freshness: '21:06 UTC' },
      { system: '信用利差', name: 'HYG / IEF 相对强度', score: 0.31, state: '稳定', source: 'Alpaca', freshness: '21:05 UTC' },
      { system: '宏观利率', name: '10Y 美债收益率斜率', score: -0.18, state: '中性', source: 'FRED', freshness: '20:30 UTC' },
      { system: '跨资产情绪', name: 'Put/Call 与拥挤度', score: -0.34, state: '轻度拥挤', source: 'Derived', freshness: '21:12 UTC' },
    ],
  }
}

export function getDemoL2(horizon: Horizon) {
  const s = horizon === 'H1' ? 0.75 : horizon === 'H5' ? 1.15 : 1.0
  return {
    factors: [
      { code: 'MOM', name: '动量 (Momentum)', z_score: +(1.42 * s).toFixed(2), persistence: '连续 6 日占优', oos_delta_ic: 0.018, lead_corr: 0.14, significant: true, proxy: 'MTUM / French UMD' },
      { code: 'RMW', name: '质量 (Quality)', z_score: +(0.86 * s).toFixed(2), persistence: '连续 4 日占优', oos_delta_ic: 0.011, lead_corr: 0.09, significant: true, proxy: 'QUAL / French RMW' },
      { code: 'VOL', name: '低波动 (Low Vol)', z_score: +(0.22 * s).toFixed(2), persistence: '震荡走平', oos_delta_ic: 0.002, lead_corr: 0.03, significant: false, proxy: 'USMV' },
      { code: 'SMB', name: '小盘 (Size)', z_score: +(-0.38 * s).toFixed(2), persistence: '弱势修复', oos_delta_ic: -0.004, lead_corr: -0.05, significant: false, proxy: 'IWM / French SMB' },
      { code: 'HML', name: '价值 (Value)', z_score: +(-0.64 * s).toFixed(2), persistence: '连续 3 日走弱', oos_delta_ic: 0.006, lead_corr: 0.04, significant: false, proxy: 'VLUE / French HML' },
    ],
    trend: {
      labels: ['11-17', '11-18', '11-19', '11-20', '11-23', '11-24'],
      MOM: [0.85, 0.96, 1.12, 1.18, 1.35, 1.42],
      RMW: [0.64, 0.70, 0.76, 0.92, 0.79, 0.86],
      HML: [-0.20, -0.35, -0.44, -0.52, -0.58, -0.64],
    },
    lead_lag: {
      labels: ['Lag-1', 'Lag-3', 'Lag-5', 'Lag-10'],
      MOM: [0.14, 0.11, 0.08, 0.03],
      RMW: [0.09, 0.08, 0.06, 0.04],
    },
  }
}

export function getDemoL3(horizon: Horizon) {
  const ov = getDemoOverview(horizon)
  return {
    active_strategy_id: 'STRAT-V4-BASE',
    candidates: ov.candidates,
    factor_diag: {
      ic: 0.046,
      icir: 1.38,
      turnover: 31.4,
      quantiles: [-0.42, -0.11, 0.14, 0.45, 0.89],
      rolling_ic_labels: ['W1', 'W2', 'W3', 'W4', 'W5', 'W6', 'W7', 'W8'],
      rolling_ic: [0.032, 0.041, 0.028, 0.055, 0.049, 0.038, 0.061, 0.046],
      redundancy: [
        { pair: 'mom20_vol_adj vs mom60', corr: 0.74, verdict: '高冗余' },
        { pair: 'mom20_vol_adj vs reversal5', corr: -0.28, verdict: '互补良好' },
        { pair: 'quality_roe vs idio_vol_20', corr: 0.22, verdict: '低相关' },
      ],
    },
    strategies: [
      { id: 'STRAT-V4-BASE', name: 'V4 条件线性多因子基线 (H3)', oos_sharpe: 1.42, max_dd: -6.8, win_rate: 58.4, status: 'FROZEN', nav: [100, 101.2, 102.5, 101.8, 103.9, 105.6, 107.1, 108.4], dd: [0, -0.4, -0.2, -1.8, -0.6, -0.3, -0.5, -0.2] },
      { id: 'STRAT-V4-REV', name: '短期反转 5 日纯量价实验', oos_sharpe: 0.94, max_dd: -9.5, win_rate: 53.1, status: 'VALIDATED', nav: [100, 100.8, 99.6, 101.4, 102.1, 101.2, 103.0, 103.8], dd: [0, -0.8, -2.6, -1.2, -0.9, -3.1, -1.4, -0.8] },
      { id: 'STRAT-V4-DRAFT', name: '高质量低波防御组合 (草稿)', oos_sharpe: 1.18, max_dd: -4.9, win_rate: 56.2, status: 'DRAFT', nav: [100, 100.4, 101.1, 101.5, 102.2, 102.9, 103.5, 104.2], dd: [0, -0.2, -0.1, -0.4, -0.3, -0.2, -0.1, 0] },
    ],
    signal_history: [
      { date: '2026-11-20', symbol: 'MSFT', horizon: 'H3', pred_ret: 1.12, real_ret: 1.34, status: '命中' },
      { date: '2026-11-20', symbol: 'LLY', horizon: 'H3', pred_ret: 0.96, real_ret: 1.20, status: '命中' },
      { date: '2026-11-19', symbol: 'COST', horizon: 'H3', pred_ret: 0.85, real_ret: -0.46, status: '未命中' },
      { date: '2026-11-19', symbol: 'AVGO', horizon: 'H3', pred_ret: 1.48, real_ret: 1.55, status: '命中' },
    ],
  }
}

export function getDemoL4() {
  return {
    positions: [
      { symbol: 'MSFT', sector: '软件服务', weight: 12.0, entry_date: '2026-11-21', entry_price: 428.4, last_price: 434.15, pnl_pct: 1.34, stop_dist_pct: -3.8, exit_rule: '11-26 收盘结算' },
      { symbol: 'LLY', sector: '医疗健康', weight: 10.0, entry_date: '2026-11-21', entry_price: 782.1, last_price: 791.5, pnl_pct: 1.2, stop_dist_pct: -4.0, exit_rule: '11-26 收盘结算' },
      { symbol: 'AVGO', sector: '半导体', weight: 11.0, entry_date: '2026-11-20', entry_price: 171.2, last_price: 173.85, pnl_pct: 1.55, stop_dist_pct: -4.5, exit_rule: '11-25 收盘结算' },
      { symbol: 'COST', sector: '必选消费', weight: 9.0, entry_date: '2026-11-20', entry_price: 912.0, last_price: 907.8, pnl_pct: -0.46, stop_dist_pct: -1.7, exit_rule: '11-25 收盘结算' },
    ],
    sector_exposure: [
      { sector: '半导体', current: 26.0, limit: 30.0 },
      { sector: '软件服务', current: 12.0, limit: 30.0 },
      { sector: '医疗健康', current: 10.0, limit: 30.0 },
      { sector: '必选消费', current: 9.0, limit: 30.0 },
    ],
    corr_matrix: {
      symbols: ['MSFT', 'LLY', 'AVGO', 'COST'],
      rows: [
        { symbol: 'MSFT', MSFT: 1.0, LLY: 0.24, AVGO: 0.62, COST: 0.31 },
        { symbol: 'LLY', MSFT: 0.24, LLY: 1.0, AVGO: 0.18, COST: 0.15 },
        { symbol: 'AVGO', MSFT: 0.62, LLY: 0.18, AVGO: 1.0, COST: 0.22 },
        { symbol: 'COST', MSFT: 0.31, LLY: 0.15, AVGO: 0.22, COST: 1.0 },
      ],
    },
    trades: [
      { date: '2026-11-21', symbol: 'MSFT', side: 'BUY (T+1 Open)', price: 428.4, cost_bps: 12, status: '已对账' },
      { date: '2026-11-21', symbol: 'LLY', side: 'BUY (T+1 Open)', price: 782.1, cost_bps: 14, status: '已对账' },
      { date: '2026-11-20', symbol: 'NVDA', side: 'SELL (T+3 Close)', price: 144.8, cost_bps: 11, status: '已结算 +2.4%' },
    ],
  }
}

export function getDemoDataCenter() {
  return {
    sources: [
      { id: 'alpaca', name: 'Alpaca US Equities Daily', latest_date: '2026-11-24', coverage_pct: 100, freshness: '新鲜', status: 'OK' },
      { id: 'french', name: 'Ken French Classic Factors', latest_date: '2026-11-24', coverage_pct: 100, freshness: '新鲜', status: 'OK' },
      { id: 'sec', name: 'SEC EDGAR PIT Filings', latest_date: '2026-11-23', coverage_pct: 97, freshness: '1 日延迟', status: 'WARN' },
      { id: 'yahoo', name: 'Yahoo Macro & VIX Snapshot', latest_date: '2026-11-24', coverage_pct: 100, freshness: '新鲜', status: 'OK' },
    ],
    universe: [
      { symbol: 'NVDA', sector: '半导体', adv20: '$42.8B', pit_since: '2017-01-03', tradable: true },
      { symbol: 'MSFT', sector: '软件服务', adv20: '$11.4B', pit_since: '2017-01-03', tradable: true },
      { symbol: 'AVGO', sector: '半导体', adv20: '$6.2B', pit_since: '2017-01-03', tradable: true },
      { symbol: 'LLY', sector: '医疗健康', adv20: '$3.9B', pit_since: '2017-01-03', tradable: true },
    ],
    actions: [
      { date: '2026-11-22', symbol: 'COST', type: 'DIVIDEND', ratio: '$1.16', evidence: 'Alpaca + SEC 对齐', status: 'VERIFIED' },
      { date: '2026-11-18', symbol: 'AVGO', type: 'SPLIT_CHECK', ratio: '无拆分', evidence: 'XNYS 快照一致', status: 'VERIFIED' },
    ],
    files: [
      { file: 'manifest.json', sha256: '9f84c2a1e04b7d66c8e21a5f092c17b842e901f3', pit_status: '通过', status: 'VERIFIED' },
      { file: 'factors.parquet', sha256: '3d20b71c99a1f104a8b1cc0171b244e18830fa12', pit_status: 'T日收盘冻结', status: 'VERIFIED' },
      { file: 'labels.parquet', sha256: 'e51200ab7c31144290aa1e09887c11220091de44', pit_status: '5日 Embargo', status: 'VERIFIED' },
      { file: 'market_style.parquet', sha256: '71bc4a908f127700cc9e028199331020c441209b', pit_status: '通过', status: 'VERIFIED' },
      { file: 'candidate_meta.parquet', sha256: 'b094e312df08441099fa12c0918273649a01bc77', pit_status: '证券池一致', status: 'VERIFIED' },
    ],
  }
}
