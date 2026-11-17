/* QDR V4 Data Warehouse: read-only operational inventory. */
(() => {
'use strict';
const V=window.V4;
if(!V)return;
const state={selected:null,query:'',category:'全部',status:'全部',tab:'overview',page:0};
const esc=V.e;
const resources={
 market_bars:'行情数据',market_universe:'证券目录',market_observations:'市场指标',
 security_features:'个股特征',reference_history:'宏观与跨资产历史',
 market_events:'事件与催化剂',source_health:'数据源监控',
 quality_checks:'质量检查',path_outcomes:'未来路径结果',
 source_receipts:'原始来源回执',maintenance_runs:'维护运行记录'
};
const statusTone=s=>({
 COLLECTED:'green',OBSERVED:'green',CURRENT:'green',PARTIAL:'amber',
 FAILED:'red',BLOCKED:'red',STALE:'amber',EMPTY:'amber',
 NOT_OBSERVED:'purple',NOT_CREATED:'purple',MAINTENANCE_RUNNING:'amber',
 READ_FAILED:'red'
}[s]||'blue');
const statusText=s=>({
 COLLECTED:'已采集',OBSERVED:'有运行观测',CURRENT:'当前',PARTIAL:'部分',
 FAILED:'失败',BLOCKED:'阻断',STALE:'过期',EMPTY:'空数据',
 NOT_OBSERVED:'尚无运行记录',NOT_CREATED:'尚未创建',
 COLLECTED_RESTRICTED_USE:'已采集 · 用途受限',
 OBSERVED_CURRENT_CATALOG_NOT_HISTORICAL_PIT:'当前目录观测 · 非历史 PIT',
 RESEARCH_REGISTRY_AVAILABLE:'研究登记可用',
 OBSERVATION_FROZEN:'已冻结观察',
 STRATEGY_VERSIONS_AVAILABLE:'策略版本已登记',
 MAINTENANCE_RUNNING:'维护中',READ_FAILED:'读取失败'
}[s]||s||'未知');
const badge=(s)=>V.badge(statusText(s),statusTone(s));
const fmt=v=>v===null||v===undefined||v===''?'—':esc(v);
const num=v=>v===null||v===undefined?'—':Number(v).toLocaleString('zh-CN');
const stamp=v=>v?esc(String(v).replace('T',' ').replace('Z',' UTC').slice(0,19)):'未记录';
const box=(title,body,meta='')=>V.card(title,body,meta);
const pair=(k,v)=>V.row(k,v);
const empty=(title,desc)=>V.empty(title,desc);
const resourceLabel=id=>resources[id]||id;
function renderSourceRows(sources){
 return sources.map(x=>[
  '<b>'+esc(x.name)+'</b><div class="wh-muted">'+esc(x.source_key)+'</div>',
  badge(x.code_status),
  badge(x.run_status),
  esc(x.asof_session||'—'),
  esc(x.error_code||x.access||'—')
 ]);
}
function renderDatasetRows(datasets){
 return datasets.map(x=>{
  const selected=x.dataset_id===state.selected;
  return '<tr data-wh-dataset="'+esc(x.dataset_id)+'" class="'+(selected?'selected':'')+'">'+
   '<td><b>'+esc(x.name||resourceLabel(x.dataset_id))+'</b><div class="wh-muted">'+esc(x.table||x.dataset_id)+'</div></td>'+
   '<td>'+badge(x.status)+'</td>'+
   '<td class="mono">'+num(x.physical_rows)+'</td>'+
   '<td class="mono">'+fmt(x.symbols)+'</td>'+
   '<td>'+fmt(x.last_observation)+'</td></tr>';
 }).join('');
}
function renderPreview(preview){
 if(!preview||preview.pending)return empty('样本正在读取','只读读取本地数据库，不触发供应商请求。');
 if(!preview.ok)return empty('样本读取失败',preview.error?.message||'检查数据库状态。');
 const data=preview.data;
 if(data.status!=='OBSERVED')return empty(statusText(data.status),'当前没有可预览的真实记录。');
 if(!data.rows?.length)return empty('当前筛选无记录','调整证券或日期范围。');
 const cols=data.columns||[];
 return '<div class="wh-table-wrap"><table class="table"><thead><tr>'+
  cols.map(c=>'<th>'+esc(c)+'</th>').join('')+
  '</tr></thead><tbody>'+data.rows.map(row=>'<tr>'+cols.map(c=>{
   const val=row[c];
   return '<td title="'+esc(val??'')+'">'+fmt(val)+'</td>';
  }).join('')+'</tr>').join('')+'</tbody></table></div>'+
  '<div class="wh-pager"><span>共 '+num(data.total)+' 条记录</span>'+
  '<button class="btn smallbtn" id="wh-prev" '+(state.page<=0?'disabled':'')+'>上一页</button>'+
  '<span>第 '+(state.page+1)+' 页</span>'+
  '<button class="btn smallbtn" id="wh-next" '+((state.page+1)*20>=data.total?'disabled':'')+'>下一页</button></div>';
}
function renderDetail(dataset,detail,preview){
 if(!dataset)return empty('选择一个数据资产','点击左侧数据集，查看实际记录、时间范围、来源和使用限制。');
 if(detail?.pending)return empty('正在读取数据集详情','读取实际存储结构与数据范围。');
 const d=detail?.ok?detail.data.dataset:null;
 if(!d)return empty('数据集详情暂不可用',detail?.error?.message||statusText(detail?.data?.status||'NOT_CREATED'));
 let body='';
 if(state.tab==='overview'){
  body='<div class="wh-detail-grid">'+
   pair('数据状态',badge(d.status))+
   pair('物理记录数','<b class="mono">'+num(d.physical_rows)+'</b>')+
   pair('业务去重记录','<b class="mono">'+num(d.unique_rows)+'</b>')+
   pair('证券数量','<b class="mono">'+num(d.symbols)+'</b>')+
   pair('最早观测',fmt(d.first_observation))+
   pair('最新观测',fmt(d.last_observation))+
   pair('最近实际观测时间',stamp(d.latest_observed_at_utc))+
   pair('供应商可用时间',stamp(d.latest_available_at_utc))+
   pair('本地抓取时间',stamp(d.latest_fetched_at_utc))+
   pair('仓库写入时间',stamp(d.latest_ingested_at_utc))+
   pair('存储表','<code>'+esc(d.table)+'</code>')+
   pair('数据文件','<code>'+esc(d.path)+'</code>')+
   pair('更新频率',fmt(d.cadence))+
   pair('使用资格',badge(d.use_policy))+'</div>'+
   '<div class="wh-policy">'+esc(d.description||'')+'<p>使用限制：'+esc((d.limitations||[]).join('；'))+'</p></div>';
 }else if(state.tab==='schema'){
  body=(d.columns||[]).length?'<div class="wh-table-wrap"><table class="table"><thead><tr><th>字段</th><th>类型</th></tr></thead><tbody>'+
   d.columns.map(c=>'<tr><td><code>'+esc(c.name)+'</code></td><td>'+esc(c.type)+'</td></tr>').join('')+
   '</tbody></table></div>':empty('字段结构暂不支持','该资产当前只提供只读数据库摘要，未开放字段结构浏览。');
 }else{
  body=renderPreview(preview);
 }
 return '<div class="wh-detail-head"><div><div class="wh-dataset-name">'+esc(d.name)+'</div><div class="wh-muted">'+esc(d.dataset_id)+' · '+esc(d.table)+'</div></div>'+badge(d.status)+'</div>'+
  '<div class="wh-tabs">'+
  [['overview','概览'],['preview','数据预览'],['schema','字段结构']].map(([id,label])=>
   '<button class="wh-tab '+(state.tab===id?'active':'')+'" data-wh-tab="'+id+'">'+label+'</button>').join('')+
  '</div>'+body;
}
V.pages.warehouse=async()=>{
 const [overview,runsResult]=await Promise.all([
  V.settle('/api/v1/warehouse/overview'),
  V.settle('/api/v1/warehouse/runs?limit=10')
 ]);
 const data=overview.ok?overview.data:null;
 if(!overview.ok||!data)return {title:'数据仓库',html:V.heading('数据仓库','数据资产、来源状态、质量问题与真实样本')+empty('仓库状态暂不可用',overview.error?.message||'本地服务尚未返回结果。')};
 if(data.status==='READ_FAILED')return {title:'数据仓库',html:V.heading('数据仓库','本地数据资产与运行可观测性')+empty('仓库读取失败',data.error_code||'检查本地数据库文件与权限。')};
 if(data.status==='MAINTENANCE_RUNNING')return {title:'数据仓库',html:V.heading('数据仓库','本地数据资产与运行可观测性')+V.card('数据维护进行中',empty('暂不并发读取仓库','维护锁释放后再刷新。'),statusText(data.status))};
 if(!state.selected&&data.datasets?.length)state.selected=data.datasets[0].dataset_id;
 const categories=['全部',...new Set((data.datasets||[]).map(x=>x.category).filter(Boolean))];
 const statuses=['全部',...new Set((data.datasets||[]).map(x=>x.status).filter(Boolean))];
 const filtered=(data.datasets||[]).filter(x=>
  (state.category==='全部'||x.category===state.category)&&
  (state.status==='全部'||x.status===state.status)&&
  (!state.query||[x.name,x.dataset_id,x.table,x.category].join(' ').toLowerCase().includes(state.query.toLowerCase()))
 );
 const selected=filtered.find(x=>x.dataset_id===state.selected)||filtered[0]||null;
 if(selected)state.selected=selected.dataset_id;
 const detail=selected?await V.settle('/api/v1/warehouse/datasets/'+encodeURIComponent(selected.dataset_id)):null;
 const preview=selected&&state.tab==='preview'?await V.settle(
  '/api/v1/warehouse/datasets/'+encodeURIComponent(selected.dataset_id)+'/preview?limit=20&offset='+(state.page*20)
 ):null;
 const summary=data.summary||{};
 const attention=(data.attention||[]).length?
  '<div class="wh-attention-list">'+data.attention.slice(0,8).map(x=>
   '<div class="wh-attention-item"><span>'+badge(x.status)+'</span><b>'+esc(x.title)+'</b><span>'+esc(x.reason||'需要检查来源运行记录')+'</span><small>'+stamp(x.last_observed_at)+'</small></div>'
  ).join('')+'</div>':empty('暂无已记录的运行阻断','没有失败记录不代表所有注册数据源都已验证；未运行的数据源会标记为尚无运行记录。');
 const sources=(data.sources||[]);
 const runData=runsResult.ok?runsResult.data:null;
 const runRows=(runData?.runs||[]).map(x=>[
  '<b>'+esc(x.command)+'</b><div class="wh-muted">'+esc(x.run_id)+'</div>',
  badge(x.status),
  stamp(x.started_at_utc),
  stamp(x.completed_at_utc),
  esc(JSON.stringify(x.counts||{}))
 ]);
 const html=V.heading('数据仓库','本地数据资产与运行可观测性 · 只读，不触发供应商请求',
  '<button class="btn smallbtn" id="wh-refresh">↻ 刷新状态</button> <a class="btn smallbtn" href="/data">打开数据维护</a>')+
  '<div class="wh-meta-line"><span>数据库 <code>'+esc(data.database_path||'—')+'</code></span><span>读取时间 '+stamp(data.generated_at_utc)+'</span><span>'+badge(data.status)+'</span></div>'+
  V.grid(4,[
   V.kpi('数据资产',num(summary.datasets??data.datasets?.length??0),'实际登记的逻辑数据集','blue'),
   V.kpi('已有记录的数据集',num(summary.populated_datasets??0),'以物理记录数判断','green'),
   V.kpi('物理记录',num(summary.physical_rows??0),'保留原始修订版本','purple'),
   V.kpi('需要关注',num(summary.attention_count??0),'来源或数据集存在阻断、缺失或过期','amber')
  ].join(''))+
  '<div class="wh-attention-section">'+box('需要关注',attention,'只列有运行证据的问题')+'</div>'+
  '<div class="wh-main-grid"><section class="card pad wh-assets"><div class="ctitle">数据资产 <span>按真实表结构统计</span></div>'+
   '<div class="wh-filters"><input id="wh-search" placeholder="搜索数据集、表名或类别" value="'+esc(state.query)+'"/>'+
   '<select id="wh-category">'+categories.map(x=>'<option '+(state.category===x?'selected':'')+'>'+esc(x)+'</option>').join('')+'</select>'+
   '<select id="wh-status">'+statuses.map(x=>'<option value="'+esc(x)+'" '+(state.status===x?'selected':'')+'>'+esc(x==='全部'?x:statusText(x))+'</option>').join('')+'</select></div>'+
   '<div class="wh-table-wrap"><table class="table"><thead><tr><th>数据集</th><th>状态</th><th>物理行数</th><th>证券数</th><th>最新观测</th></tr></thead><tbody>'+
    (filtered.length?renderDatasetRows(filtered):'<tr><td colspan="5">没有符合条件的数据资产。</td></tr>')+
   '</tbody></table></div><div class="wh-count">'+filtered.length+' / '+(data.datasets||[]).length+' 个数据集</div></section>'+
   '<section class="card pad wh-detail">'+renderDetail(selected,detail,preview)+'</section></div>'+
  '<div class="grid cols2 wh-bottom">'+
   box('数据源监控',V.table(['数据源','代码状态','运行状态','观察日','错误 / 访问限制'],renderSourceRows(sources)),'注册状态与运行状态严格分开')+
   box('最近维护记录',runRows.length?V.table(['任务','状态','开始时间','完成时间','计数摘要'],runRows):
    empty('暂无 L1 维护记录',runData?.status==='NOT_CREATED'?'L1 数据库尚未创建。':'当前没有已归档的运行记录。'),'只展示实际运行日志')+
  '</div><div class="grid cols2 wh-bottom">'+
   box('仓库使用边界',
    '<div class="wh-policy-list">'+
     '<p>• 当前证券目录与 ETF 代理不代表完整历史全市场。</p>'+
     '<p>• VIX/FRED 参考序列独立存储，不混入实时特征覆盖。</p>'+
     '<p>• 未来路径结果只用于验证，不作为预测输入。</p>'+
     '<p>• 当前页面只读，不会回补行情、重试 Provider 或修改数据库。</p>'+
     '<p>• PIT、预测与交易资格不会因数据存在而自动提升。</p></div>',
    'DATA GOVERNANCE')
  ].join(''))+
  '<div class="wh-foot">目录状态仅反映本地数据库中实际存在的记录。没有观测记录的来源显示“尚无运行记录”，不会被推断为正常。</div>';
 return {title:'数据仓库',html,mount:()=>{
  document.getElementById('wh-refresh')?.addEventListener('click',()=>{V.toast('正在重新读取本地数据状态');V.refresh()});
  document.getElementById('wh-search')?.addEventListener('input',ev=>{state.query=ev.target.value;V.show('warehouse')});
  document.getElementById('wh-category')?.addEventListener('change',ev=>{state.category=ev.target.value;V.show('warehouse')});
  document.getElementById('wh-status')?.addEventListener('change',ev=>{state.status=ev.target.value;V.show('warehouse')});
  document.querySelectorAll('[data-wh-dataset]').forEach(el=>el.addEventListener('click',()=>{
   state.selected=el.dataset.whDataset;state.page=0;state.tab='overview';V.show('warehouse');
  }));
  document.querySelectorAll('[data-wh-tab]').forEach(el=>el.addEventListener('click',()=>{
   state.tab=el.dataset.whTab;state.page=0;V.show('warehouse');
  }));
  document.getElementById('wh-prev')?.addEventListener('click',()=>{state.page=Math.max(0,state.page-1);V.show('warehouse')});
  document.getElementById('wh-next')?.addEventListener('click',()=>{state.page++;V.show('warehouse')});
 }};
};
})();
