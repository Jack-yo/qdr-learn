/* QDR V5 L1 market desk. One market page, strict evidence gating, no legacy UI. */
(() => {
'use strict';
const V=window.V4;if(!V)throw Error('QDR L1 requires V4 core');
const {pages,state,e,n,pct,settle,show}=V;
const DIGEST=/^[a-f0-9]{64}$/;
const DOMAINS=[
 ['price','价格与趋势','走势、速度、隔夜与盘中结构'],
 ['breadth','真实市场广度','上涨参与率、创新高低、广度背离'],
 ['volatility','波动率结构','实现波动、隐含波动与期限结构'],
 ['options_pricing','期权风险定价','偏斜、方差溢价、保护成本'],
 ['options_positioning','期权仓位与对冲','到期集中、Gamma 与对冲压力'],
 ['microstructure','市场微观结构','买卖价差、订单流与价格冲击'],
 ['correlation','相关性与离散度','行业相关、集中度与系统同步'],
 ['cross_asset','跨资产风险传导','利率、信用、美元与资产联动'],
 ['positioning','资金流与持仓拥挤','期货持仓、ETF 流与杠杆代理'],
 ['events','宏观与事件冲击','数据、会议、到期与再平衡'],
 ['funding','融资与金融条件','融资利差、信用与压力'],
 ['path','路径与极端事件','跳跃、下行半方差与不利波动']
];
const isNum=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
const validProbability=v=>isNum(v)&&Number(v)>=0&&Number(v)<=1;
const signedPct=(v,d=2)=>isNum(v)?(Number(v)>0?'+':'')+n(Number(v)*100,d)+'%':'—';
const text=v=>v===null||v===undefined||v===''?'—':e(v);
const statusLabel=s=>({OBSERVED:'已观测',PARTIAL:'部分覆盖',MISSING:'待接入',BLOCKED:'不可用',STALE:'已过期'}[s]||'待检查');
const forecastStatus=x=>{
 if(x?.status==='FROZEN_FORWARD_RESEARCH_ONLY')
  return x.research_only===true&&x.model_admitted===false&&x.real_orders_enabled===false;
 if(x?.status==='MODEL_OOS_ADMITTED')
  return x.model_admitted===true&&x.historical_pit_verified===true&&x.source_independently_attested===true&&x.real_orders_enabled===false;
 return false;
};
function extractForecast(response,fresh,horizon){
 if(!response?.ok||response.data?.schema!=='qdr.l1.market.v1')return null;
 const data=response.data,cutoff=Date.parse(data.knowledge_cutoff_utc||''),frozen=Date.parse(data.frozen_at_utc||''),entry=Date.parse(data.entry_at_utc||'');
 if(!forecastStatus(data)||data.asof_session !== fresh?.asof_session||
    !DIGEST.test(data.source_snapshot_sha256 || '')||!data.model_version||
    !Number.isFinite(cutoff)||!Number.isFinite(frozen)||!Number.isFinite(entry)||
    frozen < cutoff || cutoff >= entry)return null;
 const f=data.forecast;
 if(!f||Number(f.horizon)!==horizon||!validProbability(f.p_up)||
    (f.p_downside!==null&&f.p_downside!==undefined&&!validProbability(f.p_downside))||
    !isNum(f.expected_return)||!Array.isArray(f.quantiles)||f.quantiles.length!==5||
    f.quantiles.some(q=>!isNum(q))||
    f.quantiles.some((q,i) => i > 0 && Number(q)<Number(f.quantiles[i-1])))return null;
 if(f.first_passage!==undefined&&f.first_passage!==null){
  const p=f.first_passage;
  if(!['up_first','down_first','neither'].every(k=>validProbability(p[k]))||
     Math.abs(Number(p.up_first)+Number(p.down_first)+Number(p.neither)-1)>0.001||
     !isNum(p.up_threshold)||Number(p.up_threshold)<=0||
     !isNum(p.down_threshold)||Number(p.down_threshold)>=0)return null;
 }
 return {data,f};
}
const row=(label,value,sub='')=>'<div class="market-stat"><span>'+e(label)+'</span><b>'+value+'</b>'+(sub?'<small>'+e(sub)+'</small>':'')+'</div>';
function sourceStrip(fresh,system){
 const day=system?.dataset?.asof_date_et,prices=Array.isArray(system?.prices)?system.prices:[],same=day&&day===fresh?.asof_session;
 const q=s=>prices.find(x=>x.symbol===s&&String(x.date).slice(0,10)===day&&x.basis==='raw');
 const price=x=>same&&isNum(x?.close)?'$'+n(x.close,2):'—';
 const obs=fresh?.modules?.market_observation||{};
 return '<div class="market-source-strip">'+
  row('观察交易日',text(fresh?.asof_session))+
  row('SPY',price(q('SPY')),'收盘')+
  row('IWM',price(q('IWM')),'收盘')+
  row('数据覆盖',isNum(obs.covered_symbols)&&isNum(obs.required_symbols)?n(obs.covered_symbols,0)+' / '+n(obs.required_symbols,0):'—',statusLabel(obs.freshness_status))+
 '</div>';
}
function forecastView(rec,horizon){
 if(!rec)return '<section class="market-primary"><div class="market-section-head"><div><span>MARKET OUTLOOK</span><h2>市场结论</h2></div><em>暂无合格预测</em></div>'+
  '<div class="market-horizons">'+[1,3,5].map(h=>'<button type="button" data-l1-horizon="'+h+'" class="'+(h===horizon?'active':'')+'" aria-pressed="'+(h===horizon)+'">H'+h+'<small>'+h+'D</small></button>').join('')+'</div>'+
  '<div class="market-empty"><b>暂无合格预测</b><span>当前仅展示市场观察；前向预测通过验证后会自动出现。</span></div></section>';
 const f=rec.f;
 return '<section class="market-primary"><div class="market-section-head"><div><span>MARKET OUTLOOK</span><h2>市场结论</h2></div><em>已读取冻结预测</em></div>'+
  '<div class="market-horizons">'+[1,3,5].map(h=>'<button type="button" data-l1-horizon="'+h+'" class="'+(h===horizon?'active':'')+'" aria-pressed="'+(h===horizon)+'">H'+h+'<small>'+h+'D</small></button>').join('')+'</div>'+
  '<div class="market-metrics">'+
   row('条件预期收益',signedPct(f.expected_return))+
   row('上涨概率',pct(f.p_up),f.probability_calibration_status||'')+
   row('下行尾部概率',validProbability(f.p_downside)?pct(f.p_downside):'—',isNum(f.downside_threshold)?'阈值 '+signedPct(f.downside_threshold):'')+
  '</div>'+
  '<div class="market-range"><span>'+signedPct(f.quantiles[0])+'</span><i><b style="left:'+Math.max(0,Math.min(100,(Number(f.quantiles[2])-Number(f.quantiles[0]))/Math.max(1e-9,Number(f.quantiles[4])-Number(f.quantiles[0]))*100))+'%"></b></i><span>'+signedPct(f.quantiles[4])+'</span></div>'+
  '<div class="market-meta">模型 '+text(rec.data.model_version)+' · 数据 '+text(rec.data.asof_session)+'</div></section>';
}
function pathRisk(rec){
 const p=rec?.f?.first_passage;
 const eligible=p&&rec?.f?.first_passage_calibration_status==='CALIBRATED_TEMP_HOLDOUT'&&['up_first','down_first','neither'].every(k=>validProbability(p[k]));
 if(!eligible)return '<section class="market-side"><div class="market-section-head"><div><span>PATH RISK</span><h2>路径风险</h2></div></div><div class="market-empty small"><b>路径事件待验证</b><span>暂无可用的首次触及概率。</span></div></section>';
 return '<section class="market-side"><div class="market-section-head"><div><span>PATH RISK</span><h2>路径风险</h2></div><em>独立时间序列校准</em></div>'+
  '<div class="market-path"><div><span>先向上触及</span><b class="is-up">'+pct(p.up_first)+'</b></div><div><span>先向下触及</span><b class="is-down">'+pct(p.down_first)+'</b></div><div><span>期限内均未触及</span><b>'+pct(p.neither)+'</b></div></div>'+
  '<small class="market-caption">边界 '+signedPct(p.up_threshold)+' / '+signedPct(p.down_threshold)+' · 只比较路径风险，不等同于见底判断。</small></section>';
}
function drivers(data){
 const xs=Array.isArray(data?.drivers)?data.drivers.filter(x=>x&&x.label&&isNum(x.value)).slice(0,8):[];
 if(!xs.length)return '<div class="market-empty small"><b>暂无关键变化</b><span>当前没有可展示的已核验变化。</span></div>';
 return '<div class="market-driver-list">'+xs.map(x=>'<div><span>'+e(x.label)+'</span><b>'+n(x.value,2)+(x.unit?e(x.unit):'')+'</b><em class="'+(isNum(x.delta)?Number(x.delta)>0?'is-up':Number(x.delta)<0?'is-down':'':'')+'">'+(isNum(x.delta)?'日变化 '+signedPct(x.delta):statusLabel(x.status))+'</em></div>').join('')+'</div>';
}
function evidence(data){
 const raw=Array.isArray(data?.domains)?data.domains:[],map=new Map(raw.filter(x=>x?.id).map(x=>[x.id,x]));
 return '<details class="market-details"><summary><span>12 维市场自动观测</span><small>完整市场证据</small></summary><div class="market-domain-grid">'+DOMAINS.map(([id,name,desc])=>{
  const x=map.get(id),status=x?.status||'MISSING',val=['OBSERVED','PARTIAL'].includes(status)&&isNum(x?.value)?n(x.value,x.precision??2)+(x.unit||''):'—';
  return '<div class="market-domain"><div><span>'+e(name)+'</span><em>'+e(statusLabel(status))+'</em></div><b>'+e(val)+'</b><small>'+e(desc)+'</small></div>';
 }).join('')+'</div></details>';
}
function audit(old,validation,anomalies,replay){
 const summary=old?.summary?.direction?.[0]||null,items=Array.isArray(anomalies?.anomalies)?anomalies.anomalies:[];
 return '<details class="market-details market-audit"><summary><span>模型验证与研究记录</span><small>按需查看</small></summary><div class="market-audit-grid">'+
  '<div><span>历史 Brier</span><b>'+ (isNum(summary?.brier)?n(summary.brier,4):'—')+'</b></div>'+
  '<div><span>验证状态</span><b>'+e(validation?.status||'—')+'</b></div>'+
  '<div><span>异常记录</span><b>'+n(items.length,0)+'</b></div>'+
  '<div><span>历史回放</span><b>'+e(replay?.status||'未选择')+'</b></div>'+
  '</div><div class="market-replay"><input type="date" id="l1-replay-date"><button type="button" data-l1-replay>查看研究日</button></div></details>';
}
pages.market=async()=>{
 const horizon=[1,3,5].includes(Number(state.marketHorizon))?Number(state.marketHorizon):3;
 const replayDate=state.l1ReplayDate||'';
 const [forecast,freshR,statusR,oldR,anomalyR,validationR,replayR]=await Promise.all([
  settle('/api/v1/l1/market/overview?horizon='+horizon),settle('/api/v1/v4/freshness'),settle('/api/status'),
  settle('/api/v1/market/research?horizon='+horizon),settle('/api/v1/l1/anomalies'),settle('/api/v1/l1/validation'),
  replayDate?settle('/api/v1/l1/replay?asof='+encodeURIComponent(replayDate)+'&horizon='+horizon):Promise.resolve(null)
 ]);
 const fresh=freshR?.ok?freshR.data:null,system=statusR?.ok?statusR.data:null,typed=forecast?.ok&&forecast.data?.schema==='qdr.l1.market.v1'?forecast.data:null;
 const rec=extractForecast(forecast,fresh,horizon),old=oldR?.ok?oldR.data:null;
 const status=rec?'已读取冻结预测':typed?'已读取市场观察':'数据待检查';
 const html='<div class="market-desk"><div class="heading market-head"><div><div class="market-kicker">MARKET · L1</div><h1 class="title">市场展望</h1><div class="subtitle">未来 1 / 3 / 5 个交易日的收益、路径风险与关键变化。</div></div><div class="market-status">'+e(status)+'</div></div>'+
  sourceStrip(fresh,system)+'<div class="market-top">'+forecastView(rec,horizon)+pathRisk(rec)+'</div>'+
  '<section class="market-section"><div class="market-section-head"><div><span>CONDITION CHANGE</span><h2>关键变化</h2></div></div>'+drivers(typed)+'</section>'+
  evidence(typed)+audit(old,validationR?.ok?validationR.data:null,anomalyR?.ok?anomalyR.data:null,replayR?.ok?replayR.data:null)+'</div>';
 return {title:'市场展望',html,mount(){
  document.querySelectorAll('[data-l1-horizon]').forEach(btn=>btn.addEventListener('click',()=>{state.marketHorizon=Number(btn.dataset.l1Horizon);show('market');}));
  document.querySelector('[data-l1-replay]')?.addEventListener('click',()=>{state.l1ReplayDate=document.querySelector('#l1-replay-date')?.value||'';if(state.l1ReplayDate)show('market');});
 }};
};
})();