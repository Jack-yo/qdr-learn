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
  const stamp = v => v && typeof v === 'string' ? e(v.replace('T',' ').slice(0,19)) : '—';
  const small = (key, value, hint) => `<div class="l1-mini"><span>${e(key)}</span><strong>${value}</strong><small>${e(hint)}</small></div>`;
  const empty = (name, detail, kind='no-data') => `<div class="l1-empty" data-empty-kind="${e(kind)}"><div class="l1-empty-icon">◇</div><strong>${e(name)}</strong><p>${e(detail)}</p></div>`;
  const header = (eyebrow, title, aside='') => `<div class="l1-section-heading"><div><div class="l1-eyebrow">${e(eyebrow)}</div><h2>${e(title)}</h2></div>${aside}</div>`;
  const panel = (cls, body) => `<section class="l1-panel ${cls}">${body}</section>`;
  const validProbability = v => isNum(v) && Number(v)>=0 && Number(v)<=1;
  const forecastStatus = x => {
    if (x?.status === 'FROZEN_FORWARD_RESEARCH_ONLY')
      return x.research_only === true && x.model_admitted === false && x.real_orders_enabled === false;
    if (x?.status === 'MODEL_OOS_ADMITTED')
      return x.model_admitted === true && x.historical_pit_verified === true &&
             x.source_independently_attested === true && x.real_orders_enabled === false;
    return false;
  };

  function extractForecast(response, fresh, horizon) {
    if (!response?.ok || response.data?.schema !== 'qdr.l1.market.v1') return null;
    const data = response.data;
    const cutoff = Date.parse(data.knowledge_cutoff_utc || '');
    const frozen = Date.parse(data.frozen_at_utc || '');
    const entry = Date.parse(data.entry_at_utc || '');
    if (!forecastStatus(data) || data.asof_session !== fresh?.asof_session ||
        !DIGEST.test(data.source_snapshot_sha256 || '') || !data.model_version ||
        !Number.isFinite(cutoff) || !Number.isFinite(frozen) || !Number.isFinite(entry) ||
        frozen < cutoff || cutoff >= entry) return null;
    const f = data.forecast;
    if (!f || Number(f.horizon) !== horizon || !validProbability(f.p_up) ||
        (f.p_downside !== null && f.p_downside !== undefined && !validProbability(f.p_downside)) ||
        !isNum(f.expected_return) || !Array.isArray(f.quantiles) || f.quantiles.length !== 5 ||
        f.quantiles.some(q => !isNum(q)) ||
        f.quantiles.some((q,i) => i > 0 && Number(q)<Number(f.quantiles[i-1]))) return null;
    if (f.first_passage !== undefined && f.first_passage !== null) {
      const p = f.first_passage;
      if (!['up_first','down_first','neither'].every(k => validProbability(p[k])) ||
          Math.abs(Number(p.up_first)+Number(p.down_first)+Number(p.neither)-1)>0.001 ||
          !isNum(p.up_threshold) || Number(p.up_threshold)<=0 ||
          !isNum(p.down_threshold) || Number(p.down_threshold)>=0) return null;
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
    const max = Math.max(Math.abs(quant[0]),Math.abs(quant[4]),Math.abs(Number(f.expected_return)),0.001)*1.18;
    const x = v => 25+650*(Number(v)+max)/(2*max);
    const zero=x(0), y=119;
    return `<div class="l1-distribution-chart"><svg viewBox="0 0 700 230" role="img" aria-label="真实已冻结预测收益分位区间"><line x1="${zero}" x2="${zero}" y1="20" y2="200" stroke="#9db0c4" stroke-dasharray="3 6"/>
    <line x1="25" x2="675" y1="${y}" y2="${y}" stroke="#9db0c4"/>
    <rect x="${x(quant[0])}" y="104" width="${Math.max(1,x(quant[4])-x(quant[0]))}" height="30" rx="8" fill="#c4d4e3"/>
    <rect x="${x(quant[1])}" y="94" width="${Math.max(1,x(quant[3])-x(quant[1]))}" height="50" rx="9" fill="#7dbfb4" fill-opacity=".62"/>
    <line x1="${x(quant[2])}" x2="${x(quant[2])}" y1="79" y2="160" stroke="#087d6e" stroke-width="3"/>
    <circle cx="${x(f.expected_return)}" cy="119" r="8" fill="#2b5b9d" stroke="#ffffff" stroke-width="4"/>
    <text x="25" y="194" fill="#596e84" font-size="12">${n(quant[0]*100,2)}%</text>
    <text x="${zero}" y="34" fill="#596e84" text-anchor="middle" font-size="12">0%</text>
    <text x="675" y="194" fill="#596e84" text-anchor="end" font-size="12">${n(quant[4]*100,2)}%</text></svg>
    <div class="l1-chart-legend"><span><i class="l1-key med"></i>10–90% 分位区间</span><span><i class="l1-key teal"></i>25–75% 分位区间</span><span><i class="l1-key bright"></i>中位数</span><span><i class="l1-key dot"></i>预期收益</span></div>
    <div class="l1-chart-footnote">预测分布区间 · 覆盖率见验证。</div></div>`;
  }
  function currentForecast(rec, horizon) {
    const f=rec?.f || null;
    const status = rec?.data?.status==='MODEL_OOS_ADMITTED'?'样本外模型已验收':'前向研究';
    return panel('l1-primary', `${header('01 / MARKET OUTLOOK', '未来市场展望', f?`<span class="l1-valid">${e(status)}</span>`:'<span class="l1-caution">暂无合格预测</span>')}
      <div class="l1-period">${[1,3,5].map(h=>`<button data-l1-horizon="${h}" type="button" aria-pressed="${h===horizon}" class="${h===horizon?'active':''}">H${h}<small>${h} 个交易日</small></button>`).join('')}</div>
      <div class="l1-prediction-metrics">
        ${small('条件预期收益',f?signed(Number(f.expected_return)*100)+'%':'—','T+1 开盘至 T+H 收盘')}
        ${small('上涨概率 · 研究估计',f?pct(f.p_up):'—',f?.probability_calibration_status||'无概率校准证据')}
        ${small('下行尾部概率',f&&validProbability(f.p_downside)?pct(f.p_downside):'—',f?.downside_threshold!==undefined?'阈值 '+signed(Number(f.downside_threshold)*100,2)+'%':'未提供事件阈值')}
      </div>
      ${distribution(f)}
      <div class="l1-subline">${f?`模型 ${asText(rec.data.model_version)} · 数据 ${asText(rec.data.asof_session)} · 冻结 ${stamp(rec.data.frozen_at_utc)}`:'只接受包含时点、来源哈希、模型版本及一致收益分位的 L1 冻结预测；不将旧历史回放拼接为当前预测。'}</div>`);
  }
  function firstPassage(rec) {
    const p=rec?.f?.first_passage;
    const eligible=p && rec?.f?.first_passage_calibration_status==='CALIBRATED_TEMP_HOLDOUT' &&
      ['up_first','down_first','neither'].every(k=>validProbability(p[k])) &&
      Math.abs(Number(p.up_first)+Number(p.down_first)+Number(p.neither)-1)<=0.001 &&
      isNum(p.up_threshold) && Number(p.up_threshold)>0 &&
      isNum(p.down_threshold) && Number(p.down_threshold)<0;
    const rows=[['先向上触及','up_first','gain'],['先向下触及','down_first','loss'],['期限内均未触及','neither','neutral']];
    return panel('l1-event', `${header('02 / PRICE PATH', '风险与路径事件', '<span class="l1-kicker">FIRST PASSAGE</span>')}
     <div class="l1-event-caption">对比未来价格先触及上涨或下跌边界的事件，而不是事后定义“底部”。</div>
     ${eligible ? `<div class="l1-event-bars">${rows.map(([label,key,cls])=>`<div class="l1-event-item"><div><span>${label}</span><strong>${pct(p[key])}</strong></div><div class="l1-track"><i class="${cls}" style="width:${Number(p[key])*100}%"></i></div></div>`).join('')}</div><div class="l1-tiny">边界：+${n(Number(p.up_threshold)*100,2)}% / ${n(Number(p.down_threshold)*100,2)}% · 独立时间序列校准</div>`
      :empty('路径事件尚无合格预测','等数据与首次触及标签接入后，展示先反弹 / 先下跌 / 均未触及三类互斥结果。')}
      <div class="l1-caveat"><strong>需要验证的风险：</strong>同时关注误报、提前量与尾部风险。</div>`);
  }
  function driversAndSignals(data) {
    const records=Array.isArray(data?.drivers)?data.drivers.filter(x=>x&&x.label&&isNum(x.value)&&['OBSERVED','PARTIAL'].includes(x.status||'OBSERVED')).slice(0,7):[];
    return panel('l1-driver', `${header('03 / CONDITION CHANGE', '哪些市场特征正在变化？', '<span class="l1-kicker">FEATURE EVIDENCE</span>')}
      <div class="l1-subtitle">模型贡献仅显示已验证结果。</div>
      ${records.length ? `<div class="l1-driver-rows">${records.map((x)=>`<div class="l1-driver-row"><div class="l1-driver-head"><span>${e(x.label)}</span><strong>${num(x.value,x.unit||'',2)}</strong></div><div class="l1-driver-meta"><span>${asText(x.status||'OBSERVED')}</span><span>${x.delta!==null&&isNum(x.delta)?'日变化 '+signed(x.delta):'变化待核验'}</span><span>${x.oos_increment===null||!isNum(x.oos_increment)?'增量未验证':'样本外增量 '+signed(x.oos_increment,4)}</span></div></div>`).join('')}</div>`
        :empty('尚无经过审计的特征变化', '暂无已验证的特征变化。')}
      <div class="l1-driver-footer"></div>`);
  }
  function domainsGrid(data) {
    const raw=Array.isArray(data?.domains)?data.domains:[];
    const lookup=new Map(raw.filter(x=>x&&x.id).map(x=>[x.id,x]));
    const displayed=DOMAINS.filter(([id,, ,group])=>S.dimension==='all'||S.dimension===group);
    const observed=DOMAINS.filter(([id])=>lookup.get(id)?.status==='OBSERVED').length;
    const partial=DOMAINS.filter(([id])=>lookup.get(id)?.status==='PARTIAL').length;
    return panel('l1-monitor', `${header('04 / MARKET OBSERVATORY', '12 维市场自动观测', `<span class="l1-kicker">已观测 ${observed} / 12 · 部分覆盖 ${partial}</span>`)}
      <div class="l1-subtitle">缺失维度不按 0 处理。</div>
      <div class="l1-filters" role="group" aria-label="观测维度筛选">${FILTERS.map(([id,name])=>`<button type="button" data-l1-domain="${e(id)}" class="${S.dimension===id?'active':''}" aria-pressed="${S.dimension===id}">${e(name)}</button>`).join('')}</div>
      <div class="l1-domain-grid">${displayed.map(([id,name,desc,group],i)=>{
        const item=lookup.get(id), status=item?.status||'MISSING';
        const val=['OBSERVED','PARTIAL'].includes(status)&&isNum(item.value)?num(item.value,item.unit||'',item.precision??2):'—';
        return `<button type="button" class="l1-domain" data-l1-open-domain="${e(id)}" aria-pressed="${S.selectedDomain===id}"><div class="l1-domain-h"><span class="l1-domain-icon">${String(DOMAINS.findIndex(x=>x[0]===id)+1).padStart(2,'0')}</span><span class="l1-domain-state ${e(status.toLowerCase())}">${label(status)}</span></div><strong>${e(name)}</strong><p>${e(desc)}</p><div class="l1-domain-number">${val}</div><small>${status==='OBSERVED'?asText(item.label||'已到达的数据观察值') : status==='PARTIAL'?'部分覆盖：仅显示已取得的实际数值': '数据或计算尚未完成'}<span class="l1-domain-coverage">${item?.coverage?e(item.coverage.available+' / '+item.coverage.registered+' 项特征'):''}</span></small></button>`;
      }).join('')}</div>
      ${S.selectedDomain ? `<div class="l1-domain-details"><h3>${e((DOMAINS.find(x=>x[0]===S.selectedDomain)||[])[1]||'指标明细')}</h3><p>来源与可得时点</p><div class="l1-domain-details-list">${(Array.isArray(data?.features)?data.features:[]).filter(x=>x.domain===S.selectedDomain).map(x=>`<div class="l1-research-row"><span>${e(x.id)} <small>${asText(x.status)} · ${asText(x.source)}</small></span><strong>${isNum(x.value)?n(x.value,4):'—'} <small>${asText(x.available_at)}</small></strong></div>`).join('')||'<p class="l1-no-features">该维度尚未取得可核验的指标明细</p>'}</div></div>` : ''}`);
  }
  function validation(oldStudy, rec) {
    const rows=Array.isArray(oldStudy?.summary?.direction)?oldStudy.summary.direction:[];
    const metric=rows.find(x=>isNum(x.brier)&&isNum(x.naive_brier));
    return panel('l1-validation', `${header('05 / MODEL EVIDENCE', '预测验证与历史对照', '<span class="l1-kicker">RESEARCH / OOS</span>')}
      <div class="l1-valid-grid">
      ${small('当前 L1 冻结预测',rec?asText(rec.data.status):'未取得','必须是当日的前向模型归档')}
      ${small('旧实验 · 模型 Brier',metric?num(metric.brier,'',4):'—','历史回顾研究，非当前模型')}
      ${small('旧实验 · 常数基准 Brier',metric?num(metric.naive_brier,'',4):'—','历史回顾研究，非当前模型')}
      </div><div class="l1-qualify">${metric?`历史回溯 Brier 差（模型−基准）：${signed(Number(metric.brier)-Number(metric.naive_brier),4)}；负值较优。该实验不得用于证明最新 L1 预测已经验收。`:'当前没有可核验的历史验证结果。'}</div>
      <details class="l1-method"><summary>方法与验证</summary><p>信号：T 日收盘后；观察窗口：T+1 开盘至 T+H 收盘。</p><p>验证：校准、预测损失、误报/提前量与基准对照。</p><p>PIT 与覆盖证据不足时仅作观察。</p></details>`);
  }
  function researchTools(anomalyData, validationData, replayData) {
    const alerts=Array.isArray(anomalyData?.anomalies)?anomalyData.anomalies:[];
    const metrics=Array.isArray(validationData?.metrics)?validationData.metrics:[];
    const replay=replayData?.prediction;
    const alertsHTML=alerts.length?alerts.slice(-8).reverse().map(x=>`<div class="l1-research-row"><span>${asText(x.date)} · ${asText(x.feature)}</span><strong>${isNum(x.z_score)?signed(x.z_score)+'σ':'—'}</strong></div>`).join(''):
      empty('无已归档的异常发现','缺少历史特征或过去窗口的异常扫描证据。');
    const metricsHTML=metrics.length?`<div class="l1-metrics-table"><div class="l1-metrics-header">期限　波动 MSE / 基准　分位损失 / 基准　事件 Brier / 基准</div>${metrics.map(x=>`<div class="l1-research-row"><span>H${e(x.horizon)} · ${num(x.e01_rv_mse,'',4)} / ${num(x.e01_baseline_mse,'',4)} · ${num(x.e03_pinball_loss,'',4)} / ${num(x.e03_baseline_pinball_loss,'',4)}</span><strong>${num(x.e02_brier,'',4)} / ${num(x.e02_baseline_brier,'',4)}</strong></div>`).join('')}</div>`:
      empty('暂无新版 L1 样本外研究指标','必须先运行 E01 / E02 / E03 的完整时间外实验，不能借旧实验冒充。');
    return panel('l1-research',`${header('06 / RESEARCH WORKBENCH', '历史验证与回放', '<span class="l1-kicker">RESEARCH-ONLY</span>')}
      <div class="l1-research-columns"><div><h3>市场异常扫描</h3>${alertsHTML}</div><div><h3>模型与基准对照</h3>${metricsHTML}</div></div>
      <div class="l1-replay"><label for="l1-replay-date">回放历史研究日</label><input type="date" id="l1-replay-date" value="${e(S.replayDate)}"><button type="button" data-l1-replay>查看当时研究</button>
        <span>${replay?'研究预测 '+num(replay.expected_return*100,'%',2)+' · 后续实际 '+num(replay.actual_return*100,'%',2)+' · 非真实冻结预测':replayData?.status==='NO_OOS_PREDICTION'?'该日期无样本外实验记录':'选择日期后显示真实研究记录'}</span></div>
      <p class="l1-research-warning">历史回放与前向预测分开验证。</p>`);
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
    const html=`<div class="l1-cockpit">
      <div class="l1-head"><div><div class="l1-breadcrumb">L1 / MARKET FORECAST <span>· 01</span></div><h1>市场未来展望 <span class="l1-beta">RESEARCH</span></h1><p>未来收益、风险分布与关键驱动。</p></div>
      <div class="l1-head-actions"><span class="l1-access ${rec?'good':''}"><i></i>${rec?'已读取冻结预测':typed?'已读取市场观察':'等待研究归档'}</span><button class="l1-refresh" type="button" data-l1-refresh>↻ 重新核查</button></div></div>
      ${indicatorCards(fresh,system,observationStatus)}
      <div class="l1-top-grid">${currentForecast(rec,S.horizon)}${firstPassage(rec)}</div>
      ${driversAndSignals(typed)}${domainsGrid(typed)}${validation(old,rec)}${researchTools(anomalyRaw?.ok?anomalyRaw.data:null, validationRaw?.ok?validationRaw.data:null, replayRaw?.ok?replayRaw.data:null)}
      <div class="l1-bottom-note"><span>QDR · MARKET RESEARCH · L1</span><span>观察 · 回放 · 前向</span></div></div>`;
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
      document.querySelector('[data-l1-refresh]')?.addEventListener('click',()=>{const global=document.querySelector('#v4-refresh');if(global)global.click();else show('market');});
      document.querySelector('[data-l1-replay]')?.addEventListener('click',()=>{
        S.replayDate=document.querySelector('#l1-replay-date')?.value||'';
        if (S.replayDate) show('market');
      });
    }};
  };
})();
