/* QDR V5 L2 style rotation desk. */
(() => {
'use strict';
const V=window.V4;if(!V)throw Error('QDR L2 requires V4 core');
const {pages,state,e,n,signed,date,settle,show}=V;
const STYLE_LABELS={size:'规模',value:'价值',growth:'成长',momentum:'动量',quality:'质量',low_vol:'低波动',cyc_def:'周期 / 防御'};
const STATES={STRONG_ACCELERATING:['强势加速','is-up'],STRONG_DECELERATING:['强势减速','is-down'],WEAK_IMPROVING:['弱势改善','is-up'],WEAK_DETERIORATING:['弱势恶化','is-down'],UNKNOWN:['待判定','']};
const finite=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
const styleName=id=>STYLE_LABELS[id]||id||'—';
const stateMeta=s=>STATES[String(s)||'UNKNOWN']||STATES.UNKNOWN;
state.l2Tab=state.l2Tab||'overview';state.l2Style=state.l2Style||'size';state.l2AsOf=state.l2AsOf||'';
const tab=(id,label)=>'<button type="button" role="tab" aria-selected="'+(state.l2Tab===id)+'" class="v4-subtab '+(state.l2Tab===id?'active':'')+'" data-l2-tab="'+e(id)+'">'+e(label)+'</button>';
const empty=(title,detail)=>'<div class="l2-empty"><b>'+e(title)+'</b><span>'+e(detail)+'</span></div>';
function quadrant(rows){
 const valid=(rows||[]).filter(x=>x.rotation_state!=='UNKNOWN'&&finite(x.strength_relative_return_20d)&&finite(x.acceleration_relative_return_5d));
 if(!valid.length)return empty('轮动位置不可用','需要 20D 相对收益和 5D 加速度。');
 const mx=Math.max(.0001,...valid.map(x=>Math.abs(Number(x.acceleration_relative_return_5d))));
 const my=Math.max(.0001,...valid.map(x=>Math.abs(Number(x.strength_relative_return_20d))));
 const point=x=>{
  const cx=Math.max(28,Math.min(532,280+Number(x.acceleration_relative_return_5d)/mx*235));
  const cy=Math.max(26,Math.min(284,155-Number(x.strength_relative_return_20d)/my*115));
  return '<g><circle cx="'+cx.toFixed(1)+'" cy="'+cy.toFixed(1)+'" r="'+(x.style_id===state.l2Style?'8':'6')+'" class="'+(x.style_id===state.l2Style?'selected':'')+'"/><text x="'+(cx+10).toFixed(1)+'" y="'+(cy-7).toFixed(1)+'">'+e(styleName(x.style_id))+'</text></g>';
 };
 return '<svg class="l2-rotation-map" viewBox="0 0 560 310" role="img" aria-label="风格轮动四象限">'+
 '<line x1="280" y1="14" x2="280" y2="292"/><line x1="14" y1="155" x2="546" y2="155"/>'+
 '<text x="18" y="28" class="quad">强势减速</text><text x="455" y="28" class="quad">强势加速</text>'+
 '<text x="18" y="286" class="quad">弱势恶化</text><text x="455" y="286" class="quad">弱势改善</text>'+valid.map(point).join('')+'</svg>';
}
function ranked(items,rotation){
 const rmap=new Map((rotation||[]).map(x=>[x.style_id,x]));
 const rows=(items||[]).filter(x=>finite(x.relative_return_20d)).sort((a,b)=>Number(b.relative_return_20d)-Number(a.relative_return_20d));
 if(!rows.length)return empty('暂无可比较风格','当前没有完整的 20D 相对收益。');
 return '<table class="l2-table"><thead><tr><th>风格</th><th>5D</th><th>20D</th><th>60D</th><th>状态</th></tr></thead><tbody>'+
 rows.map(x=>{const s=rmap.get(x.style_id),m=stateMeta(s?.rotation_state);return '<tr data-l2-style="'+e(x.style_id)+'" class="'+(state.l2Style===x.style_id?'selected':'')+'"><td><b>'+e(styleName(x.style_id))+'</b></td><td>'+signed(x.relative_return_5d)+'</td><td>'+signed(x.relative_return_20d)+'</td><td>'+signed(x.relative_return_60d)+'</td><td class="'+m[1]+'">'+e(m[0])+'</td></tr>';}).join('')+'</tbody></table>';
}
function trend(series,id){
 const rows=(series||[]).filter(x=>x.style_id===id&&x.date&&finite(x.relative_return_20d)).sort((a,b)=>String(a.date).localeCompare(String(b.date))).slice(-80);
 if(rows.length<2)return empty('历史趋势不足','需要至少两个真实观测点。');
 const vals=rows.map(x=>Number(x.relative_return_20d)),lo=Math.min(0,...vals),hi=Math.max(0,...vals),span=Math.max(1e-8,hi-lo);
 const pts=rows.map((x,i)=>[(18+514*i/(rows.length-1)).toFixed(1),(150-122*(Number(x.relative_return_20d)-lo)/span).toFixed(1)]);
 return '<svg class="l2-trend" viewBox="0 0 550 170"><line x1="18" x2="532" y1="'+(150-122*(0-lo)/span).toFixed(1)+'" y2="'+(150-122*(0-lo)/span).toFixed(1)+'"/><path d="'+pts.map((p,i)=>(i?'L':'M')+p.join(' ')).join(' ')+'"/></svg><div class="l2-trend-foot"><span>'+date(rows[0].date)+'—'+date(rows[rows.length-1].date)+'</span><span>20D 相对收益</span></div>';
}
function turns(rotation){
 const xs=(rotation||[]).filter(x=>x.rotation_state&&x.rotation_state!=='UNKNOWN').sort((a,b)=>String(b.last_transition_session||'').localeCompare(String(a.last_transition_session||''))).slice(0,6);
 if(!xs.length)return empty('暂无已确认转折','当前没有可显示的风格状态变化。');
 return '<div class="l2-turns">'+xs.map(x=>{const m=stateMeta(x.rotation_state);return '<div><span>'+e(styleName(x.style_id))+'</span><b class="'+m[1]+'">'+e(m[0])+'</b><small>'+e(x.last_transition_session||x.rotation_state_start_session||'—')+'</small></div>';}).join('')+'</div>';
}
function forecastView(result,validation){
 const d=result?.ok?result.data:null,v=validation?.ok?validation.data:null;
 if(!d||d.status==='BLOCKED'){
  return '<div class="l2-forecast-empty"><b>领先预测待验证</b><span>当前不展示缺少合格标签或训练证据的 H1 / H3 / H5 结果。</span><details><summary>查看阻断原因</summary><code>'+e(d?.code||result?.error?.message||'EVIDENCE_REQUIRED')+'</code></details></div>';
 }
 const rows=Array.isArray(d.forecasts)?d.forecasts:[];
 const qualification=Array.isArray(v?.qualification)?v.qualification:[];
 const oos=Array.isArray(v?.oos_validation)?v.oos_validation:[];
 const forward=Array.isArray(v?.forward_validation)?v.forward_validation:[];
 const key=(style,h)=>style+'::'+Number(h);
 const qmap=new Map(qualification.map(x=>[key(x.style_id,x.horizon),x]));
 const omap=new Map(oos.map(x=>[key(x.style_id,x.horizon),x]));
 const fmap=new Map(forward.map(x=>[key(x.style_id,x.horizon),x]));
 const grouped=new Map();
 rows.forEach(x=>{if(!grouped.has(x.style_id))grouped.set(x.style_id,{});grouped.get(x.style_id)[Number(x.horizon)]=x;});
 const qualText=q=>{
  const status=q?.qualification_status;
  return status==='MODEL_ADMITTED'?'ADMITTED':status==='OOS_VALIDATED'?'OOS':'研究';
 };
 const cell=(id,h)=>{
  const x=grouped.get(id)?.[h],q=qmap.get(key(id,h));
  if(!x)return '<td>—</td>';
  if(x.forecast_status!=='RESEARCH_ONLY'||!finite(x.predicted_relative_return)){
   return '<td><span class="l2-cell-blocked" title="'+e(x.block_reason||'BLOCKED')+'">BLOCKED</span></td>';
  }
  const cls=Number(x.predicted_relative_return)>0?'is-up':Number(x.predicted_relative_return)<0?'is-down':'';
  const qclass=q?.qualification_status==='MODEL_ADMITTED'?'admitted':q?.qualification_status==='OOS_VALIDATED'?'oos':'research';
  return '<td class="l2-forecast-cell '+cls+'"><b>'+signed(x.predicted_relative_return)+'</b><small class="'+qclass+'">'+e(qualText(q))+'</small></td>';
 };
 const body=[...grouped.keys()].map(id=>'<tr data-l2-style="'+e(id)+'" class="'+(state.l2Style===id?'selected':'')+'"><td><b>'+e(styleName(id))+'</b></td>'+[1,3,5].map(h=>cell(id,h)).join('')+'</tr>').join('');
 let evidence='';
 if(v?.status==='P5_RESEARCH_VALIDATION'){
  const selected=[1,3,5].map(h=>{
   const q=qmap.get(key(state.l2Style,h))||{},o=omap.get(key(state.l2Style,h))||{},fw=fmap.get(key(state.l2Style,h))||{};
   const gain=finite(o.relative_mse_gain_vs_best_baseline)?signed(o.relative_mse_gain_vs_best_baseline):'—';
   const direction=finite(o.directional_accuracy)?(Number(o.directional_accuracy)*100).toFixed(1)+'%':'—';
   const rank=finite(o.rank_ic)?n(o.rank_ic,3):'—';
   const fwd=finite(fw.genuine_forward_sessions)?n(fw.genuine_forward_sessions,0):'0';
   const reasons=Array.isArray(q.reasons)?q.reasons:[];
   return '<tr><td>H'+h+'</td><td>'+e(q.qualification_status||'RESEARCH_ONLY')+'</td><td>'+gain+'</td><td>'+direction+'</td><td>'+rank+'</td><td>'+fwd+'</td><td class="l2-reason">'+e(reasons.join(' · ')||'—')+'</td></tr>';
  }).join('');
  evidence='<details class="l2-method"><summary>样本外验证 · '+e(styleName(state.l2Style))+'</summary>'+
   '<div class="l2-validation"><span>OOS '+n(v?.summary?.oos_validated_units||0,0)+' / '+n(v?.summary?.total_units||21,0)+'</span><span>真实前向 '+n(v?.summary?.genuine_forward_units||0,0)+'</span><span>ADMITTED '+n(v?.summary?.model_admitted_units||0,0)+'</span><span>'+e(v?.probability_calibration_status||'CONTINUOUS_RETURN_ONLY')+'</span></div>'+
   '<div class="l2-validation-scroll"><table class="l2-table l2-validation-table"><thead><tr><th>期限</th><th>资格</th><th>MSE 改善</th><th>方向</th><th>Rank IC</th><th>前向日</th><th>阻断</th></tr></thead><tbody>'+selected+'</tbody></table></div>'+
   '<p>预测值是相对基准的连续收益研究估计，不是概率或交易目标。</p></details>';
 }else{
  evidence='<details class="l2-method"><summary>样本外验证</summary><div class="l2-validation"><span>暂无冻结 P5 验证报告</span><span>'+e(v?.code||validation?.error?.message||'L2_P5_VALIDATION_REPORT_NOT_FOUND')+'</span></div></details>';
 }
 return '<table class="l2-table l2-forecast-table"><thead><tr><th>风格</th><th>H1</th><th>H3</th><th>H5</th></tr></thead><tbody>'+body+'</tbody></table>'+evidence;
}
function evidenceView(data,french){
 const coverage=data?.coverage||{},latest=Array.isArray(french?.latest)?french.latest:[];
 return '<div class="l2-evidence-grid"><div><span>研究交易日</span><b>'+date(data?.asof_session)+'</b></div><div><span>ETF 覆盖</span><b>'+n(coverage.symbols_with_asof_price||0,0)+' / '+n(coverage.required_symbols||0,0)+'</b></div><div><span>观察层状态</span><b>'+e(data?.status||'OBSERVATION_ONLY')+'</b></div><div><span>数据指纹</span><b>'+e(String(data?.source_snapshot_sha256||'—').slice(0,12))+'</b></div></div>'+
 '<details class="l2-method" open><summary>计算口径</summary><p>相对收益：风格组合相对于对应基准 ETF 的复合收益；5 / 20 / 60 均为交易日。</p><p>加速度：最近 5 日相对收益减去前 5 日相对收益。</p><p>四象限：20D 相对收益正负 × 5D 加速度正负；缺失或边界时不强行分类。</p></details>'+
 '<details class="l2-method"><summary>French 因子独立对照</summary>'+(latest.length?'<table class="l2-table"><tbody>'+latest.map(x=>'<tr><td>'+e(x.factor_name)+'</td><td>'+signed(x.sum_5d)+'</td><td>'+signed(x.sum_20d)+'</td></tr>').join('')+'</tbody></table>':empty('暂无 French 因子','独立因子数据当前不可用。'))+'</details>';
}
pages.style=async()=>{
 const args=state.l2AsOf?'&asof='+encodeURIComponent(state.l2AsOf):'';
 const request=await settle('/api/v1/l2/styles/overview?rotation=1'+args),data=request?.ok?request.data:null;
 const items=Array.isArray(data?.latest)?data.latest:[],rotation=Array.isArray(data?.rotation?.latest)?data.rotation.latest:[];
 const leaders=items.filter(x=>finite(x.relative_return_20d)).sort((a,b)=>Number(b.relative_return_20d)-Number(a.relative_return_20d));
 if(!items.find(x=>x.style_id===state.l2Style)&&leaders.length)state.l2Style=leaders[0].style_id;
 const improving=rotation.filter(x=>x.rotation_state==='WEAK_IMPROVING'||x.rotation_state==='STRONG_ACCELERATING');
 const weakening=rotation.filter(x=>x.rotation_state==='STRONG_DECELERATING'||x.rotation_state==='WEAK_DETERIORATING');
 const known=rotation.filter(x=>x.rotation_state&&x.rotation_state!=='UNKNOWN');
 const header='<div class="heading l2-head"><div><div class="l2-kicker">STYLE · L2</div><h1 class="title">风格轮动</h1><div class="subtitle">当前强弱、转折与未来领先性研究。</div></div><div class="l2-date"><input type="date" id="l2-asof" value="'+e(state.l2AsOf)+'"><button type="button" id="l2-current">最新</button></div></div>';
 const tabs='<div class="v4-subtabs l2-tabs" role="tablist">'+tab('overview','轮动总览')+tab('forecast','领先预测')+tab('evidence','方法与证据')+'</div>';
 const tape='<div class="l2-tape"><div><span>20D 相对领先</span><b>'+e(leaders.length?styleName(leaders[0].style_id):'—')+'</b><small>'+(leaders.length?signed(leaders[0].relative_return_20d):'—')+'</small></div><div><span>正在转强</span><b class="is-up">'+n(improving.length,0)+'</b><small>'+e(improving.slice(0,2).map(x=>styleName(x.style_id)).join(' / ')||'—')+'</small></div><div><span>正在转弱</span><b class="is-down">'+n(weakening.length,0)+'</b><small>'+e(weakening.slice(0,2).map(x=>styleName(x.style_id)).join(' / ')||'—')+'</small></div><div><span>可判定状态</span><b>'+n(known.length,0)+' / 7</b><small>'+date(data?.asof_session)+'</small></div></div>';
 let body='';
 if(!data)body=empty('风格数据暂不可用',request?.error?.message||'数据源尚未返回。');
 else if(state.l2Tab==='forecast'){
  const q=state.l2AsOf?'?asof='+encodeURIComponent(state.l2AsOf):'';
  const [forecast,validation]=await Promise.all([settle('/api/v1/l2/styles/forecast'+q),settle('/api/v1/l2/styles/validation'+q)]);
  body='<section class="l2-section"><div class="l2-section-head"><h2>H1 / H3 / H5 领先预测</h2><span>研究预测 · 资格独立显示</span></div>'+forecastView(forecast,validation)+'</section>';
 }else if(state.l2Tab==='evidence'){
  const french=await settle('/api/v1/styles?mode=observation');
  body='<section class="l2-section"><div class="l2-section-head"><h2>方法与证据</h2><span>默认不占据决策视图</span></div>'+evidenceView(data,french?.ok?french.data:null)+'</section>';
 }else{
  body='<div class="l2-layout"><main><section class="l2-section"><div class="l2-section-head"><h2>轮动地图</h2><span>Y：20D 强弱 · X：5D 加速度</span></div>'+quadrant(rotation)+'</section><section class="l2-section"><div class="l2-section-head"><h2>七类风格排名</h2><span>点击行查看趋势</span></div>'+ranked(items,rotation)+'</section></main><aside><section class="l2-section"><div class="l2-section-head"><h2>最新转折</h2></div>'+turns(rotation)+'</section><section class="l2-section"><div class="l2-section-head"><h2>'+e(styleName(state.l2Style))+' · 20D 趋势</h2></div>'+trend(data.series,state.l2Style)+'</section></aside></div>';
 }
 return {title:'风格轮动',html:'<div class="l2-desk">'+header+tabs+tape+body+'</div>',mount(){
  document.querySelectorAll('[data-l2-tab]').forEach(x=>x.addEventListener('click',()=>{state.l2Tab=x.dataset.l2Tab;show('style');}));
  document.querySelectorAll('[data-l2-style]').forEach(x=>x.addEventListener('click',()=>{state.l2Style=x.dataset.l2Style;show('style');}));
  document.querySelector('#l2-asof')?.addEventListener('change',ev=>{state.l2AsOf=String(ev.target.value||'');show('style');});
  document.querySelector('#l2-current')?.addEventListener('click',()=>{state.l2AsOf='';show('style');});
 }};
};
})();