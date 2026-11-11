/* V4 high-fidelity data-connected overview, market and classic style views. */
(() => {
'use strict';
const V=window.V4;
const {pages,state,$,e,n,pct,signed,date,short,badge,button,link,heading,card,kpi,empty,note,row,table,fail,value,api,settle,grid,toolbar,field,select,svgLine,progress,toast,show}=V;
function result(x){return x&&x.ok?x.data:null}
function errorText(x){return x?.error?.message||'尚无符合资格的真实数据'}
function statusName(x){return String(x||'UNKNOWN').replaceAll('_',' ')}
function statusBadge(x){const v=String(x||'未核验'),positive=['PASS','OBSERVATION_ONLY','INTERNALLY_RECONCILED_PAPER_ESTIMATE','VERIFIED_LOCAL_RESEARCH_ARTIFACT_ONLY','CONCENTRATION_MEASURED'].includes(v);return badge(statusName(v),positive?'green':/BLOCKED|INVALID|FAILED|NOT_READY/i.test(v)?'red':'amber')}
function areaTitle(name,detail){return '<div class="v4-hero"><h2>'+e(name)+'</h2><p>'+e(detail)+'</p></div>'}
function whenData(condition,val){return condition?val:'—'}
pages.overview=async()=>{
 const all=await Promise.all([
  settle('/api/status'),settle('/api/v1/v4/daily'),settle('/api/v1/v4/forecasts'),
  settle('/api/v1/styles?mode=observation'),settle('/api/v1/paper/risk'),settle('/api/v1/research/readiness'),
  settle('/api/v1/v4/plans')]);
 const [system,diary,forecasts,style,risk,readiness,planIndex]=all.map(result);
 const planInfo=(planIndex?.records||[])[0];
 const latestPlan=planInfo&&planInfo.status!=='CORRUPT_RESEARCH_PLAN'?
   result(await settle('/api/v1/v4/plans/'+encodeURIComponent(planInfo.session_date_et)+'/'+encodeURIComponent(planInfo.identity))):null;
 const latest=(diary?.runs||[])[0]||null;
 const styleData=(style?.latest||[]).filter(x=>x.factor_name!=='RF'&&x.sum_5d!==null);
 const styleStrong=[...styleData].filter(x=>Number(x.sum_5d)>0).sort((a,b)=>Number(b.sum_5d)-Number(a.sum_5d)).slice(0,3);
 const runs=forecasts?.records||[];
 const recent=runs.find(x=>x.status==='VERIFIED_LOCAL_FORWARD_RESEARCH_ONLY')||runs[0]||null;
 const hasPaper=risk?.status==='CONCENTRATION_MEASURED';
 const day=system?.dataset?.asof_date_et||latest?.session_date_et||'—';
 const kpis=grid(4,[
   kpi('L1 / 市场状态','—','当日校准后的市场方向概率未形成','blue'),
   kpi('L2 / 经典风格',styleStrong.length?e(styleStrong.map(x=>x.factor_name).join(' / ')):'—',styleStrong.length?'真实历史因子最近5日表现（非预测）':'无可用因子观察','purple'),
   kpi('L3 / Alpha 预测研究',recent?n(recent.forecast_rows,0):'—',recent?'已存档个股预测记录，不等于合格交易候选':'当前无冻结预测记录','green'),
   kpi('L4 / 持仓风险',hasPaper?n(risk.alerts?.length||0,0):'—',hasPaper?'本地对账持仓的规则预警数量':'组合风险证据未完整','amber')
 ].join(''));
 const stages=latest?.stages||[];
 const stageRows=stages.map(x=>[e(({data:'数据来源',market:'① 市场',styles:'② 风格',alpha:'③ Alpha',risk:'④ 风控',freeze:'计划冻结'})[x.stage]||x.stage),statusBadge(x.status),e(x.code||'—')]);
 const factorBars=styleStrong.length?styleStrong.map(x=>progress(x.factor_name,Math.min(100,Math.abs(Number(x.sum_5d))*1400),signed(x.sum_5d))).join(''):empty('暂无风格监测数据','等待来自真实来源的经典因子观察记录。');
 const isnum=(v)=>v!=null&&Number.isFinite(Number(v));
 const riskRows=hasPaper?(risk.alerts||[]).map(x=>[e(x.code),e(x.subject||'组合'),e(isnum(x.actual)?pct(x.actual):'—')]):[];
 const content=heading('研究总览','四层模型的日终研究结论、实际预测归档与组合风险，统一按真实证据展示',
     link('/market','查看市场研究')+link('/strategies','进入因子组选股'))+
     '<div class="v4-muted-note" style="margin-bottom:15px">数据交易日 '+e(day)+' · 未验收的研究结果不会包装成交易建议</div>'+
     kpis+'<div class="grid cols2" style="margin:15px 0">'+
       card('市场状态预测 · 未来 1 / 3 / 5 日',
         grid(3,[1,3,5].map(h=>'<div class="mini-stat"><div class="muted">H'+h+' 上涨概率</div><div class="val blue">—</div><div class="fine">需要真实前向校准结果</div></div>').join(''))+
         note('当前展示框架保留三个交易期限；不借用历史回溯预测或演示概率填充。')+
         '<div class="v4-actions" style="margin-top:14px">'+link('/studio#market','市场预测研究')+'</div>','L1 · 前向预测资格待核验')+
       card('经典因子 · 风格轮动',factorBars+note('French 历史修订版本仅供当前观察；领先性须另行样本外验证。')+
         '<div style="margin-top:10px">'+link('/studio#style','查看经典因子趋势')+'</div>','L2 · 实际因子观察')+
     '</div>'+
     '<div class="grid cols2" style="margin-bottom:15px">'+
       card('Alpha 研究与候选',latestPlan?
         row('研究计划归档日',e(planInfo.session_date_et))+
         row('已通过风险过滤',n(latestPlan.plans?.length||0,0))+
         (latestPlan.plans?.length?table(['研究候选','预期净优势','权益权重'],
           latestPlan.plans.slice(0,4).map(x=>[e(x.symbol||x.security_id),signed(x.estimated_net_edge),pct(x.indicative_weight)])):
           empty('当日无候选通过过滤','研究规则允许明确输出不交易。'))+
         note('这是考虑成本的非执行研究计划，未通过历史 PIT 和真实前向收益验收。'):
         recent?row('最近归档交易日',e(recent.session_date_et))+
         row('归档研究预测行数',n(recent.forecast_rows,0))+
         row('研究资格',statusBadge(recent.status))+
         note('预测归档尚未形成完整的风险过滤研究计划。'):
         empty('尚无前向研究记录','完成真实数据研究后，此处展示已归档预测或明确的不交易结论。'), 'L3 · 条件收益研究')+
       card('组合持仓 · 预警',hasPaper?
         row('组合权益仓位',pct(risk.gross_weight))+
         row('集中度预警',n(risk.alerts?.length||0,0))+
         (riskRows.length?table(['规则','对象','当前暴露'],riskRows.slice(0,5)):badge('当前无规则超限','green'))+
         note('VaR 和预期尾部损失只有存在真实合格历史收益时才展示。'):
         empty('尚无有效的风险账本','缺少已内部核对的持仓及估值，不生成虚构风险结果。'),'L4 · 风险审阅')+
     '</div>'+
     grid(2,[
       card('每日四层运行记录',latest?row('日终研究状态',statusBadge(latest.status))+
         table(['层级','状态','原因'],stageRows):empty('尚无真实日终运行记录','日终模型和数据源尚未形成可核验的统一归档。'),'已归档研究日志'),
       card('系统数据资格',readiness?row('独立市场预测模型资格',statusBadge(readiness.stages?.historical_model?.status))+
         row('历史回测数据资格',statusBadge(readiness.stages?.historical_backtest?.status))+
         row('前向模拟资格',statusBadge(readiness.stages?.forward_shadow?.status))+
         row('实际券商订单',badge('永久关闭','amber'))+
         note('研究数据可以观察，不自动获得历史证券池、实际成交和策略有效性资格。'):
         empty('尚未读取数据资格','请检查真实数据仓库和已完成的研究记录。'),'数据来源与能力矩阵')
     ].join(''));
 return {title:'研究总览',html:content};
};

pages.market=async()=>{
 const horizon=state.marketHorizon;
 const [history,diary,study]=await Promise.all([
  settle('/api/v1/market/research?horizon='+horizon),
  settle('/api/v1/v4/daily'),settle('/api/v1/v4/research/runs')]);
 const d=result(history);
 const pred=d?.predictions?.[0]||null,st=d?.states?.[0]||null;
 const latest=(result(diary)?.runs||[])[0];
 const researchRows=(result(study)?.runs||[]).slice(0,6).map(x=>[
   e(x.run_id),date(x.created_at_utc),statusBadge(x.status)]);
 const up=pred?.p_up??pred?.probability_up??null;
 const risk=pred?.p_downside??pred?.downside_probability??null;
 const predicted=pred?.predicted_return??pred?.expected_gross_trade_return??null;
 const marketValid=!!d;
 const header=heading('市场状态预测','研究未来市场方向、尾部风险和状态转移；历史回溯与今日真实前向预测明确区分',
   link('/market','打开完整市场研究工具'));
 const controls=toolbar(
   select('研究持有期','v4-market-h',[['1','未来1日'],['3','未来3日'],['5','未来5日']],horizon)+
   '<div class="v4-actions">'+badge(marketValid?'历史模型研究 · 非当前预测':'等待真实模型归档',marketValid?'blue':'amber')+'</div>'
 );
 const kpis=grid(4,[
   kpi('H'+horizon+' / 上涨概率',up===null?'—':pct(up),marketValid?'历史研究样本结果':'未取得经校准概率','blue'),
   kpi('H'+horizon+' / 显著下跌概率',risk===null?'—':pct(risk),'该事件与上涨概率不是简单互补','amber'),
   kpi('H'+horizon+' / 预测总收益',predicted===null?'—':signed(predicted),'仅实际模型输出','green'),
   kpi('市场状态',st?.market_state?e(st.market_state):'—','历史观察结果，非未来状态','purple')
 ].join(''));
 const dataPanel=d?row('实际研究截止',date(d.manifest?.asof_date_et))+
   row('市场20日收益',st?.market_return_20==null?'—':signed(st.market_return_20))+
   row('20日年化波动',st?.market_vol_20==null?'—':pct(st.market_vol_20))+
   row('模型和特征有效时间',date(st?.state_available_at))+
   row('资格',badge('历史描述/研究','amber')):
   empty('尚无市场预测研究',errorText(history));
 const clinical=card('市场环境 · 真实观察',dataPanel,'L1 · 当前/历史区分');
 const diagnostics=d?card('概率可靠性与模型验证',row('研究状态',statusBadge(d.status))+
  row('已归档预测行',n(d.manifest?.prediction_rows,0))+
  row('未来样本资格',badge(d.manifest?.historical_decision_eligible?'已核验':'未取得','amber'))+
  note('当前接口是历史研究视图。只有真实 OOS 可靠性图、Brier/LogLoss 和前向结果才可作为预测性能证据。'),'验证协议'):
  card('模型可靠性与风险传导',empty('尚无历史概率校准材料','获取真实样本外预测后再展示可靠性、下行事件分布与状态转移。'),'严禁示意热力图');
 const mid=grid(2,[clinical,diagnostics].join(''));
 const bottom=grid(2,[
   card('四层联动中的市场模型',latest?table(['研究阶段','状态','原因'],(latest.stages||[])
     .filter(x=>x.stage==='market').map(x=>[e('市场状态'),statusBadge(x.status),e(x.code||'—')])):
     empty('暂无四层日终任务','市场层尚未执行真实当日预测冻结。'),'每日模型状态'),
   card('历史研究与对照版本',researchRows.length?table(['实验','运行日','状态'],researchRows):
     empty('暂无已归档样本外实验','市场基线必须和新增特征模型作时间外比较。'),'研究版本')
 ].join(''));
 return {title:'市场状态预测',html:header+controls+kpis+'<div style="margin-top:15px">'+mid+'</div><div style="margin-top:15px">'+bottom+'</div>',
 mount(){ $('#v4-market-h')?.addEventListener('change',x=>{state.marketHorizon=Number(x.target.value);show('market')});}};
};

pages.style=async()=>{
 const response=await settle('/api/v1/styles?mode=observation');
 const data=result(response),items=data?.latest||[],series=data?.series||[];
 const selected=items.find(x=>x.factor_name===state.styleFactor)||items.find(x=>x.factor_name!=='RF')||items[0]||null;
 state.styleFactor=selected?.factor_name||null;
 const history=selected?series.filter(x=>x.factor_name===selected.factor_name&&x.sum_20d!=null):[];
 const seriesValues=history.map(x=>x.sum_20d);
 const metrics=items.filter(x=>x.factor_name!=='RF'&&x.sum_5d!=null)
     .sort((a,b)=>Number(b.sum_5d)-Number(a.sum_5d));
 const bars=metrics.slice(0,7).map(x=>progress(
    x.factor_label||x.factor_name,Math.min(100,Math.abs(Number(x.sum_5d))*3000),
    signed(x.sum_5d))).join('');
 const rows=items.map(x=>[
   '<button type="button" data-factor="'+e(x.factor_name)+'" class="btn smallbtn">'+e(x.factor_name)+'</button>',
   e(x.factor_label||'—'),signed(x.sum_5d),signed(x.sum_20d),
   e(x.state||'未知'),e(x.missing_reason||'—')]);
 const html=heading('经典因子与风格跟踪','跟踪 SMB/HML/RMW/CMA/MOM 等实际因子收益，区分已发生表现与未来领先性',
  link('/styles','完整因子监测与导出'))+
  grid(4,[
    kpi('因子观察日',data?.asof_date_et?date(data.asof_date_et):'—','当前下载版本的可用日期','blue'),
    kpi('可观察因子数',items.length?n(items.length,0):'—','不包括未来收益标签','purple'),
    kpi('近5日正收益风格',metrics.length?n(metrics.filter(x=>Number(x.sum_5d)>0).length,0):'—','仅描述历史强弱','green'),
    kpi('历史领先性研究','未验收','需要独立未来相对收益 OOS','amber')
  ].join(''))+
  '<div style="margin-top:15px">'+grid(2,[
    card('经典风格强弱 · 近 5 日',bars||empty('暂无有效因子强弱数据',errorText(response))+
      note('指标单位来自实际因子收益。多空因子不等同于可直接交易的 ETF 产品。'),'历史收益观测'),
    card(selected?e(selected.factor_label||selected.factor_name)+' · 20日滚动收益':'滚动风格趋势',
      history.length>1?svgLine(seriesValues,'#9a8bf5',195)+
        row('最近 5 日',signed(selected.sum_5d))+row('最近20日',signed(selected.sum_20d)):
        empty('当前没有可绘制的因子序列','至少需要两个真实历史观测点。'),'实际历史序列')
  ].join(''))+'</div>'+
  '<div style="margin-top:15px">'+card('风格观察明细',items.length?table(
    ['因子','类别','5日累计','20日累计','当前状态','缺失原因'],rows):
     empty('经典因子尚未接入',errorText(response)),
   '点击因子代码在上方查看趋势')+'</div>'+
  '<div style="margin-top:15px">'+card('风格预测研究边界',
     areaTitle('研究的是风格能否领先，而不只是目前谁更强',
       '对可交易风格代理构建未来 1/3/5 日相对收益标签，并在相同时间切分上比较简单基线与市场条件模型。只有 OOS 增量被证实时，才进入个股 Alpha 的条件特征。')+
     '<div class="v4-actions" style="margin-top:15px">'+link('/studio#screen','查看条件 Alpha 研究')+
     link('/styles','查看 French 数据来源')+'</div>','L2 · 因子研究');
 return {title:'经典因子跟踪',html,
  mount(){document.querySelectorAll('[data-factor]').forEach(el=>el.addEventListener('click',()=>{state.styleFactor=el.dataset.factor;show('style')}))}};
};
})();