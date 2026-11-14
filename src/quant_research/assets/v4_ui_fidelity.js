/* QDR six-workspace fidelity layer: preserves live API actions and approved page hierarchy.
 * Loaded after the data-connected pages. No demonstration probabilities, trades, or returns. */
(() => {
'use strict';
const V=window.V4;
if(!V)throw Error('V4 core must load before the approved workspace');
const {pages,state,e,n,pct,signed,date,short,badge,button,link,card,table,empty,note,row,settle,svgLine,progress,show}=V;
const saved={};for(const name of ['overview','market','style','lab','screen','risk'])saved[name]=pages[name];
const view={tabs:{screen:1},strategy:null,symbol:null,labLeft:null,labRight:null,marketObs:null};
const specs={
 market:['市场预测','状态识别','风险驱动','预测验证'],
 style:['风格总览','经典因子收益','ETF 代理观察','轮动与历史','领先性验证'],
 lab:['因子实验室','因子有效性','因子相关性','版本与实验记录'],
 screen:['因子组合配置','候选股票与解释','策略回测','样本外实验'],
 risk:['持仓总览','风险模型','实时预警','仓位与退出规则','交易复盘']
};
function layout(a,b,cls=''){return '<div class="v4-workspace-pair '+cls+'">'+a+b+'</div>';}
function stack(...items){return '<div class="v4-workspace-stack">'+items.filter(Boolean).join('')+'</div>';}
function aside(left,right){return '<div class="v4-workspace-aside">'+left+'<div class="v4-workspace-main">'+right+'</div></div>';}
function actual(v){return v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));}
function numeric(v,precision=4){return actual(v)?n(v,precision):'—';}
function titleNumber(label,value){return '<div class="v4-mini-metric"><div class="muted">'+e(label)+'</div><b>'+value+'</b></div>';}
function metricCard(label,value,detail,tone='blue'){
 return '<div class="kpi v4-metric-card"><div class="klabel">'+e(label)+
   '</div><div class="kval '+e(tone)+'">'+value+'</div><div class="knote">'+e(detail)+'</div></div>';
}
function metricStrip(items,cls=''){
 return '<div class="grid kpis v4-metric-strip '+cls+'">'+items.join('')+'</div>';
}
function box(name,body,sub=''){return card(name,body,sub);}
function currentQuoteStrip(systemResult,freshResult){
 const system=systemResult?.ok?systemResult.data:null;
 const dataset=system?.dataset, fresh=freshResult?.ok?freshResult.data?.modules?.market_observation:null;
 if(!dataset||dataset.source!=='ALPACA'||dataset.feed!=='sip'||!dataset.adjustment_bases?.includes('raw'))
  return '<div class="v4-current-quotes v4-current-unavailable"><b>最新行情观察不可用</b>　请在数据中心检查 Alpaca SIP 原价及来源回执。</div>';
 const day=String(dataset.asof_date_et||'');
 const prices=Array.isArray(system.prices)?system.prices:[];
 const cells=['SPY','IWM','IWD','IWF','MTUM'].map(symbol=>{
  const p=prices.find(x=>x.symbol===symbol&&String(x.date).slice(0,10)===day&&x.basis==='raw');
  return '<div><span>'+e(symbol)+'</span><b>'+(p&&actual(p.close)?'$'+n(p.close,2):'—')+'</b></div>';
 }).join('');
 const sameSourceDate=day!==''&&String(fresh?.source_data_asof||'')===day;
 const known=sameSourceDate?fresh?.known_by_decision_cutoff:null;
 const qualification=known===false?'采集时间晚于当日决策截止，仅供当前观察':known===true?'数据到达时间已记录':'到达时间待核验';
 return '<section class="v4-current-quotes"><div class="v4-current-heading"><b>最新已收盘行情观察</b><span>ALPACA SIP 原价 · '+date(day)+' · '+e(sameSourceDate?(fresh?.freshness_status||'未核验'):'日期待核验')+'</span></div>'+
  '<div class="v4-current-quote-grid">'+cells+'</div><div class="v4-current-note">'+e(qualification)+'；不是最新预测或交易信号。<a href="/data">查看来源与数据状态</a></div></section>';
}
function emptyTable(columns,title,reason){
 return '<div class="v4-table-scroll"><table class="table"><thead><tr>'+columns.map(x=>'<th>'+e(x)+'</th>').join('')+
  '</tr></thead><tbody><tr><td colspan="'+columns.length+'" class="v4-table-empty">'+empty(title,reason)+'</td></tr></tbody></table></div>';
}
function emptyChart(title,reason){
 return '<div class="v4-chart-empty" role="img" aria-label="'+e(title)+'"><div><b>'+e(title)+'</b><span>'+e(reason)+'</span></div></div>';
}
function emptyStats(labels){return '<div class="grid cols'+labels.length+'">'+labels.map(x=>
 '<div class="mini-stat"><div class="muted">'+e(x)+'</div><div class="val">—</div></div>').join('')+'</div>';}
