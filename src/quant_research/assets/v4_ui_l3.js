/* L3 Alpha: result-first daily selection, immutable factor strategy configuration and validation. */
(() => {
'use strict';
const V=window.V4;
if(!V)throw Error('QDR L3 requires V4 core');
const {pages,state,$,e,n,pct,signed,date,badge,button,link,heading,card,kpi,empty,note,table,api,settle,grid,toast,show,go,refresh,moduleLoading}=V;
state.l3Tab=state.l3Tab||'today';
state.screenHorizon=state.screenHorizon||3;
state.l3SelectedSymbol=state.l3SelectedSymbol||null;

const fmtScore=v=>v===null||v===undefined||!Number.isFinite(Number(v))?'—':Number(v).toFixed(3);
const evidence=v=>v===null||v===undefined||!Number.isFinite(Number(v))?'—':Number(v).toFixed(4);
const signedOrDash=v=>v===null||v===undefined||!Number.isFinite(Number(v))?'—':signed(v);
const prob=(v,status)=>status==='CALIBRATED_CHRONOLOGICAL_HOLDOUT'?pct(v,1):'—';
const blockerLabels={
 NO_PROSPECTIVE_FORWARD_FORECAST:'暂无真实前向预测',
 NO_ACTIVE_ALPHA_STRATEGY:'尚未启用 Alpha 组合',
 FROZEN_FORWARD_INPUT_BUNDLE_NOT_FOUND:'冻结预测输入无法复核',
 ACTIVE_STRATEGY_FORECAST_FACTOR_SET_MISMATCH:'当前组合与预测因子集合不一致',
 L3_CURRENT_FACTOR_ROWS_MISSING:'当日缺少组合因子',
 L3_CURRENT_FACTORS_NOT_DECISION_ELIGIBLE:'当前因子仅可回顾研究',
 L3_ACTIVE_FACTORS_NOT_IN_FORWARD_BUNDLE:'当前组合未进入前向因子包',
 NO_FROZEN_L3_DAILY_SELECTION:'当日 Alpha 排名尚未冻结',
 FROZEN_L3_DAILY_SELECTION_INVALID:'当日 Alpha 排名完整性校验失败',
 ACTIVE_STRATEGY_RETROSPECTIVE_VALIDATION_UNAVAILABLE:'组合历史验证不可用',
 STRATEGY_REGISTRY_UNAVAILABLE:'策略注册表不可用'
};
const blockers=data=>(data?.blockers||[]).length?
 '<div class="l3-blockers">'+data.blockers.map(x=>'<span class="l3-blocker">'+e(blockerLabels[x]||x)+'</span>').join('')+'</div>':'';

function tabs(){
 const items=[['today','今日选股'],['strategy','因子组合'],['lab','因子实验室'],['validation','验证与回测']];
 return '<div class="l3-tabs" role="tablist" aria-label="L3 个股 Alpha">'+items.map(([key,label])=>
   '<button type="button" class="l3-tab '+(state.l3Tab===key?'active':'')+'" data-l3-tab="'+key+'" role="tab" aria-selected="'+(state.l3Tab===key?'true':'false')+'">'+label+'</button>'
 ).join('')+'</div>';
}
function horizon(){
 return '<div class="l3-horizon" aria-label="研究周期">'+[1,3,5].map(h=>
  '<button type="button" data-l3-h="'+h+'" class="'+(state.screenHorizon===h?'active':'')+'">H'+h+'</button>'
 ).join('')+'</div>';
}
function strategyHeader(data){
 const s=data.active_strategy;
 return '<div class="l3-statusline"><span>研究日 <b>'+e(data.daily?.session_date_et||'—')+'</b></span>'+
  '<span>当前组合 <b>'+(s?e(s.name+' · v'+s.version):'未启用')+'</b></span>'+
  '<span>股票池 <b>'+n(data.daily?.observed_security_count,0)+'</b></span>'+
  '<span>有效 Alpha <b>'+n(data.daily?.complete_alpha_score_count,0)+'</b></span>'+
  '<span>候选 <b>'+n(data.daily?.candidate_count,0)+'</b></span>'+
  '<span style="margin-left:auto">'+horizon()+'</span></div>';
}
function today(data){
 const candidates=data.candidates||[];
 const rows=candidates.map(x=>[
   '<button type="button" class="btn smallbtn l3-stock-open" data-symbol="'+e(x.symbol)+'"><span class="l3-symbol"><b>'+e(x.symbol)+'</b><small>'+e(x.sector||x.security_id)+'</small></span></button>',
   '<span class="l3-score">'+fmtScore(x.alpha_score)+'</span>',
   '<span class="'+(Number(x.expected_excess_return)>=0?'l3-positive':'l3-negative')+'">'+signedOrDash(x.expected_excess_return)+'</span>',
   prob(x.p_up,x.probability_status_up),
   prob(x.p_downside,x.probability_status_downside),
   (x.primary_factors||[]).map(f=>e(f.factor_name)).join(' / ')||'—'
 ]);
 const stats=data.daily?grid(4,
   kpi('当前组合',data.active_strategy?e(data.active_strategy.name):'—',data.active_strategy?'v'+e(data.active_strategy.version)+' · '+n(data.active_strategy.factors?.length,0)+' 个因子':'需要先冻结并启用组合','blue')+
   kpi('股票池',n(data.daily.observed_security_count,0),n(data.daily.complete_alpha_score_count,0)+' 只完成组合计算','')+
   kpi('研究候选',n(data.daily.candidate_count,0),data.daily.candidate_count?'横截面 Top 20%':'允许明确输出 0 个候选','green')+
   kpi('条件模型',data.daily.selected_model_variant?e(data.daily.selected_model_variant):'—',e(data.daily.model_selection_reason||'无匹配的条件预测'),'purple')
 ):'';
 const list=card('今日 Alpha 排名',
   candidates.length?'<div class="l3-candidate-table">'+table(
     ['标的','Alpha Score','H'+state.screenHorizon+' 预期超额','上涨概率','下行概率','主导因子'],rows)+'</div>':
     empty(data.active_strategy?'当前没有可展示的 Alpha 候选':'尚未启用 Alpha 组合',
       data.active_strategy?'只有真实当日因子与组合完全匹配时才生成排名，不补示意数据。':'前往「因子组合」选择 2–8 个已完成实验，保存、冻结并启用一个组合。'),
   'Alpha Score 与收益预测分开计算');
 return strategyHeader(data)+blockers(data)+stats+'<div style="margin-top:14px">'+list+'</div>'+
   '<div id="l3-candidate-detail">'+candidateDetail(candidates[0]||null,data)+'</div>';
}
function candidateDetail(x,data){
 if(!x)return '';
 const factors=Object.entries(x.factor_contributions||{}).filter(([,v])=>Number.isFinite(Number(v))).sort((a,b)=>Number(b[1])-Number(a[1]));
 const max=Math.max(...factors.map(([,v])=>Number(v)),.0001);
 const bars=factors.length?factors.map(([name,value])=>
  '<div class="l3-factor-row"><span>'+e(name)+'</span><div class="l3-factor-track"><i style="width:'+Math.max(3,Math.min(100,Number(value)/max*100)).toFixed(1)+'%"></i></div><b>'+fmtScore(value)+'</b></div>'
 ).join(''):empty('暂无贡献分解','当前候选没有可复核的组合因子贡献。');
 const ranks=data.model_evidence?.alpha_ranking||[];
 const rankMap=new Map(ranks.map(r=>[r.variant,r]));
 const variants=['A','B','C','D'];
 const modelRows=variants.map(v=>{
   const r=rankMap.get(v);const val=r?.rank_ic_mean;
   return '<div class="l3-model-row '+(x.model_variant===v?'selected':'')+'"><span>'+e(({A:'Alpha',B:'Alpha + L1',C:'Alpha + L2',D:'Full'})[v])+'</span><div class="l3-model-track"><i style="width:'+(Number.isFinite(Number(val))?Math.max(5,Math.min(100,Math.abs(Number(val))*900)):0)+'%"></i></div><b>'+e(evidence(val))+'</b></div>';
 }).join('');
 return '<div class="l3-detail-grid">'+
  card('为什么进入候选',
   '<div class="l3-detail-head"><div><h3>'+e(x.symbol)+'</h3><p>'+e(x.sector||x.security_id)+'</p></div>'+badge('横截面 '+pct(x.alpha_rank_pct,1)+' 分位','blue')+'</div>'+
   '<div class="l3-mini-grid"><div class="l3-mini"><span>Alpha Score</span><b>'+fmtScore(x.alpha_score)+'</b></div>'+
   '<div class="l3-mini"><span>H'+state.screenHorizon+' 预期超额</span><b>'+signedOrDash(x.expected_excess_return)+'</b></div>'+
   '<div class="l3-mini"><span>P(up)</span><b>'+prob(x.p_up,x.probability_status_up)+'</b></div>'+
   '<div class="l3-mini"><span>P(down)</span><b>'+prob(x.p_downside,x.probability_status_downside)+'</b></div></div>'+
   '<div class="v4-muted-note">因子贡献</div>'+bars,
   '真实组合分位贡献')+
  card('L1 / L2 条件增量',
   data.model_evidence?modelRows+
    note(data.model_evidence.selection_reason==='FULL_MODEL_PAIRED_OOS_INCREMENT_CONFIRMED'?
      'Full 模型在相同样本的配对 OOS 比较中同时改善上涨概率 Brier 与收益 MSE，当前允许使用 D。':
      '没有足够证据证明条件模型优于 Alpha-only，因此默认保留 A；不会因为四层完整就强行使用 D。'):
    empty('暂无匹配的条件模型证据','当前策略的因子集合与冻结预测或 OOS 研究不一致。'),
   'Rank IC · 同样本 OOS')+
  '</div>';
}
function strategy(data){
 const active=data.active_strategy;
 const activeMap=new Map((active?.factors||[]).map(x=>[x.experiment_id,x]));
 const library=data.factor_library||[];
 const factorRows=library.length?library.map((f,i)=>{
   const selected=activeMap.get(f.experiment_id);const weight=selected?Math.round(Number(selected.weight)*100):0;
   return '<label class="l3-factor-pick"><input type="checkbox" class="l3-factor-check" data-exp="'+e(f.experiment_id)+'"'+(selected?' checked':'')+' />'+
    '<span><div class="l3-factor-name">'+e(f.factor_name||'未命名因子')+' · v'+e(f.factor_version||'—')+'</div>'+
    '<div class="l3-factor-evidence">H'+state.screenHorizon+' Rank IC '+e(evidence(f.rank_ic_mean))+' · ICIR '+e(evidence(f.icir_unannualized))+' · 覆盖 '+pct(f.label_pair_coverage,0)+'</div></span>'+
    '<input type="number" class="l3-factor-weight" min="0" max="100" step="1" value="'+weight+'" aria-label="'+e(f.factor_name)+' 权重百分比" /></label>';
 }).join(''):empty('暂无已完成的因子实验','先到因子实验室创建并完成真实历史研究。');
 const activeInfo=active?'<div class="l3-active-factors">'+(active.factors||[]).map(x=>'<span class="l3-factor-chip">'+e(x.factor_name)+' '+pct(x.weight,0)+'</span>').join('')+'</div>':
   empty('没有当前组合','保存组合后系统会先冻结该版本，再显式设为当前 L3 组合。');
 const strategies=(data.strategies||[]).map(s=>[
   e(s.name)+' · v'+e(s.version),'H'+e(s.horizon),e(s.status),
   '<button type="button" class="btn smallbtn l3-activate" data-id="'+e(s.id)+'">'+(s.status==='FROZEN'?'启用':'冻结并启用')+'</button>'
 ]);
 return blockers(data)+'<div class="l3-strategy-layout">'+
  card('有效因子库',factorRows,'选择 2–8 个 · 权重合计 100%')+
  card('Alpha 组合',
   '<div class="v4-form"><div class="v4-field"><label for="l3-strategy-name">组合名称</label><input id="l3-strategy-name" maxlength="80" value="'+e(active?.name||'Alpha 组合')+'" /></div></div>'+
   activeInfo+'<div class="l3-strategy-actions">'+button('l3-save-strategy','保存为新版本并启用','primary')+
   '<span class="v4-muted-note">活跃组合必须是冻结版本，历史版本不会被覆盖。</span></div>',
   active?('当前 v'+active.version+' · H'+active.horizon):'未启用')+
  '</div><div style="margin-top:14px">'+card('历史组合版本',
   strategies.length?'<div class="l3-strategy-table">'+table(['组合','周期','状态','操作'],strategies)+'</div>':
   empty('暂无组合版本','保存第一个 Alpha 组合后会出现在这里。'),
   '配置版本不可覆盖')+'</div>';
}
function validation(data){
 const v=data.validation;const m=data.model_evidence;
 const summary=v?'<div class="l3-validation-grid"><div class="l3-validation-card"><span>组合验证 Rank IC</span><b>'+e(evidence(v.validation_rank_ic_mean))+'</b></div>'+
  '<div class="l3-validation-card"><span>有效交易日</span><b>'+n(v.validation_daily_ic_count,0)+'</b></div>'+
  '<div class="l3-validation-card"><span>冗余警告</span><b>'+n(v.redundancy_warning_count,0)+'</b></div></div>':
  empty('当前组合暂无可用历史验证','组合还未启用，或真实研究产物不能通过完整性检查。');
 const ranks=m?.alpha_ranking||[];
 const rankTable=ranks.length?table(['模型','H','Rank IC','ICIR','样本日'],ranks.map(x=>[
   e(({A:'Alpha',B:'Alpha + L1',C:'Alpha + L2',D:'Full'})[x.variant]||x.variant),
   e(state.screenHorizon),e(evidence(x.rank_ic_mean)),e(evidence(x.rank_icir_unannualized)),n(x.sessions,0)
 ])):empty('暂无匹配的 OOS 模型比较','只有与当前组合因子集合和来源快照一致的研究才会显示。');
 const outcomes=data.outcomes||[];
 const outcomeRows=outcomes.length?'<div class="l3-outcome-list">'+outcomes.map(x=>
  '<div class="l3-outcome"><b>'+e(x.session_date_et)+'</b><span>'+e(x.status)+' · '+n(x.evaluated_trades,0)+' 个已到期研究候选</span><span>'+signedOrDash(x.mean_modeled_net_return)+'</span></div>'
 ).join('')+'</div>':empty('暂无完成期限的前向结果','冻结预测到达 H1/H3/H5 后才进入这里，不用历史结果倒填。');
 return blockers(data)+summary+'<div class="grid cols2">'+
   card('A / B / C / D 条件模型',rankTable,m?e(m.selection_reason):'无匹配证据')+
   card('冻结预测兑现',outcomeRows,'只读真实后续结果')+'</div>';
}

pages.screen=async()=>{
 const r=await settle('/api/v1/l3/overview?horizon='+encodeURIComponent(state.screenHorizon)+'&limit=20');
 if(!r.ok){
   const content=heading('个股 Alpha','自定义因子 → 组合 → 每日横截面选股 → H1/H3/H5 条件预测',
     link('/studio#lab','因子实验室'))+tabs()+(r.pending?moduleLoading('L3 Alpha'):empty('L3 数据暂不可用',String(r.error?.message||'研究证据尚未形成')));
   return {title:'个股 Alpha',html:content,mount:mountTabs};
 }
 const data=r.data;
 let body=state.l3Tab==='strategy'?strategy(data):state.l3Tab==='validation'?validation(data):today(data);
 if(state.l3Tab==='lab')body=empty('因子实验室是独立研发区','正在打开因子实验室。');
 const html=heading('个股 Alpha','自定义因子驱动的每日个股 Alpha 选股系统',
   link('/strategies','完整策略工具')+link('/backtests','严格回测'))+tabs()+body;
 return {title:'个股 Alpha',html,mount(){mountTabs();mountCommon(data);if(state.l3Tab==='strategy')mountStrategy(data);if(state.l3Tab==='today')mountToday(data);if(state.l3Tab==='lab')go('lab');}};
};

function mountTabs(){
 const tabs=[...document.querySelectorAll('[data-l3-tab]')];
 const activate=(btn)=>{
   const key=btn.dataset.l3Tab;if(key==='lab'){go('lab');return}
   state.l3Tab=key;show('screen');
 };
 tabs.forEach((btn,index)=>{
   btn.addEventListener('click',()=>activate(btn));
   btn.addEventListener('keydown',event=>{
     if(!['ArrowRight','ArrowLeft','Home','End'].includes(event.key))return;
     event.preventDefault();
     const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:
       (index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
     tabs[next].focus();activate(tabs[next]);
   });
 });
}
function mountCommon(){
 document.querySelectorAll('[data-l3-h]').forEach(btn=>btn.addEventListener('click',()=>{
   const value=Number(btn.dataset.l3H);if(![1,3,5].includes(value))return;
   state.screenHorizon=value;state.l3SelectedSymbol=null;refresh('/api/v1/l3/overview');
 }));
}
function mountToday(data){
 const candidates=data.candidates||[];
 document.querySelectorAll('.l3-stock-open').forEach(btn=>btn.addEventListener('click',()=>{
   const item=candidates.find(x=>String(x.symbol)===String(btn.dataset.symbol));if(!item)return;
   state.l3SelectedSymbol=item.symbol;
   const target=$('#l3-candidate-detail');if(target)target.innerHTML=candidateDetail(item,data);
   document.querySelectorAll('.l3-candidate-table tbody tr').forEach(x=>x.classList.remove('selected'));
   btn.closest('tr')?.classList.add('selected');
 }));
 if(state.l3SelectedSymbol){
   const btn=[...document.querySelectorAll('.l3-stock-open')].find(x=>x.dataset.symbol===state.l3SelectedSymbol);
   btn?.click();
 }
}
function mountStrategy(data){
 const checks=[...document.querySelectorAll('.l3-factor-check')];
 checks.forEach(check=>check.addEventListener('change',()=>{
   const weight=check.closest('.l3-factor-pick')?.querySelector('.l3-factor-weight');
   if(weight&&check.checked&&Number(weight.value)<=0)weight.value='10';
 }));
 const action=async fn=>{try{await fn()}catch(error){toast(error.message||'L3 操作失败')}};
 $('#l3-save-strategy')?.addEventListener('click',()=>action(async()=>{
   const picked=checks.filter(x=>x.checked).map(x=>{
     const parent=x.closest('.l3-factor-pick');const weight=Number(parent.querySelector('.l3-factor-weight').value);
     return {factor_experiment_id:x.dataset.exp,weight:weight/100};
   });
   if(picked.length<2||picked.length>8)throw Error('请选择 2–8 个已完成因子');
   const total=picked.reduce((sum,x)=>sum+x.weight,0);
   if(picked.some(x=>!Number.isFinite(x.weight)||x.weight<=0)||Math.abs(total-1)>1e-8)throw Error('因子权重必须合计 100%');
   const name=$('#l3-strategy-name')?.value.trim();if(!name)throw Error('请输入组合名称');
   const active=data.active_strategy;
   const payload={name,horizon:state.screenHorizon,max_stock_weight:.10,max_total_weight:.50,max_sector_weight:.25,minimum_adv20:20000000,stop_atr_multiple:2,factors:picked};
   if(active&&active.name===name)payload.parent_version_id=active.id;
   const created=await api('/api/v1/strategies',payload);
   await api('/api/v1/strategies/'+encodeURIComponent(created.id)+'/freeze',{});
   await api('/api/v1/l3/active-strategy',{strategy_version_id:created.id});
   toast('Alpha 组合已保存、冻结并启用');
   refresh('/api/v1/l3/');
 }));
 document.querySelectorAll('.l3-activate').forEach(btn=>btn.addEventListener('click',()=>action(async()=>{
   const id=btn.dataset.id;const row=(data.strategies||[]).find(x=>x.id===id);
   if(!row)throw Error('组合版本不存在');
   if(row.status!=='FROZEN')await api('/api/v1/strategies/'+encodeURIComponent(id)+'/freeze',{});
   await api('/api/v1/l3/active-strategy',{strategy_version_id:id});
   toast('已切换当前 Alpha 组合');
   refresh('/api/v1/l3/');
 })));
}
})();