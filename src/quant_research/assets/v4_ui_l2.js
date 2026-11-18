/* QDR L2 P3: read-only seven-style observation cockpit.
   One snapshot request for P1 observations and P2 rotation, no model claims. */
(() => {
'use strict';
const V=window.V4;
if(!V)throw Error('QDR L2 requires V4 core');
const {pages,state,e,n,pct,signed,date,short,badge,heading,card,empty,note,table,settle,show}=V;
const STYLE_LABELS={
 size:'规模',value:'价值',growth:'成长',momentum:'动量',
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
state.l2Style=state.l2Style||'size';
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
const point=(row,rangeX,rangeY)=>{
 const x=number(row.acceleration_relative_return_5d);
 const y=number(row.strength_relative_return_20d);
 if(x===null||y===null)return '';
 const cx=Math.max(30,Math.min(530,280+(x/rangeX)*245)).toFixed(1);
 const cy=Math.max(28,Math.min(282,155-(y/rangeY)*120)).toFixed(1);
 const selected=row.style_id===state.l2Style;
 return '<g class="'+(selected?'l2-selected-point':'')+'"><circle cx="'+cx+'" cy="'+cy+'" r="'+(selected?'10':'7')+'" class="l2-plot-point"/><text x="'+(Number(cx)+12)+'" y="'+(Number(cy)-8)+'" class="l2-point-label">'+e(itemName(row.style_id))+'</text><title>'+e(itemName(row.style_id)+' · 20D '+percent(y)+' · 加速度 '+percent(x))+'</title></g>';
};
function quadrant(rows){
 const valid=rows.filter(x=>x.rotation_state!=='UNKNOWN'&&finite(x.strength_relative_return_20d)&&finite(x.acceleration_relative_return_5d));
 if(!valid.length)return empty('轮动位置无法绘制','需要 20 日相对收益、5 日相对加速度及来源时间证明。');
 const maxX=Math.max(0.0001,...valid.map(x=>Math.abs(Number(x.acceleration_relative_return_5d))));
 const maxY=Math.max(0.0001,...valid.map(x=>Math.abs(Number(x.strength_relative_return_20d))));
 return '<div class="l2-plot-scroll"><svg viewBox="0 0 560 320" class="l2-plot" role="img" aria-label="七类ETF风格：横轴五日相对加速度，纵轴二十日相对收益，零点为四象限原点">'+
 '<rect x="0" y="0" width="280" height="155" class="l2-q-neutral"/><rect x="280" y="0" width="280" height="155" class="l2-q-good"/>'+
 '<rect x="0" y="155" width="280" height="155" class="l2-q-low"/><rect x="280" y="155" width="280" height="155" class="l2-q-warn"/>'+
 '<line x1="280" y1="0" x2="280" y2="310" class="l2-axis"/>'+
 '<line x1="0" y1="155" x2="560" y2="155" class="l2-axis"/>'+
 '<text x="14" y="18" class="l2-quadrant-label">强势减速</text><text x="454" y="18" class="l2-quadrant-label">强势加速</text>'+
 '<text x="14" y="292" class="l2-quadrant-label">弱势恶化</text><text x="454" y="292" class="l2-quadrant-label">弱势改善</text>'+
 '<text x="4" y="150" class="l2-axis-label">0</text><text x="284" y="310" class="l2-axis-label">0</text>'+
 valid.map(x=>point(x,maxX,maxY)).join('')+'</svg></div>'+
 '<div class="l2-chart-foot"><span>↑ 20 日相对收益</span><span>→ 5 日相对加速度</span><span>归一化比例坐标 · 两轴独立缩放 · 非交易信号</span></div>';
}
function historyGraph(series,style){
 const rows=(Array.isArray(series)?series:[]).filter(x=>x.style_id===style&&x.date)
   .sort((a,b)=>String(a.date).localeCompare(String(b.date)));
 const values=rows.map(x=>number(x.relative_return_20d)),good=values.filter(x=>x!==null);
 if(good.length<2)return empty('历史曲线缺少足够观测','不会插值、补零或跨缺口连接。');
 const lo=Math.min(0,...good),hi=Math.max(0,...good),span=Math.max(1e-8,hi-lo);
 let path='',drawing=false;
 rows.forEach((row,i)=>{
  const val=values[i];
  if(val===null){drawing=false;return;}
  const px=14+532*i/Math.max(1,rows.length-1);
  const py=170-145*(val-lo)/span;
  path+=(drawing?'L':'M')+px.toFixed(1)+' '+py.toFixed(1)+' ';
  drawing=true;
 });
 const zeroY=(170-145*(0-lo)/span).toFixed(1);
 return '<svg viewBox="0 0 560 185" class="l2-trend" role="img" aria-label="真实20交易日ETF相对收益历史，缺失时断线">'+
 '<line x1="14" y1="'+zeroY+'" x2="546" y2="'+zeroY+'" class="l2-zero"/>'+
 '<path d="'+path+'" fill="none" class="l2-trend-line" stroke-width="2.5" stroke-linejoin="round" />'+
 '</svg><div class="l2-chart-foot"><span>'+date(rows[0].date)+'—'+date(rows[rows.length-1].date)+'</span><span>20D 相对收益 · 无补值</span></div>';
}
function tableStyles(items,rotation){
 const s=new Map(rotation.map(x=>[x.style_id,x]));
 const rows=items.filter(x=>STYLE_KEYS.includes(x.style_id))
  .slice().sort((a,b)=>{
   const av=number(a.relative_return_20d),bv=number(b.relative_return_20d);
   return av===null&&bv===null?0:av===null?1:bv===null?-1:bv-av;
  }).map(x=>{
   const r=s.get(x.style_id)||{};
   return ['<button type="button" class="l2-style-select'+(state.l2Style===x.style_id?' current':'')+'" data-l2-style="'+e(x.style_id)+'">'+e(itemName(x.style_id))+'</button>',
     figure(x.relative_return_5d),figure(x.relative_return_20d),figure(x.relative_return_60d),
     figure(x.relative_acceleration_5d),htmlStatus(r.rotation_state),e(x.missing_reason||r.block_reason||'—')];
  });
 return table(['ETF 风格','5D 相对收益','20D 相对收益','60D 相对收益','5D 加速度','轮动状态','缺失原因'],rows);
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
 const header=heading('经典因子与风格轮动','L2 · 七类 ETF 风格相对收益、转折与历史证据。French 因子独立对照，不把表现描述为预测。');
 const controls='<div class="l2-controls"><label for="l2-asof">研究日期</label><input type="date" id="l2-asof" value="'+e(state.l2AsOf)+'" aria-label="L2 研究日期，留空表示最新完整交易日"/>'+
 '<button type="button" id="l2-current" class="btn smallbtn">返回最新</button>'+
 '<span>当前观察：'+resolvedDay+'</span><span>'+badge(data?.status|| (request?.pending?'加载中':'BLOCKED'),
 data?.status==='OBSERVATION_ONLY'?'blue':'amber')+'</span></div>';
 const tabs='<div class="l2-tabs" role="group" aria-label="L2 研究视图">'+[
 linkTab('overview','风格总览'),linkTab('rotation','轮动与转折'),
 linkTab('evidence','计算证据'),linkTab('french','French 因子')].join('')+'</div>';
 const summary=strip([
 ['20D 相对强势',leaders.length?e(itemName(leaders[0].style_id)):'—',leaders.length?'已发生的相对收益领先':'数据不可用'],
 ['弱势改善',rot?n(improving,0):'—','七类风格中的有效状态'],
 ['可判定状态',rot?n(known.length,0)+' / 7':'—','缺口或中性边界不推断'],
 ['未来 H1 / H3 / H5','尚未验证','不得展示虚构模型概率']
 ]);
 const disclaimer='<div class="l2-disclaimer">当前产品资格：<b>OBSERVATION_ONLY</b> · ETF 当前版本历史观察不等于独立 PIT 研究；不生成交易建议或概率。</div>';
 let body='';
 if(!data){
  body=problem(request,'L2 七风格观测')+
   card('领先性研究资格',empty('没有已核验的预测','请先完成真实历史标签、时间分割和样本外模型验证。'));
 }else if(state.l2Tab==='rotation'){
  body='<div class="l2-main-grid">'+card('轮动四象限 · 七类风格',quadrant(rotationRows),'X：5D 加速度 · Y：20D 相对收益')+
    card('各风格状态',rotationRows.length?table(['风格','状态','持续交易日','前一状态'],rotationRows.map(x=>[
    '<button class="l2-style-select" data-l2-style="'+e(x.style_id)+'">'+e(itemName(x.style_id))+'</button>',
    htmlStatus(x.rotation_state),figure(x.consecutive_sessions,'integer'),htmlStatus(x.previous_state)])):
    empty('轮动状态不可用','请检查源数据窗口和截止时间。'))+'</div>'+
    '<div class="l2-main-grid">'+details(data,rot)+transitions(rot)+'</div>';
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
  body='<div class="l2-main-grid">'+card('七风格轮动地图',quadrant(rotationRows),'已发生表现 · 不是未来概率')+
    card('聚焦风格 · 20D 相对趋势',historyGraph(data.series,state.l2Style),'选择下表风格查看历史')+'</div>'+
    card('七类 ETF 风格 · 当前强弱',items.length?tableStyles(items,rotationRows):problem(request,'风格强弱'),'点击风格切换右侧详情 · 缺失值显示 —')+
    '<div class="l2-main-grid">'+details(data,rot)+
    card('未来 H1 / H3 / H5 领先预测',empty('预测模型尚未通过资格验收',
    '待建立独立验证的 T+1 开盘到 T+H 收盘相对收益标签、Walk-forward、样本外指标和时间证明。')+
    '<div class="l2-future"><span>H1 —</span><span>H3 —</span><span>H5 —</span></div>','没有生成概率、收益目标或交易指令')+'</div>';
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