function realMultiLine(records,series,description='五日相对收益'){
 const rows=records.filter(x=>x.date).sort((a,b)=>String(a.date).localeCompare(String(b.date)));
 const available=series.filter(s=>rows.filter(x=>actual(x[s.key])).length>=2);
 const values=rows.flatMap(x=>available.map(s=>x[s.key]).filter(actual).map(Number));
 if(rows.length<2||values.length<2)return emptyChart('暂无足够历史观察','至少需要两个可核验观察。');
 const low=Math.min(...values),span=Math.max(1e-10,Math.max(...values)-low),W=740,H=175,pad=20;
 const lines=available.map(s=>{let previous=-2,points=0,path='';
  rows.forEach((x,i)=>{if(!actual(x[s.key]))return;const px=pad+(W-2*pad)*i/(rows.length-1);
   const py=H-pad-(H-2*pad)*(Number(x[s.key])-low)/span;
   path+=(i===previous+1?'L':'M')+px.toFixed(1)+' '+py.toFixed(1)+' ';previous=i;points++;});
  return points>1?'<path d="'+path+'" fill="none" stroke="'+s.color+'" stroke-width="2.5"/>':'';
 }).join('');
 return '<svg class="v4-spark" style="height:175px" viewBox="0 0 740 175" preserveAspectRatio="none" role="img" aria-label="真实风格代理历史观察">'+
  [0,.25,.5,.75,1].map(t=>'<line x1="20" x2="720" y1="'+(20+135*t)+'" y2="'+(20+135*t)+'" stroke="#30445f"/>').join('')+lines+'</svg>'+
  '<div class="legend">'+available.map(s=>'<span><i class="lg-dot" style="background:'+s.color+'"></i>'+e(s.label)+'</span>').join('')+'</div>'+
  note(description+' · '+date(rows[0].date)+' 至 '+date(rows.at(-1).date)+'；缺失点断线。');
}
function compactFactorDefinition(markup){
 const host=document.createElement('div');host.innerHTML=markup;
 const cardNode=host.firstElementChild;if(!cardNode)return markup;
 cardNode.classList.add('v4-factor-definition');
 const assumption=cardNode.querySelector('#v4-factor-hypothesis')?.closest('.v4-field');
 if(assumption){
  const details=document.createElement('details');details.className='v4-hypothesis-details';
  details.innerHTML='<summary>研究假设 · 展开编辑</summary>';
  assumption.replaceWith(details);details.appendChild(assumption);
 }
 return cardNode.outerHTML;
}
function factorLibrary(markup){
 const host=document.createElement('div');host.innerHTML=markup;
 const title=host.querySelector('.ctitle');
 if(title)title.insertAdjacentHTML('afterend','<label for="v4-library-search" class="v4-library-label">搜索已显示的因子</label><input id="v4-library-search" type="search" placeholder="按名称或类型筛选">');
 return host.innerHTML;
}
function collapsedCard(markup,label){
 return '<details class="v4-collapsed-card"><summary>'+e(label)+'</summary>'+markup+'</details>';
}
function unwrap(markup){
 const doc=document.createElement('div');
 doc.innerHTML=markup;
 const heading=doc.querySelector('.heading');
 const hero=doc.querySelector('.grid.cols4');
 const toolbar=doc.querySelector(':scope > .v4-toolbar');
 const steps=doc.querySelector('.v4-step')?.closest('.v4-actions');
 const items=[...doc.querySelectorAll('section.card.pad')].map(element=>({
  title:element.querySelector('.ctitle')?.textContent||'',
  markup:element.outerHTML,used:false
 }));
 function take(prefix){
  const found=items.find(item=>!item.used&&item.title.includes(prefix));
  if(!found)return box(prefix,empty('数据模块尚未就绪','当前没有可显示的合格研究记录。'));
  found.used=true;return found.markup;
 }
 function remaining(){return items.filter(x=>!x.used).map(x=>x.markup).join('');}
 return {heading:heading?.outerHTML||'',hero:hero?.outerHTML||'',
   toolbar:toolbar?.outerHTML||'',steps:steps?.outerHTML||'',take,remaining};
}
function panelHtml(page,head,content){
 const names=specs[page],selected=Math.min(names.length-1,Math.max(0,view.tabs[page]||0));
 let out=head+'<div class="v4-subtabs" role="tablist" aria-label="'+e(page)+' 研究子页面">';
 names.forEach((name,i)=>out+='<button type="button" role="tab" class="v4-subtab'+(i===selected?' active':'')+
  '" data-v4-tab="'+i+'" id="v4-tab-'+page+'-'+i+'" aria-selected="'+(i===selected)+
  '" aria-controls="v4-panel-'+page+'-'+i+'">'+e(name)+'</button>');
 out+='</div>';
 names.forEach((name,i)=>out+='<section class="v4-tabpanel" role="tabpanel" tabindex="0"'+
  ' id="v4-panel-'+page+'-'+i+'" aria-labelledby="v4-tab-'+page+'-'+i+'"'+
  (i===selected?'':' hidden')+'>'+content[i]+'</section>');
 return out;
}
function bindTabs(page){
 const tabs=[...document.querySelectorAll('[data-v4-tab]')];
 const activate=(idx)=>{
  view.tabs[page]=idx;
  tabs.forEach((el,i)=>{
   const selected=i===idx;el.classList.toggle('active',selected);
   el.setAttribute('aria-selected',String(selected));
   const panel=document.getElementById('v4-panel-'+page+'-'+i);
   if(panel)panel.hidden=!selected;
  });
 };
 tabs.forEach((el,i)=>{
  el.addEventListener('click',()=>activate(i));
  el.addEventListener('keydown',ev=>{
   if(!['ArrowRight','ArrowLeft','Home','End'].includes(ev.key))return;
   ev.preventDefault();
   const index=ev.key==='Home'?0:ev.key==='End'?tabs.length-1:
     (i+(ev.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
   activate(index);tabs[index].focus();
  });
 });
}
function studyNote(text){return note(text);}
function asList(items,emptyTitle,body){
 return items.length?items.join(''):empty(emptyTitle,body);
}


function realQuintileChart(items){
 const good=items.filter(x=>actual(x.value));
 if(good.length<2)return '';
 const width=540,height=200,mid=94,scale=70/Math.max(1e-10,...good.map(x=>Math.abs(Number(x.value))));
 const parts=['<svg class="v4-factor-chart" viewBox="0 0 '+width+' '+height+
   '" role="img" aria-label="实际历史因子分组未来收益图，仅用于历史研究">'+
   '<line x1="18" x2="'+(width-18)+'" y1="'+mid+'" y2="'+mid+'" stroke="#546a84" stroke-width="1.2"/>'];
 for(const item of items){
  const index=item.bucket-1,x=40+index*103,v=actual(item.value)?Number(item.value):null;
  const bh=v===null?0:Math.abs(v)*scale,y=v===null?mid:(v>=0?mid-bh:mid);
  if(v!==null)parts.push('<rect x="'+x+'" y="'+y.toFixed(2)+'" width="62" height="'+
   bh.toFixed(2)+'" rx="3" fill="'+(v>=0?'#50c6af':'#e58793')+'"/>');
  parts.push('<text x="'+(x+31)+'" y="180" fill="#a8bad2" font-size="12" text-anchor="middle">Q'+item.bucket+'</text>');
  if(v!==null)parts.push('<text x="'+(x+31)+'" y="'+(v>=0?Math.max(15,y-8):Math.min(167,y+bh+15)).toFixed(2)+
    '" fill="#e0edfb" font-size="11" text-anchor="middle">'+(v*100).toFixed(2)+'%</text>');
 }
 return parts.join('')+'</svg>';
}

function calibrationHistory(summary){
 const buckets=(summary?.calibration||[]).filter(x=>
  actual(x.mean_probability)&&actual(x.observed_up_rate)&&Number(x.count)>=5)
  .sort((a,b)=>Number(a.bin)-Number(b.bin));
 if(!buckets.length)return empty('无足够的历史概率分箱',
  '需至少每桶 5 次经核对的已成熟结果才能画出实际频率。');
 return '<div class="v4-calibration-rows">'+buckets.map(x=>{
  const estimate=Math.max(0,Math.min(100,Number(x.mean_probability)*100));
  const observed=Math.max(0,Math.min(100,Number(x.observed_up_rate)*100));
  return '<div class="v4-calibration-row"><div><b>'+Math.round(Number(x.bin)*20)+'%–'+
    Math.round((Number(x.bin)+1)*20)+'%</b><small>n='+n(x.count,0)+'</small></div>'+
    '<div class="v4-calibration-bar"><div style="width:'+estimate.toFixed(2)+'%"></div></div>'+
    '<div class="v4-calibration-bar observed"><div style="width:'+observed.toFixed(2)+'%"></div></div>'+
    '<span>'+estimate.toFixed(1)+'% / '+observed.toFixed(1)+'%</span></div>';
 }).join('')+'</div>'+note('每组蓝色为预测概率，青色为实际发生率。历史探索结果不得称作当前已校准预测。');
}
function historicalTransitions(history){
 const allowed=['UP_LOW_VOL','UP_HIGH_VOL','DOWN_LOW_VOL','DOWN_HIGH_VOL'];
 const labels={UP_LOW_VOL:'上涨低波',UP_HIGH_VOL:'上涨高波',DOWN_LOW_VOL:'下跌低波',DOWN_HIGH_VOL:'下跌高波'};
 const ordered=(history||[]).filter(x=>allowed.includes(x.market_state)&&x.date)
   .sort((a,b)=>String(a.date).localeCompare(String(b.date)));
 if(ordered.length<40)return empty('不足以推导历史五日状态转移',
   '至少需要 40 条有明确市场状态的真实历史观察。');
 const tally={};for(const from of allowed)tally[from]=[0,0,0,0];
 for(let i=0;i+5<ordered.length;i++){
  const a=ordered[i],b=ordered[i+5];
  const elapsed=(Date.parse(b.date)-Date.parse(a.date))/86400000;
  if(!(elapsed>=5&&elapsed<=12))continue;
  tally[a.market_state][allowed.indexOf(b.market_state)]++;
 }
 if(Object.values(tally).reduce((sum,counts)=>sum+counts.reduce((a,b)=>a+b,0),0)<20)
  return empty('有效转移样本偏少','仅计算实际相隔五个观察交易日的样本，不对缺口补值。');
 return '<div class="v4-transition-table"><table class="table"><thead><tr><th>历史当前状态 ↓</th>'+
  allowed.map(x=>'<th title="'+e(x)+'">'+e(labels[x])+'</th>').join('')+'</tr></thead><tbody>'+
  allowed.map(from=>{
   const total=tally[from].reduce((a,b)=>a+b,0);
   return '<tr><th title="'+e(from)+'">'+e(labels[from])+'<small>n='+total+'</small></th>'+tally[from].map(v=>{
     const ratio=total>=5?v/total:null;
     return '<td'+(ratio===null?'':' style="background:rgba(57,192,164,'+(0.12+0.58*ratio).toFixed(3)+')"')+'>'+
       (ratio===null?'—':(ratio*100).toFixed(1)+'%')+'</td>';
   }).join('')+'</tr>';
  }).join('')+'</tbody></table></div>'+note('这是历史经验转移频率，分母为该起始状态有效样本；不是经验证的未来状态转移概率。');
}

async function overview(original){
 const a=unwrap(original.html);
 const [historical,system,fresh]=await Promise.all([settle('/api/v1/market/research?horizon=3'),settle('/api/status'),settle('/api/v1/v4/freshness')]);
 const history=historical.ok&&Array.isArray(historical.data.state_history)?
   historical.data.state_history.filter(x=>actual(x.market_return_20)):[];
 const chart=history.length>=2?
   '<div class="v4-overview-trend"><div class="v4-chart-caption">SPY 20日历史收益趋势 · '+date(history[0].date)+' 至 '+date(history.at(-1).date)+'</div>'+
    svgLine(history.map(x=>x.market_return_20),'#50cab1',192)+
    note('真实历史观察趋势，不属于最新 H1/H3/H5 前向概率预测。')+'</div>':'';
 const baseMarket=a.take('市场状态预测');
 const market=chart?baseMarket.replace(/<\/section>\s*$/,chart+'</section>'):baseMarket;
 const style=a.take('经典因子');
 let alpha=a.take('Alpha 研究');
 let risk=a.take('组合持仓');
 const alphaHost=document.createElement('div');alphaHost.innerHTML=alpha;
 const alphaEmpty=alphaHost.querySelector('.v4-empty');
 if(alphaEmpty)alphaEmpty.outerHTML=emptyTable(['股票','选股策略','因子排名','H3 预测','交易状态'],'尚无前向研究记录','需要真实冻结预测和合格研究计划。');
 alpha=alphaHost.innerHTML;
 const riskHost=document.createElement('div');riskHost.innerHTML=risk;
 const riskEmpty=riskHost.querySelector('.v4-empty');
 if(riskEmpty)riskEmpty.outerHTML=emptyStats(['组合仓位','行业最大暴露','当前风险提醒'])+note('缺少已对账模拟账本，风险状态不可确认。');
 risk=riskHost.innerHTML;
 const score=a.take('前向 H3');
 const daily=a.take('每日四层');
 const evidence=a.take('系统数据资格');
 const flow=['数据更新','因子计算','四层条件预测','候选与风险计划','冻结及前向复盘'];
 const steps='<div class="v4-workflow-steps">'+flow.map((name,i)=>
  '<div class="v4-workflow-step"><span>0'+(i+1)+'</span><b>'+e(name)+'</b></div>').join('')+'</div>';
 const headingHost=document.createElement('div');headingHost.innerHTML=a.heading;
 const actions=headingHost.querySelector('.h-actions');
 if(actions)actions.insertAdjacentHTML('beforeend','<button type="button" class="btn primary" id="v4-run-observation">运行已有日终观察</button>');
 const wrap=headingHost.innerHTML+currentQuoteStrip(system,fresh)+a.hero+
  layout(market,style)+layout(alpha,risk)+
  box('前向研究闭环 · 日终五阶段',steps, '进展以真实研究任务为准')+
  '<details class="v4-workspace-details"><summary>预测验证、归档状态与数据资格</summary>'+
  stack(score,layout(daily,evidence))+'</details>'+a.remaining();
 return {html:wrap,mount(){
  document.getElementById('v4-run-observation')?.addEventListener('click',async()=>{
   const btn=document.getElementById('v4-run-observation');
   if(!btn||btn.disabled)return;
   btn.disabled=true;btn.textContent='提交日终观察中…';
   try{
    const result=await V.api('/api/run/daily-observation',{});
    V.toast('已提交日终观察：'+String(result.status||'RUNNING')+'。此任务不等于四层生产预测。');
   }catch(error){
    V.toast('日终观察未提交：'+String(error.message||'数据资格不满足'));
   }finally{
    btn.disabled=false;btn.textContent='运行已有日终观察';
   }
  });
 }};
}
async function market(original){
 const a=unwrap(original.html);
 const selectedH=Number(state.marketHorizon||3);
 const [r,system,fresh]=await Promise.all([settle('/api/v1/market/research?horizon='+selectedH),settle('/api/status'),settle('/api/v1/v4/freshness')]);
 const data=r.ok?r.data:null,states=Array.isArray(data?.states)?data.states:[];
 const horizonResults=await Promise.all([1,3,5].map(h=>h===selectedH?Promise.resolve(r):
   settle('/api/v1/market/research?horizon='+h)));
 const horizonData=new Map([1,3,5].map((h,i)=>[h,horizonResults[i].ok?horizonResults[i].data:null]));
 const current=states[0]||null;
 const history=Array.isArray(data?.state_history)?data.state_history:[];
 const h3Prediction=horizonData.get(3)?.predictions?.[0]||null;
 const predictionFor=(h)=>horizonData.get(h)?.predictions?.[0]||null;
 const probabilityFor=(prediction)=>prediction?.p_up??prediction?.probability_up??null;
 const horizonMetrics=[1,3,5].map((h,i)=>{
  const prediction=predictionFor(h),probability=probabilityFor(prediction);
  return metricCard('历史 H'+h+' 上涨概率',actual(probability)?pct(probability):'—',
    prediction?.date?'决策日 '+date(prediction.date)+' · 回溯研究':'该期限暂无可核验预测',
    ['green','green','green'][i]);
 });
 const downsideProbability=h3Prediction?.p_downside??h3Prediction?.downside_probability??null;
 horizonMetrics.push(metricCard('历史 H3 显著下跌概率',actual(downsideProbability)?pct(downsideProbability):'—',
   (h3Prediction?.date?'决策日 '+date(h3Prediction.date)+' · ':'')+'回溯样本 · 与上涨概率非互补','amber'));
 horizonMetrics.push(metricCard('历史市场状态',current?.market_state?e(current.market_state):'—',
   current?.date?'观察日 '+date(current.date)+' · 非前向状态':'缺少可核验状态观测','purple'));
 const summary=data?.summary||{};
 const factors=[
  ['市场 1 日收益','market_return_1','收益'],
  ['市场 5 日收益','market_return_5','收益'],
  ['市场 20 日收益','market_return_20','收益'],
  ['市场 5 日波动','market_vol_5','波动'],
  ['市场 20 日波动','market_vol_20','波动'],
  ['5D / 20D 波动比','market_vol_ratio','比率'],
  ['RSP / SPY 广度代理','market_concentration_5','收益'],
  ['HYG / LQD 信用代理','market_credit_5','收益'],
  ['行业 ETF 离散度','market_sector_dispersion','波动'],
  ['行业 ETF 相关性','market_sector_mean_correlation','系数'],
  ['行业 ETF 广度代理','market_breadth_etf_proxy','比例']
 ];
 const featureRows=factors.map(([label,key,type])=>[
  e(label),current&&actual(current[key])?(type==='收益'||type==='波动'||type==='比例'?pct(current[key]):numeric(current[key],3)):'—',
  '—',current&&actual(current[key])?badge('实测','blue'):badge('缺失','amber')
 ]);
 const why=box('领先特征 · 当前值与贡献',
   table(['市场输入','实际观察值','模型贡献','数据状态'],featureRows)+
   studyNote('模型系数与标准化参数未独立归档，因此贡献不填猜测值；此表为历史研究的真实观察而非实时交易信号。'),
   '实际特征 · 贡献待模型参数归档');
 const distribution=box('未来收益分布 · H1 / H3 / H5',
   empty('尚未建立可审核的收益预测分布',
    '分布曲线必须来自冻结的完整条件预测样本；单个上涨概率不能推断为收益密度曲线。')+
    '<div class="v4-workspace-actions"><button type="button" data-v4-switch-market="1" class="btn">H1</button>'+
    '<button type="button" data-v4-switch-market="3" class="btn">H3</button>'+
    '<button type="button" data-v4-switch-market="5" class="btn">H5</button></div>',
    '期限切换保持原始历史研究口径');
 const transition=box('未来状态转移 · 历史经验矩阵',
   historicalTransitions(history),
   '按 5 个观察交易日 · 非前向概率');
 const regime=box('市场状态与历史演变',
    current?((history.filter(x=>actual(x.market_return_20)).length>1?
       svgLine(history.filter(x=>actual(x.market_return_20)).map(x=>x.market_return_20),
       '#57d5b8',190):'')+
     '<div class="v4-regime-stats">'+row('历史市场状态',e(current.market_state||'未知'))+
     row('研究观测日期',date(current.date||data?.manifest?.asof_date_et))+
     row('输入数据可用时间',e(current.state_available_at||'—'))+
     row('市场 20 日收益',actual(current.market_return_20)?signed(current.market_return_20):'—')+
     row('市场 20 日波动',actual(current.market_vol_20)?pct(current.market_vol_20):'—')+'</div>'):
     empty('尚无可核验的市场状态','需要已完成的历史状态观测记录。'),
    '真实历史状态');
 const metrics=(summary.direction||[])[0]||null;
 const downside=(summary.downside||[])[0]||null;
 const validation=box('历史样本外概率可靠性 · 分箱与基准',
   (metrics?'<div class="v4-workspace-pair">'+
     titleNumber('上涨 Brier',numeric(metrics.brier))+
     titleNumber('基础概率 Brier',numeric(metrics.naive_brier))+'</div>'+
     row('上涨 Log Loss',numeric(metrics.log_loss))+
     row('基础概率 Log Loss',numeric(metrics.naive_log_loss))+
     row('历史验证日期数',numeric(metrics.dates,0))+
     row('研究结果状态',badge('历史探索 · 不获前向资格','amber')):
     empty('暂无历史预测误差报告','市场研究尚未返回已核验的历史样本外统计。'))+
   calibrationHistory(summary)+
   (downside?row('显著下跌 Brier / 朴素基线',
    numeric(downside.brier)+' / '+numeric(downside.naive_brier)):'')+
   studyNote('这是历史价格代理数据的回顾评估，不构成独立的真实前向预测概率校准证明。'),
   '历史研究对照 · 非正式实盘概率');
 const parameters=box('模型参数与可解释性',
    table(['模型','因子集合','参数来源','实际系数'],[
      ['M0','market_return_5, market_vol_20','训练期 Logistic / Ridge','—'],
      ['M1','已核验的 market_* 因子','训练期 Logistic / Ridge','—']])+
      studyNote('实际 beta、标准化均值/方差、Platt a/b 没有可用的参数归档接口，不输出虚构参数。'));
 const panel=[
   stack(currentQuoteStrip(system,fresh),metricStrip(horizonMetrics,'v4-five-metrics'),layout(regime,transition,'v4-reference-market'),
     '<div class="v4-reference-three">'+why+validation+parameters+'</div>',
     a.toolbar,layout(distribution,a.take('市场环境')),a.take('四层联动')),
   layout(regime,transition,'v4-reference-market'),
   layout(why,a.take('模型可靠性与风险传导')),
   stack(layout(validation,a.take('概率可靠性与模型验证')),
     a.take('历史研究与对照版本'))
 ];
 return {html:panelHtml('market',a.heading,panel),
 mount(){
  for(const x of document.querySelectorAll('[data-v4-switch-market]'))x.addEventListener('click',()=>{
   state.marketHorizon=Number(x.dataset.v4SwitchMarket);show('market');
  });
 }};
}
async function style(original){
 const a=unwrap(original.html);
 const dataResult=await Promise.all([settle('/api/v1/styles?mode=observation'),settle('/api/status'),settle('/api/v1/v4/freshness')]);
 const dat=dataResult[0].ok?dataResult[0].data:null;
 const factors=Array.isArray(dat?.latest)?dat.latest:[];
 const fseries=Array.isArray(dat?.series)?dat.series:[];
 const etf=box('ETF 风格代理 · 最新相对表现',
  emptyChart('最新相对收益暂不可用','独立的最新风格收益计算尚未接入；旧实验曲线不用于当前监控。')+
  emptyTable(['ETF 风格组合','5 日相对收益','20 日相对收益','观察日'],
   '风格代理收益受阻','已核验的最新 SIP 收盘原价显示在上方；跨期收益需要合格的公司行为调整。'),
   '独立观察 · 不等于 Fama–French 多空因子收益');
 const classic=box('经典因子收益 · Fama–French 系列',
  factors.length?table(['因子','经济含义','5日实际收益','20日实际收益','观察状态','Rank IC (H5)'],
   factors.filter(x=>x.factor_name!=='RF').map(x=>[
    e(x.factor_name),e(x.factor_label||'—'),actual(x.sum_5d)?signed(x.sum_5d):'—',
    actual(x.sum_20d)?signed(x.sum_20d):'—',e(x.state||'—'),'—'])):
    empty('尚无真实经典因子数据','需要来源可追踪的因子历史记录。'),
   '经典因子与 ETF 代理分开核验');
 const rotationFactors=['MOM','SMB','RMW','HML'].map(key=>factors.find(x=>String(x.factor_name).toUpperCase()===key)).filter(Boolean);
 const maxReturn=Math.max(1e-12,...rotationFactors.filter(x=>actual(x.sum_5d)).map(x=>Math.abs(Number(x.sum_5d))));
 const rotation=box('风格轮动观察 · 动量与持续性',
   rotationFactors.length?layout(
    '<div><div class="muted">近 5 日因子收益 · 相对幅度</div>'+rotationFactors.map(x=>
      actual(x.sum_5d)?'<div class="barrow"><div class="name">'+e(x.factor_name)+'</div><div class="progress"><div style="width:'+
       (Math.abs(Number(x.sum_5d))/maxReturn*100).toFixed(2)+'%;'+(Number(x.sum_5d)<0?'background:#d98698':'')+
       '"></div></div><div class="pct">'+signed(x.sum_5d)+'</div></div>':
      row(e(x.factor_name),'—')).join('')+'</div>',
    '<div><div class="muted">5 日与 20 日平均收益差</div>'+rotationFactors.map(x=>
      row(e(x.factor_name),actual(x.sum_5d)&&actual(x.sum_20d)?signed(Number(x.sum_5d)/5-Number(x.sum_20d)/20):'—')).join('')+'</div>'):
    empty('暂无可比较的轮动样本','需要同口径经典因子收益。'),
   '仅描述已发生变化 · 不代表领先预测');
 const series=box('风格历史观察 · 已选择因子',
   fseries.length>1?svgLine(fseries.filter(x=>x.factor_name===state.styleFactor&&actual(x.sum_20d))
     .map(x=>x.sum_20d),'#9c9bfa',185):
    empty('尚无足够的风格时间序列','选择有两个以上真实观察值的因子。'),
   '真实历史时点');
 const validation=box('领先性验证 · 样本外增量',
   empty('尚无通过验收的风格领先性结果',
    '必须比较加入风格信息前后的 H1/H3/H5 预测误差，不能将过去涨幅等同于未来收益。'),
   'ETF 相对收益标签 · 时间隔离');
 const panels=[
   stack(layout(classic,etf),layout(rotation,box('从观察到预测 · 研究约束',
     note('跟踪经典因子收益与方向，研究不同周期的变化和持续性。')+
     note('只有在时间外样本中证明增量后，才可用于 Alpha 模型；ETF 代理与 French 因子口径不同。')+
     badge('预测能力待验证','amber')))),
   stack(layout(a.take('经典风格强弱'),a.take('滚动收益')),a.take('风格观察明细')),
   layout(etf,box('代理使用口径',
     studyNote('IWM/SPY 代表小盘相对大型股，IWD/IWF 代表价值相对成长；它们不是 French SMB/HML/RMW/CMA 因子的精确替代。')+
     row('最新相对收益状态',badge('待接入与核验','amber')))),
   layout(rotation,series),
   layout(validation,a.take('风格预测研究边界'))
 ];
 const factorCards=[['动量','MOM'],['小盘','SMB'],['盈利质量','RMW'],['价值','HML']].map(([label,key])=>{
  const item=factors.find(x=>String(x.factor_name).toUpperCase()===key);
  const value=item?.sum_5d;
  return metricCard(label+' '+key,actual(value)?signed(value):'—',
   item?'French 5 日观察 · '+date(dat?.asof_date_et):'缺少该因子观察',
   actual(value)&&Number(value)<0?'red':'green');
 });
 panels[0]=currentQuoteStrip(dataResult[1],dataResult[2])+metricStrip(factorCards)+panels[0];
 return {html:panelHtml('style',a.heading,panels)};
}
async function lab(original){
 const a=unwrap(original.html);
 const res=await settle('/api/v1/factor-lab/library');
 const fac=res.ok?(res.data.factor_versions||[]):[];
 const exp=res.ok?(res.data.experiments||[]):[];
 const completed=exp.filter(x=>x.status==='COMPLETED');
 const selected=completed.find(x=>(x.config?.factor_version_id||x.factor_version_id)===state.factorVersion)||completed[0]||null;
 const detail=selected?await settle('/api/v1/factor-lab/experiments/'+encodeURIComponent(selected.id)):null;
 const report=detail?.ok?detail.data.result:null;
 const rollingIC=Array.isArray(detail?.data?.rolling_ic_h3)?detail.data.rolling_ic_h3:[];
 const validation=Array.isArray(report?.summary)?report.summary.filter(x=>x.partition==='validation'):[];
 const metricRows=validation.map(x=>[
  'H'+e(x.horizon),numeric(x.rank_ic_mean,4),numeric(x.icir_unannualized,3),
  numeric(x.daily_ic_count,0),actual(x.label_pair_coverage)?pct(x.label_pair_coverage):'—',
  actual(x.ic_mean_ci95_low)&&actual(x.ic_mean_ci95_high)?
    numeric(x.ic_mean_ci95_low)+' ～ '+numeric(x.ic_mean_ci95_high):'—'
 ]);
 const analysis=box('因子有效性 · 历史验证期研究指标',
   metricRows.length?table(['持有期','Rank IC','ICIR','有效日期','配对覆盖','区块置信区间'],metricRows):
    empty('尚无可审查的因子有效性报告','完成真实因子实验后展示 Rank IC、ICIR、收益分组和时间外稳定性。')+
   note('仅用于现存版本的历史探索；不是未来 Alpha 盈利能力已被证实。'),
   selected?'已完成实验 '+short(selected.id):'不填造假的 Rank IC');
 const h3=validation.find(x=>Number(x.horizon)===3)||null;
 const quintiles=h3?[1,2,3,4,5].map(i=>({bucket:i,
  value:h3['q'+i+'_mean_forward_price_return']})):[];
 const outcome=box('历史价格代理 · 未来 3 日因子分组收益',
   quintiles.some(x=>actual(x.value))?
    realQuintileChart(quintiles)+table(['因子组','事后价格代理收益'],quintiles.map(x=>[
      'Q'+x.bucket,actual(x.value)?signed(x.value):'—']))+
    row('Q5 − Q1 价格收益差',actual(h3.q5_minus_q1_price_return_spread)?
      signed(h3.q5_minus_q1_price_return_spread):'—')+
    note('当前版本标签是价格代理，不等于可执行收益或真实手续费后收益。'):
    empty('暂无可比较的真实历史分组','Q1–Q5 收益必须来源已完成的因子实验报告，不能生成演示曲线。'));
 const stability=box('滚动 IC 与稳定性',
   (rollingIC.length?realMultiLine(rollingIC,[
     {label:'20 观察日滚动 Rank IC',key:'rolling_ic_20',color:'#57d5b8'},
     {label:'逐日 Rank IC',key:'rank_ic',color:'#bd96f1'}],'历史验证期 Rank IC'):
     emptyChart('滚动 IC 序列未提供','当前实验没有可核验的逐日 IC 文件。'))+
   (metricRows.length?table(['H','IC 5%分位','IC 中位数','IC 95%分位','平均证券数'],
     validation.map(x=>['H'+e(x.horizon),numeric(x.ic_p05),numeric(x.ic_median),
       numeric(x.ic_p95),numeric(x.mean_covered_securities,0)])):
    empty('缺少逐期样本外 IC 统计','至少需要完整的历史日期分组研究报告。')),
   'H3 历史验证期 · 价格代理标签 · 非前向交易');
 const strategyResponse=await settle('/api/v1/strategies');
 const strategies=strategyResponse.ok?(strategyResponse.data.strategies||[]):[];
 const multi=strategies.find(x=>Array.isArray(x.config?.strategy?.factors)&&x.config.strategy.factors.length>=2)||null;
 const composite=multi?await settle('/api/v1/strategies/'+encodeURIComponent(multi.id)+'/composite'):null;
 const correlations=composite?.ok?(composite.data.factor_correlations||[]):[];
 const choice=(id,items,selectedValue)=>'<select id="'+id+'" aria-label="选择比较因子版本">'+
  '<option value="">请选择版本</option>'+items.map(x=>'<option value="'+e(x.id)+'"'+
   (String(x.id)===String(selectedValue)?' selected':'')+'>'+e(x.name)+' · v'+e(x.version)+'</option>').join('')+'</select>';
 const corr=box('因子版本 · 预测增量对照',
  '<div class="v4-compare-factors">'+choice('v4-compare-left',fac,view.labLeft)+
  choice('v4-compare-right',fac,view.labRight)+
  button('v4-compare-run','比较真实因子','primary')+'</div>'+
  '<div id="v4-compare-output">'+empty('请选择两个因子版本',
   '比较必须来自双方共同覆盖的真实股票 / 日期，不根据因子名称推断相关性。')+'</div>',
  '相同数据快照与验证协议下的 Rank IC 差异');
 const corrRows=correlations.map(x=>[short(x.factor_a,12),short(x.factor_b,12),
   numeric(x.median_daily_spearman),numeric(x.valid_sessions,0),
   x.redundancy_warning?'高相关':'未触发']);
 const corrSummary=box('因子相关性 · 研究摘要',
   corrRows.length?table(['因子 A','因子 B','日横截面 Spearman','有效日','冗余标记'],corrRows):
    empty('暂无同日可比相关性','需要至少两个真实因子版本拥有共同股票与共同日期。'),
   '真实共同样本；仅表示相关性，不是增量结论');
 const versions=box('不可变因子版本与实验记录',
   fac.length?table(['因子','版本','研究定义'],fac.slice(0,30).map(x=>[e(x.name),'v'+e(x.version),
    e(x.config?.template||'自定义')])):empty('暂无已定义因子','在因子实验室新增并保存。'));
 const experiments=box('实验状态与结果入口',
   exp.length?table(['实验 ID','状态','数据源'],exp.slice(0,30).map(x=>[
    short(x.id),e(x.status||'—'),e(x.config?.source||x.source||'—')])):
    empty('暂无实验记录','建立因子版本并运行实验。'));
 const maxCorrelation=correlations.map(x=>x.median_daily_spearman)
   .filter(actual).map(Number).sort((a,b)=>Math.abs(b)-Math.abs(a))[0];
 const labMetrics=metricStrip([
   metricCard('H3 Rank IC',actual(h3?.rank_ic_mean)?numeric(h3.rank_ic_mean):'—',
     selected?'历史验证期 · 截止 '+(report?.asof_date_et?date(report.asof_date_et):'未标明'):'没有可审查实验','green'),
   metricCard('H3 ICIR',actual(h3?.icir_unannualized)?numeric(h3.icir_unannualized,3):'—',
     actual(h3?.daily_ic_count)?n(h3.daily_ic_count,0)+' 个有效研究日':'有效日不足','blue'),
   metricCard('H3 Q5 − Q1',actual(h3?.q5_minus_q1_price_return_spread)?
      signed(h3.q5_minus_q1_price_return_spread):'—',
     '事后价格代理价差 · 不扣交易成本','purple'),
   metricCard('最大因子相关性',actual(maxCorrelation)?numeric(maxCorrelation,3):'—',
     correlations.length?'同日横截面中位数':'缺少共同样本','amber')
 ],'v4-lab-metrics');
 const panels=[
   aside(factorLibrary(a.take('已保存因子')),stack(compactFactorDefinition(a.take('创建因子')),
     note('下方结果为已归档的历史实验，数据截止 '+(report?.asof_date_et?date(report.asof_date_et):'未提供')+'；不是最新交易日预测。'),
     labMetrics,layout(outcome,stability),corrSummary,
     collapsedCard(a.take('真实数据预览'),'真实数据预览及实验操作'),
     analysis,layout(versions,experiments),a.take('最近因子实验'))),
   stack(layout(analysis,outcome),stability),
   layout(corr,box('因子相关性 · 历史同日横截面',
     correlations.length?table(['因子A','因子B','Spearman 中位数','有效日','冗余风险'],
       correlations.map(x=>[short(x.factor_a,12),short(x.factor_b,12),
        numeric(x.median_daily_spearman),numeric(x.valid_sessions,0),
        x.redundancy_warning?badge('高相关','amber'):badge('未触发','blue')])):
       empty('暂无可审核的因子相关性矩阵',
       '需要至少两个同源真实因子以及策略版本，形成逐日共同股票样本。'),
     '相关性来自历史策略共同股票横截面')),
   stack(layout(versions,experiments))
 ];
 return {html:panelHtml('lab',a.heading,panels),
 mount(){
   document.getElementById('v4-library-search')?.addEventListener('input',ev=>{
    const query=ev.target.value.trim().toLocaleLowerCase();
    document.querySelectorAll('[data-factor-version]').forEach(item=>{
     item.hidden=!item.textContent.toLocaleLowerCase().includes(query);
    });
   });
   document.getElementById('v4-compare-run')?.addEventListener('click',async()=>{
    const l=document.getElementById('v4-compare-left')?.value;
    const r=document.getElementById('v4-compare-right')?.value;
    view.labLeft=l;view.labRight=r;
    const out=document.getElementById('v4-compare-output');
    if(!out)return;
    if(!l||!r||l===r){out.innerHTML=empty('请选择两个不同因子版本','两个版本的身份不得相同。');return;}
    out.innerHTML=note('正在核对真实研究样本…');
    const q=await settle('/api/v1/factor-lab/compare?left='+encodeURIComponent(l)+'&right='+encodeURIComponent(r));
    const d=q.ok?q.data:null;
    if(!d){out.innerHTML=empty('比较受阻',String(q.error?.message||'来源/共同样本尚未合格'));return;}
    const comparisons=Array.isArray(d.rows)?d.rows:[];
    out.innerHTML=comparisons.length?table(
      ['样本段','预测H','左侧 Rank IC','右侧 Rank IC','IC增量','共同样本覆盖'],
      comparisons.map(x=>[e(x.partition),e(x.horizon),
        numeric(x.rank_ic_mean_left),numeric(x.rank_ic_mean_right),
        numeric(x.delta_rank_ic),numeric(x.label_pair_coverage_left)])):
      empty('比较无可用统计','共同样本数量或数据资格不足。');
    out.innerHTML+=note('这里对照的是历史验证期的 IC 差异，而不是因子之间的相关系数。');
   });
 }};
}
function candidateRows(ranking){
 return ranking.slice(0,30).map((x,i)=>[
  n(i+1,0),
  '<button type="button" class="v4-link v4-symbol-pick" data-v4-stock="'+i+'">'+e(x.symbol||x.security_id||'未知')+'</button>',
  e(x.sector||'—'),n(x.score,4),'—','—','—','—',badge('历史排名','blue')
 ]);
}
function candidateDetail(item){
 if(!item)return '<div class="v4-muted-note">请选择候选股票，查看实际因子拆解。</div>'+
   ['超跌程度 · A','卖压衰竭 · B','重新转强 · C'].map(x=>row(e(x),'—')).join('');
 const con=item.weighted_factor_contributions||{};
 const values=Object.entries(con).filter(([,v])=>actual(v))
   .sort((a,b)=>Math.abs(Number(b[1]))-Math.abs(Number(a[1])));
 const max=Math.max(1e-12,...values.map(([,v])=>Math.abs(Number(v))));
 return '<h3 class="v4-detail-title">'+e(item.symbol||item.security_id||'研究标的')+'</h3>'+
  row('综合因子分位/得分',n(item.score,4))+
  row('历史证券ID',e(item.security_id||'—'))+
  row('行业',e(item.sector||'未提供历史行业分类'))+
  (values.length?table(['因子版本','加权贡献','占最大绝对贡献比例'],values.map(([name,val])=>[
    e(name),n(val,5),Math.min(100,Math.round(Math.abs(Number(val))/max*100))+'%'])):
    empty('没有可核查的分项贡献','服务端没有返回因子贡献字段。'))+
  note('因子贡献解释的是候选排序，不是个股 H3 概率或可交易预测；需要单独联接合格的 Alpha 冻结结果。');
}
async function screen(original){
 const a=unwrap(original.html);
 const index=await Promise.all([
  settle('/api/v1/strategies'),settle('/api/v1/v4/plans'),
  settle('/api/v1/backtests/verified'),settle('/api/v1/v4/research/runs')
 ]);
 const allStrategies=index[0].ok?(index[0].data.strategies||[]):[];
 const strategies=allStrategies.filter(x=>Array.isArray(x.config?.strategy?.factors)&&x.config.strategy.factors.length>=2);
 if(!strategies.some(x=>String(x.id)===view.strategy))view.strategy=strategies[0]?.id||null;
 const composite=view.strategy?await settle('/api/v1/strategies/'+encodeURIComponent(view.strategy)+'/composite'):null;
 const ranks=composite?.ok?(composite.data.latest_composite_ranking||[]):[];
 const candidate=ranks.find(x=>String(x.security_id)===view.symbol)||ranks[0]||null;
 view.symbol=candidate?.security_id||null;
 const selector='<label class="v4-field">选择已保存策略<select id="v4-workspace-strategy">'+
  '<option value="">请选择策略</option>'+strategies.map(s=>'<option value="'+e(s.id)+'"'+
   (String(s.id)===String(view.strategy)?' selected':'')+'>'+e(s.name)+' · v'+e(s.version)+'</option>').join('')+
  '</select></label>';
 const activeStrategy=strategies.find(x=>String(x.id)===String(view.strategy))||null;
 const strategyFactors=Array.isArray(activeStrategy?.config?.strategy?.factors)?
   activeStrategy.config.strategy.factors:[];
 const groupNames=[['A','超跌程度'],['B','卖压衰竭'],['C','重新转强']];
 const groups=groupNames.map(([key,label])=>{
  const members=strategyFactors.filter(x=>String(x.group||'').toUpperCase()===key);
  const weight=members.length&&members.every(x=>actual(x.weight))?members.reduce((v,x)=>v+Number(x.weight),0):null;
  return '<div class="v4-strategy-group"><b>因子组 '+key+' · '+label+'</b><span>'+ (weight===null?'未配置':pct(weight))+'</span>'+
    (members.length?members.map(x=>row(e(x.factor_experiment_id||x.factor_version_id||x.factor_id||'未归档'),actual(x.weight)?pct(x.weight):'—')).join(''):
     '<div class="v4-muted-note">未配置真实因子版本</div>')+'</div>';
 }).join('');
 const strategySummary=box('筛选策略配置',selector+
   (activeStrategy?table(['历史因子实验','研究组别','冻结权重'],strategyFactors.map(x=>[
     e(x.factor_experiment_id||x.factor_version_id||x.factor_id||'未归档'),
     e(x.group||'未归档'),actual(x.weight)?pct(x.weight):'未归档']))+
     row('策略版本',e(activeStrategy.name)+' · v'+e(activeStrategy.version))+
     row('原定持有期',e(activeStrategy.config?.strategy?.horizon||'—')+' 日')+
     row('策略来源状态',e(composite?.ok?composite.data.status:'等待策略验证')):
     note('缺少可审查的多因子策略；至少需要两个真实完成的因子实验。'))+
   '<div class="v4-muted-note">历史股票池与基础过滤条件：'+(activeStrategy?'以已冻结配置为准':'尚未配置')+'</div>'+groups+
   note('因子权重仅重现已冻结配置，不代表因子贡献或预测收益。'),
   '策略条件 · 历史候选需单独验证');
 const selected=box('所选股票 · 个股因子解释',
  '<div id="v4-stock-detail">'+candidateDetail(candidate)+'</div>',
  '选择股票实时联动');
 const candidates=box('历史候选股票 · 因子排名',
  (ranks.length?table(['排名','股票','行业','综合分位','超跌 A','衰竭 B','转强 C','H3 预测','状态'],candidateRows(ranks)):
   emptyTable(['排名','股票','行业','综合分位','超跌 A','衰竭 B','转强 C','H3 预测','状态'],'尚无已验证的历史多因子排名',composite?.ok?
    '策略没有可审查的真实横截面复合排名。':
    strategies.length?'请核对各因子实验的共同交易日及数据来源。':'需要至少一个由两个以上已完成因子实验组成的策略。'))+
  row('实际研究观察日',date(composite?.ok?composite.data.asof_date_et:null))+
  note('此排名来自历史验证期的实际样本，非当日可交易股票；不自动当作 Alpha 未来收益预测。'),
  '选择候选展示右侧因子拆解');
 const planIdx=index[1].ok?(index[1].data.records||[]):[];
 const planRow=planIdx.find(x=>x.status!=='CORRUPT_RESEARCH_PLAN')||null;
 const plan=planRow?await settle('/api/v1/v4/plans/'+encodeURIComponent(planRow.session_date_et)+'/'+encodeURIComponent(planRow.identity)):null;
 const planData=plan?.ok?plan.data:null;
 const planCard=box('H3 冻结 Alpha 预测与交易条件',
  planData?.plans?.length?table(['证券','预期净优势','权益建议权重','冻结日'],
    planData.plans.slice(0,25).map(x=>[
      e(x.symbol||x.security_id),signed(x.estimated_net_edge),pct(x.indicative_weight),
      date(planRow.session_date_et)])):
   empty('尚无可比对的前向交易计划',
    '必须经过独立冻结的模型预测、真实身份元数据和风控条件；不把因子分数冒充预测收益。'),
  '独立研究计划 · 不等于模拟成交');
 const backtests=index[2].ok?(index[2].data.results||index[2].data.runs||[]):[];
 const backtestCard=box('策略模拟回测 · 样本外成本后表现',
  backtests.length?table(['运行版本','验证状态'],backtests.slice(0,20).map(x=>[
   short(x.run_id||x.id,22),e(x.status||'—')])):
   emptyStats(['净收益','最大回撤','Rank IC'])+emptyChart('尚无严格回测收益曲线',
    '缺历史 PIT 证券身份、公司行为、原始成交价格或交易成本。'),
  '可用性与证据分开');
 const panels=[
   stack(a.take('因子组合配置'),a.take('已保存策略与候选解释')),
   stack(aside(strategySummary,stack(a.hero,candidates,
     layout(selected,backtestCard,'v4-stock-master-detail'))),planCard),
   stack(layout(backtestCard,a.take('严格回测与前向冻结记录'))),
   stack(a.take('样本外预测'),a.take('冻结预测的后续结果复盘'))
 ];
 return {html:panelHtml('screen',a.heading,panels),
 mount(){
  document.getElementById('v4-workspace-strategy')?.addEventListener('change',ev=>{
   view.strategy=ev.target.value||null;view.symbol=null;view.tabs.screen=1;show('screen');
  });
  for(const pick of document.querySelectorAll('[data-v4-stock]'))pick.addEventListener('click',()=>{
   const chosen=ranks[Number(pick.dataset.v4Stock)];
   if(!chosen)return;
   view.symbol=String(chosen.security_id);
   document.querySelectorAll('[data-v4-stock]').forEach(x=>x.classList.toggle('v4-stock-selected',x===pick));
   const target=document.getElementById('v4-stock-detail');
   if(target)target.innerHTML=candidateDetail(chosen);
  });
 }};
}
async function risk(original){
 const a=unwrap(original.html);
 const [plans,outcomes,accountResult,riskResult,timelineResult]=await Promise.all([
  settle('/api/v1/v4/plans'),settle('/api/v1/v4/outcomes'),
  settle('/api/v1/paper/account'),settle('/api/v1/paper/risk'),
  settle('/api/v1/paper/timeline')]);
 const p=plans.ok?(plans.data.records||[]):[];
 const o=outcomes.ok?(outcomes.data.records||[]):[];
 const account=accountResult.ok?accountResult.data:null;
 const risk=riskResult.ok?riskResult.data:null;
 const timeline=timelineResult.ok?timelineResult.data:null;
 const verified=account?.status==='INTERNALLY_RECONCILED_PAPER_ESTIMATE';
 const riskOK=risk?.status==='CONCENTRATION_MEASURED';
 const riskAlerts=riskOK?(risk.alerts||[]):[];
 const sessions=timeline?.status==='INTERNALLY_RECONCILED_PAPER_ESTIMATE'?
   (timeline.sessions||[]):[];
 const alertsCard=a.take('风险预警');
 const actualPositions=a.take('当前模拟持仓');
 const actualRisk=a.take('组合风险度量');
 const actualHistory=a.take('逐日权益');
 const positionCard=verified?actualPositions:box('当前模拟持仓 · 风险与退出计划',
   emptyTable(['证券','持仓市值','仓位','浮动盈亏','行业','风险预算','退出条件','警示'],
    '当前没有具备内部对账的持仓','缺少合格模拟账本，不显示虚构持仓。'),'缺少合格持仓');
 const riskCard=riskOK?actualRisk:box('风险模型仪表',
   ['总仓位利用率','行业集中度','风险预算占用'].map(x=>row(e(x),'—')).join('')+
   emptyStats(['最大行业暴露','组合平均 Beta'])+emptyStats(['持仓相互相关','组合风险状态'])+
   note('缺少已对账账本及合格风险输入，无法计算。'),'证据不足');
 const historyCard=sessions.length>1?actualHistory:box('组合净值与回撤',
   emptyChart('暂无足够连续交易日数据','需要已冻结并真实观察的模拟账本。'),'模拟账本 · 非券商绩效');
 const evidenceCard=a.take('来源与模型可靠性');
 const rulesCard=a.take('仓位与退出规则');
 const equityWindow=sessions.filter(x=>actual(x.equity)).slice(-30).map(x=>Number(x.equity));
 let maxDrawdown=null,peak=null;
 for(const equity of equityWindow){
  peak=peak===null?equity:Math.max(peak,equity);
  if(peak>0)maxDrawdown=Math.max(maxDrawdown??0,1-equity/peak);
 }
 const riskMetrics=metricStrip([
   metricCard('模拟组合权益',verified&&actual(account.equity)?'$'+n(account.equity,2):'—',
     verified?'内部对账估值':'缺少合格模拟账本','blue'),
   metricCard('组合持仓占比',riskOK&&actual(risk.gross_weight)?pct(risk.gross_weight):'—',
     riskOK?'按已核验持仓估算':'暂无可核验持仓','green'),
   metricCard('组合日 VaR95',riskOK&&actual(risk.daily_var95)?pct(risk.daily_var95):'—',
     riskOK?'实际风险接口结果':'缺少合格组合收益序列','amber'),
   metricCard('逐日账本最大回撤',maxDrawdown!==null?signed(-maxDrawdown):'—',
     equityWindow.length>1?'最多近 30 个已核验账本日':'历史账本记录不足','purple'),
   metricCard('已核验风险预警',riskOK?n(riskAlerts.length,0):'—',
     riskOK?'仅统计已触发规则':'缺少风险核验','red')
 ],'v4-five-metrics');
 const analysis=box('尾部风险与模型失效评估',
   empty('暂无经核验的动态压力与模型失效概率',
    '当前组合风险接口仅能展示已有的规则阈值及合格历史风险统计；不能从持仓比例直接猜测 VaR。'));
 const exitPlans=box('仓位与退出 · 已冻结研究计划',
   p.length?table(['冻结日','研究候选数量','证据状态'],p.slice(0,20).map(x=>[
    date(x.session_date_et),n(x.research_plan_count,0),e(x.status||'—')])):
    empty('没有可读取的退出计划','需要事前冻结的策略参数及仓位证据。'),
   '1 / 3 / 5 日持有期限与 2×ATR 需逐笔核对');
 const replay=box('交易复盘与实际研究观察',
    o.length?table(['研究日','计划 ID','结果状态'],o.slice(0,20).map(x=>[
     date(x.session_date_et),short(x.plan_identity,18),e(x.status||'—')])):
     empty('没有完成期限的研究复盘','先事前冻结研究计划，再按真实价格和来源回执检验后续结果。'),
    '不把回测价格路径当真实券商成交');
 const panels=[
   stack(riskMetrics,layout(positionCard,riskCard,'v4-reference-market'),
     '<div class="v4-reference-three">'+historyCard+alertsCard+rulesCard+'</div>',exitPlans),
   stack(layout(analysis,riskCard),evidenceCard),
   stack(alertsCard,analysis),
   layout(rulesCard,exitPlans),
   layout(historyCard,replay)
 ];
 return {html:panelHtml('risk',a.heading,panels)};
}
const generators={overview,market,style,lab,screen,risk};
for(const name of Object.keys(generators)){
 pages[name]=async()=>{
  const initial=await saved[name]();
  const built=await generators[name](initial);
  return {title:initial.title,html:built.html,mount(){
    if(typeof initial.mount==='function')initial.mount();
    if(specs[name])bindTabs(name);
    if(typeof built.mount==='function')built.mount();
  }};
 }
}
})();
