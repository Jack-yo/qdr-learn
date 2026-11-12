/* QDR six-workspace fidelity layer: preserves live API actions and approved page hierarchy.
 * Loaded after the data-connected pages. No demonstration probabilities, trades, or returns. */
(() => {
'use strict';
const V=window.V4;
if(!V)throw Error('V4 core must load before the approved workspace');
const {pages,state,e,n,pct,signed,date,short,badge,button,link,card,table,empty,note,row,settle,svgLine,progress,show}=V;
const saved={};for(const name of ['overview','market','style','lab','screen','risk'])saved[name]=pages[name];
const view={tabs:{},strategy:null,symbol:null,labLeft:null,labRight:null,marketObs:null};
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
function box(name,body,sub=''){return card(name,body,sub);}
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
  allowed.map(x=>'<th>'+e(x)+'</th>').join('')+'</tr></thead><tbody>'+
  allowed.map(from=>{
   const total=tally[from].reduce((a,b)=>a+b,0);
   return '<tr><th>'+e(from)+' (n='+total+')</th>'+tally[from].map(v=>
     '<td>'+(total>=5?(v/total*100).toFixed(1)+'%':'—')+'</td>').join('')+'</tr>';
  }).join('')+'</tbody></table></div>'+note('这是历史经验转移频率，分母为该起始状态有效样本；不是经验证的未来状态转移概率。');
}

function overview(original){
 const a=unwrap(original.html);
 const market=a.take('市场状态预测');
 const style=a.take('经典因子');
 const alpha=a.take('Alpha 研究');
 const risk=a.take('组合持仓');
 const score=a.take('前向 H3');
 const daily=a.take('每日四层');
 const evidence=a.take('系统数据资格');
 const flow=['数据更新','因子计算','四层条件预测','候选与风险计划','冻结及前向复盘'];
 const steps='<div class="v4-workflow-steps">'+flow.map((name,i)=>
  '<div class="v4-workflow-step"><span>0'+(i+1)+'</span><b>'+e(name)+'</b></div>').join('')+'</div>';
 const wrap=a.heading+a.hero+
  layout(market,style)+layout(alpha,risk)+
  box('前向研究闭环 · 日终五阶段',steps, '进展以真实研究任务为准')+
  '<details class="v4-workspace-details"><summary>预测验证、归档状态与数据资格</summary>'+
  stack(score,layout(daily,evidence))+'</details>'+a.remaining();
 return {html:wrap};
}
async function market(original){
 const a=unwrap(original.html);
 const r=await settle('/api/v1/market/research?horizon='+Number(state.marketHorizon||3));
 const data=r.ok?r.data:null,states=Array.isArray(data?.states)?data.states:[];
 const current=states[0]||null;
 const history=Array.isArray(data?.state_history)?data.state_history:[];
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
     row('历史市场状态',e(current.market_state||'未知'))+
     row('研究观测日期',date(current.date||data?.manifest?.asof_date_et))+
     row('输入数据可用时间',e(current.state_available_at||'—'))+
     row('市场 20 日收益',actual(current.market_return_20)?signed(current.market_return_20):'—')+
     row('市场 20 日波动',actual(current.market_vol_20)?pct(current.market_vol_20):'—')):
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
   stack(layout(distribution,a.take('市场环境')),a.take('四层联动')),
   layout(regime,transition),
   stack(layout(why,a.take('模型可靠性与风险传导')),parameters),
   stack(layout(validation,a.take('概率可靠性与模型验证')),
     a.take('历史研究与对照版本'))
 ];
 return {html:panelHtml('market',a.heading+a.toolbar+a.hero,panel),
 mount(){
  for(const x of document.querySelectorAll('[data-v4-switch-market]'))x.addEventListener('click',()=>{
   state.marketHorizon=Number(x.dataset.v4SwitchMarket);show('market');
  });
 }};
}
async function style(original){
 const a=unwrap(original.html);
 const dataResult=await Promise.all([settle('/api/v1/styles?mode=observation'),settle('/api/v1/market/research?horizon=3')]);
 const dat=dataResult[0].ok?dataResult[0].data:null;
 const m=dataResult[1].ok?dataResult[1].data:null;
 const factors=Array.isArray(dat?.latest)?dat.latest:[];
 const fseries=Array.isArray(dat?.series)?dat.series:[];
 const mstate=Array.isArray(m?.states)?m.states[0]:null;
 const pairs=[
  ['小盘 IWM / SPY','style_small_relative_return_5d','style_small_relative_return_20d'],
  ['价值 IWD / IWF','style_value_relative_return_5d','style_value_relative_return_20d'],
  ['动量 MTUM / SPY','style_momentum_relative_return_5d','style_momentum_relative_return_20d'],
  ['质量 QUAL / SPY','style_quality_relative_return_5d','style_quality_relative_return_20d'],
  ['低波 USMV / SPY','style_low_vol_relative_return_5d','style_low_vol_relative_return_20d']
 ];
 const etf=box('ETF 风格代理 · 历史相对表现',
  mstate?table(['ETF 风格组合','5 日相对收益','20 日相对收益','观察日'],
   pairs.map(([name,s,t])=>[e(name),actual(mstate[s])?signed(mstate[s]):'—',
    actual(mstate[t])?signed(mstate[t]):'—',date(mstate.date||m?.manifest?.asof_date_et)])):
   empty('暂无 ETF 风格代理观测','市场数据未形成满足时间资格的同日 ETF 组合历史。'),
   '不等于 Fama–French 多空因子收益');
 const classic=box('经典因子收益 · Fama–French 系列',
  factors.length?table(['因子','经济含义','5日实际收益','20日实际收益','观察状态'],
   factors.filter(x=>x.factor_name!=='RF').map(x=>[
    e(x.factor_name),e(x.factor_label||'—'),actual(x.sum_5d)?signed(x.sum_5d):'—',
    actual(x.sum_20d)?signed(x.sum_20d):'—',e(x.state||'—')])):
    empty('尚无真实经典因子数据','需要来源可追踪的因子历史记录。'),
   '经典因子与 ETF 代理分开核验');
 const rotation=box('风格轮动 · 动量变化与持续性',
   factors.length?table(['风格','5 日收益','20 日收益','5D - 20D 平均日收益差'],
    factors.filter(x=>x.factor_name!=='RF').map(x=>[
     e(x.factor_name),actual(x.sum_5d)?signed(x.sum_5d):'—',
     actual(x.sum_20d)?signed(x.sum_20d):'—',
     actual(x.sum_5d)&&actual(x.sum_20d)?signed(Number(x.sum_5d)/5-Number(x.sum_20d)/20):'—'])):
    empty('暂无可比较的轮动样本','需要至少 20 日同口径经典因子收益。'),
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
   stack(layout(a.take('经典风格强弱'),a.take('滚动收益')),a.take('风格观察明细')),
   layout(classic,series),
   layout(etf,box('代理使用口径',
     studyNote('IWM/SPY 代表小盘相对大型股，IWD/IWF 代表价值相对成长；它们不是 French SMB/HML/RMW/CMA 因子的精确替代。')+
     row('ETF 历史研究日期',date(mstate?.date||m?.manifest?.asof_date_et)))),
   layout(rotation,series),
   layout(validation,a.take('风格预测研究边界'))
 ];
 return {html:panelHtml('style',a.heading+a.hero,panels)};
}
async function lab(original){
 const a=unwrap(original.html);
 const res=await settle('/api/v1/factor-lab/library');
 const fac=res.ok?(res.data.factor_versions||[]):[];
 const exp=res.ok?(res.data.experiments||[]):[];
 const completed=exp.filter(x=>x.status==='COMPLETED');
 const selected=completed[0]||null;
 const detail=selected?await settle('/api/v1/factor-lab/experiments/'+encodeURIComponent(selected.id)):null;
 const metrics=detail?.ok?detail.data.metrics:null;
 const metricRows=metrics&&typeof metrics==='object'?
  Object.entries(metrics).slice(0,24).map(([k,v])=>[e(k),typeof v==='number'?n(v,5):e(JSON.stringify(v).slice(0,100))]):[];
 const analysis=box('因子有效性 · 真实研究度量',
   metricRows.length?table(['研究指标','实际结果'],metricRows):
    empty('尚无可审查的因子有效性报告','完成真实因子实验后展示 Rank IC、ICIR、收益分组和时间外稳定性。'),
   selected?'已完成实验 '+short(selected.id):'不填造假的 Rank IC');
 const outcome=box('分组未来收益 · H1 / H3 / H5',
   empty('暂无可比较的真实收益分组',
    'Q1–Q5 的未来回报需来自符合当时时点的历史股票池和经核验交易标签；暂不绘制演示曲线。'));
 const stability=box('滚动 IC 与跨市场稳定性',
   empty('缺少逐期样本外 IC 序列',
    '因子报告应保留每个评价期的 Rank IC、有效样本量与回测版本。'));
 const left=fac.filter(x=>x.id!==view.labLeft);
 const right=fac.filter(x=>x.id!==view.labRight);
 const choice=(id,items,selectedValue)=>'<select id="'+id+'" aria-label="选择比较因子版本">'+
  '<option value="">请选择版本</option>'+items.map(x=>'<option value="'+e(x.id)+'"'+
   (String(x.id)===String(selectedValue)?' selected':'')+'>'+e(x.name)+' · v'+e(x.version)+'</option>').join('')+'</select>';
 const corr=box('因子冗余与相关性检验 · 两版本比较',
  '<div class="v4-compare-factors">'+choice('v4-compare-left',fac,view.labLeft)+
  choice('v4-compare-right',fac,view.labRight)+
  button('v4-compare-run','比较真实因子','primary')+'</div>'+
  '<div id="v4-compare-output">'+empty('请选择两个因子版本',
   '比较必须来自双方共同覆盖的真实股票 / 日期，不根据因子名称推断相关性。')+'</div>',
  '共同样本 Pearson / Spearman 由服务端报告');
 const versions=box('不可变因子版本与实验记录',
   fac.length?table(['因子','版本','研究定义'],fac.slice(0,30).map(x=>[e(x.name),'v'+e(x.version),
    e(x.config?.template||'自定义')])):empty('暂无已定义因子','在因子实验室新增并保存。'));
 const experiments=box('实验状态与结果入口',
   exp.length?table(['实验 ID','状态','数据源'],exp.slice(0,30).map(x=>[
    short(x.id),e(x.status||'—'),e(x.config?.source||x.source||'—')])):
    empty('暂无实验记录','建立因子版本并运行实验。'));
 const panels=[
   stack(aside(a.take('已保存因子'),stack(a.take('创建因子'),a.take('真实数据预览'))),a.take('最近因子实验')),
   stack(layout(analysis,outcome),stability),
   layout(corr,box('如何解释相关性',studyNote('高相关可能导致多因子冗余；仅在相同样本、相同可用日期上计算，且需要检查标签独立性。'))),
   stack(layout(versions,experiments))
 ];
 return {html:panelHtml('lab',a.heading+a.steps+a.hero,panels),
 mount(){
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
    const stats=Object.entries(d).filter(([,v])=>v!==null&&typeof v!=='object');
    out.innerHTML=stats.length?table(['统计字段','实际结果'],stats.map(([k,v])=>[e(k),e(v)])):
      empty('比较无可用统计','共同样本数量或数据资格不足。');
   });
 }};
}
function candidateRows(ranking){
 return ranking.slice(0,30).map((x,i)=>[
  '<button type="button" class="v4-link v4-symbol-pick" data-v4-stock="'+i+'">'+e(x.symbol||x.security_id||'未知')+'</button>',
  n(x.score,4),e(x.sector||'—'),
  Object.keys(x.weighted_factor_contributions||{}).length+' 项',badge('研究排名','blue')
 ]);
}
function candidateDetail(item){
 if(!item)return empty('请选择候选股票','点击左侧实际策略排名查看因子拆解，不显示模拟目标价。');
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
 const strategies=index[0].ok?(index[0].data.strategies||[]):[];
 if(!strategies.some(x=>String(x.id)===view.strategy))view.strategy=strategies[0]?.id||null;
 const composite=view.strategy?await settle('/api/v1/strategies/'+encodeURIComponent(view.strategy)+'/composite'):null;
 const ranks=composite?.ok?(composite.data.latest_composite_ranking||[]):[];
 const candidate=ranks.find(x=>String(x.security_id)===view.symbol)||ranks[0]||null;
 view.symbol=candidate?.security_id||null;
 const selector='<label class="v4-field">选择已保存策略<select id="v4-workspace-strategy">'+
  '<option value="">请选择策略</option>'+strategies.map(s=>'<option value="'+e(s.id)+'"'+
   (String(s.id)===String(view.strategy)?' selected':'')+'>'+e(s.name)+' · v'+e(s.version)+'</option>').join('')+
  '</select></label>';
 const selected=box('所选股票 · 个股因子解释',
  '<div id="v4-stock-detail">'+candidateDetail(candidate)+'</div>',
  '选择股票实时联动');
 const candidates=box('历史候选股票 · 因子排名',
  selector+
  (ranks.length?table(['股票','综合分位','行业','有效因子','状态'],candidateRows(ranks)):
   empty('尚无当前策略可用排名',composite?.ok?
    '策略没有合格的真实横截面复合排名。':
    '需要保存策略及已完成的共同交易日因子实验，或核查当前数据来源。'))+
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
   empty('尚无严格回测收益曲线',
    '缺历史 PIT 证券身份、公司行为、原始成交价格或交易成本时，不呈现虚假的年化收益及回撤。'),
  '可用性与证据分开');
 const panels=[
   stack(a.take('因子组合配置'),a.take('已保存策略与候选解释')),
   stack(layout(candidates,selected,'v4-stock-master-detail'),planCard),
   stack(layout(backtestCard,a.take('严格回测与前向冻结记录'))),
   stack(a.take('样本外预测'),a.take('冻结预测的后续结果复盘'))
 ];
 return {html:panelHtml('screen',a.heading+a.steps+a.hero,panels),
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
 const [plans,outcomes]=await Promise.all([settle('/api/v1/v4/plans'),settle('/api/v1/v4/outcomes')]);
 const p=plans.ok?(plans.data.records||[]):[];
 const o=outcomes.ok?(outcomes.data.records||[]):[];
 const alerts=box('预警中心 · 研究信号与优先级',
   a.take('风险预警'));
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
 const equityHistory=a.take('逐日权益');
 const panels=[
   stack(layout(a.take('当前模拟持仓'),a.take('组合风险度量'))),
   layout(analysis,a.take('来源与模型可靠性')),
   stack(alerts),
   layout(a.take('仓位与退出规则'),exitPlans),
   layout(equityHistory,replay)
 ];
 return {html:panelHtml('risk',a.heading+a.hero,panels)};
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
