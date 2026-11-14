/* QDR L1 research cockpit. No invented signal, quote, score or market observation.
 * This module supersedes ONLY V4.pages.market; L2/L3/L4 are unchanged.
 * Backend contract: docs/L1_MARKET_UI_CONTRACT.md, schema qdr.l1.market.v1.
 */
(() => {
  'use strict';
  const V = window.V4;
  if (!V) throw Error('QDR L1 must load after the V4 UI core');
  const {pages, state, e, n, pct, date, settle, show} = V;
  const S = { horizon: state.marketHorizon || 3, dimension: 'all', selectedDomain: null, view: 'distribution', expanded: false, replayDate: '' };
  const DOMAINS = [
    ['price', '价格与趋势', '走势、速度、隔夜与盘中结构', '价格'],
    ['breadth', '真实市场广度', '上涨参与率、创新高低、广度背离', '内部结构'],
    ['volatility', '波动率结构', '实现波动、隐含波动与期限结构', '风险'],
    ['options_pricing', '期权风险定价', '偏斜、方差溢价、保护成本', '衍生品'],
    ['options_positioning', '期权仓位与对冲', '到期集中、Gamma 情景与仓位', '衍生品'],
    ['microstructure', '市场微观结构', '买卖价差、订单流、价格冲击', '流动性'],
    ['correlation', '相关性与离散度', '行业相关、集中度、系统性同步', '内部结构'],
    ['cross_asset', '跨资产风险传导', '利率、信用、美元与资产联动', '风险'],
    ['positioning', '资金流与持仓拥挤', '期货持仓、ETF 资金流及杠杆代理', '流动性'],
    ['events', '宏观与事件冲击', '重大数据、会议、到期与再平衡', '事件'],
    ['funding', '融资与金融条件', '融资利差、信用条件与压力', '流动性'],
    ['path', '路径与极端事件', '跳跃、下行半方差、最大不利波动', '风险'],
  ];
  const FILTERS = [['all', '全部维度'], ['内部结构', '内部结构'], ['风险', '风险'], ['衍生品', '衍生品'], ['流动性', '流动性'], ['事件', '事件'], ['价格', '价格']];
  const isNum = v => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v));
  const signed = (v, decimals=2) => isNum(v) ? `${Number(v) > 0 ? '+' : ''}${n(v,decimals)}` : '—';
  const DIGEST = /^[a-f0-9]{64}$/;
  const asText = v => v === undefined || v === null || v === '' ? '—' : e(v);
  const num = (v, unit='', digits=2) => isNum(v) ? n(v,digits)+e(unit) : '—';
  const label = (status) => ({'OBSERVED':'已观测','PARTIAL':'部分覆盖','MISSING':'待接入','BLOCKED':'不可用','STALE':'已过期'}[status] || '待接入');
  const reason = v => ({HISTORICAL_PIT_UNIVERSE_NOT_VERIFIED:'历史时点股票池未核验',OPTION_PRICING_HISTORY_NOT_CONNECTED:'期权定价历史未接入',OPTION_POSITION_HISTORY_NOT_CONNECTED:'期权持仓历史未接入',ORDER_BOOK_HISTORY_NOT_CONNECTED:'订单簿历史未接入',POSITION_FLOW_HISTORY_NOT_CONNECTED:'资金与持仓历史未接入',POINT_IN_TIME_EVENT_HISTORY_NOT_CONNECTED:'宏观事件时点历史未接入',POINT_IN_TIME_FUNDING_HISTORY_NOT_CONNECTED:'融资数据时点历史未接入',EXTERNAL_SERIES_NOT_CONNECTED:'外部数据序列未接入',CORPORATE_ACTION_CONSISTENT_HISTORY_NOT_VERIFIED:'公司行为一致的历史价格未核验',INSUFFICIENT_OR_GAPPED_ETF_HISTORY:'ETF 连续行情不足或缺失'}[v]||v||'');
  const stamp = v => v && typeof v === 'string' ? e(v.replace('T',' ').slice(0,19)) : '—';
  const small = (key, value, hint) => `<div class="l1-mini"><span>${e(key)}</span><strong>${value}</strong><small>${e(hint)}</small></div>`;
  const empty = (name, detail, kind='no-data') => `<div class="l1-empty" data-empty-kind="${e(kind)}"><div class="l1-empty-icon">◇</div><strong>${e(name)}</strong><p>${e(detail)}</p></div>`;
  const header = (eyebrow, title, aside='') => `<div class="l1-section-heading"><div><div class="l1-eyebrow">${e(eyebrow)}</div><h2>${e(title)}</h2></div>${aside}</div>`;
  const panel = (cls, body) => `<section class="l1-panel ${cls}">${body}</section>`;
  const validProbability = v => isNum(v) && Number(v)>=0 && Number(v)<=1;
  const FEATURE_NAMES = {
    market_return_1:'SPY 1日价格涨跌',market_return_5:'SPY 5日价格涨跌',market_return_20:'SPY 20日价格涨跌',
    market_overnight_return:'SPY 隔夜价格涨跌',market_intraday_return:'SPY 当日开盘至收盘涨跌',
    market_close_location:'SPY 收盘价在当日区间的位置',market_return_acceleration:'SPY 价格动量变化',
    market_vol_5:'SPY 5日年化历史波动',market_vol_20:'SPY 20日年化历史波动',
    market_vol_ratio:'SPY 5日 / 20日波动比',market_downside_rv20:'SPY 20日年化下行波动',
    market_vol_change_5:'SPY 20日波动的5日变化',market_gap_abs_5:'SPY 5日平均绝对隔夜缺口',
    market_range_5:'SPY 5日平均日内振幅',sector_dispersion_5:'行业 ETF 5日收益离散度',
    sector_corr_20:'行业 ETF 20日平均相关系数',
    equal_weight_relative_return_5:'RSP / SPY 5日相对表现',
    credit_proxy_relative_return_5:'HYG / LQD 5日相对表现',
    small_cap_relative_return_5:'IWM / SPY 5日相对表现'
  };
  const featureValue = x => !isNum(x?.value)?'—':x.unit==='fraction'?pct(x.value):num(x.value,'',4);
  const forecastStatus = x => x?.status === 'FROZEN_FORWARD_RESEARCH_ONLY' || x?.status === 'MODEL_OOS_ADMITTED';

  function extractForecast(response, fresh, horizon) {
    if (!response?.ok || response.data?.schema !== 'qdr.l1.market.v1') return null;
    const data = response.data;
    if (!forecastStatus(data) || data.asof_session !== fresh?.asof_session ||
        !DIGEST.test(data.source_snapshot_sha256 || '') || !data.model_version ||
        !data.knowledge_cutoff_utc || !data.frozen_at_utc ||
        new Date(data.frozen_at_utc) < new Date(data.knowledge_cutoff_utc) ||
        new Date(data.knowledge_cutoff_utc) >= new Date(data.entry_at_utc || 0)) return null;
    const f = data.forecast;
    if (!f || Number(f.horizon) !== horizon || !validProbability(f.p_up) || !validProbability(f.p_downside) ||
        !isNum(f.expected_return) || !Array.isArray(f.quantiles) || f.quantiles.length !== 5 ||
        f.quantiles.some(q => !isNum(q)) ||
        f.quantiles.some((q,i) => i > 0 && Number(q)<Number(f.quantiles[i-1]))) return null;
    if (f.first_passage !== undefined && f.first_passage !== null) {
      const p = f.first_passage;
      if (!['up_first','down_first','neither'].every(k => validProbability(p[k])) ||
          Math.abs(Number(p.up_first)+Number(p.down_first)+Number(p.neither)-1)>0.001) return null;
    }
    return { data, f };
  }
  function indicatorCards(fresh, source, status) {
    const observed = fresh?.modules?.market_observation;
    const count = observed?.covered_symbols;
    const total = observed?.required_symbols;
    const quoteDay = source?.dataset?.asof_date_et;
    const quotes = Array.isArray(source?.prices) ? source.prices : [];
    const getPrice = sym => quotes.find(q=>q.symbol===sym && String(q.date).slice(0,10)===quoteDay && q.basis==='raw');
    const spy = getPrice('SPY');
    const iwm = getPrice('IWM');
    const same = quoteDay && fresh?.asof_session===quoteDay;
    const quote = q => same && isNum(q?.close) ? '$'+n(q.close,2) : '—';
    return `<div class="l1-topstats">
      ${small('观察交易日', asText(fresh?.asof_session), '美东交易所日历')}
      ${small('SPY · 现价观察', quote(spy), '仅实际日线收盘价')}
      ${small('IWM · 现价观察', quote(iwm), '仅实际日线收盘价')}
      ${small('源数据覆盖', isNum(count)&&isNum(total)?`${n(count,0)} / ${n(total,0)}`:'—', '已核验 ETF 观察集合，不代表全市场广度')}
    </div><div class="l1-data-note"><span class="l1-dot ${status==='CURRENT'?'ok':'warn'}"></span>
      <span>${same ? '已匹配最新完成交易日' : '最新观察日期未匹配'} · 数据状态 ${e(status||'待检查')} · 观察价不构成未来预测</span>
      <a href="/data">检查数据中心 ↗</a></div>`;
  }
  function distribution(f) {
    if (!f) return `<div class="l1-chart-placeholder"><div class="l1-chart-grid" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>${empty('预测分布尚未建立', '完成 Codex 数据接入、模型验证及当日预测冻结后，此处展示 H1 / H3 / H5 收益分位分布。')}</div>`;
    const quant = f.quantiles.map(Number);
    const spread = Math.max(0.0001, quant[4]-quant[0]);
    const max = Math.max(Math.abs(quant[0]),Math.abs(quant[4]),0.001)*1.18;
    const x = v => 25+650*(Number(v)+max)/(2*max);
    const zero=x(0), y=119;
    return `<div class="l1-distribution-chart"><svg viewBox="0 0 700 230" role="img" aria-label="真实已冻结预测收益分位区间"><line x1="${zero}" x2="${zero}" y1="20" y2="200" stroke="#46647d" stroke-dasharray="3 6"/>
    <line x1="25" x2="675" y1="${y}" y2="${y}" stroke="#42627b"/>
    <rect x="${x(quant[0])}" y="104" width="${Math.max(1,x(quant[4])-x(quant[0]))}" height="30" rx="8" fill="#39536c"/>
    <rect x="${x(quant[1])}" y="94" width="${Math.max(1,x(quant[3])-x(quant[1]))}" height="50" rx="9" fill="#1d9caa" fill-opacity=".62"/>
    <line x1="${x(quant[2])}" x2="${x(quant[2])}" y1="79" y2="160" stroke="#7bf0df" stroke-width="3"/>
    <circle cx="${x(f.expected_return)}" cy="119" r="8" fill="#b9ddff" stroke="#0b1728" stroke-width="4"/>
    <text x="25" y="194" fill="#98a9c0" font-size="12">${n(quant[0]*100,2)}%</text>
    <text x="${zero}" y="34" fill="#859eb9" text-anchor="middle" font-size="12">0%</text>
    <text x="675" y="194" fill="#98a9c0" text-anchor="end" font-size="12">${n(quant[4]*100,2)}%</text></svg>
    <div class="l1-chart-legend"><span><i class="l1-key med"></i>10–90% 分位区间</span><span><i class="l1-key teal"></i>25–75% 分位区间</span><span><i class="l1-key bright"></i>中位数</span><span><i class="l1-key dot"></i>预期收益</span></div>
    <div class="l1-chart-footnote">展示预测分布的分位数，不是未来真实价格路径；区间覆盖率仍需样本外评价。</div></div>`;
  }
  function currentForecast(rec, horizon) {
    const f=rec?.f || null;
    const status = rec?.data?.status==='MODEL_OOS_ADMITTED'?'样本外模型已验收':'前向研究 · 非交易';
    return panel('l1-primary', `${header('01 / MARKET OUTLOOK', '未来市场展望', f?`<span class="l1-valid">${e(status)}</span>`:'<span class="l1-caution">暂无合格预测</span>')}
      <div class="l1-period">${[1,3,5].map(h=>`<button data-l1-horizon="${h}" type="button" aria-pressed="${h===horizon}" class="${h===horizon?'active':''}">H${h}<small>${h} 个交易日</small></button>`).join('')}</div>
      <div class="l1-prediction-metrics">
        ${small('条件预期收益',f?signed(Number(f.expected_return)*100)+'%':'—','T+1 开盘至 T+H 收盘')}
        ${small('上涨概率',f?pct(f.p_up):'—','样本外校准需另行确认')}
        ${small('预测下行尾部',f&&validProbability(f.p_downside)?pct(f.p_downside):'—','事先定义的风险事件')}
      </div>
      ${distribution(f)}
      <div class="l1-subline">${f?`模型 ${asText(rec.data.model_version)} · 数据 ${asText(rec.data.asof_session)} · 冻结 ${stamp(rec.data.frozen_at_utc)}`:'只接受包含时点、来源哈希、模型版本及一致收益分位的 L1 冻结预测；不将旧历史回放拼接为当前预测。'}</div>`);
  }
  function retrospectiveWindows(data) {
    if (data?.status!=='CURRENT_VINTAGE_RETROSPECTIVE_OBSERVATION') return '';
    const windows=data.return_windows||{};
    return panel('l1-windows', `${header('PRICE HISTORY / RETROSPECTIVE', 'SPY 历史价格变化', '<span class="l1-kicker">原价回顾 · 非预测</span>')}
      <div class="l1-window-grid">${[1,3,5,10,20,60].map(n=>small(n+' 个交易日',featureValue(windows[String(n)]),'原价变化，不含分红')).join('')}</div>
      <div class="l1-subline">截至 ${asText(data.asof_session)}；缺失交易日时对应窗口不计算。拆股和分红一致性尚未验收。</div>`);
  }
  function firstPassage(rec) {
    const p=rec?.f?.first_passage;
    const eligible=p && ['up_first','down_first','neither'].every(k=>validProbability(p[k]));
    const rows=[['先向上触及','up_first','gain'],['先向下触及','down_first','loss'],['期限内均未触及','neither','neutral']];
    return panel('l1-event', `${header('02 / PRICE PATH', '风险与路径事件', '<span class="l1-kicker">FIRST PASSAGE</span>')}
     <div class="l1-event-caption">对比未来价格先触及上涨或下跌边界的事件，而不是事后定义“底部”。</div>
     ${eligible ? `<div class="l1-event-bars">${rows.map(([label,key,cls])=>`<div class="l1-event-item"><div><span>${label}</span><strong>${pct(p[key])}</strong></div><div class="l1-track"><i class="${cls}" style="width:${Number(p[key])*100}%"></i></div></div>`).join('')}</div><div class="l1-tiny">界限：${asText(p.up_threshold)} / ${asText(p.down_threshold)} · 若日线无法确定先后顺序应标记未知</div>`
      :empty('路径事件尚无合格预测','等数据与首次触及标签接入后，展示先反弹 / 先下跌 / 均未触及三类互斥结果。')}
      <div class="l1-caveat"><strong>需要验证的风险：</strong>压力衰减并不等于市场见底；模型必须同时报告误报、提前量和尾部风险。</div>`);
  }
  function driversAndSignals(data) {
    const records=Array.isArray(data?.drivers)?data.drivers.filter(x=>x&&x.label&&isNum(x.value)).slice(0,7):[];
    return panel('l1-driver', `${header('03 / CONDITION CHANGE', '当前市场观察与变化', '<span class="l1-kicker">FEATURE EVIDENCE</span>')}
      <div class="l1-subtitle">观察到的变化 ≠ 已验证的预测驱动。贡献必须来自实际模型与样本外增量。</div>
      ${records.length ? `<div class="l1-driver-rows">${records.map((x)=>`<div class="l1-driver-row"><div class="l1-driver-head"><span>${e(FEATURE_NAMES[x.label]||x.label)}</span><strong>${featureValue(x)}</strong></div><div class="l1-driver-meta"><span>${asText(x.status||'OBSERVED')}</span><span>${x.delta!==null&&isNum(x.delta)?'日变化 '+signed(x.delta):'变化待核验'}</span><span>${x.oos_increment===null||!isNum(x.oos_increment)?'增量未验证':'样本外增量 '+signed(x.oos_increment,4)}</span></div></div>`).join('')}</div>`
        :empty('尚无经过审计的特征变化', '后续接入 12 维日频观测。若因子未经过增量验证，只展示变化，不标记为有效领先信号。')}
      <div class="l1-driver-footer">支持未来展开历史条件检索、相似环境、模型贡献与条件情景；本阶段不伪造解释性数值。</div>`);
  }
  function domainsGrid(data) {
    const raw=Array.isArray(data?.domains)?data.domains:[];
    const lookup=new Map(raw.filter(x=>x&&x.id).map(x=>[x.id,x]));
    const displayed=DOMAINS.filter(([id,, ,group])=>S.dimension==='all'||S.dimension===group);
    const observed=DOMAINS.filter(([id])=>lookup.get(id)?.status==='OBSERVED').length;
    const partial=DOMAINS.filter(([id])=>lookup.get(id)?.status==='PARTIAL').length;
    return panel('l1-monitor', `${header('04 / MARKET OBSERVATORY', '12 维市场自动观测', `<span class="l1-kicker">已观测 ${observed} / 12 · 部分覆盖 ${partial}</span>`)}
      <div class="l1-subtitle">每个维度独立校验数据来源、发布时间及股票池覆盖率；未接入维度不计算为零。</div>
      <div class="l1-filters" role="group" aria-label="观测维度筛选">${FILTERS.map(([id,name])=>`<button type="button" data-l1-domain="${e(id)}" class="${S.dimension===id?'active':''}" aria-pressed="${S.dimension===id}">${e(name)}</button>`).join('')}</div>
      <div class="l1-domain-grid">${displayed.map(([id,name,desc,group],i)=>{
        const item=lookup.get(id), status=item?.status||'MISSING';
        const val=['OBSERVED','PARTIAL'].includes(status)&&isNum(item.value)?(item.unit==='fraction'?pct(item.value):num(item.value,item.unit||'',item.precision??2)):'—';
        return `<button type="button" class="l1-domain" data-l1-open-domain="${e(id)}" aria-pressed="${S.selectedDomain===id}"><div class="l1-domain-h"><span class="l1-domain-icon">${String(DOMAINS.findIndex(x=>x[0]===id)+1).padStart(2,'0')}</span><span class="l1-domain-state ${e(status.toLowerCase())}">${label(status)}</span></div><strong>${e(name)}</strong><p>${e(desc)}</p><div class="l1-domain-number">${val}</div><small>${status==='OBSERVED'?asText(item.label||'已到达的数据观察值') : status==='PARTIAL'?'部分覆盖：仅显示已取得的实际数值': '数据或计算尚未完成'}<span class="l1-domain-coverage">${item?.coverage?e(item.coverage.available+' / '+item.coverage.registered+' 项特征'):''}</span></small></button>`;
      }).join('')}</div>
      ${S.selectedDomain ? `<div class="l1-domain-details"><h3>${e((DOMAINS.find(x=>x[0]===S.selectedDomain)||[])[1]||'指标明细')}</h3><p>数据、来源及可得时点，研究观察不代表领先预测有效。</p><div class="l1-domain-details-list">${(Array.isArray(data?.features)?data.features:[]).filter(x=>x.domain===S.selectedDomain).map(x=>`<div class="l1-research-row"><span>${e(FEATURE_NAMES[x.id]||x.id)} <small>${asText(x.status)} · ${x.status==='OBSERVED'?asText(x.source):e(reason(x.reason))}</small></span><strong>${featureValue(x)} <small>${asText(x.available_at)}</small></strong></div>`).join('')||'<p class="l1-no-features">该维度尚未取得可核验的指标明细</p>'}</div></div>` : ''}`);
  }
  function validation(oldStudy, rec) {
    const rows=Array.isArray(oldStudy?.summary?.direction)?oldStudy.summary.direction:[];
    const metric=rows.find(x=>isNum(x.brier)&&isNum(x.naive_brier));
    return panel('l1-validation', `${header('05 / MODEL EVIDENCE', '预测验证与历史对照', '<span class="l1-kicker">RESEARCH / OOS</span>')}
      <div class="l1-valid-grid">
      ${small('当前 L1 冻结预测',rec?asText(rec.data.status):'未取得','必须是当日的前向模型归档')}
      ${small('旧实验 · 模型 Brier',metric?num(metric.brier,'',4):'—','历史回顾研究，非当前模型')}
      ${small('旧实验 · 常数基准 Brier',metric?num(metric.naive_brier,'',4):'—','历史回顾研究，非当前模型')}
      </div><div class="l1-qualify">${metric?`历史回溯 Brier 差（模型−基准）：${signed(Number(metric.brier)-Number(metric.naive_brier),4)}；负值较优。该实验不得用于证明最新 L1 预测已经验收。`:'当前没有可核验的历史验证结果。'} <a href="/market">查看原历史研究入口 ↗</a></div>
      <details class="l1-method"><summary>展开数据资格与验证口径</summary><p>交易窗口：T 日收盘后形成信号，T+1 日开盘至 T+H 日收盘。历史实验与连续冻结预测严格分开；所有分位数、事件概率必须在同一预测时点生成。</p><p>验收目标：概率校准、分布预测损失、波动预测误差、首触事件误报与提前量、基准对照。H3/H5 重叠标签必须使用适当的滚动净化、区块自助法和独立时间外测试。</p><p>数据缺少 PIT 身份、公司行为、当时已知发布时间、覆盖率证据时，仅能作观察或探索性研究。</p></details>`);
  }
  function researchTools(anomalyData, validationData, replayData) {
    const alerts=Array.isArray(anomalyData?.anomalies)?anomalyData.anomalies:[];
    const metrics=Array.isArray(validationData?.metrics)?validationData.metrics:[];
    const yearly=Array.isArray(validationData?.yearly_metrics)?validationData.yearly_metrics:[];
    const ablation=Array.isArray(validationData?.ablation_metrics)?validationData.ablation_metrics:[];
    const replay=replayData?.prediction;
    const alertsHTML=alerts.length?alerts.slice(-8).reverse().map(x=>`<div class="l1-research-row"><span>${asText(x.date)} · ${asText(x.feature)}</span><strong>${isNum(x.z_score)?signed(x.z_score)+'σ':'—'}</strong></div>`).join(''):
      empty('无已归档的异常发现','缺少历史特征或过去窗口的异常扫描证据。');
    const metricsHTML=metrics.length?`<div class="l1-metrics-table"><div class="l1-metrics-header">期限　波动 MSE / 基准 / EWMA　分位损失 / 基准　事件 Brier / 基准</div>${metrics.map(x=>`<div class="l1-research-row"><span>H${e(x.horizon)} · ${num(x.e01_rv_mse,'',4)} / ${num(x.e01_baseline_mse,'',4)} / ${num(x.e01_ewma_mse,'',4)} · ${num(x.e03_pinball_loss,'',4)} / ${num(x.e03_baseline_pinball_loss,'',4)}</span><strong>${num(x.e02_brier,'',4)} / ${num(x.e02_baseline_brier,'',4)}</strong></div><div class="l1-research-row"><span>样本 ${num(x.samples,'',0)} · 10–90% 区间覆盖 ${isNum(x.e03_q10_q90_coverage)?pct(x.e03_q10_q90_coverage):'—'} · 正确事件平均触及 ${num(x.e02_correct_event_mean_lead_sessions,' 日',1)}</span><strong>上涨 Brier ${num(x.e03_up_brier_unverified,'',4)} / ${num(x.e03_up_baseline_brier,'',4)} · 未校准</strong></div>`).join('')}</div>`:
      empty('暂无新版 L1 样本外研究指标','必须先运行 E01 / E02 / E03 的完整时间外实验，不能借旧实验冒充。');
    return panel('l1-research',`${header('06 / RESEARCH WORKBENCH', '历史验证与回放', '<span class="l1-kicker">RESEARCH-ONLY</span>')}
      <div class="l1-research-columns"><div><h3>市场异常扫描</h3>${alertsHTML}</div><div><h3>模型与基准对照</h3>${metricsHTML}${yearly.length?`<details class="l1-method"><summary>按年份查看样本外结果</summary>${yearly.map(x=>`<div class="l1-research-row"><span>${e(x.year)} · H${e(x.horizon)} · 样本 ${num(x.samples,'',0)}</span><strong>分位损失 ${num(x.e03_pinball_loss,'',4)} / 基准 ${num(x.e03_baseline_pinball_loss,'',4)}</strong></div>`).join('')}</details>`:''}${ablation.length?`<details class="l1-method"><summary>特征组配对消融（负值表示损失降低）</summary>${ablation.map(x=>`<div class="l1-research-row"><span>H${e(x.horizon)} · 配对样本 ${num(x.samples,'',0)}</span><strong>波动 MSE 差 ${signed(x.e01_extended_minus_base_mse,5)} · 分位损失差 ${signed(x.e03_extended_minus_base_pinball,5)}</strong></div>`).join('')}</details>`:''}</div></div>
      <div class="l1-replay"><label for="l1-replay-date">回放历史研究日</label><input type="date" id="l1-replay-date" value="${e(S.replayDate)}"><button type="button" data-l1-replay>查看当时研究</button>
        <span>${replay?'研究预测 '+num(replay.expected_return*100,'%',2)+' · 后续实际 '+num(replay.actual_return*100,'%',2)+' · 非真实冻结预测':replayData?.status==='NO_OOS_PREDICTION'?'该日期无样本外实验记录':replayData?.status==='INSUFFICIENT_OUTCOME_DATA'?'记录缺少有效结果，无法回放':replayData?.status==='BLOCKED'?'回放不可用：'+asText(replayData.code):'选择日期后显示真实研究记录'}</span></div>
      <p class="l1-research-warning">历史回溯 ≠ 当时已冻结的前向预测。研究指标不自动授予模型使用资格，误报、校准和概率增量必须使用独立样本外评价。</p>`);
  }
  pages.market=async()=>{
    const horizon=Number(state.marketHorizon||S.horizon||3);
    S.horizon=[1,3,5].includes(horizon)?horizon:3;
    const [forecast,freshRaw,statusRaw,oldRaw,anomalyRaw,validationRaw,replayRaw] = await Promise.all([
      settle('/api/v1/l1/market/overview?horizon='+S.horizon),
      settle('/api/v1/v4/freshness'), settle('/api/status'),
      settle('/api/v1/market/research?horizon='+S.horizon),
      settle('/api/v1/l1/anomalies'),settle('/api/v1/l1/validation'),
      S.replayDate?settle('/api/v1/l1/replay?asof='+encodeURIComponent(S.replayDate)+'&horizon='+S.horizon):Promise.resolve(null)
    ]);
    const fresh=freshRaw.ok?freshRaw.data:null, system=statusRaw.ok?statusRaw.data:null;
    const typed=forecast.ok&&forecast.data?.schema==='qdr.l1.market.v1'?forecast.data:null;
    const rec=extractForecast(forecast,fresh,S.horizon);
    const old=oldRaw.ok?oldRaw.data:null;
    const observationStatus=fresh?.modules?.market_observation?.freshness_status || 'BLOCKED';
    const retrospective=typed?.status==='CURRENT_VINTAGE_RETROSPECTIVE_OBSERVATION';
    const stale=typed?.asof_session&&fresh?.asof_session&&typed.asof_session!==fresh.asof_session;
    const html=`<div class="l1-cockpit">
      <div class="l1-head"><div><div class="l1-breadcrumb">L1 / MARKET FORECAST <span>· 01</span></div><h1>市场未来展望 <span class="l1-beta">RESEARCH</span></h1><p>从市场内部变化推断未来收益与风险分布；对每个预测提供真实证据，不把过去行情包装成未来信号。</p></div>
      <div class="l1-head-actions"><span class="l1-access ${rec?'good':''}"><i></i>${rec?'已读取冻结预测':'模型 / 数据接入待完成'}</span><button class="l1-refresh" type="button" data-l1-refresh>↻ 重新核查</button></div></div>
      ${indicatorCards(fresh,system,observationStatus)}
      ${retrospective?`<div class="l1-data-note"><span class="l1-dot warn"></span><span>当前版本行情回顾观察 · 交易日 ${asText(typed.asof_session)} · 数据获取时间 UTC ${stamp(typed.source_time?.available_at)} · 多日原价指标未完成拆股分红一致性核验，不代表含分红总收益或当时冻结预测</span></div>`:''}
      ${stale?`<div class="l1-data-note"><span class="l1-dot warn"></span><span>观察日期 ${asText(typed.asof_session)} 与最新完成交易日 ${asText(fresh.asof_session)} 不一致，属于过期数据。</span></div>`:''}
      ${retrospectiveWindows(typed)}
      <div class="l1-top-grid">${currentForecast(rec,S.horizon)}${firstPassage(rec)}</div>
      ${driversAndSignals(typed)}${domainsGrid(typed)}${validation(old,rec)}${researchTools(anomalyRaw?.ok?anomalyRaw.data:null, validationRaw?.ok?validationRaw.data:null, replayRaw?.ok?replayRaw.data:replayRaw?{status:'BLOCKED',code:replayRaw.error?.message}:null)}
      <div class="l1-bottom-note"><span>QDR · MARKET RESEARCH · L1</span><span>观察 / 回溯 / 前向预测分级 · 真实订单关闭</span></div></div>`;
    return {title:'L1 市场未来展望',html,mount(){
      document.querySelectorAll('[data-l1-horizon]').forEach(btn=>btn.addEventListener('click',()=>{
        const h=Number(btn.dataset.l1Horizon);
        if (![1,3,5].includes(h)) return;
        state.marketHorizon=h;S.horizon=h;show('market');
      }));
      document.querySelectorAll('[data-l1-domain]').forEach(btn=>btn.addEventListener('click',()=>{
        S.dimension=btn.dataset.l1Domain;show('market');
      }));
      document.querySelectorAll('[data-l1-open-domain]').forEach(btn=>btn.addEventListener('click',()=>{
        const d=btn.dataset.l1OpenDomain;
        S.selectedDomain=S.selectedDomain===d?null:d;show('market');
      }));
      document.querySelector('[data-l1-refresh]')?.addEventListener('click',()=>show('market'));
      document.querySelector('[data-l1-replay]')?.addEventListener('click',()=>{
        S.replayDate=document.querySelector('#l1-replay-date')?.value||'';
        if (S.replayDate) show('market');
      });
    }};
  };
})();
