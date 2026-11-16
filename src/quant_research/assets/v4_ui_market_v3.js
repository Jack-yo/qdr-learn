/* QDR L1 V3 progressive market experience. Preserve V4's original dark theme.
 * No illustrative forecast values, fabricated history, model weights or signals.
 * V2 remains available as a legacy research view, not deleted.
 */
(() => {
'use strict';
const V=window.V4;
if(!V) throw Error('V3 needs the existing V4 core');
const {pages,state,settle,show,e,n}=V;
const legacyMarket=pages.market;
const S={horizon:[1,3,5].includes(state.marketHorizon)?state.marketHorizon:3,
         category:'all',legacyMode:false,expanded:false,force:false};
const categories=[
  ['all','全部'],['price','价格与趋势'],['breadth','市场广度'],
  ['options','波动与期权'],['credit','信用与利率'],
  ['positioning','资金与持仓'],['events','宏观与事件']
];
const domainCategories={
  price:'price',breadth:'breadth',volatility:'options',options_pricing:'options',
  options_positioning:'options',microstructure:'positioning',correlation:'breadth',
  cross_asset:'credit',positioning:'positioning',events:'events',
  funding:'credit',path:'options'
};
const DOMAIN_NAMES={
  price:'价格与趋势',breadth:'市场广度',volatility:'波动率',
  options_pricing:'期权风险定价',options_positioning:'期权持仓',
  microstructure:'市场微观结构',correlation:'相关性与离散度',
  cross_asset:'跨资产风险传导',positioning:'资金与持仓',
  events:'宏观事件',funding:'融资条件',path:'路径风险'
};
const statuses={OBSERVED:'已观测',PARTIAL:'部分覆盖',MISSING:'待接入'};
const isNum=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
const fmt=(v,d=2)=>isNum(v)?n(Number(v),d):'—';
const sign=(v,d=2)=>isNum(v)?(Number(v)>0?'+':'')+n(Number(v),d):'—';
const moveClass=v=>isNum(v)?Number(v)>0?'is-up':Number(v)<0?'is-down':'is-flat':'is-flat';
const percent=v=>isNum(v)?n(Number(v)*100,1)+'%':'—';
const emDash='—';
const stripTime=t=>t?e(String(t).replace('T',' ').slice(0,16)):'—';
const box=(cls,inner)=>'<section class="lv3-panel '+cls+'">'+inner+'</section>';
const title=(name,more='')=>'<div class="lv3-panel-title"><h2>'+e(name)+'</h2>'+more+'</div>';
const errorText=r=>r?.pending?'正在读取真实数据…':r?.error?.message||'当前来源尚未取得可核验数据';
const pill=(text,cls='')=>'<span class="lv3-pill '+cls+'">'+e(text)+'</span>';
const pClass=key=>key==='UP'?'up':key==='DOWN'?'down':'flat';
const pName={UP:'上涨',FLAT:'震荡',DOWN:'下跌'};
const rawKeyRank={
 SPY:0,spy_return_5:1,breadth_proxy_rsp_spy_5:2,small_cap_relative_5:3,
 rv5:4,vol_ratio:5,vix:6,cboe_pcr_total:7,treasury_10y_pct:8,ofr_fsi:9,
 credit_proxy_hyg_lqd_5:10,cftc_emini_sp500_lev_net_pct_oi:11,
 ici_weekly_etf_net_issuance_bn_usd:12,finra_spy_short_volume_pct:13
};
function metric(v,unit){
 if(!isNum(v))return emDash;
 const number=fmt(v,unit==='家'||unit==='项'?0:2);
 return unit==='美元'?'$'+number:number+(unit?' '+e(unit):'');
}
function tinySpark(history){
 if(!Array.isArray(history)||history.length<3||history.some(x=>!isNum(x)))
   return '<div class="lv3-no-spark">暂无可核验历史序列</div>';
 const nums=history.map(Number),min=Math.min(...nums),span=Math.max(1e-9,Math.max(...nums)-min);
 const pts=nums.map((x,i)=>[(3+(i/(nums.length-1))*140).toFixed(1),
                            (46-40*(x-min)/span).toFixed(1)]);
 const d=pts.map((p,i)=>(i?'L':'M')+p.join(',')).join(' ');
 return '<svg class="lv3-spark" viewBox="0 0 146 49" role="img" aria-label="实际近20次观测变化"><path d="'+
   d+'" fill="none" stroke="#62b7d9" stroke-width="2" stroke-linejoin="round"/>'+
   '<circle cx="'+pts.at(-1)[0]+'" cy="'+pts.at(-1)[1]+'" r="3" fill="#73d8c6"/></svg>';
}
function fromSources(v3,v2,official,extended){
 const asof=v3?.asof_session||v2?.asof_session||null;
 let rows=(Array.isArray(v3?.raw_observations)?v3.raw_observations:[]).map(x=>({
   ...x,category:x.category||'price',kind:'ACTUAL_MARKET_BAR'}));
 // V2's already-returned observations can populate the raw-data view while
 // slower V3 research is still calculating; no invented history or changes.
 if(!v3 || !v2 || v3.asof_session===v2.asof_session){
   const quotes=v2?.quotes||{};
   for(const sym of ['SPY','QQQ','IWM']){
     if(isNum(quotes[sym]))rows.push({id:sym,label:sym+'收盘',value:quotes[sym],
       source:'ALPACA_ETF_DAILY',observed_date:v2.asof_session,
       category:'price',unit:'美元',history:[]});
   }
   const fraction=new Set(['spy_return_1','spy_return_5','spy_return_20',
     'breadth_proxy_rsp_spy_5','small_cap_relative_5',
     'credit_proxy_hyg_lqd_5','downside_rv20','rv5','rv20','drawdown20']);
   for(const domain of (v2?.domains||[])){
     for(const x of (domain.features||[])){
       if(x.status!=='OBSERVED'||!isNum(x.value))continue;
       const scale=fraction.has(x.id)?100:1;
       rows.push({id:x.id,label:x.label||x.id,
         value:Number(x.value)*scale,unit:fraction.has(x.id)?'%':x.id==='vol_ratio'?'倍':x.id==='vix'?'点':'',
         source:x.source||'ALPACA_ETF_PROXY',observed_date:x.observed_date||v2.asof_session,
         category:domainCategories[domain.id]||'events',history:[],kind:'V2_OBSERVATION'});
     }
   }
 }
 for(const source of [official,extended]){
   if(!source || (asof && source.asof_session!==asof))continue;
   for(const f of (Array.isArray(source.features)?source.features:[])){
     if(f?.status!=='OBSERVED'||!isNum(f.value))continue;
     rows.push({...f,category:domainCategories[f.domain]||'events',
                kind:'OFFICIAL_OBSERVATION',history:[]});
   }
 }
 const seen=new Set();
 rows=rows.filter(x=>{if(!x.id||seen.has(x.id))return false;seen.add(x.id);return true;});
 return rows.sort((a,b)=>(rawKeyRank[a.id]??100)-(rawKeyRank[b.id]??100));
}
function statusBar(v2,v3,rows){
 const scores=v2?.scores||{},pressure=scores.sell_pressure,momentum=scores.momentum;
 const signal=isNum(momentum)&&isNum(pressure)?
   (Number(pressure)>=65?'风险压力较高':Number(momentum)>=62&&Number(pressure)<58?'动能相对占优':'结构信号混合'):
   '市场结构待核验';
 const spy=rows.find(x=>x.id==='SPY');
 const daily=rows.find(x=>x.id==='spy_return_5');
 const breadth=rows.find(x=>x.id==='breadth_proxy_rsp_spy_5');
 return '<div class="lv3-status-strip">'+
   '<div class="lv3-status-primary"><small>市场结构观察</small><strong>'+e(signal)+'</strong>'+
   '<span>仅描述已观测市场，不代表上涨概率</span></div>'+
   '<div class="lv3-status-stat"><span>SPY 收盘</span><strong>'+metric(spy?.value,spy?.unit)+'</strong>'+
   '<small>交易日 '+e(v3?.asof_session||v2?.asof_session||'待核验')+'</small></div>'+
   '<div class="lv3-status-stat"><span>SPY 五日走势</span><strong class="lv3-market-change '+moveClass(daily?.value)+'">'+
   (isNum(daily?.value)?sign(daily.value,2)+(daily.unit?' '+e(daily.unit):''):'—')+'</strong>'+
   '<small>当日已收盘的五日变化</small></div>'+
   '<div class="lv3-status-stat"><span>市场内部 · RSP−SPY</span><strong class="lv3-market-change '+moveClass(breadth?.value)+'">'+
   (isNum(breadth?.value)?sign(breadth.value,2)+(breadth.unit?' '+e(breadth.unit):''):'—')+'</strong>'+
   '<small>等权 ETF 相对表现代理</small></div>'+
   '<div class="lv3-status-stat"><span>卖压评分</span><strong>'+fmt(pressure,1)+'</strong>'+
   '<small>0–100 · 相对历史尺度</small></div></div>';
}
function forecast(v3,r){
 const horizons=v3?.horizons||{};
 const cards=[1,3,5].map(h=>{
   const record=horizons[String(h)]||{},p=record.research_estimates;
   const valid=p&&['UP','FLAT','DOWN'].every(k=>isNum(p[k]))&&
               Math.abs(Number(p.UP)+Number(p.FLAT)+Number(p.DOWN)-1)<.002;
   return '<button class="lv3-horizon'+(h===S.horizon?' selected':'')+
     '" type="button" data-lv3-h="'+h+'" aria-pressed="'+(h===S.horizon)+'">'+
     '<div class="lv3-horizon-head"><b>H'+h+'</b><small>未来 '+h+' 个交易日</small>'+
     (record.qualification?.admitted?pill('已验收','ok'):pill('研究估计','warn'))+'</div>'+
     (valid?'<div class="lv3-probs">'+['UP','FLAT','DOWN'].map(k=>
         '<span class="lv3-prob '+pClass(k)+'"><small>'+pName[k]+'</small><strong>'+
         percent(p[k])+'</strong></span>').join('')+'</div>'+
       '<div class="lv3-split">'+['UP','FLAT','DOWN'].map(k=>
         '<i class="'+pClass(k)+'" style="width:'+Math.max(0,Math.min(100,Number(p[k])*100))+'%"></i>').join('')+'</div>':
       '<div class="lv3-no-pred">'+e(record.reason||errorText(r))+'</div>')+
     '<div class="lv3-horizon-foot">阈值 '+(isNum(record.boundary_return)?
       '±'+percent(record.boundary_return):'待计算')+
     ' · '+(h===S.horizon?'正在查看计算明细':'点击查看计算明细')+'</div></button>';
 }).join('');
 return box('lv3-forecast',title('未来 1 / 3 / 5 日情景研究',pill('未经历史 PIT 认证 · 非交易概率','warn'))+
   '<p class="lv3-forecast-note">预测对象：SPY 下一交易日开盘至期限末收盘；上涨/震荡/下跌使用预测日已知的波动阈值划分，三类互斥且总和为 100%。</p>'+
   '<div class="lv3-horizon-grid">'+cards+'</div>');
}
function traceTable(rec){
 const inputs=rec?.trace?.feature_inputs;
 if(!Array.isArray(inputs)||!inputs.length)
   return '<div class="lv3-empty">该期限的训练或特征不足，无法展示可复核的数值计算过程。</div>';
 return '<div class="lv3-trace-table-wrap"><table class="lv3-trace-table"><thead><tr>'+
   '<th>因子输入</th><th>原始值</th><th>标准化</th><th>上涨 Logit 影响</th></tr></thead><tbody>'+
   inputs.map(x=>'<tr><td>'+e(x.name)+'</td><td class="mono">'+metric(x.raw_value,x.unit)+
     '</td><td class="mono">'+sign(x.standardized,2)+'</td>'+
     '<td class="mono '+(Number(x.up_logit_contribution)>=0?'positive':'negative')+'">'+
     sign(x.up_logit_contribution,3)+'</td></tr>').join('')+
   '</tbody><tfoot><tr><td>模型截距</td><td colspan="2">加入所有输入影响</td>'+
   '<td class="mono">'+sign(rec.trace.up_logit_intercept,3)+'</td></tr>'+
   '<tr><td>上涨类 Logit</td><td colspan="2">输入影响之和 + 截距</td>'+
   '<td class="mono">'+sign(rec.trace.up_logit_sum,3)+'</td></tr></tfoot></table></div>'+
   '<p class="lv3-small">Logit 影响是模型计算项，不是“贡献了多少个百分点”，也不是因果解释。</p>';
}
function calibration(rec){
 const tr=rec?.trace;
 if(!tr)return '<div class="lv3-empty">暂无合格的校准计算输入。</div>';
 const a=tr.raw_probabilities||{},b=tr.calibrated_probabilities||{};
 return '<div class="lv3-stage-head"><span>模型输出</span><span>校准后研究估计</span></div>'+
   ['UP','FLAT','DOWN'].map(k=>'<div class="lv3-prob-step"><span>'+pName[k]+'</span>'+
    '<strong>'+percent(a[k])+'</strong><i>→</i>'+
    '<strong class="'+pClass(k)+'">'+percent(b[k])+'</strong>'+
    '<small>'+((isNum(a[k])&&isNum(b[k]))?
      sign((b[k]-a[k])*100,1)+' pp':'—')+'</small></div>').join('')+
   '<div class="lv3-cal-meta"><span>温度参数 <b>'+fmt(tr.temperature,3)+'</b></span>'+
   '<span>训练样本 <b>'+fmt(rec.train_samples,0)+'</b></span>'+
   '<span>校准样本 <b>'+fmt(rec.calibration_samples,0)+'</b></span></div>'+
   '<p class="lv3-small">温度仅使用独立的历史校准窗口拟合；此处展示的是实际模型输出变化。</p>';
}
function validation(rec){
 const v=rec?.validation;
 if(!v||v.status==='INSUFFICIENT_OOS')
   return '<div class="lv3-empty">历史样本外窗口不足，概率不能通过发布资格。</div>';
 const beat=isNum(v.model_brier)&&isNum(v.baseline_brier)&&v.model_brier<v.baseline_brier;
 return '<div class="lv3-validation-grid">'+
   '<div><span>滚动测试</span><b>'+fmt(v.samples,0)+' 次</b></div>'+
   '<div><span>模型 Brier</span><b>'+fmt(v.model_brier,4)+'</b></div>'+
   '<div><span>基准 Brier</span><b>'+fmt(v.baseline_brier,4)+'</b></div>'+
   '<div><span>校准误差 ECE</span><b>'+fmt(v.ece,4)+'</b></div>'+
   '</div><div class="lv3-validation-foot">'+
   pill(beat?'Brier 优于基准':'未优于基准',beat?'ok':'warn')+
   pill(v.numeric_gates_passed?'数值门槛达标':'数值门槛未达标',v.numeric_gates_passed?'ok':'warn')+
   pill('历史 PIT 尚未核验','warn')+'</div>'+
   '<p class="lv3-small">Log Loss：模型 '+fmt(v.model_log_loss,4)+' / 基准 '+fmt(v.baseline_log_loss,4)+
   '；滚动分组 '+fmt(v.folds,0)+' 组。当前数据仍不是历史时点已验证的输入。</p>';
}
function calculations(rec,v3,response){
 const valid=rec&&rec.trace&&rec.research_estimates;
 return box('lv3-calculation',title('H'+S.horizon+' · 这次概率如何算出',
   pill(valid?'数值可追溯 · 研究状态':'等待数据或训练','muted'))+
   '<div class="lv3-calc-intro"><span>真实 ETF 日线输入 → 7 项市场特征 → 多分类模型 → 历史校准</span>'+
   '<span>当前来源 '+e(v3?.data_feed||'待核验')+' · '+e(v3?.asof_session||'—')+'</span></div>'+
   (valid?'<div class="lv3-calc-grid"><div class="lv3-calc-input">'+
       '<h3>① 原始数据与本次因子值</h3>'+traceTable(rec)+'</div>'+
       '<div class="lv3-calc-output"><h3>② 原始概率 → 校准结果</h3>'+calibration(rec)+
       '<div class="lv3-divider"></div><h3>③ 真正经过哪些检验？</h3>'+
       validation(rec)+'</div></div>':
       '<div class="lv3-empty">'+e(rec?.reason||errorText(response))+
       '。系统不会以随机比例填充计算明细。</div>')+
   '<div class="lv3-research-scope"><b>发布状态：未取得正式预测资格。</b> '+
   '目前只有 Alpaca 的 ETF 历史行情进入这一版概率模型；Cboe、CFTC、OFR 等最新观测尚未证明历史 PIT 可回放，不会被暗中纳入模型。</div>'+
   (valid?'<details class="lv3-audit"><summary>查看模型版本、三类 Logit、证据哈希</summary>'+
      '<div class="lv3-audit-line">模型：'+e(v3.model_version)+' · 特征：'+e(v3.feature_version)+'</div>'+
      '<div class="lv3-audit-line">原始 Logit：[ '+(rec.trace.class_logits||[]).map(z=>fmt(z,4)).join(' / ')+' ]</div>'+
      '<div class="lv3-audit-line">计算指纹：<code>'+e(rec.trace_sha256||'')+'</code></div>'+
      '</details>':'') );
}
function rawPanel(rows,official,extended,v3){
 const filter=rows.filter(x=>S.category==='all'||x.category===S.category);
 const visible=S.category==='all'?filter.slice(0,16):filter.slice(0,36);
 const tabs=categories.map(([id,label])=>'<button type="button" data-lv3-cat="'+id+
    '" aria-pressed="'+(S.category===id)+'" class="'+(S.category===id?'selected':'')+'">'+
    e(label)+'</button>').join('');
 const cards=visible.map(x=>{
   const delta=isNum(x.delta)?
     '<span class="lv3-change '+moveClass(x.delta)+'">'+sign(x.delta,2)+' '+e(x.unit||'')+'</span>':
     '<span class="lv3-change neutral">单期观测 · 无可比变化</span>';
   return '<article class="lv3-raw-item"><div class="lv3-raw-name">'+e(x.label||x.id)+
     '</div><strong class="mono '+(/^(spy_return_(1|5|20)|breadth_proxy_rsp_spy_5|small_cap_relative_5|credit_proxy_hyg_lqd_5)$/.test(x.id)?'lv3-market-change '+moveClass(x.value):'')+'">'+metric(x.value,x.unit)+'</strong>'+delta+
     tinySpark(x.history)+'<div class="lv3-raw-foot"><span>'+e(x.source||'来源待核验')+
     '</span><span>'+e(x.observed_date||v3?.asof_session||'—')+'</span></div></article>';
 }).join('');
 const healthy=[...(Object.values(official?.source_health||{})),
                ...(Object.values(extended?.source_health||{}))];
 const ok=healthy.filter(x=>x?.status==='OBSERVED').length;
 return box('lv3-data',title('市场原始数据监测',
    '<span class="lv3-soft">真实来源 '+ok+'/'+healthy.length+' 取得观测 · 未提供历史的指标不画虚假曲线</span>')+
   '<div class="lv3-raw-tabs">'+tabs+'</div>'+
   (visible.length?'<div class="lv3-raw-grid">'+cards+'</div>':
    '<div class="lv3-empty">当前分类尚无可验证的观测值。请查看数据中心和来源健康状态。</div>')+
   '<p class="lv3-small">市场数据以实际交易日和官方发布时间为准；CFTC 为周频持仓，ICI 是周度净发行估算，FINRA 卖空成交不是空头持仓。</p>');
}
function outcomePanel(result){
 const data=result?.ok&&result.data?.schema==='qdr.l1.v3.outcomes'?result.data:null;
 const records=Array.isArray(data?.records)?data.records:[];
 const aggregate=data?.forward_scorecard?.horizons||{};
 const scoreCards=[1,3,5].map(h=>{
   const x=aggregate[String(h)]||{};
   const enough=Number(x.samples)>0&&isNum(x.brier)&&isNum(x.baseline_brier);
   return '<div class="lv3-score-item"><span>H'+h+' · 已到期 '+(isNum(x.samples)?fmt(x.samples,0):'0')+' 条</span>'+
    '<strong>'+ (enough?fmt(x.brier,4):'—')+'</strong>'+
    '<small>三类 Brier'+(enough?' / 历史基准 '+fmt(x.baseline_brier,4):' · 暂无可核验结果')+'</small></div>';
 }).join('');
 const content=records.length?
   '<div class="lv3-outcome-table-wrap"><table class="lv3-outcome-table"><thead>'+
    '<tr><th>预测交易日</th><th>期限</th><th>已发生情景</th><th>实际收益</th><th>三分类 Brier</th></tr>'+
    '</thead><tbody>'+records.slice(0,12).map(item=>
      '<tr><td>'+e(item.asof_session)+'</td><td>H'+e(item.horizon)+'</td>'+
      '<td>'+e(pName[item.actual_scenario]||'—')+'</td>'+
      '<td class="mono">'+percent(item.actual_return)+'</td>'+
      '<td class="mono">'+fmt(item.brier_3class,4)+'</td></tr>').join('')+
    '</tbody></table></div>':
   '<div class="lv3-outcome-empty">'+e(errorText(result?.pending?result:{error:{message:
      '目前没有到期且已冻结的研究预测；本地每日任务负责生成快照，到期后才追加实际结果。'}}))+'</div>';
 return box('lv3-outcomes',title('前向冻结与到期核验',
    '<span class="lv3-soft">仅已完成的实际交易日 · 不代表实盘收益</span>')+
    '<div class="lv3-forward-score-grid">'+scoreCards+'</div>'+
    content+
    '<p class="lv3-small">Brier 衡量三类概率与实际结果的距离，越小越好；只有历史归档与结果数据同时存在才会显示评分。</p>');
}
function evidence(v2,official,extended){
 const lookup=new Map((v2?.domains||[]).map(x=>[x.id,x]));
 const added=[...(official?.features||[]),...(extended?.features||[])].filter(x=>x?.status==='OBSERVED');
 const domainIds=Object.keys(DOMAIN_NAMES);
 const statusesHtml=domainIds.map(id=>{
   const base=lookup.get(id);
   const count=(base?.features||[]).filter(x=>x?.status==='OBSERVED').length+
               added.filter(x=>x.domain===id).length;
   const status=count?((base?.status==='OBSERVED')?'已观测':'部分覆盖'):'待接入';
   return '<div class="lv3-domain-row"><span>'+e(DOMAIN_NAMES[id])+'</span>'+
      '<b>'+count+' 项</b><small>'+status+'</small></div>';
 }).join('');
 const events=extended?.calendar_events||[];
 const eventRows=events.slice(0,8).map(x=>'<div class="lv3-event-row"><span>'+
    e(x.name||'经济发布')+'</span><b>'+stripTime(x.start_utc)+' UTC</b></div>').join('');
 return '<div class="lv3-extra-grid">'+box('lv3-source-evidence',title('12 维数据覆盖与来源',
   '<span class="lv3-soft">完整证据与缺口按需展开</span>')+
   '<details class="lv3-evidence-details"><summary>查看 12 维覆盖清单和真实来源</summary>'+
   '<div class="lv3-domains">'+statusesHtml+'</div></details>'+
   '<button class="lv3-legacy-button" type="button" data-lv3-old>打开原 L1 完整研究视图（E01/E02/E03）</button>')+
   box('lv3-events',title('近期已公布日程',
    '<span class="lv3-soft">BLS 官方排程 · UTC</span>')+
   (eventRows||'<div class="lv3-empty">当前没有已核验的近期发布日程。</div>'))+'</div>';
}
function pipelineLine(status,p){
 const current=status?.status==='CURRENT_RESEARCH';
 const model=status?.model_reference?.asof_session;
 const job=status?.last_job;
 const frozenModel=p?.model_reference?.model_sha256;
 const currentModel=status?.model_reference?.model_sha256;
 const priorModel=Boolean(frozenModel&&currentModel&&frozenModel!==currentModel);
 const parts=[
   p?.status==='RESEARCH_ONLY'?('已冻结研究 · '+p.asof_session):'最新研究待生成',
   model?('模型训练 '+model):'模型尚未建立',
   p?.frozen_at_utc?('实际冻结 '+p.frozen_at_utc):'',
   priorModel?'当前预测使用先前模型；新模型将在后续预测使用':'',
   p?.model_version==='L1_V3_ETF7.2'?'旧版 H1/H3 未满足五交易日隔离，研究结果不符合当前准入规则':'',
   status?.model_retrain_due?'待训练/更新':'模型在更新周期内',
   job?.status==='BLOCKED'?('上次任务失败：'+String(job.code||'见运行日志')):''
 ].filter(Boolean);
 return '<div class="lv3-pipeline-state">'+
   pill(current?'最新研究已就绪':'研究数据待更新',current?'ok':'warn')+
   '<span>'+e(parts.join(' · '))+'</span></div>';
}
pages.market=async()=>{
 if(S.legacyMode && typeof legacyMarket==='function'){
   const old=await legacyMarket();
   return {title:'L1 旧版完整研究视图',html:
      '<button type="button" class="lv3-back" data-lv3-return>← 返回新版市场研判</button>'+old.html,
      mount(){
        document.querySelector('[data-lv3-return]')?.addEventListener('click',()=>{
          S.legacyMode=false;show('market');});
        old.mount?.();
      }};
 }
 const suffix=S.force?'?refresh=1':'';
 S.force=false;
 const [pRaw,statusRaw,v2Raw,officialRaw,extendedRaw,outcomesRaw]=await Promise.all([
   // Read-only: this GET never trains a model or downloads historical prices.
   settle('/api/v1/l1/v3/latest'),
   settle('/api/v1/l1/v3/status'),
   settle('/api/v1/l1/v2/overview?horizon=3'+(suffix?'&refresh=1':'')),
   settle('/api/v1/l1/v2/official'+suffix),
   settle('/api/v1/l1/v2/extended'+suffix),
   settle('/api/v1/l1/v3/outcomes')
 ]);
 const p=pRaw?.ok&&pRaw.data?.schema==='qdr.l1.probability.v3'&&pRaw.data.status==='RESEARCH_ONLY'?pRaw.data:null;
 const pipeline=statusRaw?.ok&&statusRaw.data?.schema==='qdr.l1.v3.pipeline.status'?statusRaw.data:null;
 const v2=v2Raw?.ok&&v2Raw.data?.schema==='qdr.l1.v2'?v2Raw.data:null;
 const official=officialRaw?.ok&&officialRaw.data?.schema==='qdr.l1.official.v1'?officialRaw.data:null;
 const extended=extendedRaw?.ok&&extendedRaw.data?.schema==='qdr.l1.extended.v1'?extendedRaw.data:null;
 const raw=fromSources(p,v2,official,extended);
 const selected=p?.horizons?.[String(S.horizon)]||null;
 const waiting=[pRaw,statusRaw,v2Raw,officialRaw,extendedRaw,outcomesRaw].filter(x=>x?.pending).length;
 const html='<div class="lv3">'+
   '<div class="lv3-heading"><div><small>L1 / MARKET INTELLIGENCE</small>'+
   '<h1>市场状态与情景研究 <span>V3</span></h1></div>'+
   '<div class="lv3-heading-actions">'+pill(p?'研究估计 · 尚未发布':'模型数据待核验','warn')+
   '<button type="button" data-lv3-refresh class="lv3-button">↻ 刷新数据</button></div></div>'+
   pipelineLine(pipeline,p)+
   statusBar(v2,p,raw)+
   (waiting?'<div class="lv3-loading" role="status">'+waiting+' 项数据模块正在独立加载，已返回部分可先查看。</div>':'')+
   forecast(p,pRaw)+
   calculations(selected,p,pRaw)+
   '<div class="lv3-data-divider"><strong>市场数据与证据</strong><span>向下继续查看当前指标、实际变动及来源时点</span></div>'+
   rawPanel(raw,official,extended,p)+
   outcomePanel(outcomesRaw)+
   evidence(v2,official,extended)+
   '<footer class="lv3-footer">QDR · L1 V3 · 仅研究用途 · 不执行真实交易 · 概率需先通过历史 PIT 与前向验收</footer></div>';
 return {title:'L1 市场状态与情景研究',html,mount(){
   document.querySelectorAll('[data-lv3-h]').forEach(button=>button.addEventListener('click',()=>{
     const h=Number(button.dataset.lv3H);
     if(![1,3,5].includes(h))return;
     S.horizon=h;state.marketHorizon=h;show('market');
   }));
   document.querySelectorAll('[data-lv3-cat]').forEach(button=>button.addEventListener('click',()=>{
     S.category=button.dataset.lv3Cat;show('market');
   }));
   document.querySelector('[data-lv3-refresh]')?.addEventListener('click',()=>{
     S.force=true;
     // V4 global refresh purges its progressive GET memo before the redraw.
     const global=document.querySelector('#v4-refresh');
     if(global)global.click();
     else show('market');
   });
   document.querySelector('[data-lv3-old]')?.addEventListener('click',()=>{
     S.legacyMode=true;show('market');
   });
 }};
};
})();
