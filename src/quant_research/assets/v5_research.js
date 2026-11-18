/* QDR V5 research workspace organizer. Presentation-only. */
(() => {
'use strict';
const V=window.V4;if(!V)throw Error('QDR V5 research requires V4 core');
const {pages}=V;
function setHeading(host,title,subtitle){
 const h=host.querySelector('.heading .title');if(h)h.textContent=title;
 const s=host.querySelector('.heading .subtitle');if(s)s.textContent=subtitle;
}
function compactBoundary(host){
 host.querySelectorAll('.l2-disclaimer').forEach(el=>{el.classList.add('v5-boundary');el.innerHTML='当前为<strong>观察层</strong>；预测结果只在通过验证时显示。';});
 host.querySelectorAll('.wh-policy-note').forEach(el=>{el.classList.add('v5-boundary');el.textContent='数据健康与研究资格分开管理；PIT / 回测准入请到「研究准入」。';});
 host.querySelectorAll('.v4-muted-note').forEach(el=>{
  const t=(el.textContent||'').trim();
  if(t.includes('选择 2–8 个已完成的真实实验'))el.textContent='选择 2–8 个已完成实验，权重合计 100%。';
  else if(t.includes('本表为真实来源的观察数据'))el.textContent='当前为观察数据；历史准入在「研究准入」查看。';
  else if(t.includes('上述为研究基线阈值'))el.textContent='当前显示策略基线与已冻结规则；跳空等风险单独复核。';
 });
}

function cleanProductCopy(host){
 const replacements=[
  ['OBSERVATION_ONLY','观察可用'],
  ['RESEARCH_ONLY','研究结果'],
  ['NOT_READY','未就绪'],
  ['BLOCKED','暂不可用'],
  ['FAILED','异常'],
  ['不可变因子版本','因子版本'],
  ['保存不可变因子版本','保存因子版本'],
  ['保存不可变策略','保存策略版本'],
  ['注册历史，不能覆盖旧版','保留历史版本'],
  ['需真实历史来源资格','历史数据'],
  ['Yahoo（仅当前版本历史探索）','Yahoo'],
  ['Alpaca（需真实历史来源资格）','Alpaca'],
  ['研究结果不自动进入交易',''],
  ['没有生成概率、收益目标或交易指令',''],
  ['研究口径 v1 · 不构成投资建议','方法说明'],
  ['L3 · Alpha / Factor Lab','Alpha 因子'],
  ['L3 · 多因子选股','Alpha 选股'],
  ['L4 · 证据检查','按需查看'],
  ['静态研究限制','风险规则'],
  ['数据源时间序列 · 非券商绩效','权益变化'],
  ['账本已内部对账 · 非券商订单','账本已核对']
 ];
 host.querySelectorAll('.badge,.ctitle span,.v4-muted-note,.fine,.hint,.knote,.l2-card-foot,.l2-chart-foot,.wh-source-foot,.wh-policy-note,.v4-message,.notice').forEach(el=>{
  if(el.closest('code,pre'))return;
  let t=el.textContent||'';
  replacements.forEach(([a,b])=>{t=t.split(a).join(b);});
  el.textContent=t.trim();
  if(!el.textContent)el.remove();
 });
 host.querySelectorAll('.ctitle').forEach(el=>{
  const t=(el.textContent||'').trim();
  if(t.includes('开发')||t.includes('Codex'))el.querySelector('span')?.remove();
 });
}

function collapseCard(host,needle,label){
 const card=[...host.querySelectorAll('.card')].find(x=>(x.querySelector('.ctitle')?.textContent||'').includes(needle));
 if(!card||card.closest('.v5-tech-details'))return;
 const details=document.createElement('details');details.className='v5-tech-details';
 const summary=document.createElement('summary');summary.textContent=label;
 card.parentNode.insertBefore(details,card);details.appendChild(summary);details.appendChild(card);
}
function wrap(key,transform){
 const original=pages[key];if(typeof original!=='function')return;
 pages[key]=async()=>{const result=await original();const host=document.createElement('div');host.innerHTML=result.html;transform(host);cleanProductCopy(host);return {...result,html:host.innerHTML};};
}
wrap('style',host=>{setHeading(host,'风格轮动','七类风格的强弱、转折与领先性研究。');compactBoundary(host);host.querySelectorAll('.l2-tabs button').forEach(btn=>{if(btn.textContent.trim()==='计算证据')btn.textContent='方法与证据';});});
wrap('lab',host=>{setHeading(host,'因子实验','定义因子 → 计算样本 → 验证有效性 → 保存版本。');compactBoundary(host);collapseCard(host,'研究运行与历史','实验记录与技术状态');});
wrap('screen',host=>{setHeading(host,'选股与回测','组合因子 → 查看候选 → 验证样本外表现 → 形成研究计划。');compactBoundary(host);collapseCard(host,'严格回测与前向冻结记录','回测资格与前向研究证据');});
wrap('risk',host=>{setHeading(host,'持仓与风控','当前持仓、组合敞口、预警与退出规则。');compactBoundary(host);collapseCard(host,'来源与模型可靠性','数据与模型证据');});
wrap('data',host=>{setHeading(host,'研究准入','判断当前数据、模型和回测证据能否进入正式研究流程。');compactBoundary(host);collapseCard(host,'资格边界','查看资格边界');});
wrap('warehouse',host=>{setHeading(host,'数据与保障','数据资产、来源、质量、更新与异常。');compactBoundary(host);});
})();