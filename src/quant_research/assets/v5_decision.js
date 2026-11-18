/* QDR V5 decision desk — decision context first, diagnostics only on exception. */
(() => {
'use strict';
const V=window.V4;if(!V)throw Error('QDR V5 requires V4 core');
const {pages,e,n,pct,signed,date,settle}=V;
const STYLE_LABELS={size:'规模',value:'价值',growth:'成长',momentum:'动量',quality:'质量',low_vol:'低波动',cyc_def:'周期 / 防御'};
const ROT={STRONG_ACCELERATING:'强势加速',STRONG_DECELERATING:'强势减速',WEAK_IMPROVING:'弱势改善',WEAK_DETERIORATING:'弱势恶化',UNKNOWN:'待判定'};
const finite=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
const bad=v=>/BLOCKED|FAILED|INVALID|NOT_READY|ERROR/i.test(String(v||''));
const DIGEST=/^[a-f0-9]{64}$/;
const styleName=id=>STYLE_LABELS[id]||id||'—';
const rotationName=s=>ROT[s]||'待判定';
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
const tone=v=>!finite(v)?'':Number(v)>0?'is-up':Number(v)<0?'is-down':'';
const metric=(label,value,sub='',cls='')=>'<div class="desk-metric"><span>'+e(label)+'</span><strong class="'+e(cls)+'">'+value+'</strong><small>'+e(sub)+'</small></div>';
const head=(title,action='')=>'<div class="desk-section-head"><h2>'+e(title)+'</h2>'+action+'</div>';
const empty=(title,detail)=>'<div class="desk-empty"><b>'+e(title)+'</b><span>'+e(detail)+'</span></div>';
function candidates(rows){
 if(!rows.length)return empty('今日无候选','没有股票通过当前研究过滤；不交易是有效结果。');
 return '<div class="desk-table-wrap"><table class="desk-table"><thead><tr><th>股票</th><th>净优势</th><th>参考权重</th><th>状态</th></tr></thead><tbody>'+rows.slice(0,8).map(x=>'<tr><td class="desk-symbol">'+e(x.symbol||x.security_id||'—')+'</td><td class="'+tone(x.estimated_net_edge)+'">'+signed(x.estimated_net_edge)+'</td><td>'+pct(x.indicative_weight)+'</td><td>通过过滤</td></tr>').join('')+'</tbody></table></div>';
}
function humanizeTopbar(){
 const el=document.getElementById('v4-source-status');if(!el)return;
 const apply=()=>{const raw=String(el.textContent||'').trim();const map={CURRENT:'正常',FRESH:'正常',STALE:'已过期',BLOCKED:'异常',FAILED:'异常',MISSING:'待检查','待验证':'待检查','核验中':'核验中'};if(map[raw]&&el.textContent!==map[raw])el.textContent=map[raw];};
 apply();new MutationObserver(apply).observe(el,{childList:true,characterData:true,subtree:true});
}
pages.overview=async()=>{
 const [freshR,l1R,l2R,plansR,riskR,dailyR,layersR]=await Promise.all([settle('/api/v1/v4/freshness'),settle('/api/v1/l1/market/overview?horizon=3'),settle('/api/v1/l2/styles/overview?rotation=1'),settle('/api/v1/v4/plans'),settle('/api/v1/paper/risk'),settle('/api/v1/v4/daily'),settle('/api/v1/v4/layers?horizon=3')]);
 const fresh=freshR?.ok?freshR.data:null,l1=l1R?.ok?l1R.data:null,l2=l2R?.ok?l2R.data:null,risk=riskR?.ok?riskR.data:null,daily=dailyR?.ok?dailyR.data:null,layers=layersR?.ok?layersR.data:null;
 const f=okForecast(l1,fresh);
 const items=Array.isArray(l2?.latest)?l2.latest:[],leaders=items.filter(x=>finite(x.relative_return_20d)).sort((a,b)=>Number(b.relative_return_20d)-Number(a.relative_return_20d)),leader=leaders[0]||null;
 const rotation=Array.isArray(l2?.rotation?.latest)?l2.rotation.latest:[],leaderRot=leader?rotation.find(x=>x.style_id===leader.style_id):null;
 const planInfo=(plansR?.ok?plansR.data?.records||[]:[])[0]||null;let plan=null;
 if(planInfo&&planInfo.status!=='CORRUPT_RESEARCH_PLAN'){const d=await settle('/api/v1/v4/plans/'+encodeURIComponent(planInfo.session_date_et)+'/'+encodeURIComponent(planInfo.identity));plan=d?.ok?d.data:null;}
 const rows=Array.isArray(plan?.plans)?plan.plans:[],hasRisk=risk?.status==='CONCENTRATION_MEASURED',alerts=hasRisk&&Array.isArray(risk.alerts)?risk.alerts:[];
 const stages=(daily?.runs||[])[0]?.stages||[],issues=stages.filter(x=>bad(x.status)),freshness=fresh?.modules?.market_observation?.freshness_status||'待检查';
 const day=fresh?.asof_session||l1?.asof_session||l2?.asof_session||planInfo?.session_date_et||'—';
 const marketMain=f?pct(f.p_up):'待验证',marketSub=f?'H3 上涨概率 · 预期 '+signed(f.expected_return):l1?'仅市场观察':'数据待检查';
 const styleMain=leader?styleName(leader.style_id):'—',styleSub=leader?rotationName(leaderRot?.rotation_state)+' · 20D '+signed(leader.relative_return_20d):'暂无可比较风格';
 const riskMain=hasRisk?(alerts.length?n(alerts.length,0)+' 项预警':'正常'):'待核对',riskSub=hasRisk?'组合权益 '+pct(risk.gross_weight):'持仓账本未形成';
 const drivers=Array.isArray(l1?.drivers)?l1.drivers.filter(x=>x&&x.label&&finite(x.delta)).slice(0,4):[];
 const turns=rotation.filter(x=>['WEAK_IMPROVING','STRONG_ACCELERATING','STRONG_DECELERATING','WEAK_DETERIORATING'].includes(x.rotation_state)).slice(0,4);
 const changes=[...drivers.map(x=>({type:'市场',name:x.label,value:'日变化 '+signed(x.delta),tone:tone(x.delta)})),...turns.map(x=>({type:'风格',name:styleName(x.style_id),value:rotationName(x.rotation_state),tone:/ACCELERATING|IMPROVING/.test(x.rotation_state)?'is-up':'is-down'}))].slice(0,6);
 const changesHtml=changes.length?'<div class="desk-change-list">'+changes.map(x=>'<div class="desk-change"><span>'+e(x.type)+'</span><b>'+e(x.name)+'</b><em class="'+e(x.tone)+'">'+e(x.value)+'</em></div>').join('')+'</div>':empty('暂无显著变化','当前数据没有新的可归纳变化。');
 const riskHtml=hasRisk?'<div class="desk-risk-grid"><div><span>组合权益仓位</span><b>'+pct(risk.gross_weight)+'</b></div><div><span>规则预警</span><b class="'+(alerts.length?'is-down':'is-up')+'">'+n(alerts.length,0)+'</b></div>'+(alerts.length?alerts.slice(0,4).map(x=>'<div><span>'+e(x.subject||'风险项')+'</span><b class="is-down">'+e(x.code||'已触发')+'</b></div>').join(''):'<div><span>规则状态</span><b class="is-up">未触发超限</b></div>')+'</div>':empty('风险待核对','当前没有已内部对账的持仓风险结果。');
 const layer=layers?.layers||{},blockers=Array.isArray(layers?.blockers)?layers.blockers:[];
 const layerText=(id)=>{
  if(id==='l1')return layer.l1_market?.downstream_context_eligible?'已准入':'研究中';
  if(id==='l2')return layer.l2_style?.l3_style_context_available?n(layer.l2_style.admitted_units||0,0)+' 单元':'未准入';
  if(id==='l3')return layer.l3_alpha?.style_input_binding_verified?(layer.l3_alpha?.style_historical_pit_attested?'绑定 + PIT':'已绑定 · PIT 待验'):'未绑定';
  return ['RESEARCH_PLANS_ONLY','NO_RESEARCH_CANDIDATES'].includes(layer.l4_risk?.status)?'已复核':'待复核';
 };
 const chainHtml=layers?'<div class="desk-layer-chain"><div><span>L1 市场</span><b>'+e(layerText('l1'))+'</b></div><div><span>L2 风格</span><b>'+e(layerText('l2'))+'</b></div><div><span>L3 Alpha</span><b>'+e(layerText('l3'))+'</b></div><div><span>L4 风控</span><b>'+e(layerText('l4'))+'</b></div></div>'+
  (blockers.length?'<details class="desk-layer-detail"><summary>当前 '+n(blockers.length,0)+' 项研究阻断</summary><p>'+e(blockers.slice(0,5).join(' · '))+'</p></details>':'<div class="desk-layer-ready">四层研究证据已对齐</div>'):
  empty('研究链待核对','四层资格快照当前不可用。');
 const exception=issues.length||/STALE|BLOCKED|FAILED|MISSING/.test(String(freshness))?'<div class="desk-exception"><b>需要处理</b><span>'+e([/STALE|BLOCKED|FAILED|MISSING/.test(String(freshness))?'市场数据 '+freshness:'',...issues.slice(0,3).map(x=>(x.stage||'流程')+' · '+(x.code||x.status))].filter(Boolean).join('；'))+'</span><a href="/studio#warehouse">查看诊断 →</a></div>':'';
 const html='<div class="desk"><div class="desk-head"><div><div class="desk-kicker">US EQUITY · EOD</div><h1>每日决策</h1><p>'+e(day)+' · 收盘后研究快照</p></div><div class="desk-links"><a href="/studio#market">市场</a><a href="/studio#style">风格</a><a href="/studio#screen">选股</a><a href="/studio#risk">风控</a></div></div>'+
 exception+'<div class="desk-tape">'+metric('H3 市场',marketMain,marketSub,f?'':'is-muted')+metric('相对强势风格',e(styleMain),styleSub)+metric('候选',n(rows.length,0)+' 个',rows.length?'通过当前过滤':'当前无机会')+metric('组合风险',riskMain,riskSub,alerts.length?'is-down':'')+'</div>'+
 '<div class="desk-layout"><main class="desk-primary"><section class="desk-section">'+head('今日候选','<a href="/studio#screen">完整选股 →</a>')+candidates(rows)+'</section><section class="desk-section">'+head('今日变化','<a href="/studio#style">风格轮动 →</a>')+changesHtml+'</section></main>'+
 '<aside class="desk-context"><section class="desk-section">'+head('决策上下文')+'<div class="desk-context-list"><div><span>市场</span><b>'+marketMain+'</b><small>'+e(marketSub)+'</small></div><div><span>风格</span><b>'+e(styleMain)+'</b><small>'+e(styleSub)+'</small></div><div><span>候选</span><b>'+n(rows.length,0)+' 个</b><small>'+(rows.length?'进入风险过滤':'无通过项')+'</small></div></div></section><section class="desk-section">'+head('研究链资格')+chainHtml+'</section><section class="desk-section">'+head('持仓与风险','<a href="/studio#risk">详情 →</a>')+riskHtml+'</section></aside></div>'+
 '<div class="desk-footer"><span>数据 '+e(freshness)+'</span><a href="/studio#warehouse">数据与保障</a><a href="/studio#data">研究准入</a></div></div>';
 return {title:'每日决策',html};
};
document.addEventListener('DOMContentLoaded',humanizeTopbar);
})();