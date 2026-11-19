/* QDR L2 P3: read-only seven-style observation cockpit.
   One snapshot request for P1 observations and P2 rotation, no model claims. */
(() => {
'use strict';
const V=window.V4;
if(!V)throw Error('QDR L2 requires V4 core');
const {pages,state,e,n,pct,signed,date,short,badge,heading,card,empty,note,table,settle,show}=V;
const STYLE_LABELS={
 size:'小盘 / 大盘',value:'价值 / 成长',growth:'成长',momentum:'动量',
 quality:'质量',low_vol:'低波动',cyc_def:'周期 / 防御'
};
const STATES={
 STRONG_ACCELERATING:['强势加速','strong'],
 STRONG_DECELERATING:['强势减速','cooling'],
 WEAK_IMPROVING:['弱势改善','improving'],
 WEAK_DETERIORATING:['弱势恶化','weak'],
 UNKNOWN:['暂不可判定','unknown']
};
const STYLE_KEYS=Object.keys(STYLE_LABELS);
state.l2Tab=state.l2Tab||'overview';
state.l2Style=state.l2Style||'quality';
state.l2AsOf=state.l2AsOf||'';
const finite=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
const number=v=>finite(v)?Number(v):null;
const percent=v=>finite(v)?signed(v):'—';
const htmlStatus=(s)=>{const a=STATES[String(s)||'UNKNOWN']||STATES.UNKNOWN;return '<span class="l2-state l2-'+a[1]+'">'+e(a[0])+'</span>';};
const availability=(v)=>v?e(String(v).replace('T',' ').slice(0,16)):'—';
const linkTab=(id,name)=>'<button type="button" class="l2-tab'+(state.l2Tab===id?' selected':'')+'" data-l2-tab="'+e(id)+'" aria-pressed="'+(state.l2Tab===id?'true':'false')+'">'+e(name)+'</button>';
const shownData=(data,style)=>Array.isArray(data)?data.find(x=>x.style_id===style):null;
const problem=(result,title)=>result?.pending?
  empty(title+'正在加载','各模块独立获取真实研究数据，尚未返回不是数据缺失。'):
  empty(title+'暂不可用',result?.error?.message||'没有可用的真实观测或来源校验未通过。');
const strip=(items)=>'<div class="l2-stat-strip">'+items.map(x=>'<div class="l2-stat"><div>'+e(x[0])+'</div><b>'+x[1]+'</b><small>'+e(x[2])+'</small></div>').join('')+'</div>';
const itemName=id=>STYLE_LABELS[id]||id||'—';
const tone=v=>!finite(v)?'na':Number(v)>0?'up':Number(v)<0?'down':'flat';
const figure=(value,kind='return')=>'<span class="l2-number '+tone(value)+'">'+(kind==='return'?percent(value):finite(value)?n(value,kind==='integer'?0:4):'—')+'</span>';
const pp=v=>finite(v)?signed(v).replace('%',' pp'):'—';
const styleRows=(series,style)=>(
 (Array.isArray(series)?series:[]).filter(x=>x.style_id===style&&x.date)
   .sort((a,b)=>String(a.date).localeCompare(String(b.date)))
);
const stateMeaning=s=>{
 const map={
  STRONG_ACCELERATING:'强势 · 改善',
  STRONG_DECELERATING:'强势 · 恶化',
  WEAK_IMPROVING:'弱势 · 改善',
  WEAK_DETERIORATING:'弱势 · 恶化',
  UNKNOWN:'暂不可判定'
 };
 return map[String(s)||'UNKNOWN']||map.UNKNOWN;
};
const prior=(rows,offset)=>rows.length>offset?rows[rows.length-1-offset]:null;
const miniSparkline=(series,style)=>{
 const rows=styleRows(series,style).slice(-24);
 const vals=rows.map(x=>number(x.relative_return_20d)).filter(x=>x!==null);
 if(vals.length<2)return '<span class="l2-spark-empty">—</span>';
 const lo=Math.min(...vals),hi=Math.max(...vals),span=Math.max(1e-8,hi-lo);
 let d='',drawing=false;
 rows.forEach((row,i)=>{
  const v=number(row.relative_return_20d);
  if(v===null){drawing=false;return;}
  const x=2+76*i/Math.max(1,rows.length-1),y=27-23*(v-lo)/span;
  d+=(drawing?'L':'M')+x.toFixed(1)+' '+y.toFixed(1)+' ';drawing=true;
 });
 return '<svg class="l2-spark" viewBox="0 0 80 30" aria-hidden="true"><path d="'+d+'" /></svg>';
};
const latestRank=(items,style)=>{
 const ranked=(Array.isArray(items)?items:[]).filter(x=>finite(x.relative_return_20d))
  .slice().sort((a,b)=>Number(b.relative_return_20d)-Number(a.relative_return_20d));
 const i=ranked.findIndex(x=>x.style_id===style);
 return i<0?null:{rank:i+1,total:ranked.length};
};
const point=(row,rangeX,rangeY)=>{
 const x=number(row.strength_relative_return_20d);
 const y=number(row.acceleration_relative_return_5d);
 if(x===null||y===null)return '';
 const cx=Math.max(35,Math.min(525,280+(x/rangeX)*235)).toFixed(1);
 const cy=Math.max(30,Math.min(280,155-(y/rangeY)*116)).toFixed(1);
 const selected=row.style_id===state.l2Style;
 return '<g class="'+(selected?'l2-selected-point':'')+'"><circle cx="'+cx+'" cy="'+cy+'" r="'+(selected?'8':'5.5')+'" class="l2-plot-point"/><text x="'+(Number(cx)+10)+'" y="'+(Number(cy)-7)+'" class="l2-point-label">'+e(itemName(row.style_id))+'</text><title>'+e(itemName(row.style_id)+' · 20D '+percent(x)+' · 5D边际 '+percent(y))+'</title></g>';
};
function quadrant(rows,series){
 const valid=rows.filter(x=>x.rotation_state!=='UNKNOWN'&&finite(x.strength_relative_return_20d)&&finite(x.acceleration_relative_return_5d));
 if(!valid.length)return empty('轮动位置无法绘制','需要 20 日相对收益、5 日相对加速度及来源时间证明。');
 const selectedHistory=styleRows(series,state.l2Style).filter(x=>finite(x.relative_return_20d)&&finite(x.relative_acceleration_5d)).slice(-10);
 const maxX=Math.max(0.0001,...valid.map(x=>Math.abs(Number(x.strength_relative_return_20d))),...selectedHistory.map(x=>Math.abs(Number(x.relative_return_20d))));
 const maxY=Math.max(0.0001,...valid.map(x=>Math.abs(Number(x.acceleration_relative_return_5d))),...selectedHistory.map(x=>Math.abs(Number(x.relative_acceleration_5d))));
 const trail=selectedHistory.map((x,i)=>{
  const cx=Math.max(35,Math.min(525,280+(Number(x.relative_return_20d)/maxX)*235));
  const cy=Math.max(30,Math.min(280,155-(Number(x.relative_acceleration_5d)/maxY)*116));
  return [cx,cy,i===selectedHistory.length-1];
 });
 const path=trail.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' ');
 return '<div class="l2-plot-scroll"><svg viewBox="0 0 560 320" class="l2-plot" role="img" aria-label="横轴20日相对收益，纵轴5日相对收益加速度；选中风格显示最近10个交易日轨迹">'+
 '<rect x="0" y="0" width="280" height="155" class="l2-q-neutral"/><rect x="280" y="0" width="280" height="155" class="l2-q-good"/>'+
 '<rect x="0" y="155" width="280" height="155" class="l2-q-low"/><rect x="280" y="155" width="280" height="155" class="l2-q-warn"/>'+
 '<line x1="280" y1="0" x2="280" y2="310" class="l2-axis"/><line x1="0" y1="155" x2="560" y2="155" class="l2-axis"/>'+
 '<text x="14" y="18" class="l2-quadrant-label">弱势 · 改善</text><text x="454" y="18" class="l2-quadrant-label">强势 · 改善</text>'+
 '<text x="14" y="292" class="l2-quadrant-label">弱势 · 恶化</text><text x="454" y="292" class="l2-quadrant-label">强势 · 恶化</text>'+
 (path?'<path d="'+path+'" class="l2-trail-line"/>'+trail.map((p,i)=>'<circle cx="'+p[0].toFixed(1)+'" cy="'+p[1].toFixed(1)+'" r="'+(p[2]?'4':'2.4')+'" class="l2-trail-point"><title>'+e(itemName(state.l2Style)+' · 轨迹 '+(i+1)+'/'+trail.length)+'</title></circle>').join(''):'')+
 valid.map(x=>point(x,maxX,maxY)).join('')+'</svg></div>'+
 '<div class="l2-chart-foot"><span>横轴：20D 相对收益</span><span>纵轴：5D 边际变化</span><span>细线：'+e(itemName(state.l2Style))+' 最近 10 个交易日轨迹</span></div>';
}
function multiStyleEvolution(series,selectedStyle){
 const all=Array.isArray(series)?series:[];
 const dates=[...new Set(all.map(x=>String(x.date||'').slice(0,10)).filter(Boolean))].sort().slice(-60);
 if(dates.length<2)return empty('历史演化不足','至少需要两个有效交易日。');
 const dateSet=new Set(dates);
 const grouped=new Map(STYLE_KEYS.map(k=>[k,styleRows(all,k).filter(x=>dateSet.has(String(x.date).slice(0,10)))]));
 const vals=[];
 grouped.forEach(rows=>rows.forEach(x=>{const v=number(x.relative_return_20d);if(v!==null)vals.push(v);}));
 if(vals.length<2)return empty('历史演化不足','20D 相对收益缺少可画观测。');
 const lo=Math.min(0,...vals),hi=Math.max(0,...vals),span=Math.max(1e-8,hi-lo);
 const index=new Map(dates.map((d,i)=>[d,i]));
 const pathFor=(rows)=>{
  let d='',drawing=false;
  rows.forEach(row=>{
   const v=number(row.relative_return_20d),i=index.get(String(row.date).slice(0,10));
   if(v===null||i===undefined){drawing=false;return;}
   const x=38+650*i/Math.max(1,dates.length-1),y=242-200*(v-lo)/span;
   d+=(drawing?'L':'M')+x.toFixed(1)+' '+y.toFixed(1)+' ';drawing=true;
  });
  return d;
 };
 const zeroY=(242-200*(0-lo)/span).toFixed(1);
 const lines=STYLE_KEYS.map(style=>{
  const d=pathFor(grouped.get(style)||[]);
  if(!d)return '';
  const cls=style===selectedStyle?'l2-evo-line selected':'l2-evo-line context';
  return '<path d="'+d+'" class="'+cls+'"><title>'+e(itemName(style))+'</title></path>';
 }).join('');
 const sel=grouped.get(selectedStyle)||[],last=sel.filter(x=>finite(x.relative_return_20d)).slice(-1)[0];
 return '<svg viewBox="0 0 720 270" class="l2-evolution" role="img" aria-label="最近60个交易日七风格20日相对收益演化，选中风格高亮">'+
 '<line x1="38" y1="'+zeroY+'" x2="688" y2="'+zeroY+'" class="l2-zero"/>'+lines+
 (last?'<text x="680" y="24" text-anchor="end" class="l2-evo-current">'+e(itemName(selectedStyle))+' '+e(percent(last.relative_return_20d))+'</text>':'')+
 '</svg><div class="l2-chart-foot"><span>'+e(dates[0])+'—'+e(dates[dates.length-1])+'</span><span>20D 相对收益 · 选中风格高亮</span><span>其他风格仅作横截面对照</span></div>';
}
function overviewMatrix(items,rotation){
 const map=new Map((rotation||[]).map(x=>[x.style_id,x]));
 const styles=STYLE_KEYS.filter(id=>(items||[]).some(x=>x.style_id===id));
 const row=(label,key,kind='return')=>'<tr><th>'+e(label)+'</th>'+styles.map(id=>{
  const x=shownData(items,id);
  return '<td>'+(kind==='state'?'<span class="l2-state-plain">'+e(stateMeaning(map.get(id)?.rotation_state))+'</span>':figure(x?.[key],kind))+'</td>';
 }).join('')+'</tr>';
 return '<div class="l2-matrix-scroll"><table class="l2-matrix"><thead><tr><th>观察维度</th>'+styles.map(id=>'<th><button type="button" class="l2-matrix-style'+(state.l2Style===id?' current':'')+'" data-l2-style="'+e(id)+'">'+e(itemName(id))+'</button></th>').join('')+'</tr></thead><tbody>'+
 row('20D 相对收益','relative_return_20d')+
 row('5D 相对收益','relative_return_5d')+
 row('60D 相对收益','relative_return_60d')+
 row('5D 边际变化','relative_acceleration_5d')+
 row('当前象限','rotation_state','state')+
 '</tbody></table></div>';
}
function styleRail(items,series){
 const ranked=(items||[]).filter(x=>STYLE_KEYS.includes(x.style_id)).slice().sort((a,b)=>{
  const av=number(a.relative_return_20d),bv=number(b.relative_return_20d);
  return av===null&&bv===null?0:av===null?1:bv===null?-1:bv-av;
 });
 return '<div class="l2-style-rail">'+ranked.map((x,i)=>
  '<button type="button" class="l2-rail-item'+(state.l2Style===x.style_id?' current':'')+'" data-l2-style="'+e(x.style_id)+'">'+
   '<span class="l2-rail-rank">'+(i+1)+'</span><span class="l2-rail-main"><b>'+e(itemName(x.style_id))+'</b><small>20D '+e(percent(x.relative_return_20d))+' · Δ5D '+e(percent(x.relative_acceleration_5d))+'</small></span>'+
   miniSparkline(series,x.style_id)+'</button>'
 ).join('')+'</div>';
}
function rankChanges(series){
 const all=Array.isArray(series)?series:[];
 const dates=[...new Set(all.map(x=>String(x.date||'').slice(0,10)).filter(Boolean))].sort();
 if(!dates.length)return empty('排名历史不足','没有可用于横截面排名的历史日期。');
 const snap=(offset)=>{
  const d=dates[Math.max(0,dates.length-1-offset)];
  const rows=all.filter(x=>String(x.date||'').slice(0,10)===d&&finite(x.relative_return_20d))
   .slice().sort((a,b)=>Number(b.relative_return_20d)-Number(a.relative_return_20d));
  return {date:d,rank:new Map(rows.map((x,i)=>[x.style_id,i+1]))};
 };
 const now=snap(0),d5=snap(5),d20=snap(20);
 const rows=STYLE_KEYS.filter(id=>now.rank.has(id)).sort((a,b)=>now.rank.get(a)-now.rank.get(b)).map(id=>{
  const a=now.rank.get(id),b=d5.rank.get(id),c=d20.rank.get(id);
  const move=finite(c)?Number(c)-Number(a):null;
  const movement=move===null?'—':move>0?'↑ '+move:move<0?'↓ '+Math.abs(move):'—';
  return ['<button class="l2-style-select'+(state.l2Style===id?' current':'')+'" data-l2-style="'+e(id)+'">'+e(itemName(id))+'</button>',n(a,0),b?String(b):'—',c?String(c):'—','<span class="l2-rank-move '+(move>0?'up':move<0?'down':'flat')+'">'+movement+'</span>'];
 });
 return table(['风格','当前','5D 前','20D 前','20D 排名变化'],rows)+
  '<div class="l2-chart-foot"><span>当前：'+e(now.date)+'</span><span>排名依据：20D 相对收益</span></div>';
}
function diagnosticPanel(data,rotation){
 const x=shownData(data?.latest,state.l2Style),r=shownData(rotation?.latest,state.l2Style);
 const rows=styleRows(data?.series,state.l2Style);
 if(!x)return card('变化诊断 · '+itemName(state.l2Style),empty('暂无可诊断观测','当前风格缺少有效观测。'));
 const p5=prior(rows,5),p20=prior(rows,20);
 const delta=(key,p)=>p&&finite(x[key])&&finite(p[key])?Number(x[key])-Number(p[key]):null;
 const evidence=[
  ['短期表现','5D 相对收益',figure(x.relative_return_5d),p5?('5D前 '+percent(p5.relative_return_5d)):'—'],
  ['中期表现','20D 相对收益',figure(x.relative_return_20d),delta('relative_return_20d',p5)!==null?('近5D变化 '+pp(delta('relative_return_20d',p5))):'—'],
  ['边际变化','5D 加速度',figure(x.relative_acceleration_5d),delta('relative_acceleration_5d',p5)!==null?('较5D前 '+pp(delta('relative_acceleration_5d',p5))):'—'],
  ['持续性','10D 占优天数',figure(x.relative_up_days_10,'integer'),'正相对收益交易日'],
  ['风险','20D 相对波动',figure(x.relative_volatility_20d),delta('relative_volatility_20d',p5)!==null?('近5D '+pp(delta('relative_volatility_20d',p5))):'—']
 ];
 const open=[];
 if(!finite(x.relative_return_60d))open.push('60D 相对收益缺失，中期结构尚不可核验。');
 else if(finite(x.relative_return_20d)&&Math.sign(Number(x.relative_return_60d))!==Math.sign(Number(x.relative_return_20d)))open.push('20D 与 60D 相对收益尚未同向，中期共振未确认。');
 if((number(r?.consecutive_sessions)||0)<5)open.push('当前象限仅持续 '+n(r?.consecutive_sessions||0,0)+' 个交易日，持续性仍短。');
 if(p5&&finite(x.relative_acceleration_5d)&&finite(p5.relative_acceleration_5d)&&Number(x.relative_acceleration_5d)<Number(p5.relative_acceleration_5d))open.push('边际改善速度低于 5 个交易日前，需观察是否继续回落。');
 if(p20&&finite(x.relative_return_20d)&&finite(p20.relative_return_20d)&&Number(x.relative_return_20d)>Number(p20.relative_return_20d)&&finite(x.relative_drawdown_20d)&&Number(x.relative_drawdown_20d)<-0.03)open.push('相对收益改善，但 20D 回撤仍较深，趋势质量并不完全一致。');
 if(!open.length)open.push('主要观察维度暂时一致；仍需通过后续交易日确认，而不是据此推断未来收益。');
 const invalid=[];
 if(r?.rotation_state==='STRONG_ACCELERATING'||r?.rotation_state==='STRONG_DECELERATING')invalid.push('20D 相对收益 ≤ 0：退出“强势”区域。');
 else if(r?.rotation_state==='WEAK_IMPROVING'||r?.rotation_state==='WEAK_DETERIORATING')invalid.push('20D 相对收益 > 0：进入“强势”区域，当前弱势描述失效。');
 if(number(r?.acceleration_relative_return_5d)>0)invalid.push('5D 边际变化 ≤ 0：改善状态失效并转入恶化侧。');
 else if(number(r?.acceleration_relative_return_5d)<0)invalid.push('5D 边际变化 > 0：恶化状态失效并转入改善侧。');
 invalid.push('关键窗口缺失或来源晚于截止时间：状态直接变为 UNKNOWN。');
 const current=stateMeaning(r?.rotation_state);
 return card('变化诊断 · '+itemName(state.l2Style),
  '<div class="l2-diagnostic-head"><span>当前象限</span><b>'+e(current)+'</b><small>持续 '+n(r?.consecutive_sessions||0,0)+' 个交易日</small></div>'+
  '<section class="l2-diag-section"><h4>1. 最近为什么在变化？</h4><div class="l2-evidence-list">'+evidence.map(a=>'<div><span>'+e(a[0])+'</span><b>'+e(a[1])+'</b><strong>'+a[2]+'</strong><small>'+e(a[3])+'</small></div>').join('')+'</div></section>'+
  '<section class="l2-diag-section"><h4>2. 尚未确认 / 需要观察</h4><ul>'+open.map(v=>'<li>'+e(v)+'</li>').join('')+'</ul></section>'+
  '<section class="l2-diag-section"><h4>3. 当前描述何时失效？</h4><ul class="l2-invalid">'+invalid.map(v=>'<li>'+e(v)+'</li>').join('')+'</ul></section>'+
  '<section class="l2-diag-section l2-research-note"><h4>研究解释</h4><p>'+e(itemName(state.l2Style))+' 当前的“'+e(current)+'”只由 20D 相对收益与 5D 边际变化定义。它描述已经发生的轮动位置，不等于未来收益判断；H1/H3/H5 前瞻证据独立放在“领先预测”中。</p></section>',
  '可观察事实 → 未确认项 → 失效边界');
}
function details(data,rotation){
 const x=shownData(data?.latest,state.l2Style),r=shownData(rotation?.latest,state.l2Style);
 const registry=data?.styles?.find?.(v=>v.style_id===state.l2Style);
 if(!x)return card(itemName(state.l2Style)+' · 研究详情',empty('该风格当前没有可用数据','请检查样本覆盖或切换研究日期。'));
 const vals=[['5D 相对收益',figure(x.relative_return_5d)],['20D 相对收益',figure(x.relative_return_20d)],
 ['60D 相对收益',figure(x.relative_return_60d)],['5D 加速度',figure(x.relative_acceleration_5d)],
 ['20D 相对波动率',figure(x.relative_volatility_20d)],['60D 相对回撤',figure(x.relative_drawdown_60d)],
 ['10 日相对占优天数',figure(x.relative_up_days_10,'integer')],['状态持续日',figure(r?.consecutive_sessions,'integer')]];
 const labels=vals.map(([k,v])=>'<div class="l2-mini"><span>'+e(k)+'</span><b>'+v+'</b></div>').join('');
 const info=registry?'<div class="l2-pair"><span>风格代理：'+e((registry.numerator||[]).join(' / '))+'</span><span>比较基准：'+e((registry.denominator||[]).join(' / '))+'</span></div>':'';
 return card(itemName(state.l2Style)+' · 状态与计算',
   '<div class="l2-detail-status">'+htmlStatus(r?.rotation_state)+'<span>状态开始：'+date(r?.rotation_state_start_session)+'</span><span>上次有效转折：'+date(r?.last_transition_session)+'</span></div>'+
   '<div class="l2-mini-grid">'+labels+'</div>'+info+
   '<div class="l2-source-line">数据可用时间：'+availability(x.available_at)+' · 来源版本：'+e(x.registry_version||'—')+'</div>'+
   (x.missing_reason||r?.block_reason?note('数据限制：'+(x.missing_reason||r?.block_reason)):'')+
   note('四象限是描述性分类；不代表未来上涨概率、入场位置或已通过样本外验证的信号。'),
   '单一风格 · 实际计算');
}
function transitions(rotation){
 const events=(rotation?.transitions||[]).slice().reverse();
 const selected=events.filter(x=>x.style_id===state.l2Style);
 return card('状态转折 · '+itemName(state.l2Style),
   selected.length?table(['转折日','前一状态','当前状态','20D 相对收益','5D 加速度'],
   selected.slice(0,15).map(x=>[date(x.date),htmlStatus(x.previous_state),htmlStatus(x.rotation_state),
     figure(x.strength_relative_return_20d),figure(x.acceleration_relative_return_5d)])):
   empty('暂无已确认转折','只统计相邻、有效状态之间的变化；无法确认的时点不会伪造转折。'),
   '历史状态仅以现存当前版本数据回放，非历史 PIT 证明');
}
function quality(data){
 const coverage=data?.coverage||{};
 const symbols=Array.isArray(coverage.symbols)?coverage.symbols:[];
 return card('14 个源符号 · 观测质量',
   '<div class="l2-quality"><b>'+n(coverage.symbols_with_asof_price,0)+' / '+n(coverage.required_symbols,0)+'</b><span>研究截止前拥有观测的 ETF 数量</span></div>'+
   (symbols.length?table(['符号','首个交易日','最近交易日','当日可用','截止前可用'],
    symbols.map(x=>[e(x.symbol),date(x.first_session),date(x.last_session),
    x.asof_present?'是':'否',x.asof_available_by_cutoff?'是':'否'])):
    empty('尚无符号级覆盖记录','无法判断缺失是数据源、交易日还是时间资格导致。'))+
   '<div class="l2-source-line">数据指纹：'+short(data?.source_snapshot_sha256,24)+' · 分割调整价格（不含完整分红总收益）</div>',
   '缺失不补值 · 失败关闭');
}
function forecastResearch(result){
 const d=result?.ok?result.data:null;
 if(!d){
  return problem(result,'H1 / H3 / H5 风格领先预测');
 }
 const rows=Array.isArray(d.forecasts)?d.forecasts:[];
 const missing=Array.isArray(d.missing_evidence)?d.missing_evidence:[];
 if(d.status==='BLOCKED'&&!rows.length){
  return card('P4 · H1 / H3 / H5 领先预测',
    empty('预测研究被数据资格阻断',
      String(d.code||'缺少合格预测输入')+(missing.length?' · '+missing.join('；'):''))
    +note('不会从当前版本 Yahoo 历史临时生成未来标签，也不会把轮动四象限转换成预测概率。'),
    'BLOCKED · '+String(d.code||'EVIDENCE_REQUIRED'));
 }
 const byStyle=new Map();
 rows.forEach(x=>{
  if(!byStyle.has(x.style_id))byStyle.set(x.style_id,new Map());
  byStyle.get(x.style_id).set(Number(x.horizon),x);
 });
 const cells=(style,horizon)=>{
  const x=byStyle.get(style)?.get(horizon);
  if(!x)return '—';
  if(x.forecast_status!=='RESEARCH_ONLY')return '<span class="l2-forecast-blocked" title="'+e(x.block_reason||'BLOCKED')+'">BLOCKED</span>';
  return figure(x.predicted_relative_return);
 };
 const tableRows=STYLE_KEYS.map(style=>[
   '<button type="button" class="l2-style-select'+(state.l2Style===style?' current':'')+'" data-l2-style="'+e(style)+'">'+e(itemName(style))+'</button>',
   cells(style,1),cells(style,3),cells(style,5),
   e([1,3,5].map(h=>byStyle.get(style)?.get(h)?.forecast_status||'MISSING').join(' / '))
 ]);
 const selectedRows=[1,3,5].map(h=>byStyle.get(state.l2Style)?.get(h)).filter(Boolean);
 const detail=selectedRows.length?selectedRows.map(x=>
   '<div class="l2-forecast-h"><div><b>H'+e(x.horizon)+'</b>'+(
    x.forecast_status==='RESEARCH_ONLY'?badge('RESEARCH_ONLY','blue'):badge('BLOCKED','amber'))+'</div>'+
   '<div class="l2-mini-grid">'+
   '<div class="l2-mini"><span>Ridge 相对收益</span><b>'+figure(x.predicted_relative_return)+'</b></div>'+
   '<div class="l2-mini"><span>历史均值基准</span><b>'+figure(x.mean_baseline)+'</b></div>'+
   '<div class="l2-mini"><span>动量基准</span><b>'+figure(x.momentum_baseline)+'</b></div>'+
   '<div class="l2-mini"><span>训练交易日</span><b>'+figure(x.train_sessions,'integer')+'</b></div>'+
   '</div>'+(x.block_reason?note('阻断原因：'+x.block_reason):'')+'</div>'
 ).join(''):empty('当前风格没有预测记录','该风格/期限可能因历史时点、标签或训练样本不足被阻断。');
 return '<div class="l2-main-grid">'+
  card('七风格 · 未来相对收益研究',
   table(['风格','H1','H3','H5','资格'],tableRows)+
   note('数值是相对基准的研究预测收益，不是绝对收益、概率或交易目标。'),
   '模型 '+String(d.model_version||'—')+' · '+String(d.status||'—'))+
  card(itemName(state.l2Style)+' · P4 预测依据',detail+
   '<div class="l2-source-line">标签包：'+e(String(d.label_bundle_id||'—'))+' · 合格单元：'+e(String(d.eligible_units??0))+' / '+e(String((d.eligible_units??0)+(d.blocked_units??0)))+'</div>',
   '前瞻研究证据 · 与描述性轮动状态分离')+
  '</div>'+
  card('P4 研究边界',
    '<div class="l2-protocol"><p><b>标签：</b>T+1 开盘 → T+H 收盘的风格相对收益，必须来自公司行为一致、来源可验证的标签包。</p>'+
    '<p><b>训练：</b>每个 style × horizon 独立 StandardScaler + Ridge；训练标签必须在信号前已知，并执行至少 5 个交易日 embargo。</p>'+
    '<p><b>基准：</b>Zero、历史扩展均值、当前 5D 动量外推。P5 必须证明 OOS 增量，P4 本身不授予模型准入。</p>'+
    '<p><b>当前资格：</b>'+e(d.status||'BLOCKED')+'；historical_decision_eligible=false，real_orders_enabled=false。</p></div>',
    '没有概率校准 · 没有模型准入 · 没有订单');
}

function french(result){
 const d=result?.ok?result.data:null,items=Array.isArray(d?.latest)?d.latest:[];
 return card('Fama–French 因子 · 独立观测',
   items.length?'<div class="l2-fr-note">法玛—弗伦奇因子与 ETF 风格不是同一条收益序列；当前下载版本不能直接用作历史 PIT 训练。</div>'+
   table(['因子','含义','5D','20D','状态'],items.map(x=>[e(x.factor_name),e(x.factor_label||'—'),
   figure(x.sum_5d),figure(x.sum_20d),e(x.state||'—')])):
   problem(result,'French 因子'),
   '研究日期：'+date(d?.asof_date_et)+' · 不合并为 ETF 评分');
}
pages.style=async()=>{
 const args=state.l2AsOf?'&asof='+encodeURIComponent(state.l2AsOf):'';
 const request=await settle('/api/v1/l2/styles/overview?rotation=1'+args);
 const data=request?.ok?request.data:null;
 const rot=data?.rotation||null;
 const items=Array.isArray(data?.latest)?data.latest:[];
 const rotationRows=Array.isArray(rot?.latest)?rot.latest:[];
 const selected=shownData(items,state.l2Style);
 if(!selected&&items.length)state.l2Style=items[0].style_id;
 const known=rotationRows.filter(x=>x.rotation_state&&x.rotation_state!=='UNKNOWN');
 const leaders=items.filter(x=>finite(x.relative_return_20d)).sort((a,b)=>Number(b.relative_return_20d)-Number(a.relative_return_20d));
 const improving=known.filter(x=>x.rotation_state==='WEAK_IMPROVING').length;
 const resolvedDay=date(data?.asof_session);
 const header=heading('经典因子 / 风格监测','L2 · 先看相对表现如何演化，再看边际变化、横截面位置与证据缺口；状态标签只作辅助描述。');
 const controls='<div class="l2-controls"><label for="l2-asof">研究日期</label><input type="date" id="l2-asof" value="'+e(state.l2AsOf)+'" aria-label="L2 研究日期，留空表示最新完整交易日"/>'+
 '<button type="button" id="l2-current" class="btn smallbtn">返回最新</button>'+
 '<span>当前观察：'+resolvedDay+'</span><span>'+badge(data?.status|| (request?.pending?'加载中':'BLOCKED'),
 data?.status==='OBSERVATION_ONLY'?'blue':'amber')+'</span></div>';
 const tabs='<div class="l2-tabs" role="group" aria-label="L2 研究视图">'+[
 linkTab('overview','风格概览'),linkTab('rotation','风格演化'),
 linkTab('forecast','领先预测'),linkTab('evidence','计算证据'),
 linkTab('french','French 因子')].join('')+'</div>';
 const selectedNow=shownData(items,state.l2Style);
 const selectedRotation=shownData(rotationRows,state.l2Style);
 const rank=latestRank(items,state.l2Style);
 const summary=strip([
 ['当前聚焦',e(itemName(state.l2Style)),'点击任一风格切换同一套诊断'],
 ['20D 相对排名',rank?e(rank.rank+' / '+rank.total):'—','只描述当前横截面位置'],
 ['5D 边际变化',selectedNow?figure(selectedNow.relative_acceleration_5d):'—','最近 5D 相对收益 - 前 5D'],
 ['当前象限',e(stateMeaning(selectedRotation?.rotation_state)),'20D 相对收益 × 5D 边际变化']
 ]);
 const disclaimer='<div class="l2-disclaimer">观察层：<b>OBSERVATION_ONLY</b> · 横截面相对表现用于解释风格轮动过程，不把象限、排名或短期改善直接解释为未来收益或交易信号。</div>';
 let body='';
 if(!data){
  body=problem(request,'L2 七风格观测')+
   card('领先性研究资格',empty('没有已核验的预测','请先完成真实历史标签、时间分割和样本外模型验证。'));
 }else if(state.l2Tab==='rotation'){
  body='<div class="l2-main-grid">'+card('相对位置 × 边际变化',quadrant(rotationRows,data.series),'X：20D 相对收益 · Y：5D 边际变化')+
    card('各风格状态',rotationRows.length?table(['风格','状态','持续交易日','前一状态'],rotationRows.map(x=>[
    '<button class="l2-style-select" data-l2-style="'+e(x.style_id)+'">'+e(itemName(x.style_id))+'</button>',
    htmlStatus(x.rotation_state),figure(x.consecutive_sessions,'integer'),htmlStatus(x.previous_state)])):
    empty('轮动状态不可用','请检查源数据窗口和截止时间。'))+'</div>'+
    '<div class="l2-main-grid">'+details(data,rot)+transitions(rot)+'</div>';
 }else if(state.l2Tab==='forecast'){
  const forecastArgs=state.l2AsOf?'?asof='+encodeURIComponent(state.l2AsOf):'';
  const forecast=await settle('/api/v1/l2/styles/forecast'+forecastArgs);
  body=forecastResearch(forecast);
 }else if(state.l2Tab==='evidence'){
  body='<div class="l2-main-grid">'+quality(data)+details(data,rot)+'</div>'+
    card('计算口径与验证边界','<div class="l2-protocol">'+
    '<p><b>相对收益</b>：风格组合收益相对于对应 ETF 基准的复合收益；5 / 20 / 60 为交易日，不是自然日。</p>'+
    '<p><b>加速度</b>：最近 5 个交易日相对收益减去前 5 个交易日相对收益。</p>'+
    '<p><b>四象限</b>：20 日相对收益正负 × 5 日相对收益加速度正负；零值及缺数据时为 UNKNOWN。</p>'+
    '<p><b>数据限制</b>：Yahoo 拆股调整收盘价为当前版本价格收益代理，不是分红再投总收益，也不是交易时点可验证 PIT 历史。</p>'+
    '</div>','研究口径 v1 · 不构成投资建议');
 }else if(state.l2Tab==='french'){
  const factors=await settle('/api/v1/styles?mode=observation');
  body='<div class="l2-main-grid">'+french(factors)+quality(data)+'</div>';
 }else{
  body=card('风格变化概览 · 各自基准',
    overviewMatrix(items,rotationRows),
    '20D / 5D / 60D 为已发生相对收益；5D 边际变化 = 最近 5D 相对收益 - 前 5D。')+
   '<div class="l2-research-grid">'+
    '<div class="l2-research-left">'+card('风格列表 · 20D 排名',styleRail(items,data.series),'排名不是推荐顺序')+'</div>'+
    '<div class="l2-research-center">'+
      card('60D 风格演化 · 20D 相对收益',multiStyleEvolution(data.series,state.l2Style),'同一坐标观察七类风格，避免只看单一风格')+
      '<div class="l2-research-lower">'+
       card('相对位置 × 边际变化',quadrant(rotationRows,data.series),'选中风格显示最近 10 个交易日轨迹')+
       card('相对排名变化',rankChanges(data.series),'关注相对位置如何迁移，而不是只看当前第一名')+
      '</div>'+
    '</div>'+
    '<div class="l2-research-right">'+diagnosticPanel(data,rot)+'</div>'+
   '</div>';

 }
 return {title:'L2 · 风格轮动',html:'<div class="l2-page">'+header+controls+tabs+summary+disclaimer+body+'</div>',
  mount(){
    document.querySelectorAll('[data-l2-tab]').forEach(el=>el.addEventListener('click',()=>{
      state.l2Tab=el.dataset.l2Tab;show('style');
    }));
    document.querySelectorAll('[data-l2-style]').forEach(el=>el.addEventListener('click',()=>{
      state.l2Style=el.dataset.l2Style;show('style');
    }));
    document.getElementById('l2-asof')?.addEventListener('change',ev=>{
      state.l2AsOf=String(ev.target.value||'');show('style');
    });
    document.getElementById('l2-current')?.addEventListener('click',()=>{
      state.l2AsOf='';show('style');
    });
  }};
};
})();