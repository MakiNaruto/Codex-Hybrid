'use strict';
(() => {
  const fields=['requests','requests_with_usage','input_tokens','output_tokens','cached_tokens','total_tokens'];
  const empty=()=>Object.fromEntries(fields.map(key=>[key,0]));
  const number=value=>value.toLocaleString('zh-CN');
  const compact=value=>new Intl.NumberFormat('zh-CN',{notation:'compact',maximumFractionDigits:1}).format(value);
  let days='7',metric='total_tokens',data=null,requestId=0;
  function svgNode(tag,attrs,text){
    const node=document.createElementNS('http://www.w3.org/2000/svg',tag);
    for(const [key,value] of Object.entries(attrs))node.setAttribute(key,String(value));
    if(text!==undefined)node.textContent=text;
    return node;
  }
  function bucketLabel(time,full=false){
    const date=new Date(time*1000);
    return date.toISOString().slice(5,10)+(data.bucket_seconds===3600?' '+date.toISOString().slice(11,16):'')+(full?' UTC':'');
  }
  function renderTrend(series){
    const root=$('usage-trend');root.replaceChildren();
    const svg=svgNode('svg',{viewBox:'0 0 640 240',role:'img','aria-label':metric==='requests'?'请求数趋势柱状图':'Token 用量趋势柱状图'});
    const max=Math.max(1,...series.map(row=>row[metric]));
    const top=Math.ceil(max/4)*4;
    for(let i=0;i<=4;i++){
      const y=20+i*46;
      svg.append(svgNode('line',{x1:52,x2:628,y1:y,y2:y,class:'usage-grid'}),svgNode('text',{x:44,y:y+4,'text-anchor':'end',class:'usage-axis'},compact(top*(4-i)/4)));
    }
    const width=576/series.length;
    const labels=new Set([0,.25,.5,.75,1].map(fraction=>Math.round((series.length-1)*fraction)));
    series.forEach((row,index)=>{
      const height=row[metric]/top*184;
      const label=bucketLabel(row.time,true)+' · '+number(row[metric])+(metric==='requests'?' 次请求':' Tokens');
      const bar=svgNode('rect',{x:52+index*width+width*.18,y:204-Math.max(height,2),width:width*.64,height:Math.max(height,2),rx:2,class:'usage-bar',tabindex:0,role:'img','aria-label':label});
      bar.append(svgNode('title',{},label));
      for(const event of ['pointerenter','focus'])bar.addEventListener(event,()=>{$('usage-chart-detail').textContent=label;});
      svg.append(bar);
      if(labels.has(index))svg.append(svgNode('text',{x:52+(index+.5)*width,y:228,'text-anchor':index===0?'start':index===series.length-1?'end':'middle',class:'usage-axis'},data.bucket_seconds===3600?new Date(row.time*1000).toISOString().slice(11,16):bucketLabel(row.time)));
    });
    root.append(svg);$('usage-chart-detail').textContent='时间范围内未记录的时段显示为 0。';
  }
  function render(){
    if(!data)return;
    const selected=$('usage-model').value;
    const models=data.models.filter(row=>!selected||row.model===selected);
    const totals=empty(),series=data.buckets.map(time=>({time,...empty()}));
    for(const row of models)for(const key of fields){totals[key]+=row[key];row.series.forEach((bucket,index)=>{series[index][key]+=bucket[key];});}
    const metrics=$('usage-metrics');metrics.replaceChildren();
    for(const [title,key,note] of [['总用量','total_tokens','已返回的 Token 用量'],['输入 Tokens','input_tokens','含缓存命中 '+number(totals.cached_tokens)],['输出 Tokens','output_tokens','模型生成的 Token'],['请求数','requests','含失败及未返回用量的请求']]){
      const item=el('div',undefined,'usage-stat');item.append(el('span',title,'hint'),el('strong',number(totals[key])),el('small',note));metrics.append(item);
    }
    const warnings={missing:'尚无请求日志。',unavailable:'日志无法读取，请稍后重试。',partial:'部分日志无法读取，统计不完整。',available:''};
    const missing=totals.requests-totals.requests_with_usage;
    $('usage-status').textContent=warnings[data.state]+(totals.requests?number(totals.requests)+' 次请求 · '+(missing?number(missing)+' 次未返回有效用量 · ':''):'当前范围暂无请求记录 · ')+'更新于 '+new Date(data.generated_at*1000).toLocaleTimeString('zh-CN');
    $('usage-content').hidden=data.state==='unavailable';
    renderTrend(series);
    const ranking=$('usage-ranking'),rows=$('usage-model-rows');ranking.replaceChildren();rows.replaceChildren();
    const max=Math.max(1,...models.map(row=>row.total_tokens));
    for(const row of models.slice(0,6)){
      const item=el('div',undefined,'usage-rank'),heading=el('div',undefined,'usage-rank-heading');heading.append(el('span',row.model),el('strong',compact(row.total_tokens)));
      const svg=svgNode('svg',{viewBox:'0 0 300 6','aria-hidden':'true',preserveAspectRatio:'none'});svg.append(svgNode('rect',{width:300,height:6,rx:3,class:'usage-rank-track'}),svgNode('rect',{width:row.total_tokens/max*300,height:6,rx:3,class:'usage-bar'}));item.append(heading,svg);ranking.append(item);
    }
    for(const row of models){const tr=el('tr');const name=el('th',row.model);name.scope='row';tr.append(name);for(const key of ['requests','input_tokens','cached_tokens','output_tokens','total_tokens'])tr.append(el('td',number(row[key])));rows.append(tr);}
    if(!models.length){ranking.append(el('p','暂无模型用量','diagnostic-empty'));const tr=el('tr'),td=el('td','此时间范围内暂无数据');td.colSpan=6;tr.append(td);rows.append(tr);}
  }
  async function load(){
    const id=++requestId;$('usage-status').textContent='正在读取用量…';$('usage-content').hidden=true;
    try{
      const result=await api('usage?days='+days);if(id!==requestId)return;
      data=result;const select=$('usage-model'),previous=select.value;
      select.replaceChildren(el('option','全部模型'));select.firstChild.value='';
      for(const row of data.models){const option=el('option',row.model);option.value=row.model;select.append(option);}
      select.value=data.models.some(row=>row.model===previous)?previous:'';render();
    }catch{if(id!==requestId)return;data=null;$('usage-status').textContent='用量读取失败，请点击刷新重试。';$('usage-content').hidden=true;}
  }
  $('usage-model').onchange=render;
  for(const button of $('usage-period').querySelectorAll('button'))button.onclick=()=>{
    days=button.dataset.days;
    for(const option of $('usage-period').querySelectorAll('button'))option.setAttribute('aria-pressed',String(option===button));
    load();
  };
  for(const button of $('usage-metric').querySelectorAll('button'))button.onclick=()=>{
    metric=button.dataset.metric;
    for(const option of $('usage-metric').querySelectorAll('button'))option.setAttribute('aria-pressed',String(option===button));render();
  };
  $('refresh-usage').onclick=load;
  window.addEventListener('hashchange',()=>{if(!$('page-usage').hidden)load();});
  if(window.hybridDesktop)window.addEventListener('hybrid-management-ready',()=>{if(!$('page-usage').hidden)load();});
  else if(!$('page-usage').hidden)load();
})();
