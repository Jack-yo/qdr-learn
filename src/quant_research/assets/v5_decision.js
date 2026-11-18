/* QDR V5 decision-first overview. Existing read-only APIs only. */
(() => {
'use strict';
const V=window.V4;if(!V)throw Error('QDR V5 requires V4 core');
const {pages,e,n,pct,signed,date,settle}=V;
const STYLE_LABELS={size:'规模',value:'价值',growth:'成长',momentum:'动量',quality:'质量',low_vol:'低波动',cyc_def:'周期 / 防御'};
const finite=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
const bad=v=>/BLOCKED|FAILED|INVALID|NOT_READY|ERROR/i.test(String(v||''));
const DIGEST=/^[a-f0-9]{64}$/;
const styleName=id=>STYLE_LABELS[id]||id||'—';
const okForecast=(data,fresh)=>{
 if(!data||data.schema!=='qdr.l1.market.v1'||data.asof_session!==fresh?.asof_session)return null;
 const statusOk=data.status==='FROZEN_FORWARD_RESEARCH_ONLY'?
  data.research_only===true&&data.model_admitted===false&&data.real_orders_enabled===false:
  data.status==='MODEL_OOS_ADMITTED'&&data.model_admitted===true&&data.historical_pit_verified===true&&data.source_independently_attested===true&&data.real_orders_enabled===false;
 const cutoff=Date.parse(data.knowledge_cutoff_utc||''),frozen=Date.parse(data.frozen_at_utc||''),entry=Date.parse(data.entry_at_utc||'');
 if(!statusOk||!DIGEST.test(data.source_snapshot_sha256||'')||!data.model_version||!Number.isFinite(cutoff)||!Number.isFinite(frozen)||!Number.isFinite(entry)||frozen<cutoff||cutoff>=entry)return null;
 const f=data.forecast;
 if(!f||Number(f.horizon)!==3||!finite(f.p_up)||Number(f.p_up)<0||Number(f.p_up)>1||!finite(f.expected_return)||!Array.isArray(f.quantiles)||f.quantiles.length!==5||f.quantiles.some(x=>!finite(x))||f.quantiles.some((x,i)=>i>0&&Number(x)<Number(f.quantiles[i-1])))return null;
 return f;
};
function summary(label,value,hint,cls=''){return '<div class="v5-summary-item"><span>'+e(label)+'</span><b class="'+e(cls)+'">'+value+'</b><small>'+e(hint)+'</small></div>';}
function panel(title,body,action='',meta=''){return '<section class="v5-panel"><div class="v5-panel-head"><div><h2>'+e(title)+'</h2>'+(meta?'<div class="v5-panel-meta">'+e(meta)+'</div>':'')+'</div>'+action+'</div>'+body+'</section>';}
function emptyState(title,detail){return '<div class="v5-empty"><b>'+e(title)+'</b>'+e(detail)+'</div>';}
function candidateTable(rows){
 if(!rows.length)return emptyState('今日暂无候选','当前研究计划没有股票通过全部过滤条件。');
 return '<table class="v5-candidate-table"><thead><tr><th>股票</th><th>预期净优势</th><th>参考权重</th></tr></thead><tbody>'+rows.slice(0,6).map(x=>'<tr><td><b>'+e(x.symbol||x.security_id||'—')+'</b></td><td>'+signed(x.estimated_net_edge)+'</td><td>'+pct(x.indicative_weight)+'</td></tr>').join('')+'</tbody></table>';
}
function humanizeTopbar(){
 const el=document.getElementById('v4-source-status');if(!el)return;
 const apply=()=>{const raw=String(el.textContent||'').trim();const map={CURRENT:'正常',FRESH:'正常',STALE:'已过期',BLOCKED:'异常',FAILED:'异常',MISSING:'待检查','待验证':'待检查'};if(map[raw]&&el.textContent!==map[raw])el.textContent=map[raw];};
 apply();new MutationObserver(apply).observe(el,{childList:true,characterData:true,subtree:true});
}
pages.overview=async()=>{
 const [freshR,l1R,l2R,plansR,riskR,dailyR]=await Promise.all([settle('/api/v1/v4/freshness'),settle('/api/v1/l1/market/overview?horizon=3'),settle('/api/v1/l2/styles/overview?rotation=1'),settle('/api/v1/v4/plans'),settle('/api/v1/paper/risk'),settle('/api/v1/v4/daily')]);
 const fresh=freshR?.ok?freshR.data:null,l1=l1R?.ok?l1R.data:null,l2=l2R?.ok?l2R.data:null,risk=riskR?.ok?riskR.data:null,daily=dailyR?.ok?dailyR.data:null;
 const f=okForecast(l1,fresh);
 const items=Array.isArray(l2?.latest)?l2.latest:[],leaders=items.filter(x=>finite(x.relative_return_20d)).sort((a,b)=>Number(b.relative_return_20d)-Number(a.relative_return_20d)),leader=leaders[0]||null;
 const rotation=Array.isArray(l2?.rotation?.latest)?l2.rotation.latest:[];
 const planInfo=(plansR?.ok?plansR.data?.records||[]:[])[0]||null;let plan=null;
 if(planInfo&&planInfo.status!=='CORRUPT_RESEARCH_PLAN'){const detail=await settle('/api/v1/v4/plans/'+encodeURIComponent(planInfo.session_date_et)+'/'+encodeURIComponent(planInfo.identity));plan=detail?.ok?detail.data:null;}
 const candidates=Array.isArray(plan?.plans)?plan.plans:[],hasRisk=risk?.status==='CONCENTRATION_MEASURED',alerts=hasRisk&&Array.isArray(risk.alerts)?risk.alerts:[];
 const day=fresh?.asof_session||l1?.asof_session||l2?.asof_session||planInfo?.session_date_et||'—';
 const marketValue=f?pct(f.p_up):'待验证',marketHint=f?'H3 上涨概率 · 预期收益 '+signed(f.expected_return):l1?'当前仅有市场观察':'市场数据待检查';
 const styleValue=leader?styleName(leader.style_id):'—',styleHint=leader?'20D 相对收益 '+signed(leader.relative_return_20d):'暂无可比较风格';
 const candidateValue=candidates.length?n(candidates.length,0)+' 个':'0 个',candidateHint=candidates.length?'已通过当前研究过滤':'没有强制生成交易';
 const riskValue=hasRisk?(alerts.length?n(alerts.length,0)+' 项':'正常'):'待核对',riskHint=hasRisk?'组合规则预警':'持仓账本尚未形成';
 const driverChanges=Array.isArray(l1?.drivers)?l1.drivers.filter(x=>x&&x.label&&finite(x.delta)).slice(0,3):[];
 const rotationChanges=rotation.filter(x=>['WEAK_IMPROVING','STRONG_ACCELERATING','STRONG_DECELERATING','WEAK_DETERIORATING'].includes(x.rotation_state)).slice(0,3);
 const changes=[...driverChanges.map(x=>['市场',x.label,'日变化 '+signed(x.delta)]),...rotationChanges.map(x=>['风格',styleName(x.style_id),({WEAK_IMPROVING:'弱势改善',STRONG_ACCELERATING:'强势加速',STRONG_DECELERATING:'强势减速',WEAK_DETERIORATING:'弱势恶化'})[x.rotation_state]])].slice(0,5);
 const stages=(daily?.runs||[])[0]?.stages||[],issues=stages.filter(x=>bad(x.status)),freshness=fresh?.modules?.market_observation?.freshness_status||'待检查';
 const changesHtml=changes.length?'<div class="v5-change-list">'+changes.map(x=>'<div class="v5-change"><span>'+e(x[0])+'</span><b>'+e(x[1])+'</b><em>'+e(x[2])+'</em></div>').join('')+'</div>':emptyState('今日没有显著变化','当前已返回的数据中没有新的可归纳变化。');
 const riskHtml=hasRisk?'<div class="v5-risk-line"><span>组合权益仓位</span><b>'+pct(risk.gross_weight)+'</b></div><div class="v5-risk-line"><span>规则预警</span><b class="'+(alerts.length?'v5-alert':'v5-quiet')+'">'+n(alerts.length,0)+'</b></div>'+(alerts.length?alerts.slice(0,3).map(x=>'<div class="v5-risk-line"><span>'+e(x.subject||x.code||'风险项')+'</span><b class="v5-alert">'+e(x.code||'已触发')+'</b></div>').join(''):'<div class="v5-risk-line"><span>当前状态</span><b class="v5-quiet">未触发规则超限</b></div>'):emptyState('风险账本待核对','没有已内部对账的组合风险结果。');
 const healthRows=[['市场数据',freshness],['L1 预测',f?'可用':l1?'待验证':'待检查'],['L2 风格',l2?.status==='OBSERVATION_ONLY'?'观察可用':l2?'已返回':'待检查'],['日终流程',issues.length?issues.length+' 项异常':'无阻断']];
 const health='<div class="v5-health">'+healthRows.map(x=>'<div class="v5-health-row"><span>'+e(x[0])+'</span><b class="'+(String(x[1]).includes('异常')?'v5-alert':'')+'">'+e(x[1])+'</b></div>').join('')+'</div>'+(issues.length?'<div class="v5-footnote">'+e(issues.slice(0,3).map(x=>(x.stage||'任务')+' · '+(x.code||x.status)).join('；'))+'</div>':'');
 const html='<div class="v5-page"><div class="heading v5-decision-head"><div><h1>每日决策</h1><p>'+e(day)+' · 收盘后研究快照</p></div><div class="v5-head-actions"><a href="/studio#warehouse">数据与保障</a><a href="/studio#data">研究准入</a></div></div>'+
 '<div class="v5-summary-strip">'+summary('市场',marketValue,marketHint)+summary('相对强势风格',e(styleValue),styleHint)+summary('候选',candidateValue,candidateHint)+summary('组合风险',riskValue,riskHint,alerts.length?'v5-alert':'')+'</div>'+
 '<div class="v5-main-grid">'+panel('今日候选',candidateTable(candidates),'<a href="/studio#screen">查看选股 →</a>',planInfo?'研究日 '+date(planInfo.session_date_et):'')+panel('持仓与风险',riskHtml,'<a href="/studio#risk">查看风控 →</a>')+'</div>'+
 '<div class="v5-main-grid">'+panel('今日变化',changesHtml,'<a href="/studio#market">市场详情 →</a>')+panel('数据与模型状态',health,'<a href="/studio#warehouse">诊断 →</a>')+'</div>'+
 '<div class="v5-footnote">首页只汇总影响今日判断的信息；模型版本、PIT、校准和完整研究证据保留在各研究页与研究准入中。</div></div>';
 return {title:'每日决策',html};
};
document.addEventListener('DOMContentLoaded',humanizeTopbar);
})();