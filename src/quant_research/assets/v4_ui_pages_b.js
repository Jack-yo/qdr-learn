/* V4 production factor lab. L3 daily selection/strategy lives in v4_ui_l3.js. */
(() => {
'use strict';
const V=window.V4;
const {pages,state,$,e,n,pct,signed,date,short,badge,button,link,heading,card,kpi,empty,note,row,table,fail,value,api,settle,grid,toolbar,field,select,svgLine,progress,toast,show,moduleLoading}=V;
const stepper=(steps)=>'<div class="v4-actions" style="margin-bottom:15px">'+steps.map((x,i)=>'<span class="v4-step"><strong>'+(i+1)+'</strong>'+e(x)+'</span>').join('')+'</div>';
const savedFactor=(x)=>'<button type="button" class="btn smallbtn" data-factor-version="'+e(x.id)+'" style="width:100%;text-align:left;margin-bottom:7px">'+e(x.name)+' · v'+e(x.version)+'　'+badge(x.config?.template||'未知','purple')+'</button>';
const runError=(x)=>'<div class="v4-message">'+e(x?.message||'缺少可用来源或研究资格')+'</div>';
pages.lab=async()=>{
 const r=await settle('/api/v1/factor-lab/library');
 const lib=r.ok?r.data:{factor_versions:[],experiments:[]};
 const factors=lib.factor_versions||[];
 const experiments=lib.experiments||[];
 const selected=factors.find(x=>x.id===state.factorVersion)||factors[0]||null;
 if(!state.factorVersion&&selected)state.factorVersion=selected.id;
 const rows=experiments.slice(0,12).map(x=>[
   short(x.id,12),e(x.config?.source||x.source||'—'),
   e(x.status||'未知'),button('lab-exp-'+x.id,'查看记录')]);
 const html=heading('自定义因子实验室',
   '像研究员一样定义公式、冻结版本、用真实数据计算因子，并检验跨日期的收益预测能力',
   link('/factors','完整因子工作台'))+
   stepper(['定义因子','真实价格计算','历史预测检验','因子报告与版本'])+
   grid(4,[
     kpi('已定义因子版本',n(factors.length,0),'注册表中的不可变定义','blue'),
     kpi('历史实验记录',n(experiments.length,0),'完成与受阻实验均保留','purple'),
     kpi('已选版本',selected?'v'+e(selected.version):'—',selected?.name||'先创建因子','green'),
     kpi('真实预测检验','待核验','Rank IC 与分组收益必须来源真实结果','amber')
   ].join(''))+
   '<div class="grid cols2" style="margin-top:15px;grid-template-columns:1.15fr .85fr">'+
     card('创建因子 · 可执行研究定义',
       '<form id="v4-factor-form">'+
       '<div class="v4-form">'+
         field('因子名称','v4-factor-name','text','','required maxlength="80" placeholder="例如 行业残差短期反转"')+
         select('研究类型','v4-factor-type',[['custom','自定义公式'],['reversal','短期反转'],['momentum','动量'],['volatility','波动'],['liquidity','流动性'],['amihud','Amihud非流动性'],['sector_relative','行业相对强度']], 'custom')+
         field('回看交易日','v4-factor-window','number','5','min="1" max="252" required')+
         select('排序方向','v4-factor-direction',[['1','高分优先'],['-1','低分优先']],'1')+
         '<div class="v4-field wide" id="v4-formula-wrap"><label for="v4-factor-expression">自定义公式（历史时间窗口，禁止未来函数）</label><textarea id="v4-factor-expression" placeholder="-ret(close,5)" maxlength="512">-ret(close,5)</textarea></div>'+
         '<div class="v4-field wide"><label for="v4-factor-hypothesis">研究假设</label><textarea id="v4-factor-hypothesis" maxlength="1000" placeholder="该信号为什么可能影响未来1/3/5日的收益分布？"></textarea></div>'+
       '</div>'+
       '<div class="v4-actions" style="margin-top:15px">'+button('v4-save-factor','保存因子版本','primary')+'</div>'+
       '<div class="v4-muted-note">支持 lag / ret / mean / std / sum / abs / rank / zscore；禁止未来函数。</div>'+
       '</form>','L3 · Alpha / Factor Lab')+
     card('已保存因子 · 版本管理',
       factors.length?'<div class="v4-table-scroll">'+factors.slice(0,35).map(savedFactor).join('')+'</div>':
       empty('暂无因子版本',r.ok?'使用左侧表单创建第一项研究因子。':String(r.error?.message||'注册表尚未就绪')),
       '保留历史版本')+
   '</div>'+
   '<div class="grid cols2" style="margin-top:15px">'+
     card('数据预览与实验',
        row('当前选择',selected?e(selected.name)+' · v'+e(selected.version):'—')+
        '<div class="v4-toolbar" style="margin-top:12px">'+
         select('数据来源','v4-factor-source',[
           ['alpaca','Alpaca'],
           ['yahoo','Yahoo（仅当前版本历史探索）']],'alpaca')+
         '<div class="v4-actions">'+button('v4-factor-preview','预览真实计算')+
           button('v4-factor-run','创建并运行因子实验','primary')+'</div></div>'+
        '<div id="v4-factor-result">'+empty('尚未选择计算','选择版本后读取已有的真实行情及其因子计算值。')+'</div>',
        '研究结果不自动进入交易')+
     card('最近因子实验',
       experiments.length?table(['实验ID','数据源','任务状态','操作'],rows):
         empty('尚无真实实验记录','保存因子后，执行真实来源预览和预测检验。'),
       '仅展示已登记实验结果')+
   '</div>';
 return {title:'自定义因子实验室',html,mount(){
   $('#v4-factor-type')?.addEventListener('change',ev=>{$('#v4-formula-wrap').hidden=ev.target.value!=='custom'});
   document.querySelectorAll('[data-factor-version]').forEach(b=>b.addEventListener('click',()=>{
     state.factorVersion=b.dataset.factorVersion;show('lab')}));
   const action=async(fn)=>{try{await fn()}catch(error){toast(error.message||'操作未完成') }};
   $('#v4-save-factor')?.addEventListener('click',()=>action(async()=>{
     const name=$('#v4-factor-name').value.trim(),kind=$('#v4-factor-type').value;
     if(!name)throw Error('请输入因子名称');
     const body={name,template:kind,window:Number($('#v4-factor-window').value),
       direction:Number($('#v4-factor-direction').value),
       hypothesis:$('#v4-factor-hypothesis').value.trim()};
     if(kind==='custom')body.expression=$('#v4-factor-expression').value.trim();
     const saved=await api('/api/v1/factor-lab/factors',body);
     state.factorVersion=saved.id;toast('因子版本已保存：'+saved.name);show('lab');
   }));
   $('#v4-factor-preview')?.addEventListener('click',()=>action(async()=>{
      if(!state.factorVersion)throw Error('请先保存或选择一个因子版本');
      $('#v4-factor-result').innerHTML=moduleLoading('因子预览');
      const query=new URLSearchParams({version_id:state.factorVersion,source:$('#v4-factor-source').value});
      const result=await api('/api/v1/factor-lab/preview?'+query);
      const rows=(result.rows||[]).slice(0,20).map(x=>[
         date(x.date),e(x.symbol||x.security_id),n(x.close,2),n(x.value,5)]);
      $('#v4-factor-result').innerHTML=table(['交易日','证券','收盘价','因子值'],rows)+
         note('本表为真实来源的观察数据，不代表已取得 PIT 身份或历史可交易资格。');
   }));
   $('#v4-factor-run')?.addEventListener('click',()=>action(async()=>{
      if(!state.factorVersion)throw Error('请先保存或选择因子版本');
      const source=$('#v4-factor-source').value;
      const created=await api('/api/v1/factor-lab/experiments',
              {factor_version_id:state.factorVersion,source});
      await api('/api/v1/factor-lab/experiments/'+encodeURIComponent(created.id)+'/run',{});
      $('#v4-factor-result').innerHTML=empty('因子实验已提交','已记录实验编号：'+created.id+'。可在实验历史中查看真实运行状态。');
      toast('实验任务已创建，可在工作台查看实际执行情况');
   }));
   experiments.slice(0,12).forEach(x=>{
    $('#lab-exp-'+CSS.escape(x.id))?.addEventListener('click',()=>action(async()=>{
      const d=await api('/api/v1/factor-lab/experiments/'+encodeURIComponent(x.id));
      $('#v4-factor-result').innerHTML=row('实验编号',e(x.id))+
        row('实际状态',e(d.status||'—'))+
        row('数据快照',short(d.data_sha256||d.source_snapshot_sha256,20))+
        (d.metrics?table(['指标','结果'],Object.entries(d.metrics).slice(0,15).map(([k,v])=>[e(k),e(JSON.stringify(v))])):'')+
        link('/factors','查看完整统计报告');
    }));
   });
 }};
};

})();