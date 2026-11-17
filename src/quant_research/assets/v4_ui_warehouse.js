/* QDR Data Warehouse workspace. All figures are read from the read-only warehouse API. */
(() => {
 'use strict';
 const V=window.V4;
 if(!V)throw Error('V4 core must load before the data warehouse workspace');
 const {pages,e,n,date,badge,heading,kpi,grid,empty,settle}=V;
 const state={selected:null,tab:'overview',search:'',category:'all',status:'all',
              previewQ:'',previewSymbol:'',previewStart:'',previewEnd:'',previewOffset:0};
 let systemNames={};
 const categories=['行情数据','市场指标','因子数据','证券身份','个股特征','宏观与跨资产',
                   '公司行为','公司与财务','事件催化','来源与溯源','数据源监控','数据质量',
                   '结果验证','任务运行','研究与归档'];
 const statusText={
  COLLECTED_RESTRICTED_USE:'已采集 · 用途受限',OBSERVATION_FROZEN:'已冻结观察',
  STRATEGY_VERSIONS_AVAILABLE:'策略版本可用',RESEARCH_REGISTRY_AVAILABLE:'研究登记可用',
  ARCHIVE_PRESENT_RAW_HASH_NOT_RECHECKED:'归档存在 · 原文哈希未重验',
  BLOCKED:'受阻',FAILED:'失败',TABLE_NOT_CREATED:'数据表未创建',
  EMPTY_DATASET:'暂无记录',NOT_CREATED:'尚未创建',STALE:'已过期',
  PARTIAL:'部分可用',CURRENT:'新鲜度正常',OBSERVED:'已观测',
  NOT_OBSERVED:'尚无运行观测',PLANNED:'计划中',RUNNING:'运行中',
  MAINTAINED:'维护完成',PARTIAL_BLOCKED:'部分受阻',UPDATED:'更新成功',
  MISSING:'缺失',ERROR:'错误',IMPLEMENTED:'已实现',IMPLEMENTED_PARTIAL:'部分实现',NOT_HISTORICAL_PIT_ATTESTED:'未验证历史 PIT',FUTURE_OBSERVATION:'未来日期异常',UNKNOWN_DATE:'日期未知',NOT_APPLICABLE:'不适用'
 };
 const pretty=(v)=>statusText[v]||String(v||'未知').replaceAll('_',' ');
 const tone=(v)=>{
  if(['BLOCKED','FAILED','FUTURE_OBSERVATION','ERROR'].includes(v))return 'red';
  if(v==='STALE')return 'amber';
  if(['COLLECTED_RESTRICTED_USE','OBSERVATION_FROZEN','OBSERVED','UPDATED','MAINTAINED',
      'RESEARCH_REGISTRY_AVAILABLE','STRATEGY_VERSIONS_AVAILABLE','CURRENT'].includes(v))return 'green';
  if(['NOT_CREATED','TABLE_NOT_CREATED','EMPTY_DATASET','PARTIAL','MISSING','PARTIAL_BLOCKED','PLANNED'].includes(v))return 'amber';
  return 'blue';
 };
 const stamp=(v)=>v?e(String(v).replace('T',' ').replace('Z',' UTC').slice(0,23)):'—';
 const displayValue=(v)=>{
  if(v===null||v===undefined||v==='')return '—';
  if(typeof v==='object')return e(JSON.stringify(v));
  return e(String(v));
 };
 const assetStatus=(item)=>badge(pretty(item.status),tone(item.status));
 const count=(v)=>v===null||v===undefined||v===''?'—':Number.isFinite(Number(v))?n(Number(v),0):'—';
 const pathText=(v)=>v?'<code>'+e(v)+'</code>':'—';
 const filteredAssets=(items)=>{
  const q=state.search.trim().toLocaleLowerCase();
  return (items||[]).filter(item=>
   (state.category==='all'||item.category===state.category)&&
   (state.status==='all'||item.status===state.status)&&
   (!q||[item.name,item.dataset_id,item.source,item.path,item.table,item.category,
           ...(item.field_names||[]),...(item.systems||[]),
           ...(item.systems||[]).map(key=>systemNames[key]||'')]
    .some(v=>String(v||'').toLocaleLowerCase().includes(q))));
 };
 const renderAttention=(items)=>{
  if(!items?.length)return empty('当前没有已识别的异常','这里仅显示真实状态记录；未观测不等于已验证正常。');
  return '<div class="wh-attention-list">'+items.slice(0,8).map(item=>
   '<div class="wh-attention-item"><div class="wh-attention-mark '+e(item.severity)+'"></div>'+
   '<div class="wh-attention-copy"><b>'+e(item.name)+'</b><span>'+e(item.reason||item.status)+'</span>'+
   '<small>'+e(item.type)+' · '+e(item.id)+(item.occurred_at?' · '+e(item.occurred_at):'')+'</small>'+
   (item.action?'<small class="wh-attention-action">下一步：'+e(item.action)+'</small>':'')+'</div>'+
   badge(pretty(item.status),tone(item.status))+'</div>'
  ).join('')+'</div>';
 };
 const renderAssets=(items)=>{
  const rows=filteredAssets(items);
  if(!rows.length)return empty('没有匹配的数据资产','尝试调整搜索词、分类或状态筛选。');
  return '<div class="wh-asset-list">'+rows.map(item=>
   '<button type="button" class="wh-asset-row'+(item.dataset_id===state.selected?' active':'')+'" data-wh-asset="'+e(item.dataset_id)+'">'+
    '<span class="wh-asset-main"><b>'+e(item.name)+'</b><small>'+e(item.category||'未分类')+
    ' · '+e(item.source||'来源未登记')+'</small>'+
    ((item.systems||[]).length?'<span class="wh-system-tags">'+item.systems.map(key=>
      '<em>'+e(systemNames[key]||key)+'</em>').join('')+'</span>':'')+'</span>'+
    '<span class="wh-asset-meta"><b>'+count(item.physical_rows??item.rows)+'</b><small>物理记录</small></span>'+
    '<span class="wh-asset-state">'+badge(pretty(item.status),tone(item.status))+
    '<small>'+e(item.last_observation||item.last_date||item.latest_fetched_at_utc||'时间未知')+'</small>'+
    '<small>'+e(pretty(item.freshness_status||'UNKNOWN_DATE'))+'</small></span>'+
   '</button>'
  ).join('')+'</div><div class="wh-list-foot">显示 '+n(rows.length,0)+' / '+n(items.length,0)+' 项资产</div>';
 };
 const renderOverview=(item)=>{
  const pairs=[
   ['数据来源',item.source||'—'],['存储位置',item.path||'—'],
   ['权威数据表',item.table||'—'],['更新频率',item.cadence||'—'],
   ['物理记录数',count(item.physical_rows??item.rows)],
   ['去重样本数',count(item.unique_rows??item.latest_rows)],
   ['证券数量',count(item.symbols)],['指标数量',count(item.features)],
   ['起始观测日',item.first_observation||item.first_date||'—'],
   ['最新观测日',item.last_observation||item.last_date||'—'],
   ['最近可用时间',stamp(item.latest_available_at_utc)],
   ['最近抓取时间',stamp(item.latest_fetched_at_utc)],
   ['最近写入时间',stamp(item.latest_ingested_at_utc)],
   ['数据新鲜度',pretty(item.freshness_status||'UNKNOWN_DATE')],
   ['数据年龄',item.age_days==null?'—':count(item.age_days)+' 天'],
   ['容忍天数',item.max_age_days==null?'—':count(item.max_age_days)+' 天'],
   ['使用限制',item.use_policy||'—']
  ];
  return '<div class="wh-detail-grid">'+pairs.map(([k,v])=>
   '<div class="wh-detail-cell"><small>'+e(k)+'</small><b>'+e(String(v))+'</b></div>'
  ).join('')+'</div>'+
  (item.missing_reason?'<div class="wh-reason"><b>当前原因</b><span>'+e(item.missing_reason)+'</span></div>':'')+
  ((item.limitations||[]).length?'<div class="wh-reason"><b>使用限制</b><span>'+e(item.limitations.join('；'))+'</span></div>':'')+
  '<div class="wh-policy-note">数据已采集不等于历史 PIT 已验证，也不代表已获得模型预测或交易资格。</div>';
 };
 const renderFields=(detail)=>{
  const fields=detail?.fields||[];
  if(!fields.length)return empty('暂无可读取的字段结构',detail?.preview_reason||'该资产可能是报告、归档或尚未创建的数据表。');
  return '<div class="v4-table-scroll"><table class="table wh-table"><thead><tr><th>字段名</th><th>数据类型</th><th>可空</th><th>键约束</th></tr></thead><tbody>'+
   fields.map(f=>'<tr><td><code>'+e(f.name)+'</code></td><td>'+e(f.type)+'</td><td>'+
    (f.nullable?'是':'否')+'</td><td>'+e(f.key||'—')+'</td></tr>').join('')+
   '</tbody></table></div>';
 };
 const renderPreview=(preview,detail,error)=>{
  if(!detail?.preview_supported)return empty('该资产暂不支持表格预览',detail?.preview_reason||'V1 仅开放已登记的只读表。');
  if(!preview)return empty('无法读取真实样本',error||'样本尚未返回；不会用示例数据填充。');
  const rows=preview.rows||[];
  if(!rows.length)return empty('当前筛选没有样本','该数据表在当前过滤条件下没有真实记录。');
  const cols=Object.keys(rows[0]).slice(0,12);
  return '<div class="wh-preview-meta">共 '+n(preview.total,0)+' 条匹配记录 · 当前 '+n(preview.offset+1,0)+'–'+n(Math.min(preview.offset+rows.length,preview.total),0)+' 条 · 只读</div>'+
   '<div class="v4-table-scroll"><table class="table wh-table wh-preview-table"><thead><tr>'+
   cols.map(c=>'<th>'+e(c)+'</th>').join('')+'</tr></thead><tbody>'+
   rows.map(row=>'<tr>'+cols.map(c=>'<td title="'+displayValue(row[c])+'">'+displayValue(row[c])+'</td>').join('')+'</tr>').join('')+
   '</tbody></table></div>'+
   '<div class="wh-pagination"><button type="button" class="btn smallbtn" data-wh-prev '+(preview.offset<=0?'disabled':'')+'>上一页</button>'+
   '<span>'+n(preview.offset+1,0)+'–'+n(preview.offset+rows.length,0)+' / '+n(preview.total,0)+'</span>'+
   '<button type="button" class="btn smallbtn" data-wh-next '+(preview.offset+rows.length>=preview.total?'disabled':'')+'>下一页</button></div>';
 };
 const renderHistory=(runs)=>{
  if(!runs?.length)return empty('暂无维护记录','只有 outputs/maintenance 中真实存在的 manifest 才会显示在这里。');
  return '<div class="wh-run-list">'+runs.slice(0,12).map(run=>
   '<div class="wh-run"><div><b>'+e(run.run_id)+'</b><small>'+stamp(run.created_at_utc)+' · '+e(run.end||'交易日未记录')+'</small></div>'+
   badge(pretty(run.status),tone(run.status))+
   '<div class="wh-run-tasks">'+(run.tasks||[]).map(task=>
    '<span>'+e(task.group||task.source||'任务')+' '+badge(pretty(task.status),tone(task.status))+
    (task.code?' <small>'+e(task.code)+'</small>':'')+'</span>'
   ).join('')+'</div></div>'
  ).join('')+'</div>';
 };
 const renderLineage=(item,detail)=>{
  const lineage=detail?.lineage||{};
  return '<div class="wh-lineage"><div><small>01 · 数据来源</small><b>'+e(lineage.source||item.source||'未登记')+'</b></div>'+
   '<div class="wh-lineage-arrow">↓</div><div><small>02 · 权威存储</small><b>'+e(lineage.path||item.path||'未登记')+'</b>'+
   '<span>'+e(lineage.table||item.table||'文件 / 归档')+'</span></div>'+
   '<div class="wh-lineage-arrow">↓</div><div><small>03 · 使用边界</small><b>'+e(lineage.use_policy||item.use_policy||'未定义')+'</b></div></div>'+
   '<div class="wh-policy-note">当前展示资产登记层的来源—存储关系，不代表每条样本都已逐条复核原始回执或完整派生链；未验证的 PIT、历史身份和许可条件不会因此自动通过。</div>';
 };
 const renderDetail=(item,detail,preview,runs,previewError)=>{
  if(!item)return empty('选择一个数据资产','从左侧资产清单中选择数据集，查看来源、字段、样本和维护记录。');
  const tabs=[['overview','概览'],['preview','数据预览'],['fields','字段结构'],['history','更新记录'],['lineage','血缘与资格']];
  let body='';
  if(state.tab==='overview')body=renderOverview(item);
  if(state.tab==='preview')body=renderPreview(preview,detail,previewError);
  if(state.tab==='fields')body=renderFields(detail);
  if(state.tab==='history')body=renderHistory(runs);
  if(state.tab==='lineage')body=renderLineage(item,detail);
  const fieldNames=new Set((detail?.fields||[]).map(field=>field.name));
  const hasSymbol=fieldNames.has('symbol');
  const hasDate=['session_date','observation_date','date','scheduled_at','started_at','observed_start']
    .some(field=>fieldNames.has(field));
  const filter=state.tab==='preview'?'<div class="wh-preview-filter"><input id="wh-preview-q" placeholder="搜索样本字段值" value="'+e(state.previewQ)+'" maxlength="64"/>'+
   (hasSymbol?'<input id="wh-preview-symbol" placeholder="证券代码" value="'+e(state.previewSymbol)+'" maxlength="24"/>':'')+
   (hasDate?'<input id="wh-preview-start" type="date" value="'+e(state.previewStart)+'"/>'+
    '<input id="wh-preview-end" type="date" value="'+e(state.previewEnd)+'"/>':'')+
   '<button type="button" class="btn smallbtn primary" id="wh-preview-apply">筛选样本</button></div>':'';
  return '<div class="wh-detail-head"><div><div class="wh-detail-name">'+e(item.name)+'</div>'+
   '<div class="wh-detail-sub">'+e(item.dataset_id)+' · '+e(item.category||'未分类')+'</div></div>'+
   assetStatus(item)+'</div><div class="wh-tabs">'+tabs.map(([id,label])=>
    '<button type="button" class="wh-tab'+(state.tab===id?' active':'')+'" data-wh-tab="'+id+'">'+label+'</button>'
   ).join('')+'</div>'+filter+'<div class="wh-tab-body">'+body+'</div>';
 };
 pages.warehouse=async()=>{
  const response=await settle('/api/v1/warehouse/overview');
  if(!response.ok)return {title:'数据仓库',html:heading('数据仓库','数据资产、来源、质量与更新状态')+
    empty('暂时无法读取数据仓库',response.error?.message||'请检查本地服务和数据目录。')};
  const data=response.data||{};
  if(data.status==='MAINTENANCE_RUNNING'){
   return {title:'数据仓库',html:heading('数据仓库','数据资产、来源、质量与更新状态',
     '<a class="btn" href="/data">打开数据维护</a>')+
     '<div class="wh-maintenance-banner"><b>数据维护正在运行</b><span>'+e(data.message||'数据库由维护任务持有。')+'</span></div>'+
     renderHistory(data.maintenance?.recent_runs||[])};
  }
  const assets=data.datasets||[];
  if(!assets.length)return {title:'数据仓库',html:heading('数据仓库','数据资产、来源、质量与更新状态')+
    empty('数据资产目录暂不可用','请检查数据仓库服务返回。')};
  const registry=data.registry||{};
  systemNames=Object.fromEntries((registry.systems||[]).map(item=>[item.key,item.name]));
  const visibleAssets=filteredAssets(assets);
  if(!visibleAssets.some(x=>x.dataset_id===state.selected)){
   state.selected=(visibleAssets[0]||assets.find(x=>x.dataset_id==='market_prices')||assets[0]).dataset_id;
  }
  const selected=assets.find(x=>x.dataset_id===state.selected);
  const detailResponse=await settle('/api/v1/warehouse/datasets/'+encodeURIComponent(state.selected));
  const detail=detailResponse.ok?detailResponse.data:{fields:[],preview_supported:false,preview_reason:detailResponse.error?.message||'资产详情读取失败'};
  const previewFields=new Set((detail?.fields||[]).map(field=>field.name));
  if(!previewFields.has('symbol'))state.previewSymbol='';
  if(!['session_date','observation_date','date','scheduled_at','started_at','observed_start'].some(field=>previewFields.has(field))){
   state.previewStart='';state.previewEnd='';
  }
  let preview=null,previewError=null;
  if(state.tab==='preview'&&detail?.preview_supported){
   const params=new URLSearchParams({limit:'25',offset:String(state.previewOffset)});
   if(state.previewQ)params.set('q',state.previewQ);
   if(state.previewSymbol)params.set('symbol',state.previewSymbol);
   if(state.previewStart)params.set('start',state.previewStart);
   if(state.previewEnd)params.set('end',state.previewEnd);
   const previewResponse=await settle('/api/v1/warehouse/datasets/'+encodeURIComponent(state.selected)+'/preview?'+params.toString());
   if(previewResponse.ok)preview=previewResponse.data;else previewError=previewResponse.error?.message||'样本读取失败';
  }
  const summary=data.summary||{};
  const maintenance=data.maintenance||{};
  const kpis=grid(4,[
   kpi('登记数据资产',count(summary.asset_count),'逻辑资产，不代表全部可用于预测','blue'),
   kpi('有真实记录的资产',count(summary.with_records),'按逻辑数据集计数，不重复计算数据库容器','green'),
   kpi('需要关注',count(summary.attention_count),'明确的阻断、缺失或异常状态','amber'),
   kpi('最近成功维护',maintenance.latest_success?.finished_at_utc?stamp(maintenance.latest_success.finished_at_utc):'—',
       maintenance.latest_success?'最近一次整体成功的维护任务':'尚无整体成功记录','purple')
  ].join(''));
  const reg=registry.counts||{};
  const exportLinks=data.catalog_generated_at_utc?
    '<a class="btn smallbtn" href="/api/v1/data/catalog/datasets.csv">导出资产 CSV</a>'+
    '<a class="btn smallbtn" href="/api/v1/data/catalog/cache_index.csv">导出缓存索引</a>':'';
  const top=heading('数据仓库','统一查看真实数据资产、来源运行状态、质量证据和维护历史',
    '<button type="button" class="btn smallbtn" id="wh-refresh">刷新状态</button>'+exportLinks+
    '<a class="btn primary" href="/data">打开数据维护</a>');
  const registryLine='<div class="wh-registry-line"><b>L1 数据体系登记</b><span>'+
   n(reg.systems,0)+' 个体系 · '+n(reg.dimensions,0)+' 个维度 · '+n(reg.features,0)+' 个特征定义 · '+
   n(reg.features_observed,0)+' 个特征已有观测 · '+n(reg.sources,0)+' 个来源定义 · 目录快照 '+
   (data.catalog_generated_at_utc?stamp(data.catalog_generated_at_utc):'尚未生成')+'</span></div>';
  const main='<div class="wh-layout"><section class="card pad wh-assets-card"><div class="wh-section-title"><b>数据资产</b><span>'+n(assets.length,0)+' 项</span></div>'+
   '<div class="wh-asset-filters"><input id="wh-search" placeholder="搜索数据集、来源、字段、体系…" value="'+e(state.search)+'" maxlength="64"/>'+
   '<select id="wh-category"><option value="all">全部分类</option>'+categories.map(c=>
    '<option value="'+e(c)+'"'+(state.category===c?' selected':'')+'>'+e(c)+'</option>').join('')+'</select>'+
   '<select id="wh-status"><option value="all">全部状态</option>'+[...new Set(assets.map(x=>x.status))].sort().map(v=>
    '<option value="'+e(v)+'"'+(state.status===v?' selected':'')+'>'+e(pretty(v))+'</option>').join('')+'</select></div>'+
   renderAssets(assets)+'</section><section class="card pad wh-detail-card"><div class="wh-section-title"><b>资产详情</b><span>只读视图</span></div>'+
   renderDetail(selected,detail,preview,maintenance.recent_runs||[],previewError)+'</section></div>';
  const sources=(data.sources||[]).slice().sort((a,b)=>{
   const priority=x=>['BLOCKED','ERROR','FAILED','MISSING'].includes(x.runtime_status)?0:
    x.runtime_status==='NOT_OBSERVED'?1:2;
   return priority(a)-priority(b)||String(a.name).localeCompare(String(b.name));
  });
  const sourceRows=sources.map(x=>'<tr><td><b>'+e(x.name)+'</b><small class="wh-source-key">'+e(x.key)+'</small></td>'+
   '<td>'+badge(pretty(x.code_status),tone(x.code_status))+'</td>'+
   '<td>'+badge(pretty(x.runtime_status),tone(x.runtime_status))+'</td>'+
   '<td>'+badge(pretty(x.freshness?.status||'UNKNOWN_DATE'),tone(x.freshness?.status))+'</td>'+
   '<td>'+e(x.latest_observation?.asof_session||'—')+'</td>'+
   '<td>'+stamp(x.latest_observation?.fetched_at_utc)+'</td>'+
   '<td>'+e(x.latest_observation?.error_code||x.limitation||'—')+'</td></tr>').join('');
  const attentionBlock='<section class="card pad wh-attention-card"><div class="wh-section-title"><b>需要关注</b><span>阻断、过期、缺失与质量问题 · 按严重程度排序</span></div>'+
   renderAttention(data.attention||[])+'</section>';
  const bottom='<div class="wh-bottom-grid"><section class="card pad"><div class="wh-section-title"><b>数据源监控</b><span>'+n(sources.length,0)+' 个注册来源</span></div>'+
   (sourceRows?'<div class="v4-table-scroll"><table class="table wh-table"><thead><tr><th>数据源</th><th>代码登记</th><th>运行状态</th><th>新鲜度</th><th>观测日</th><th>最近抓取</th><th>说明 / 错误</th></tr></thead><tbody>'+sourceRows+'</tbody></table></div>':empty('暂无来源登记','L1 来源注册表尚不可用。'))+
   '<div class="wh-source-foot">注册状态不等于真实运行状态；没有运行记录时显示「尚无运行观测」。</div></section>'+
   '<section class="card pad"><div class="wh-section-title"><b>最近维护任务</b><span>真实 manifest · 最近 '+n((maintenance.recent_runs||[]).length,0)+' 次</span></div>'+
   renderHistory(maintenance.recent_runs||[])+'</section></div>';
  const html=top+kpis+registryLine+attentionBlock+main+bottom;
  return {title:'数据仓库',html,mount:()=>{
   document.getElementById('wh-refresh')?.addEventListener('click',()=>window.location.reload());
   document.getElementById('wh-search')?.addEventListener('input',ev=>{
    state.search=ev.target.value;V.show('warehouse');
   });
   document.getElementById('wh-category')?.addEventListener('change',ev=>{state.category=ev.target.value;V.show('warehouse')});
   document.getElementById('wh-status')?.addEventListener('change',ev=>{state.status=ev.target.value;V.show('warehouse')});
   document.querySelectorAll('[data-wh-asset]').forEach(node=>node.addEventListener('click',()=>{
    state.selected=node.dataset.whAsset;state.tab='overview';state.previewOffset=0;V.show('warehouse');
   }));
   document.querySelectorAll('[data-wh-tab]').forEach(node=>node.addEventListener('click',()=>{
    state.tab=node.dataset.whTab;state.previewOffset=0;V.show('warehouse');
   }));
   document.getElementById('wh-preview-apply')?.addEventListener('click',()=>{
    state.previewQ=document.getElementById('wh-preview-q')?.value||'';
    state.previewSymbol=document.getElementById('wh-preview-symbol')?.value||'';
    state.previewStart=document.getElementById('wh-preview-start')?.value||'';
    state.previewEnd=document.getElementById('wh-preview-end')?.value||'';
    state.previewOffset=0;V.show('warehouse');
   });
   document.querySelector('[data-wh-prev]')?.addEventListener('click',()=>{
    state.previewOffset=Math.max(0,state.previewOffset-25);V.show('warehouse');
   });
   document.querySelector('[data-wh-next]')?.addEventListener('click',()=>{
    state.previewOffset+=25;V.show('warehouse');
   });
  }};
 };
})();
