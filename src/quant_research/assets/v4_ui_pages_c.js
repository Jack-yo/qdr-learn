/* V4 approved dark portfolio/risk and data-evidence pages. */
(() => {
'use strict';
const V=window.V4;
const {pages,state,$,e,n,pct,signed,date,short,badge,button,link,heading,card,kpi,empty,note,row,table,fail,value,api,settle,grid,toolbar,field,select,svgLine,progress,toast,show}=V;
const good=(str)=>['PASS','INTERNALLY_RECONCILED_PAPER_ESTIMATE','CONCENTRATION_MEASURED'].includes(str);
const pretty=(str)=>e(String(str||'—').replaceAll('_',' '));
const riskStatus=(x)=>badge(pretty(x),good(x)?'green':x?.includes?.('BLOCKED')?'red':'amber');
pages.risk=async()=>{
 const requests=await Promise.all([
   settle('/api/v1/paper/account'),settle('/api/v1/paper/risk'),
   settle('/api/v1/paper/timeline'),settle('/api/v1/paper'),
   settle('/api/v1/research/readiness')]);
 const [account,risk,timeline,inventory,readiness]=requests.map(x=>x.ok?x.data:null);
 const verified=account?.status==='INTERNALLY_RECONCILED_PAPER_ESTIMATE';
 const riskOK=risk?.status==='CONCENTRATION_MEASURED';
 const positions=verified?Object.entries(account.position_details||{}):[];
 const alerts=riskOK?(risk.alerts||[]):[];
 const sessions=timeline?.status==='INTERNALLY_RECONCILED_PAPER_ESTIMATE'?(timeline.sessions||[]):[];
 const detail=positions.map(([sid,item])=>{
   const quantity=Number(item.quantity);
   const mark=Number(account.last_prices?.[sid]);
   const mv=Number.isFinite(quantity*mark)?quantity*mark:null;
   return [e(sid),Number.isFinite(quantity)?n(quantity,0):'—',
     Number.isFinite(mark)?'$'+n(mark,2):'—',mv===null?'—':'$'+n(mv,2),
     e(item.sector||'未验证')];
 });
 const warningRows=alerts.map(x=>[
    e(x.code),e(x.subject||'组合'),
    x.actual==null?'—':pct(x.actual),
    x.limit==null?'—':pct(x.limit),
    x.affected_securities?e(x.affected_securities.join(', ')):'—']);
 const nav=heading('持仓与风控',
   '当前持仓、组合敞口、预警与退出规则。',
   link('/paper','组合账本'));
 const cards=grid(4,[
   kpi('组合权益',verified?'$'+n(account.equity,2):'—',
       verified?'根据已核对的真实价格估值':'缺少合格模拟账本','blue'),
   kpi('现金',verified?'$'+n(account.cash,2):'—',
       '未发生实际券商成交','green'),
   kpi('权益仓位',riskOK?pct(risk.gross_weight):'—',
       '仓位集中度由实际持仓估算','purple'),
   kpi('风险预警',riskOK?n(alerts.length,0):'—',
       '未核验时不填零','amber')
 ].join(''));
 const limits=grid(2,[
   card('仓位与退出规则',
     row('单笔计划权益风险',pct(.003))+
     row('单只股票上限',pct(.10))+
     row('组合总仓位上限',pct(.50))+
     row('行业仓位上限',pct(.25))+
     row('初始保护止损','2 × ATR20')+
     row('默认短线持仓','1 / 3 / 5 个交易日')+
     note('当前显示策略基线与冻结规则；隔夜跳空风险需单独复核。'),
     '静态研究限制'),
   card('组合风险度量',
     riskOK?row('当前持仓集中度',riskStatus(risk.status))+
       row('组合日 VaR95',risk.daily_var95==null?'—':pct(risk.daily_var95))+
       row('尾部预期损失 ES95',risk.daily_expected_shortfall95==null?'—':pct(risk.daily_expected_shortfall95))+
       row('历史收益证据',risk.historical_return_risk_status?pretty(risk.historical_return_risk_status):'—')+
       note('VaR/ES 尚未取得合法历史收益时保持空值；不使用常数、随机数模拟填充。'):
       empty('组合风险暂不可计算',requests[1].ok?e(risk?.code||'没有内部对账的持仓估值'):e(requests[1].error?.message)),
     '波动 / 相关性 / 下行风险')
 ].join(''));
 const positionCard=card('当前持仓',
    detail.length?table(['证券ID','数量','最近估值价','估计市值','行业'],detail):
      empty('当前没有具备内部对账的持仓','只有来源真实、身份明确且完成对账的持仓才能列入风险表。'),
    verified?'账本已内部对账 · 非券商订单':'缺少合格持仓');
 const alertCard=card('风险预警',
    riskOK?(alerts.length?table(['触发规则','风险对象','当前风险','约束值','受影响标的'],warningRows):
       empty('当前未触发已核验的规则预警','无超额集中度不等于不存在市场和尾部风险。')):
      empty('尚不能确认预警状态','缺少来源可核对的持仓，不能声称不存在风险。'),
    '个股集中 / 行业集中 / 总仓位');
 const historyCard=card('权益轨迹',
   sessions.length>1?svgLine(sessions.filter(x=>x.equity!=null).map(x=>x.equity),'#6bd5bf',160)+
     table(['实际交易日','现金','组合权益','持仓数','本日模拟成交'],
     sessions.slice(-10).map(x=>[date(x.session_date_et),'$'+n(x.cash,2),
      '$'+n(x.equity,2),n(x.positions,0),n(x.new_modeled_fills,0)])):
     empty('暂无足够连续交易日数据','只有已经冻结并真实观察的未来交易日可以形成模拟账本曲线。'),
   '数据源时间序列 · 非券商绩效');
 const evidence='<details class="workspace-details"><summary>数据与模型证据</summary>'+card('证据',
   row('模拟账户',riskStatus(account?.status||'NOT_READY'))+
   row('逐日流水',riskStatus(timeline?.status||'NOT_READY'))+
   row('前向模拟数据资格',riskStatus(readiness?.stages?.forward_shadow?.status||'BLOCKED'))+
   row('持仓集中度计算',riskStatus(risk?.status||'NOT_READY'))+
   note('技术状态仅用于诊断；风险决策仍以持仓、敞口和规则触发为主。'),
   '按需查看')+'</details>';
 return {title:'持仓与风控',html:nav+cards+
   '<div class="grid cols2" style="margin-top:15px">'+limits+'</div>'+
   '<div class="grid cols2" style="margin-top:15px">'+positionCard+alertCard+'</div>'+
   '<div class="grid cols2" style="margin-top:15px">'+historyCard+evidence+'</div>'};
};
pages.data=async()=>{
 const response=await settle('/api/v1/research/readiness');
 if(response.pending){
  return {title:'研究准入',html:
   heading('研究准入','判断当前数据、模型和回测证据能否进入正式研究流程。',
    link('/studio#warehouse','查看数据仓库')+link('/data','高级数据维护'))+
   V.moduleLoading('研究资格矩阵')};
 }
 if(!response.ok){
  return {title:'研究准入',html:
   heading('研究准入','判断当前数据、模型和回测证据能否进入正式研究流程。',
    link('/studio#warehouse','查看数据仓库'))+
   V.moduleError('研究资格矩阵',response.error,'/api/v1/research/readiness')};
 }
 const readiness=response.data||{};
 const stages=readiness.stages||{};
 const nextSteps=readiness.next_steps||[];
 const label=status=>({
   PASS:'已通过',OBSERVATION_ONLY:'仅观察',BLOCKED:'受阻',
   NOT_READY:'未就绪',EVIDENCE_INVENTORY_ONLY:'仅证据盘点'
  })[status]||pretty(status);
 const qualificationBadge=status=>badge(label(status),
   status==='PASS'?'green':status==='OBSERVATION_ONLY'?'amber':/BLOCKED|NOT_READY|FAILED/i.test(status||'')?'red':'amber');
 const stageRows=ids=>ids.filter(id=>stages[id]).map(id=>{
   const item=stages[id]||{};
   const missing=(item.missing_evidence||[]).slice(0,3).join(' · ')||'—';
   return [
    e(item.description||id),
    qualificationBadge(item.status),
    e(item.code||'—'),
    e(missing),
    item.view?link(item.view,'查看证据'):'—'
   ];
 });
 const stageTable=(ids,emptyTitle)=> {
   const rows=stageRows(ids);
   return rows.length?table(['资格项目','状态','判定代码','缺失证据','入口'],rows):
    empty(emptyTitle,'当前没有可核验的资格证据。');
 };
 const hist=stages.historical_model?.status;
 const backtest=stages.historical_backtest?.status;
 const forward=stages.forward_shadow?.status;
 const html=
  heading('研究准入',
   '集中查看历史模型、严格回测和前向研究的准入状态。',
   link('/studio#warehouse','查看数据仓库')+link('/data','高级数据维护'))+
  '<div class="v4-muted-note" style="margin-bottom:15px">资格检查时间 '+e(readiness.checked_at_utc||'—')+
   ' · 策略：'+e(readiness.policy||'REAL_ONLY')+
   ' · 真实券商订单：'+(readiness.real_orders_enabled?badge('已开启','red'):badge('永久关闭','amber'))+
   '</div>'+
  grid(4,[
   kpi('历史模型 PIT',hist?qualificationBadge(hist):'—','历史证券身份与时点证据必须独立通过','blue'),
   kpi('严格历史回测',backtest?qualificationBadge(backtest):'—','原价、公司行为、历史证券池分别验收','purple'),
   kpi('前向冻结研究',forward?qualificationBadge(forward):'—','冻结模型与决策时点必须可追溯','green'),
   kpi('当前阻断项',n(nextSteps.length,0),'按真实业务依赖顺序列出，不按通过率包装','amber')
  ].join(''))+
  '<div class="grid cols2" style="margin-top:15px">'+
   card('历史数据与 PIT 准入',
    stageTable(['dataset','historical_model','asset_directory','pit_fundamentals','industry_factors'],
      '历史数据资格尚未形成'),
    '来源观察 ≠ 历史 PIT')+
   card('严格回测准入',
    stageTable(['historical_backtest','verified_backtest_runs'],
      '严格回测资格尚未形成'),
    '历史 replay 与已验收产物分别核验')+
  '</div>'+
  '<div class="grid cols2" style="margin-top:15px">'+
   card('前向研究准入',
    stageTable(['forward_data','forward_shadow','forward_observations','frozen_decision'],
      '前向研究资格尚未形成'),
    '数据 → 冻结模型 → 连续观察 → 冻结决策')+
   card('模型版本与模拟组合证据',
    stageTable(['strategy_versions','paper_account','paper_timeline'],
      '策略与模拟组合证据尚未形成'),
    '本地模拟对账不代表券商成交')+
  '</div>'+
  '<div style="margin-top:15px">'+card('当前阻断与下一步',
   nextSteps.length?table(['受阻项目','阻断代码','下一步'],nextSteps.map(item=>[
    e(item.description||item.module),
    e(item.reason||'—'),
    item.view?link(item.view,'去处理'):'—'
   ])):
   empty('当前没有已登记的阻断项','这只表示资格矩阵没有 BLOCKED 项，不代表预测有效性、交易收益或完整产品验收已经通过。'),
   '按业务依赖顺序，不以通过率替代证据')+'</div>'+
  '<div class="grid cols2" style="margin-top:15px">'+
   card('资格边界',
    row('完整产品验收',readiness.complete_product_acceptance?badge('已通过','green'):badge('未通过','amber'))+
    row('历史回测数据资格',readiness.historical_backtest_data_eligible?badge('允许','green'):badge('未允许','red'))+
    row('前向模拟数据资格',readiness.forward_shadow_data_eligible?badge('允许','green'):badge('未允许','red'))+
    row('真实券商订单',readiness.real_orders_enabled?badge('开启','red'):badge('不支持','amber'))+
    note('任何单一来源观测、文件哈希、策略版本或本地模拟余额，都不能单独证明预测能力、PIT 资格、真实成交或可交易性。'),
    'REAL_ONLY · 资格不会自动升级')+
   card('页面职责',
    row('数据仓库',link('/studio#warehouse','资产 · 来源 · 质量 · 更新 · 预览'))+
    row('研究准入',badge('当前页面','blue'))+
    row('严格回测',link('/backtests','查看回测资格与结果'))+
    row('模拟组合',link('/paper','查看本地模拟账本'))+
    note('本页不再重复展示数据集数量、行情来源、新鲜度或数据预览，避免与数据仓库职责重叠。'),
    '资格判定与数据管理分离')+
  '</div>';
 return {title:'研究准入',html};
};
})();
