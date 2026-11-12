/* V4 production factor lab and multi-factor selection / backtest workspaces. */
(() => {
'use strict';
const V=window.V4;
const {pages,state,$,e,n,pct,signed,date,short,badge,button,link,heading,card,kpi,empty,note,row,table,fail,value,api,settle,grid,toolbar,field,select,svgLine,progress,toast,show}=V;
const stepper=(steps)=>'<div class="v4-actions" style="margin-bottom:15px">'+steps.map((x,i)=>'<span class="v4-step"><strong>'+(i+1)+'</strong>'+e(x)+'</span>').join('')+'</div>';
const savedFactor=(x)=>'<button type="button" class="btn smallbtn" data-factor-version="'+e(x.id)+'" style="width:100%;text-align:left;margin-bottom:7px">'+e(x.name)+' · v'+e(x.version)+'　'+badge(x.config?.template||'未知','purple')+'</button>';
const optionFactor=(x)=>'<div class="v4-factor-config"><label style="display:flex;gap:9px;align-items:center;cursor:pointer;margin:0"><input type="checkbox" class="v4-factor-pick" data-exp="'+e(x.id)+'" style="width:17px;height:17px"/><span style="flex:1;color:#dce7f5">'+e(x.factor_name)+' · v'+e(x.factor_version)+'</span></label><div class="v4-factor-controls"><select class="v4-factor-group" aria-label="'+e(x.factor_name)+' 因子组"><option value="A">A · 超跌程度</option><option value="B">B · 卖压衰竭</option><option value="C">C · 重新转强</option></select><input type="number" class="v4-weight" min="1" max="100" value="50" title="因子权重百分比" aria-label="'+e(x.factor_name)+' 权重" style="width:80px" /><span class="muted">%</span></div></div>';
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
       '<div class="v4-actions" style="margin-top:15px">'+button('v4-save-factor','保存不可变因子版本','primary')+'</div>'+
       '<div class="v4-muted-note">公式白名单包括 lag / ret / mean / std / sum / abs / rank / zscore；不允许任意代码和未来数据。</div>'+
       '</form>','L3 · Alpha / Factor Lab')+
     card('已保存因子 · 版本管理',
       factors.length?'<div class="v4-table-scroll">'+factors.slice(0,35).map(savedFactor).join('')+'</div>':
       empty('暂无因子版本',r.ok?'使用左侧表单创建第一项研究因子。':String(r.error?.message||'注册表尚未就绪')),
       '注册历史，不能覆盖旧版')+
   '</div>'+
   '<div class="grid cols2" style="margin-top:15px">'+
     card('真实数据预览及实验',
        row('当前选择',selected?e(selected.name)+' · v'+e(selected.version):'—')+
        '<div class="v4-toolbar" style="margin-top:12px">'+
         select('数据来源','v4-factor-source',[
           ['alpaca','Alpaca（需真实历史来源资格）'],
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
      $('#v4-factor-result').innerHTML='<p class="muted">正在读取真实价格计算…</p>';
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

pages.screen=async()=>{
 const all=await Promise.all([
    settle('/api/v1/strategies'),settle('/api/v1/v4/research/runs'),
    settle('/api/v1/backtests/verified'),settle('/api/v1/v4/forecasts'),
    settle('/api/v1/v4/plans'),settle('/api/v1/v4/outcomes')]);
 const [saved,runs,backtests,forecasts,planArchive,outcomeArchive]=all.map(x=>x.ok?x.data:null);
 const strategies=saved?.strategies||[],experiments=saved?.factor_experiments||[];
 const studies=runs?.runs||[],frozen=(forecasts?.records||[]).filter(x=>x.status==='VERIFIED_LOCAL_FORWARD_RESEARCH_ONLY');
 const planRecords=(planArchive?.records||[]).filter(x=>x.status!=='CORRUPT_RESEARCH_PLAN');
 const planRow=planRecords[0]||null;
 const planDetail=planRow?((await settle('/api/v1/v4/plans/'+encodeURIComponent(planRow.session_date_et)+'/'+encodeURIComponent(planRow.identity))).data||null):null;
 const outcomeRow=(outcomeArchive?.records||[]).find(x=>x.status==='PROSPECTIVE_RESEARCH_OUTCOME_REVIEW_ONLY')||null;
 const outcomeDetail=outcomeRow?((await settle('/api/v1/v4/outcomes/'+encodeURIComponent(outcomeRow.session_date_et)+'/'+encodeURIComponent(outcomeRow.plan_identity))).data||null):null;
 const verified=Array.isArray(backtests?.results)?backtests.results:Array.isArray(backtests?.runs)?backtests.runs:[];
 const stratrows=strategies.slice(0,12).map(x=>[
    e(x.name)+' · v'+e(x.version),e(x.config?.strategy?.horizon||'—')+'日',
    e(x.status),button('v4-view-strategy-'+x.id,'查看选股')]);
 const reportrows=studies.slice(0,10).map(x=>[
    short(x.run_id,20),e(x.status),button('v4-view-study-'+x.run_id,'查看统计')]);
 const selected=state.screenHorizon;
 const html=heading('因子组选股与模拟回测',
    '从已验证的因子实验组建候选策略，用同样本预测、成本和模拟回测研究未来优势',
    link('/strategies','完整多因子策略工具')+link('/backtests','严格历史回测'))+
   stepper(['选择历史因子','配置权重与股票池','观察候选排名','条件预测 / 模拟回测'])+
   grid(4,[
    kpi('已完成因子实验',n(experiments.length,0),'只有完成的实验才能加入选股','purple'),
    kpi('策略版本',n(strategies.length,0),'历史配置不可覆盖','blue'),
    kpi('样本外研究档案',n(studies.length,0),'含 A/B/C/D 消融、IC 与增量','green'),
    kpi('具备严格资格的回测',n(verified.length,0),'只有来源完整才可显示回测表现','amber')
   ].join(''))+
   '<div class="grid cols2" style="margin-top:15px;grid-template-columns:.94fr 1.06fr">'+
      card('因子组合配置',
        '<div class="v4-form">'+field('策略名称','v4-strategy-name','text','','maxlength="80" placeholder="超跌衰竭多因子研究"')+
        select('研究持有期','v4-strategy-h',[['1','1日'],['3','3日'],['5','5日']],selected)+'</div>'+
        '<div class="v4-muted-note" style="margin:12px 0">选择 2–8 个已完成的真实实验，按超跌程度、卖压衰竭、重新转强分类，权重之和必须为 100%。组别是研究假设，不代表已验证贡献。</div>'+
        '<div class="v4-factor-groups">'+
        '<div>组 A · 超跌程度 <b data-v4-group-total="A">0%</b></div>'+
        '<div>组 B · 卖压衰竭 <b data-v4-group-total="B">0%</b></div>'+
        '<div>组 C · 重新转强 <b data-v4-group-total="C">0%</b></div>'+
        '<div>已选总权重 <b data-v4-weight-total>0%</b></div></div>'+
        (experiments.length?'<div class="v4-table-scroll">'+experiments.map(optionFactor).join('')+'</div>':
           empty('暂无可组合的因子实验','请先在因子实验室完成真实样本研究。'))+
        '<div class="v4-actions" style="margin-top:15px">'+button('v4-save-strategy','保存不可变策略','primary')+
        link('/studio#lab','去因子实验室')+'</div>'+
        note('初始风险约束：单股≤10%，总仓位≤50%，行业≤25%，ADV20≥2000万美元，止损≥2×ATR20；最终交易需独立验证。'),
        'L3 · 多因子选股')+
      card('已保存策略与候选解释',
        strategies.length?table(['策略版本','持有期','状态','操作'],stratrows):
          empty('尚无保存的组合研究','配置左侧因子组并保存后，选择版本查看真实排名。')+
        '<div id="v4-composite-result" style="margin-top:14px">'+empty('尚未选取策略研究结果','点击“查看选股”核对真实因子贡献、冗余及候选股票。')+'</div>',
        '分数不是预测交易收益')+
   '</div>'+
   '<div class="grid cols2" style="margin-top:15px">'+
      card('样本外预测 · 模型增量',
        studies.length?table(['研究版本','状态','操作'],reportrows):
          empty('尚无已归档的 OOS 对照','模型必须在同样本中比较预测增量，不能只展示历史收益高的组合。')+
        '<div id="v4-study-result" style="margin-top:12px">'+empty('选择研究版本','查看 Brier、MSE、Rank IC 和样本外增量；不填充演示胜率。')+'</div>',
        'A/B/C/D · 预测有效性')+
      card('严格回测与前向冻结记录',
        row('已验证历史回测',verified.length?n(verified.length,0):'—')+
        row('当日真实冻结的 Alpha 研究',frozen.length?n(frozen.length,0):'—')+
        row('最新风险研究计划',planRow?n(planRow.research_plan_count,0):'—')+
        (planDetail?.plans?.length?table(['H3 研究候选','成本后期望','参考持仓权重'],
          planDetail.plans.slice(0,5).map(x=>[e(x.security_id),signed(x.estimated_net_edge),pct(x.indicative_weight)])):
          empty('目前无已冻结的研究交易计划','缺少已校准预测、同日真实证券元数据或对账账户时，系统不制造买入建议。'))+
        (verified.length?table(['运行版本','来源资格'],verified.slice(0,8).map(x=>[
           short(x.run_id||x.id),e(x.status||'已登记')])):empty('暂无严格回测业绩',
           '缺少历史 PIT/公司行为/原价成交资格时，不显示净值、收益和回撤曲线。'))+
        '<div class="v4-actions" style="margin-top:15px">'+link('/backtests','查看资格检查与回测结果')+'</div>',
        '收益、成本与模拟交易')
   '</div>'+
   '<div style="margin-top:15px">'+card('冻结预测的后续结果复盘',
     outcomeDetail?.evaluated?.length?table(
       ['候选证券','实际观察止盈止损路径','原始价格模型收益','假设成本后收益','与预测净优势差'],
       outcomeDetail.evaluated.slice(0,20).map(x=>[
         e(x.security_id),e(x.modeled_exit_reason),
         signed(x.realized_gross_price_return),signed(x.modeled_net_return),
         signed(x.net_forecast_error)])):
       empty('暂无完成期限的前向研究复盘',
         '必须先在T日收盘后冻结研究计划，再等待T+H真实交易日及带来源回执的原价数据。'),
     '历史价格路径模拟，不是实际成交或已验证的投资回报')+'</div>';
 return {title:'因子组选股与模拟回测',html,mount(){
    $('#v4-strategy-h')?.addEventListener('change',x=>state.screenHorizon=Number(x.target.value));
    const refreshGroupWeights=()=>{
      const totals={A:0,B:0,C:0};
      document.querySelectorAll('.v4-factor-config').forEach(node=>{
        if(!node.querySelector('.v4-factor-pick')?.checked)return;
        const group=node.querySelector('.v4-factor-group')?.value;
        if(Object.hasOwn(totals,group))totals[group]+=Number(node.querySelector('.v4-weight')?.value)||0;
      });
      for(const group of ['A','B','C']){
        const target=document.querySelector('[data-v4-group-total="'+group+'"]');
        if(target)target.textContent=totals[group].toFixed(1)+'%';
      }
      const total=document.querySelector('[data-v4-weight-total]');
      if(total)total.textContent=(totals.A+totals.B+totals.C).toFixed(1)+'%';
    };
    document.querySelectorAll('.v4-factor-config input,.v4-factor-config select')
      .forEach(node=>node.addEventListener('change',refreshGroupWeights));
    refreshGroupWeights();
    const action=async(fn)=>{try{await fn()}catch(error){toast(error.message||'请核对研究版本与数据资格')}};
    $('#v4-save-strategy')?.addEventListener('click',()=>action(async()=>{
        const name=$('#v4-strategy-name').value.trim();if(!name)throw Error('需要策略名称');
        const factors=[...document.querySelectorAll('.v4-factor-pick:checked')].map(x=>{
          const parent=x.closest('.v4-factor-config');
          return {factor_experiment_id:x.dataset.exp,
            group:parent.querySelector('.v4-factor-group').value,
            weight:Number(parent.querySelector('.v4-weight').value)/100};
        });
        if(factors.length<2||factors.length>8)throw Error('必须选择2至8个已完成因子');
        if(factors.some(x=>!Number.isFinite(x.weight)||x.weight<=0)||
           Math.abs(factors.reduce((v,x)=>v+x.weight,0)-1)>1e-8)
           throw Error('因子权重必须合计100%');
        await api('/api/v1/strategies',{name,horizon:Number($('#v4-strategy-h').value),
             max_stock_weight:.10,max_total_weight:.50,max_sector_weight:.25,
             minimum_adv20:20000000,stop_atr_multiple:2,factors});
        toast('真实因子策略已保存，继续验证历史资格');show('screen');
    }));
    strategies.slice(0,12).forEach(x=>{
      $('#v4-view-strategy-'+CSS.escape(x.id))?.addEventListener('click',()=>action(async()=>{
        const data=await api('/api/v1/strategies/'+encodeURIComponent(x.id)+'/composite');
        const rank=(data.latest_composite_ranking||[]).slice(0,20);
        $('#v4-composite-result').innerHTML=rank.length?
         table(['证券','组合分位','主导贡献'],
            rank.map(z=>{const con=z.weighted_factor_contributions||{};
              const main=Object.entries(con).sort((a,b)=>Number(b[1])-Number(a[1]))[0];
              return [e(z.security_id),n(z.score,4),main?short(main[0],12):'—']})):
         empty('暂无符合质量要求的候选','当前策略尚无有效多因子横截面排名。');
      }));
    });
    studies.slice(0,10).forEach(x=>{
      $('#v4-view-study-'+CSS.escape(x.run_id))?.addEventListener('click',()=>action(async()=>{
        const d=await api('/api/v1/v4/research/runs/'+encodeURIComponent(x.run_id));
        const m=(d.metrics||[]).slice(0,20),r=(d.alpha_ranking||[]).slice(0,20);
        $('#v4-study-result').innerHTML=
          (m.length?table(['模型','持有期','样本量','上涨Brier','基准Brier'],m.map(y=>[
           e(y.variant),e(y.horizon),n(y.rows,0),n(y.brier_up,4),n(y.baseline_brier_up,4)])):
           empty('尚无 OOS 评分','此研究版本缺少真实标签评价。'))+
          (r.length?'<div class="v4-muted-note">个股排序检验</div>'+
           table(['模型','H','Rank IC','ICIR'],r.map(y=>[e(y.variant),e(y.horizon),n(y.rank_ic_mean,4),n(y.rank_icir_unannualized,3)])):'')+
          note('这些是研究指标，不是可执行成本后回测的投资回报率。');
      }));
    });
 }};
};
})();