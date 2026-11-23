/* L3 Alpha workbench: four task-oriented workspaces backed by immutable research evidence. */
(() => {
'use strict';
const V=window.V4;
if(!V)throw Error('QDR L3 requires V4 core');
const {pages,state,$,e,n,pct,signed,date,badge,button,link,heading,card,kpi,empty,note,table,api,settle,grid,toast,show,go,refresh,moduleLoading}=V;
if(state.l3Tab==='strategy'||state.l3Tab==='validation')state.l3Tab='model';
if(state.l3Tab==='lab')state.l3Tab='research';
state.l3Tab=['today','portfolio','model','research'].includes(state.l3Tab)?state.l3Tab:'today';
state.screenHorizon=state.screenHorizon||3;
state.l3SelectedSymbol=state.l3SelectedSymbol||null;
state.l3SignalFilter=state.l3SignalFilter||'all';
state.l3Basket=Array.isArray(state.l3Basket)?state.l3Basket:[];
state.l3BasketKey=state.l3BasketKey||'';

const fmtScore=v=>v===null||v===undefined||!Number.isFinite(Number(v))?'—':Number(v).toFixed(3);
const evidence=v=>v===null||v===undefined||!Number.isFinite(Number(v))?'—':Number(v).toFixed(4);
const signedOrDash=v=>v===null||v===undefined||!Number.isFinite(Number(v))?'—':signed(v,1);
const prob=(v,status)=>status==='CALIBRATED_CHRONOLOGICAL_HOLDOUT'?pct(v,1):'—';
const stateLabel={
 NEW:'新出现',STRENGTHENING:'排名增强',PERSISTING:'持续',WEAKENING:'排名走弱',
 NEW_TO_COHORT:'新进入样本',HISTORY_UNAVAILABLE:'历史不足'
};
const stateTone={
 NEW:'blue',STRENGTHENING:'green',PERSISTING:'',WEAKENING:'red',
 NEW_TO_COHORT:'',HISTORY_UNAVAILABLE:''
};
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
 FORWARD_FORECAST_NOT_MATCHED_TO_FROZEN_ALPHA:'Alpha 排名已可用，但条件预测未与当前组合匹配',
 ACTIVE_STRATEGY_RETROSPECTIVE_VALIDATION_UNAVAILABLE:'组合历史验证不可用',
 STRATEGY_REGISTRY_UNAVAILABLE:'策略注册表不可用'
};
const blockers=data=>(data?.blockers||[]).length?
 '<div class="l3-blockers">'+data.blockers.map(x=>'<span class="l3-blocker">'+e(blockerLabels[x]||x)+'</span>').join('')+'</div>':'';

function tabs(){
 const items=[['today','今日机会'],['portfolio','组合构建'],['model','Alpha 模型'],['research','因子研究']];
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
  '<span>当前策略 <b>'+(s?e(s.name+' · v'+s.version):'未启用')+'</b></span>'+
  '<span>观察证券 <b>'+n(data.daily?.observed_security_count,0)+'</b></span>'+
  '<span>有效 Alpha <b>'+n(data.daily?.complete_alpha_score_count,0)+'</b></span>'+
  '<span>候选 <b>'+n(data.daily?.candidate_count,0)+'</b></span>'+
  '<span style="margin-left:auto">'+horizon()+'</span></div>';
}
function signalBadge(x){
 const label=stateLabel[x.signal_state]||'历史不足';
 return badge(label,stateTone[x.signal_state]||'');
}
function rankDelta(x){
 if(x.rank_delta===null||x.rank_delta===undefined||!Number.isFinite(Number(x.rank_delta)))return '—';
 const v=Number(x.rank_delta);
 return v>0?'↑'+v:v<0?'↓'+Math.abs(v):'—';
}
function ageLabel(x){
 if(x.signal_age_sessions===null||x.signal_age_sessions===undefined)return '历史不足';
 return x.signal_age_sessions+' 日';
}
function candidateRows(candidates){
 return candidates.map(x=>[
  '<button type="button" class="btn smallbtn l3-stock-open" data-symbol="'+e(x.symbol)+'"><span class="l3-symbol"><b>'+e(x.symbol)+'</b><small>'+e(x.sector||x.security_id)+'</small></span></button>',
  '<span class="l3-score">'+fmtScore(x.alpha_score)+'</span>',
  pct(x.alpha_rank_pct,0),
  '<span class="'+(Number(x.alpha_delta)>0?'l3-positive':Number(x.alpha_delta)<0?'l3-negative':'')+'">'+signedOrDash(x.alpha_delta)+'</span>',
  rankDelta(x),
  signalBadge(x),
  ageLabel(x),
  signedOrDash(x.expected_excess_return),
  prob(x.p_up,x.probability_status_up),
  (x.primary_factors||[]).map(f=>e(f.factor_name)).join(' / ')||'—'
 ]);
}
function today(data){
 const candidates=data.candidates||[];
 const activeFilter=state.l3SignalFilter;
 const filtered=activeFilter==='all'?candidates:candidates.filter(x=>x.signal_state===activeFilter);
 const counts={};candidates.forEach(x=>{counts[x.signal_state]=(counts[x.signal_state]||0)+1;});
 const filters=[['all','全部',candidates.length],['NEW','新出现',counts.NEW||0],
  ['STRENGTHENING','增强',counts.STRENGTHENING||0],['PERSISTING','持续',counts.PERSISTING||0],
  ['WEAKENING','走弱',counts.WEAKENING||0],['HISTORY_UNAVAILABLE','历史不足',(counts.HISTORY_UNAVAILABLE||0)+(counts.NEW_TO_COHORT||0)]];
 const filterHtml='<div class="l3-filter-row">'+filters.map(x=>
  '<button type="button" class="l3-filter '+(activeFilter===x[0]?'active':'')+'" data-signal-filter="'+x[0]+'">'+
  e(x[1])+' <b>'+x[2]+'</b></button>'
 ).join('')+'</div>';
 const stats=data.daily?grid(4,
  kpi('有效 Alpha',n(data.daily.complete_alpha_score_count,0),'完整因子集 · 不填补缺失','blue')+
  kpi('今日候选',n(data.daily.candidate_count,0),'Alpha 横截面分位 ≥ 80%','green')+
  kpi('历史对照',n(data.daily.signal_history_sessions_available,0),'连续已归档交易日')+
  kpi('条件模型',data.daily.selected_model_variant?e(data.daily.selected_model_variant):'Alpha-only',e(data.daily.model_selection_reason||'无匹配收益预测'))
 ):'';
 const list=card('今日 Alpha 机会',
  filtered.length?'<div class="l3-candidate-table">'+table(
   ['标的','Alpha','分位','Δ Alpha','排名变化','信号状态','持续','H'+state.screenHorizon+' 超额预测','P(up)','主要贡献'],candidateRows(filtered))+'</div>':
   empty('当前筛选下没有候选','系统允许没有合格候选；历史不足不会被伪装成新信号。'),
  'Alpha Score 是加权横截面分位，不是预期收益率');
 const selected=candidates.find(x=>x.symbol===state.l3SelectedSymbol)||candidates[0]||null;
 return strategyHeader(data)+blockers(data)+stats+filterHtml+
  '<div class="l3-task-grid"><div>'+list+'</div><div id="l3-candidate-detail">'+candidateDetail(selected,data)+'</div></div>';
}
function candidateDetail(x,data){
 if(!x)return card('股票判断','<div class="l3-empty">选择一只候选股票查看因子贡献与预测证据。</div>');
 const factors=Object.entries(x.factor_contributions||{}).filter(([,v])=>Number.isFinite(Number(v))).sort((a,b)=>Number(b[1])-Number(a[1]));
 const max=Math.max(...factors.map(([,v])=>Number(v)),.0001);
 const bars=factors.length?factors.map(([name,value])=>
  '<div class="l3-factor-row"><span>'+e(name)+'</span><div class="l3-factor-track"><i style="width:'+Math.max(3,Math.min(100,Number(value)/max*100)).toFixed(1)+'%"></i></div><b>'+fmtScore(value)+'</b></div>'
 ).join(''):empty('暂无贡献分解','当前候选没有可复核的组合因子贡献。');
 const inBasket=state.l3Basket.includes(x.security_id);
 const forecast=x.model_version?
  '<div class="l3-evidence-grid"><span>H'+state.screenHorizon+' 预期超额</span><b>'+signedOrDash(x.expected_excess_return)+'</b><span>总收益预测</span><b>'+signedOrDash(x.expected_gross_return)+'</b><span>P(up)</span><b>'+prob(x.p_up,x.probability_status_up)+'</b><span>P(down)</span><b>'+prob(x.p_downside,x.probability_status_downside)+'</b></div>':
  '<div class="l3-muted-block">没有与当前 Alpha 快照、策略版本及来源完全匹配的收益模型；不显示收益率或概率。</div>';
 return card('机会详情',
  '<div class="l3-detail-head"><div><h3>'+e(x.symbol)+'</h3><p>'+e(x.sector||'行业映射未接入')+' · '+e(x.security_id)+'</p></div>'+signalBadge(x)+'</div>'+
  '<div class="l3-mini-grid"><div class="l3-mini"><span>Alpha Score</span><b>'+fmtScore(x.alpha_score)+'</b></div>'+
  '<div class="l3-mini"><span>横截面分位</span><b>'+pct(x.alpha_rank_pct,0)+'</b></div>'+
  '<div class="l3-mini"><span>Δ Alpha</span><b>'+signedOrDash(x.alpha_delta)+'</b></div>'+
  '<div class="l3-mini"><span>Rank Δ</span><b>'+rankDelta(x)+'</b></div></div>'+
  '<div class="l3-detail-meta"><span>信号持续 <b>'+ageLabel(x)+'</b></span><span>当前排名 <b>#'+e(x.alpha_rank??'—')+'</b></span><span>ADV20 <b>'+moneyMillions(x.adv20)+'</b></span></div>'+
  '<div class="v4-muted-note">因子贡献 · 当前组合权重 × 因子横截面分位</div>'+bars+
  '<div class="l3-detail-section"><b>收益预测证据</b>'+forecast+'</div>'+
  '<div class="l3-detail-section l3-data-limit"><span>事件风险：未接入事件数据，不代表无事件</span><span>历史对照：'+n(x.signal_history_sessions,0)+' 个连续归档交易日</span></div>'+
  '<div class="l3-detail-actions"><button type="button" id="l3-add-basket" class="btn primary" data-security="'+e(x.security_id)+'">'+(inBasket?'已加入组合草案':'加入组合草案')+'</button><span class="v4-muted-note">研究候选，不是买入指令</span></div>',
  '只展示当前归档和匹配模型可证明的字段');
}
function moneyMillions(v){
 if(v===null||v===undefined||!Number.isFinite(Number(v)))return '—';
 return '$'+(Number(v)/1000000).toFixed(1)+'M';
}
function factorOverlap(a,b){
 const left=a.factor_contributions||{},right=b.factor_contributions||{};
 const keys=new Set([...Object.keys(left),...Object.keys(right)]);
 let sumA=0,sumB=0;
 keys.forEach(k=>{sumA+=Math.max(0,Number(left[k])||0);sumB+=Math.max(0,Number(right[k])||0);});
 if(sumA<=0||sumB<=0)return null;
 let overlap=0;
 keys.forEach(k=>{
  const x=Math.max(0,Number(left[k])||0)/sumA;
  const y=Math.max(0,Number(right[k])||0)/sumB;
  overlap+=Math.min(x,y);
 });
 return overlap;
}
function basketKey(data){
 return [data.daily?.session_date_et||'none',data.active_strategy?.id||'none',data.active_strategy?.config_sha256||'none'].join('|');
}
function portfolio(data){
 const candidates=data.candidates||[];
 const key=basketKey(data);
 if(state.l3BasketKey!==key){if(state.l3BasketKey)state.l3Basket=[];state.l3BasketKey=key;}
 const byId=new Map(candidates.map(x=>[String(x.security_id),x]));
 state.l3Basket=state.l3Basket.filter(id=>byId.has(String(id)));
 const selected=state.l3Basket.map(id=>byId.get(String(id))).filter(Boolean);
 const candidateRowsHtml=candidates.map(x=>[
  '<b>'+e(x.symbol)+'</b>',
  pct(x.alpha_rank_pct,0),
  rankDelta(x),
  ageLabel(x),
  moneyMillions(x.adv20),
  state.l3Basket.includes(x.security_id)?
   '<span class="l3-added">已加入</span>':
   '<button type="button" class="btn smallbtn l3-basket-add" data-id="'+e(x.security_id)+'">加入</button>'
 ]);
 const selectedRows=selected.map(x=>[
  '<b>'+e(x.symbol)+'</b>',
  fmtScore(x.alpha_score),
  pct(x.alpha_rank_pct,0),
  ageLabel(x),
  moneyMillions(x.adv20),
  '<button type="button" class="btn smallbtn l3-basket-remove" data-id="'+e(x.security_id)+'">移除</button>'
 ]);
 const pairs=[];
 for(let i=0;i<selected.length;i++)for(let j=i+1;j<selected.length;j++){
  pairs.push([selected[i].symbol,selected[j].symbol,factorOverlap(selected[i],selected[j])]);
 }
 const pairRows=pairs.map(x=>[e(x[0])+' / '+e(x[1]),x[2]===null?'—':pct(x[2],0)]);
 const knownSectors=selected.filter(x=>x.sector).length;
 const knownLiquidity=selected.filter(x=>x.adv20!==null&&x.adv20!==undefined).length;
 const sectorCounts={};selected.forEach(x=>{if(x.sector)sectorCounts[x.sector]=(sectorCounts[x.sector]||0)+1;});
 const topSector=Object.entries(sectorCounts).sort((a,b)=>b[1]-a[1])[0];
 const sectorSummary=knownSectors===selected.length&&selected.length&&topSector?topSector[0]+' '+topSector[1]+'/'+selected.length:'行业映射不完整';
 const averagePct=selected.length?selected.reduce((a,x)=>a+(Number(x.alpha_rank_pct)||0),0)/selected.length:null;
 const overlapValues=pairs.map(x=>x[2]).filter(x=>x!==null);
 const maxOverlap=overlapValues.length?Math.max(...overlapValues):null;
 const summary=grid(4,
  kpi('候选数量',selected.length,'临时草案')+
  kpi('平均 Alpha 分位',averagePct===null?'—':pct(averagePct,0),'不代表收益预测')+
  kpi('行业映射',knownSectors+'/'+selected.length,'缺失不推断')+
  kpi('ADV20 覆盖',knownLiquidity+'/'+selected.length,'美元日均成交额')
 );
 return strategyHeader(data)+blockers(data)+summary+
  '<div class="l3-portfolio-grid"><div class="l3-work-panel">'+
  '<div class="l3-work-head"><b>今日候选池</b><span>'+candidates.length+' 只 · 按 Alpha 分位排序</span></div>'+
  (candidates.length?'<div class="l3-candidate-table">'+table(['标的','分位','Rank Δ','持续','ADV20','操作'],candidateRowsHtml)+'</div>':empty('暂无可用候选','先完成当日 Alpha 快照。'))+
  '</div><div class="l3-work-panel"><div class="l3-work-head"><b>组合草案</b><span>'+selected.length+' 只 · 不含仓位分配</span></div>'+
  (selected.length?'<div class="l3-candidate-table">'+table(['标的','Alpha','分位','持续','ADV20','操作'],selectedRows)+'</div>':empty('尚未选择股票','从左侧候选池加入股票。'))+
  '<div class="l3-overlap-title">因子贡献重叠</div>'+
  (pairRows.length?'<div class="l3-candidate-table">'+table(['股票组合','贡献重叠'],pairRows)+'</div>':'<div class="l3-muted-block">至少选择两只股票后，计算其因子贡献结构重叠。</div>')+
  '</div></div>'+
  '<div class="l3-work-panel l3-portfolio-limits"><b>当前数据边界</b><div class="l3-limit-grid">'+
  '<span>因子贡献重叠</span><b>'+(maxOverlap===null?'—':pct(maxOverlap,0))+'</b>'+
  '<span>价格收益相关性</span><b>未计算</b>'+
  '<span>行业集中度</span><b>'+e(sectorSummary)+'</b>'+
  '<span>事件风险</span><b>未接入事件数据</b>'+
  '</div><p>重叠度仅比较当前 Alpha 因子贡献构成，不是收益相关系数；L3 只整理候选，不计算仓位、止损或交易许可，后续由 L4 风控处理。</p>'+
  '<div class="l3-detail-actions"><button type="button" id="l3-clear-basket" class="btn">清空草案</button><span class="v4-muted-note">草案仅保存在当前浏览器会话；刷新页面会清空。</span></div></div>';
}
function activeFactorEvidence(data){
 const active=data.active_strategy;
 if(!active)return empty('尚未启用 Alpha 模型','先从已完成的因子实验中选择 2–8 个因子，保存并冻结组合。');
 const library=new Map((data.factor_library||[]).map(x=>[x.experiment_id,x]));
 const rows=(active.factors||[]).map(f=>{
  const ev=library.get(f.experiment_id);
  return [
   '<b>'+e(f.factor_name)+'</b><small class="l3-subline">v'+e(f.factor_version)+'</small>',
   pct(f.weight,0),
   ev?e(evidence(ev.rank_ic_mean)):'—',
   ev?e(evidence(ev.icir_unannualized)):'—',
   ev?pct(ev.label_pair_coverage,0):'—',
   ev?n(ev.daily_ic_count,0):'—',
   ev?e(evidence(ev.top_bottom_price_spread)):'—'
  ];
 });
 return rows.length?'<div class="l3-candidate-table">'+table(
  ['因子','冻结权重','验证 Rank IC','ICIR','覆盖率','有效日','Top-Bottom Spread'],rows)+'</div>':
  empty('当前组合没有因子','策略配置为空。');
}
function model(data){
 const active=data.active_strategy;
 const evidenceHtml=activeFactorEvidence(data);
 const validationHtml=validation(data);
 const strategyHtml=strategy(data);
 return strategyHeader(data)+blockers(data)+
  card('当前 Alpha 模型',evidenceHtml,
   '权重来自已冻结策略；不是每日自动调权。因子统计仅在有匹配历史实验时显示')+
  '<div class="l3-model-note">当前实现没有经过验证的动态权重引擎，因此不展示 ΔW、Regime Fit 或健康标签。上表权重是冻结组合配置；IC / ICIR 来自历史实验，不代表未来收益保证。</div>'+
  '<div class="l3-model-validation">'+validationHtml+'</div>'+
  '<div class="l3-model-config">'+strategyHtml+'</div>';
}
function strategy(data){
 const active=data.active_strategy;
 const activeMap=new Map((active?.factors||[]).map(x=>[x.experiment_id,x]));
 const library=data.factor_library||[];
 const factorRows=library.length?library.map(f=>{
  const selected=activeMap.get(f.experiment_id);const weight=selected?Math.round(Number(selected.weight)*100):0;
  return '<label class="l3-factor-pick"><input type="checkbox" class="l3-factor-check" data-exp="'+e(f.experiment_id)+'"'+(selected?' checked':'')+' />'+
   '<span><div class="l3-factor-name">'+e(f.factor_name||'未命名因子')+' · v'+e(f.factor_version||'—')+'</div>'+
   '<div class="l3-factor-evidence">H'+state.screenHorizon+' Rank IC '+e(evidence(f.rank_ic_mean))+' · ICIR '+e(evidence(f.icir_unannualized))+' · 覆盖 '+pct(f.label_pair_coverage,0)+' · '+n(f.symbol_count,0)+' 证券 · '+e(f.universe_version||'未知股票池')+'</div></span>'+
   '<input type="number" class="l3-factor-weight" min="0" max="100" step="1" value="'+weight+'" aria-label="'+e(f.factor_name)+' 权重百分比" /></label>';
 }).join(''):empty('暂无已完成的因子实验','先到「因子研究」创建并完成真实历史实验。');
 const activeInfo=active?'<div class="l3-active-factors">'+(active.factors||[]).map(x=>'<span class="l3-factor-chip">'+e(x.factor_name)+' '+pct(x.weight,0)+'</span>').join('')+'</div>':
  empty('没有当前组合','保存组合后系统会先冻结该版本，再显式设为当前 L3 组合。');
 const strategies=(data.strategies||[]).map(s=>[
  e(s.name)+' · v'+e(s.version),'H'+e(s.horizon),e(s.status),
  '<button type="button" class="btn smallbtn l3-activate" data-id="'+e(s.id)+'">'+(s.status==='FROZEN'?'启用':'冻结并启用')+'</button>'
 ]);
 return '<div class="l3-strategy-layout">'+
  card('因子库与权重配置',factorRows,'选择 2–8 个已完成实验 · 权重合计 100%')+
  card('保存 Alpha 组合',
   '<div class="v4-form"><div class="v4-field"><label for="l3-strategy-name">组合名称</label><input id="l3-strategy-name" maxlength="80" value="'+e(active?.name||'Alpha 组合')+'" /></div></div>'+
   activeInfo+'<div class="l3-strategy-actions">'+button('l3-save-strategy','保存新版本并启用','primary')+
   '<span class="v4-muted-note">版本冻结后不可覆盖；启用新版本不修改历史快照。</span></div>',
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
 const factorLabels=new Map((data.active_strategy?.factors||[]).map(x=>[x.experiment_id,x.factor_name]));
 const rankTable=ranks.length?table(['模型','H','Rank IC','ICIR','样本日'],ranks.map(x=>[
  e(({A:'Alpha',B:'Alpha + L1',C:'Alpha + L2',D:'Full'})[x.variant]||x.variant),
  e(state.screenHorizon),e(evidence(x.rank_ic_mean)),e(evidence(x.rank_icir_unannualized)),n(x.sessions,0)
 ])):empty('暂无匹配的 OOS 模型比较','只有与当前组合因子集合和来源快照一致的研究才会显示。');
 const outcomes=data.outcomes||[];
 const outcomeRows=outcomes.length?'<div class="l3-outcome-list">'+outcomes.map(x=>
  '<div class="l3-outcome"><b>'+e(x.session_date_et)+'</b><span>'+e(x.status)+' · '+n(x.evaluated_trades,0)+' 个已到期研究候选</span><span>'+signedOrDash(x.mean_modeled_net_return)+'</span></div>'
 ).join('')+'</div>':empty('暂无完成期限的前向结果','冻结预测到达 H1/H3/H5 后才进入这里，不用历史结果倒填。');
 return '<div class="grid cols2">'+
  card('因子组合历史验证',summary+
   (v?.factor_correlations?.length?'<div class="l3-candidate-table">'+table(['因子 A','因子 B','Spearman 相关','有效日'],v.factor_correlations.map(x=>[
    e(factorLabels.get(x.factor_a)||x.factor_a||'—'),e(factorLabels.get(x.factor_b)||x.factor_b||'—'),e(evidence(x.median_daily_spearman)),n(x.valid_sessions,0)
   ]))+'</div>':''),
   v?'历史回顾性证据 · 非 PIT 证明':'无验证证据')+
  card('A / B / C / D 条件模型',rankTable+
   note(m?.selection_reason==='FULL_MODEL_PAIRED_OOS_INCREMENT_CONFIRMED'?
    'Full 模型在配对 OOS 中通过既定概率与收益误差增量门。':
    '没有足够证据证明 L1/L2 条件变量优于 Alpha-only；默认不强行启用 Full。'),
   m?e(m.selection_reason):'无匹配证据')+
  '</div><div style="margin-top:14px">'+card('前向结果回填',outcomeRows,'只读已到期的冻结预测结果')+'</div>';
}
function research(data){
 return strategyHeader(data)+card('因子研究',
  '<div class="l3-research-entry"><div><b>因子构建与验证</b><p>在独立因子实验室创建/复制因子，定义信号、窗口、方向与标准化；运行冻结历史实验，再比较 IC、覆盖率和分组结果。</p></div>'+
  button('l3-open-factor-lab','打开因子实验室','primary')+'</div>',
  '研究实验不自动修改当前 Alpha Core');
}
pages.screen=async()=>{
 const section=state.l3Tab==='model'?'model':state.l3Tab==='portfolio'?'portfolio':'today';
 const r=await settle('/api/v1/l3/overview?horizon='+encodeURIComponent(state.screenHorizon)+'&limit=20&section='+encodeURIComponent(section));
 if(!r.ok){
  const content=heading('个股 Alpha','今日机会 → 候选组合 → Alpha 模型 → 因子研究',
   link('/studio#lab','因子实验室'))+tabs()+(r.pending?moduleLoading('L3 Alpha'):empty('L3 数据暂不可用',String(r.error?.message||'研究证据尚未形成')));
  return {title:'个股 Alpha',html:content,mount:mountTabs};
 }
 const data=r.data;
 const currentBasketKey=basketKey(data);
 if(state.l3BasketKey!==currentBasketKey){state.l3Basket=[];state.l3BasketKey=currentBasketKey;}
 let body=state.l3Tab==='today'?today(data):
  state.l3Tab==='portfolio'?portfolio(data):
  state.l3Tab==='model'?model(data):research(data);
 const html=heading('个股 Alpha','基于冻结因子组合的每日横截面机会研究',
  link('/strategies','完整策略工具')+link('/backtests','严格回测'))+tabs()+body;
 return {title:'个股 Alpha',html,mount(){
  mountTabs();mountCommon();
  if(state.l3Tab==='today')mountToday(data);
  if(state.l3Tab==='portfolio')mountPortfolio(data);
  if(state.l3Tab==='model')mountStrategy(data);
  if(state.l3Tab==='research')mountResearch();
 }};
};
function mountTabs(){
 const tabs=[...document.querySelectorAll('[data-l3-tab]')];
 const activate=btn=>{
  const key=btn.dataset.l3Tab;
  if(key==='research'){state.l3Tab='research';go('lab');return;}
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
 document.querySelectorAll('[data-signal-filter]').forEach(btn=>btn.addEventListener('click',()=>{
  state.l3SignalFilter=btn.dataset.signalFilter;show('screen');
 }));
 const candidates=data.candidates||[];
 document.querySelectorAll('.l3-stock-open').forEach(btn=>btn.addEventListener('click',()=>{
  const item=candidates.find(x=>String(x.symbol)===String(btn.dataset.symbol));if(!item)return;
  state.l3SelectedSymbol=item.symbol;
  const target=$('#l3-candidate-detail');if(target)target.innerHTML=candidateDetail(item,data);
  document.querySelectorAll('.l3-candidate-table tbody tr').forEach(x=>x.classList.remove('selected'));
  btn.closest('tr')?.classList.add('selected');
  mountDetailAction();
 }));
 if(state.l3SelectedSymbol){
  const btn=[...document.querySelectorAll('.l3-stock-open')].find(x=>x.dataset.symbol===state.l3SelectedSymbol);
  btn?.click();
 }
 mountDetailAction();
}
function mountDetailAction(){
 $('#l3-add-basket')?.addEventListener('click',btn=>{
  const id=btn.currentTarget.dataset.security;
  if(!state.l3Basket.includes(id))state.l3Basket.push(id);
  refresh('/api/v1/l3/overview');
 });
}
function mountPortfolio(data){
 document.querySelectorAll('.l3-basket-add').forEach(btn=>btn.addEventListener('click',()=>{
  const id=btn.dataset.id;if(!state.l3Basket.includes(id))state.l3Basket.push(id);
  show('screen');
 }));
 document.querySelectorAll('.l3-basket-remove').forEach(btn=>btn.addEventListener('click',()=>{
  state.l3Basket=state.l3Basket.filter(x=>x!==btn.dataset.id);show('screen');
 }));
 $('#l3-clear-basket')?.addEventListener('click',()=>{state.l3Basket=[];show('screen');});
}
function mountResearch(){
 $('#l3-open-factor-lab')?.addEventListener('click',()=>go('lab'));
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
  state.l3Basket=[];refresh('/api/v1/l3/');
 }));
 document.querySelectorAll('.l3-activate').forEach(btn=>btn.addEventListener('click',()=>action(async()=>{
  const id=btn.dataset.id;const row=(data.strategies||[]).find(x=>x.id===id);
  if(!row)throw Error('组合版本不存在');
  if(row.status!=='FROZEN')await api('/api/v1/strategies/'+encodeURIComponent(id)+'/freeze',{});
  await api('/api/v1/l3/active-strategy',{strategy_version_id:id});
  toast('已切换当前 Alpha 组合');
  state.l3Basket=[];refresh('/api/v1/l3/');
 })));
}
})();
