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
 const nav=heading('持仓管理与风控预警',
   '在已存在的模拟持仓基础上监控仓位、相关性、波动和模型状态；不局限于买入前止损',
   link('/paper','打开组合账本及逐日复盘'));
 const cards=grid(4,[
   kpi('模拟组合权益',verified?'$'+n(account.equity,2):'—',
       verified?'根据已核对的真实价格估值':'缺少合格模拟账本','blue'),
   kpi('现金余额',verified?'$'+n(account.cash,2):'—',
       '未发生实际券商成交','green'),
   kpi('组合权益持仓占比',riskOK?pct(risk.gross_weight):'—',
       '仓位集中度由实际持仓估算','purple'),
   kpi('当前风险预警',riskOK?n(alerts.length,0):'—',
       '未核验时不填零','amber')
 ].join(''));
 const limits=grid(2,[
   card('仓位与退出规则 · 风控政策',
     row('单笔计划权益风险',pct(.003))+
     row('单只股票上限',pct(.10))+
     row('组合总仓位上限',pct(.50))+
     row('行业仓位上限',pct(.25))+
     row('初始保护止损','2 × ATR20')+
     row('默认短线持仓','1 / 3 / 5 个交易日')+
     note('上述为研究基线阈值，具体策略版本的冻结参数须单独核对。实际止损不能保证隔夜跳空风险。'),
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
 const positionCard=card('当前模拟持仓 · 真实账本',
    detail.length?table(['证券ID','数量','最近估值价','估计市值','行业'],detail):
      empty('当前没有具备内部对账的持仓','只有来源真实、身份明确且完成对账的持仓才能列入风险表。'),
    verified?'账本已内部对账 · 非券商订单':'缺少合格持仓');
 const alertCard=card('风险预警 · 规则与解释',
    riskOK?(alerts.length?table(['触发规则','风险对象','当前风险','约束值','受影响标的'],warningRows):
       empty('当前未触发已核验的规则预警','无超额集中度不等于不存在市场和尾部风险。')):
      empty('尚不能确认预警状态','缺少来源可核对的持仓，不能声称不存在风险。'),
    '个股集中 / 行业集中 / 总仓位');
 const historyCard=card('逐日权益与模拟账本',
   sessions.length>1?svgLine(sessions.filter(x=>x.equity!=null).map(x=>x.equity),'#6bd5bf',160)+
     table(['实际交易日','现金','组合权益','持仓数','本日模拟成交'],
     sessions.slice(-10).map(x=>[date(x.session_date_et),'$'+n(x.cash,2),
      '$'+n(x.equity,2),n(x.positions,0),n(x.new_modeled_fills,0)])):
     empty('暂无足够连续交易日数据','只有已经冻结并真实观察的未来交易日可以形成模拟账本曲线。'),
   '数据源时间序列 · 非券商绩效');
 const evidence=card('来源与模型可靠性',
   row('模拟账户',riskStatus(account?.status||'NOT_READY'))+
   row('逐日流水',riskStatus(timeline?.status||'NOT_READY'))+
   row('前向模拟数据资格',riskStatus(readiness?.stages?.forward_shadow?.status||'BLOCKED'))+
   row('持仓集中度计算',riskStatus(risk?.status||'NOT_READY'))+
   row('真实券商订单',badge('不支持','amber'))+
   note('风险预警应持续复核市场环境、个股止损、行业敞口与策略模型失效，不允许把预测精度伪装为真实交易回报。'),
   'L4 · 证据检查');
 return {title:'持仓管理与风控预警',html:nav+cards+
   '<div class="grid cols2" style="margin-top:15px">'+limits+'</div>'+
   '<div class="grid cols2" style="margin-top:15px">'+positionCard+alertCard+'</div>'+
   '<div class="grid cols2" style="margin-top:15px">'+historyCard+evidence+'</div>'};
};
pages.data=async()=>{
 const all=await Promise.all([
    settle('/api/status'),settle('/api/v1/research/readiness'),
    settle('/api/v1/v4/daily'),settle('/api/v1/data/catalog'),
    settle('/api/v1/v4/freshness')]);
 const [system,readiness,diary,catalog,freshness]=all.map(x=>x.ok?x.data:null);
 const latest=(diary?.runs||[])[0]||null;
 const checks=Object.entries(readiness?.stages||{}).map(([id,x])=>[
  e(x.description||id),riskStatus(x.status),e(x.code||'—'),
  e((x.missing_evidence||[]).slice(0,2).join(' · ')||'—')]);
 const stageRows=(latest?.stages||[]).map(x=>[
   e(x.stage),riskStatus(x.status),e(x.code||'—')]);
 const prices=system?.prices||[];
 const status=system?.dataset||{};
 const limitations=(system?.limitations||[]).map(x=>'<div class="v4-stat-pair"><span class="muted">'+e(x)+'</span></div>').join('');
 const freshRows=Object.entries(freshness?.modules||{}).map(([name,x])=>[
   e(name),date(x.asof_session),date(x.source_data_asof),
   e(x.knowledge_cutoff_utc||'—'),riskStatus(x.freshness_status),
   e(x.blocked_reason||'—')]);
 const html=heading('数据中心与研究资格',
   '底层市场数据、历史证券身份、因子版本及模型运行证据集中管理，不让 API 错误占据用户主界面',
   link('/data','打开完整数据管理工具'))+
   grid(4,[
     kpi('实际接入证券',prices.length?n(prices.length,0):'—','来自现存真实数据仓库','blue'),
     kpi('最近数据观察日',status.asof_date_et?date(status.asof_date_et):'—','不是系统当前日期','purple'),
     kpi('数据能力检查',readiness?n(Object.keys(readiness.stages||{}).length,0):'—','状态需逐项核对','green'),
     kpi('四层日终归档',latest?date(latest.session_date_et):'—','不能倒填交易日','amber')
   ].join(''))+
   '<div class="grid cols2" style="margin-top:15px">'+
      card('行情来源与使用边界',
        row('市场数据来源',e(status.source||'—'))+
        row('最近交易日',date(status.asof_date_et))+
        row('数据快照 SHA256',short(status.snapshot_sha256,22))+
        row('仓库研究用途',badge('真实观测 ≠ 历史可交易','amber'))+
        note('公司行为、历史退市和 PIT 证券池需要独立证据；供应商当前可交易列表不能自动倒填历史。'),
        'DATA INFRASTRUCTURE')+
      card('自动研究任务 · 最近日终日志',
        latest?table(['阶段','运行状态','原因'],stageRows):
          empty('尚无可核验的日终任务','缺少完成的交易日数据或完整来源时，不自动制造运行成功。'),
        '真实研究任务')+
   '</div>'+
   '<div style="margin-top:15px">'+card('模型、数据与回测资格矩阵',
      checks.length?table(['项目','状态','代码','缺失证据'],checks):
         empty('资格矩阵尚未就绪',readiness?'尚无资格项':'检查本地数据库和数据审计记录。'),
      '模型训练 / 历史回测 / 前向模拟分别验收')+'</div>'+
   '<div style="margin-top:15px">'+card('统一决策时点与模块新鲜度',
      freshRows.length?table(['模块','研究交易日','实际数据日','决策截止 UTC','时效状态','阻断原因'],freshRows):
        empty('新鲜度证据暂不可用','检查本地时钟、行情仓库和来源可用时间。'),
      '行情观察 CURRENT 不代表预测或交易合格')+'</div>'+
   '<div class="grid cols2" style="margin-top:15px">'+
      card('数据使用限制',limitations||
       empty('当前无附加说明','不等于已通过历史 PIT 或策略有效性认证。'),'来源与更新时间')+
      card('研究和数据维护工具',
        '<div class="v4-actions">'+link('/data','数据接入及质量核查')+
         link('/styles','经典因子数据')+link('/backtests','回测资格审查')+'</div>'+
        note('研究工具应保留真实数据原始回执、哈希、可用时间和实验版本，不修改历史已经冻结的记录。'),
        '高级操作不改变一级导航')
   '</div>';
 return {title:'数据中心',html};
};
})();
