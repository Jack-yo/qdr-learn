/* QDR V4: production presentation of the approved six-page high-fidelity UI.
   No example prices, probability or trading P&L are rendered. */
(() => {
'use strict';
const root=document.getElementById('content');
const state={page:'overview',marketHorizon:3,styleFactor:null,factorVersion:null,screenHorizon:3,runId:null,epoch:0};
const pages={};
const $=(s)=>document.querySelector(s);
const e=(v)=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c]));
const isnum=(v)=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
const n=(v,d=2)=>isnum(v)?Number(v).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d}):'—';
const pct=(v,d=2)=>isnum(v)?n(Number(v)*100,d)+'%':'—';
const signed=(v,d=2)=>isnum(v)?(Number(v)>0?'+':'')+pct(v,d):'—';
const date=(v)=>v?e(String(v).slice(0,10)):'—';
const short=(v,len=14)=>v?e(String(v).slice(0,len)):'—';
const badge=(v,t='blue')=>'<span class="badge '+t+'">'+e(v)+'</span>';
const button=(id,text,kind='')=>'<button type="button" id="'+e(id)+'" class="btn '+e(kind)+'">'+e(text)+'</button>';
const link=(to,text)=>'<a href="'+e(to)+'" class="v4-link">'+e(text)+'</a>';
const heading=(name,description,actions='')=>'<div class="heading"><div><h1 class="title">'+e(name)+'</h1><div class="subtitle">'+e(description)+'</div></div><div class="h-actions">'+actions+'</div></div>';
const card=(name,content,meta='')=>'<section class="card pad"><div class="ctitle">'+e(name)+'<span>'+e(meta)+'</span></div>'+content+'</section>';
const kpi=(label,value,hint,color='')=>'<div class="kpi"><div class="klabel">'+e(label)+'</div><div class="kval mono '+color+'">'+value+'</div><div class="knote">'+e(hint)+'</div></div>';
const empty=(title,body)=>'<div class="v4-empty"><b>'+e(title)+'</b>'+e(body)+'</div>';
const note=(text)=>'<div class="v4-muted-note">'+e(text)+'</div>';
const row=(label,value)=>'<div class="v4-stat-pair"><span class="muted">'+e(label)+'</span><b>'+value+'</b></div>';
const table=(cols,data)=> data&&data.length?'<div class="v4-table-scroll"><table class="table"><thead><tr>'+cols.map(x=>'<th>'+e(x)+'</th>').join('')+'</tr></thead><tbody>'+data.map((r,i)=>'<tr'+(i===0?' class="selected"':'')+'>'+r.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>':empty('暂无符合条件的数据','当前没有已验证的研究记录，不显示示意数据。');
const fail=(error)=>empty('无法读取真实研究结果',String(error?.message||error?.code||'数据或来源资格尚未满足，请前往数据中心检查。'));
const value=(d,k)=>Object.prototype.hasOwnProperty.call(d||{},k)?d[k]:null;
const api=async (path,body,signal)=>{
 const opts=body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Console-Token':window.CONSOLE_TOKEN},body:JSON.stringify(body)};
 if(signal)opts.signal=signal;
 let r;try{r=await fetch(path,opts)}catch(error){throw Error(error?.name==='AbortError'?'数据请求超时，请稍后重试':'无法连接本地研究服务')}
 let j;try{j=await r.json()}catch(_){throw Error('服务未返回有效 JSON')}
 if(!r.ok)throw Error(j.code||j.message||'HTTP '+r.status);
 return j;
};
/* Progressive, bounded in-memory GET cache. Only page renders use optimistic reads;
   actions and top-bar checks retain their normal awaited semantics. */
const settledGet=async(url,signal)=>{
 try{return {ok:true,data:await api(url,undefined,signal)}}
 catch(error){return {ok:false,error}}
};
const viewResults=new Map();
let buildingPage=0, visibleRequests=new Set(), redrawTimer=null;
const pendingResult=()=>({ok:false,pending:true,error:{message:'数据正在独立加载'}});
function redrawSoon(){
 if(redrawTimer)return;
 redrawTimer=setTimeout(()=>{
   redrawTimer=null;
   if(state.page && pages[state.page])show(state.page,true);
 },120);
}
function readProgressively(url){
 visibleRequests.add(url);
 const now=Date.now();
 let entry=viewResults.get(url);
 if(entry){
   viewResults.delete(url);viewResults.set(url,entry);
   if(entry.value && entry.expires>now)return Promise.resolve(entry.value);
 }else{
   entry={value:null,expires:0,pending:false};
   viewResults.set(url,entry);
 }
 if(!entry.pending){
   entry.value=null;entry.pending=true;
   const selected=entry;
   const controller=new AbortController();
   entry.controller=controller;
   const timeout=setTimeout(()=>controller.abort(),30000);
   settledGet(url,controller.signal).then(value=>{
     clearTimeout(timeout);
     if(viewResults.get(url)!==selected)return;
     selected.value=value;
     selected.expires=Date.now()+(value.ok?60000:12000);
     selected.pending=false;
     redrawSoon();
   });
   // Bounded memory regardless of navigation churn.
   while(viewResults.size>80){
     const oldest=viewResults.keys().next().value;
     const removed=viewResults.get(oldest);
     if(removed?.pending)removed.controller?.abort();
     viewResults.delete(oldest);
   }
 }
 return Promise.resolve(pendingResult());
}
const settle=async(url)=>{
 if(buildingPage>0 && typeof url==='string' && url.startsWith('/api/'))
   return readProgressively(url);
 return settledGet(url);
};
const grid=(cols,body)=>'<div class="grid cols'+cols+'">'+body+'</div>';
const toolbar=(body)=>'<div class="v4-toolbar">'+body+'</div>';
const field=(label,id,type='text',value='',extra='')=>'<div class="v4-field"><label for="'+e(id)+'">'+e(label)+'</label><input type="'+e(type)+'" id="'+e(id)+'" value="'+e(value)+'" '+extra+' /></div>';
const select=(label,id,opts,val)=>'<div class="v4-field"><label for="'+e(id)+'">'+e(label)+'</label><select id="'+e(id)+'">'+opts.map(x=>'<option value="'+e(x[0])+'"'+(String(x[0])===String(val)?' selected':'')+'>'+e(x[1])+'</option>').join('')+'</select></div>';
const svgLine=(arr,color='#63d4be',height=170)=>{
 const values=arr.map(Number).filter(Number.isFinite);
 if(values.length<2)return empty('暂无可绘制的趋势','至少需要两个具有真实数值的历史观察点。');
 const low=Math.min(...values),high=Math.max(...values),gap=Math.max(1e-8,high-low);
 const W=740,H=height,pad=20;
 const pts=values.map((v,i)=>[(pad+(W-pad*2)*i/(values.length-1)).toFixed(1),(H-pad-(H-pad*2)*(v-low)/gap).toFixed(1)]);
 const path=pts.map((v,i)=>(i===0?'M':'L')+v.join(' ')).join(' ');
 const grads=[0,.25,.5,.75,1].map(t=>'<line x1="'+pad+'" y1="'+(pad+(H-pad*2)*t).toFixed(1)+'" x2="'+(W-pad)+'" y2="'+(pad+(H-pad*2)*t).toFixed(1)+'" stroke="#30445f" stroke-dasharray="3 7"/>').join('');
 return '<svg class="v4-spark" style="height:'+height+'px" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" role="img" aria-label="真实观察序列趋势">'+grads+'<path d="'+path+'" fill="none" stroke="'+color+'" stroke-width="2.8" stroke-linejoin="round"/><circle cx="'+pts[pts.length-1][0]+'" cy="'+pts[pts.length-1][1]+'" r="4" fill="'+color+'"/></svg>';
};
const progress=(name,fraction,show='')=>'<div class="barrow"><div class="name">'+e(name)+'</div><div class="progress"><div style="width:'+Math.max(0,Math.min(100,Number(fraction)||0))+'%"></div></div><div class="pct">'+(show||'—')+'</div></div>';
const setContent=(html)=>root.innerHTML=html;
const toast=(txt)=>{
 const el=$('#v4-toast');if(!el)return;
 el.style.pointerEvents='none';el.innerHTML='<div class="v4-message">'+e(txt)+'</div>';clearTimeout(toast.id);toast.id=setTimeout(()=>el.innerHTML='',5500);
};
async function updateStatus(){
 const [daily,fresh]=await Promise.all([settledGet('/api/v1/v4/daily'),settledGet('/api/v1/v4/freshness')]);
 const latest=(daily.ok?daily.data.runs||[]:[])[0]||null;
 const clock=fresh.ok?fresh.data:null;
 $('#v4-trading-date').textContent=clock?.asof_session||latest?.session_date_et||'—';
 $('#v4-source-status').textContent=clock?.modules?.market_observation?.freshness_status||'待验证';
 $('#v4-model-status').textContent=latest?.session_date_et===clock?.asof_session?latest.status:'当前批次未完成';
}
function loadingSkeleton(key){
 const names={overview:'总览',market:'市场未来展望',style:'经典因子',lab:'因子实验室',screen:'选股研究',risk:'持仓与风控',data:'数据资格',warehouse:'数据仓库'};
 return '<div class="v4-page-skeleton" role="status" aria-live="polite"><h1>'+e(names[key]||'研究工作区')+'</h1><p>页面已就绪，各模块正在独立读取真实数据…</p><div class="v4-skeleton-grid">'+
   Array.from({length:4},()=>'<div class="v4-skeleton-block v4-skeleton-kpi"><i></i><b></b></div>').join('')+
   '</div><div class="v4-skeleton-grid two">'+
   Array.from({length:2},()=>'<div class="v4-skeleton-block v4-skeleton-panel"><i></i><b></b><b></b></div>').join('')+'</div></div>';
}
async function show(page,progressive=false){
 const key=pages[page]?page:'overview';
 const changePage=state.page!==key;
 state.page=key;const epoch=++state.epoch;
 document.querySelectorAll('[data-page]').forEach(x=>{
   x.classList.toggle('active',x.dataset.page===key||(x.id==='nav-alpha'&&['lab','screen'].includes(key)));
   x.setAttribute('aria-current',x.dataset.page===key?'page':'false');
 });
 const previousScroll=root.scrollTop;
 const existingDetails=[...root.querySelectorAll('details')].map(node=>node.open);
 const focused=(root.contains(document.activeElement)&&document.activeElement.id)?document.activeElement.id:null;
 const selection=focused&&Number.isInteger(document.activeElement.selectionStart)?
   [document.activeElement.selectionStart,document.activeElement.selectionEnd]:null;
 if(changePage||!root.children.length)root.innerHTML=loadingSkeleton(key);
 const requested=new Set();visibleRequests=requested;
 buildingPage++;
 try{
   const result=await pages[key]();
   if(epoch!==state.epoch)return;
   const count=[...requested].filter(url=>viewResults.get(url)?.pending).length;
   const banner=count?'<div class="v4-pending-banner" role="status" aria-live="polite"><span class="v4-pending-dot"></span>正在加载 '+count+' 项数据模块；尚未返回的内容不代表数据缺失。</div>':'';
   setContent(banner+result.html);
   if((progressive||!changePage)&&previousScroll>0)root.scrollTop=previousScroll;
   existingDetails.forEach((isOpen,i)=>{
     if(isOpen){const detail=root.querySelectorAll('details')[i];if(detail)detail.open=true;}
   });
   if(typeof result.mount==='function')result.mount();
   if(focused){
     const node=document.getElementById(focused);
     if(node){node.focus({preventScroll:true});if(selection&&node.setSelectionRange){try{node.setSelectionRange(...selection)}catch(_){/* non-text input */}}}
   }
   document.title='QDR Quant Studio · '+e(result.title||key);
 }catch(error){
   if(epoch===state.epoch)setContent(heading('研究数据暂不可用','该模块未获得合格数据')+fail(error));
 }finally{buildingPage--;}
}
function go(page){
 const key=pages[page]?page:'overview';
 if(location.hash.slice(1)!==key)location.hash=key;
 else show(key);
}
function boot(){
 document.querySelectorAll('[data-page]').forEach(x=>{
  x.tabIndex=0;x.setAttribute('role','link');
  x.addEventListener('click',()=>go(x.dataset.page));
  x.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();go(x.dataset.page)}});
 });
 window.addEventListener('hashchange',()=>show(location.hash.slice(1)));
 $('#v4-refresh')?.addEventListener('click',()=>{viewResults.clear();updateStatus();show(state.page)});
 updateStatus();show(location.hash.slice(1)||'overview');
}
window.V4={pages,state,$,e,n,pct,signed,date,short,badge,button,link,heading,card,kpi,empty,note,row,table,fail,value,api,settle,grid,toolbar,field,select,svgLine,progress,setContent,toast,show,go};
document.addEventListener('DOMContentLoaded',boot);
})();
