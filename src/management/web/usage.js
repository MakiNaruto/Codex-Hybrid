'use strict';
(() => {
  const fields=['requests','requests_with_usage','input_tokens','output_tokens','cached_tokens','total_tokens'];
  const tokenParts=[['cached_tokens','cached','缓存命中'],['uncached_tokens','uncached','缓存未命中'],['output_tokens','output','输出']];
  const empty=()=>Object.fromEntries(fields.map(key=>[key,0]));
  const number=value=>value.toLocaleString('zh-CN');
  const compact=value=>new Intl.NumberFormat('zh-CN',{notation:'compact',maximumFractionDigits:1}).format(value);
  const modelLabel=row=>row.provider_name?row.provider_name+' · '+(row.model_name||row.model):row.model_name||row.model;
  const colorClass=row=>'usage-color-'+(Math.max(0,data.models.indexOf(row))%10);
  const uncached=row=>Math.max(0,(row.input_tokens||0)-(row.cached_tokens||0));
  const tokenPartsFor=row=>({cached_tokens:Math.min(row.cached_tokens||0,row.input_tokens||0),uncached_tokens:uncached(row),output_tokens:row.output_tokens||0});
  const partsTotal=parts=>parts.cached_tokens+parts.uncached_tokens+parts.output_tokens;
  const partTotal=row=>partsTotal(tokenPartsFor(row));
  let period='7',metric='total_tokens',data=null,requestId=0;
  function svgNode(tag,attrs,text){
    const node=document.createElementNS('http://www.w3.org/2000/svg',tag);
    for(const [key,value] of Object.entries(attrs))node.setAttribute(key,String(value));
    if(text!==undefined)node.textContent=text;
    return node;
  }
  const pad=value=>String(value).padStart(2,'0');
  const calendarPeriod=()=>data.period==='today'||data.period==='yesterday';
  function dateLabel(time,local=false){
    const date=new Date(time*1000),year=local?date.getFullYear():date.getUTCFullYear(),month=(local?date.getMonth():date.getUTCMonth())+1,day=local?date.getDate():date.getUTCDate();
    return year+'-'+pad(month)+'-'+pad(day);
  }
  function hourLabel(time){
    const date=new Date(time*1000),hour=calendarPeriod()?date.getHours():date.getUTCHours();
    return pad(hour)+':00';
  }
  function bucketLabel(time,full=false){
    if(data.bucket_seconds===3600){
      const date=new Date(time*1000),hour=calendarPeriod()?date.getHours():date.getUTCHours();
      return (full?dateLabel(time,calendarPeriod())+' ':'')+pad(hour)+':00–'+pad(hour+1)+':00'+(full?(calendarPeriod()?' 本地时间':' UTC'):'');
    }
    return dateLabel(time).slice(full?0:5)+(full?' UTC':'');
  }
  function periodLabel(){
    if(calendarPeriod()){
      const name=data.period==='today'?'今天':'昨天';
      return name+' '+dateLabel(data.period_start,true)+' · 00:00–24:00';
    }
    return '近'+(data.period_days||data.period)+'天';
  }
  function niceTop(value,steps=4){
    if(value<=steps)return steps;
    const step=value/steps,power=10**Math.floor(Math.log10(step)),scaled=step/power;
    const factor=scaled<=1?1:scaled<=2?2:scaled<=2.5?2.5:scaled<=3?3:scaled<=4?4:scaled<=5?5:scaled<=6?6:scaled<=8?8:10;
    return factor*power*steps;
  }
  function bucketFor(row,index){return row.series[index]||empty();}
  function bucketValue(row,index){const bucket=bucketFor(row,index);return metric==='requests'?bucket.requests:partTotal(bucket);}
  function modelSummary(row,index){
    const bucket=bucketFor(row,index);
    if(metric==='requests')return modelLabel(row)+' '+number(bucket.requests)+' 次请求';
    return modelLabel(row)+' '+number(partTotal(bucket))+' Tokens';
  }
  function modelSwatch(){
    return el('span',undefined,'usage-model-swatch');
  }
  function renderLegend(models){
    const legend=$('usage-model-legend');legend.replaceChildren();
    if(!models.length){legend.append(el('span','暂无模型用量','hint'));return;}
    for(const row of models){
      const key=el('span',undefined,'usage-model-key '+colorClass(row));
      const name=el('span',modelLabel(row),'usage-model-key-label');
      key.title=modelLabel(row)+'的模型颜色';
      key.setAttribute('aria-label',key.title);
      key.append(modelSwatch(),name);legend.append(key);
    }
  }
  function showTooltip(index,models){
    const time=data.buckets[index],tooltip=$('usage-chart-tooltip');
    tooltip.replaceChildren();tooltip.hidden=false;
    const heading=el('div',undefined,'usage-tooltip-heading'),title=el('strong',bucketLabel(time,true));
    const visibleModels=models.filter(row=>bucketValue(row,index)>0);
    let total=0;
    for(const row of visibleModels)total+=bucketValue(row,index);
    heading.append(title,el('span',number(total)+(metric==='requests'?' 次':' Tokens')));
    tooltip.append(heading);
    for(const row of visibleModels){
      const bucket=bucketFor(row,index),item=el('div',undefined,'usage-tooltip-model '+colorClass(row));
      const line=el('div',undefined,'usage-tooltip-model-heading');
      line.append(modelSwatch(),el('span',modelLabel(row),'usage-tooltip-model-name'),el('strong',number(bucketValue(row,index))));
      item.append(line);
      tooltip.append(item);
    }
    if(!visibleModels.length)tooltip.append(el('p','此时段暂无用量','usage-tooltip-empty'));
    $('usage-chart-detail').textContent=bucketLabel(time,true)+' · '+(visibleModels.length?visibleModels.map(row=>modelSummary(row,index)).join(' · '):'此时段暂无用量');
  }
  function hideTooltip(){$('usage-chart-tooltip').hidden=true;}
  function renderTrend(models){
    const root=$('usage-trend');root.replaceChildren();
    $('usage-trend-note').textContent='每个模型一种颜色，柱内按模型堆叠 · '+(calendarPeriod()?'按本地时间小时分组 · 统计时段 00:00–24:00':'按 UTC 日期分组');
    const width=Math.max(640,data.buckets.length*26+76);
    const left=58,right=18,topY=28,plotHeight=180,baseline=topY+plotHeight,plotWidth=width-left-right;
    const svg=svgNode('svg',{viewBox:'0 0 '+width+' 252',role:'group','aria-label':metric==='requests'?'按模型堆叠的请求数趋势柱状图':'按模型堆叠的 Token 用量趋势柱状图'});
    svg.setAttribute('style','min-width:'+width+'px');
    const totals=data.buckets.map((time,index)=>models.reduce((sum,row)=>sum+bucketValue(row,index),0));
    const top=niceTop(Math.max(1,...totals));
    for(let i=0;i<=4;i++){
      const y=topY+i*plotHeight/4;
      svg.append(svgNode('line',{x1:left,x2:width-right,y1:y,y2:y,class:'usage-grid'}),svgNode('text',{x:left-9,y:y+4,'text-anchor':'end',class:'usage-axis'},compact(top*(4-i)/4)));
    }
    const bucketWidth=plotWidth/data.buckets.length;
    const labels=new Set(data.buckets.length<=10?data.buckets.map((time,index)=>index):[0,.25,.5,.75,1].map(fraction=>Math.round((data.buckets.length-1)*fraction)));
    data.buckets.forEach((time,index)=>{
      const bucketX=left+index*bucketWidth,barWidth=Math.min(34,bucketWidth*.58);
      const group=svgNode('g',{class:'usage-chart-bucket'});
      let y=baseline;
      for(const row of models){
        const value=bucketValue(row,index),height=Math.max(value?0.8:0,value/top*plotHeight);
        if(!height)continue;
        y-=height;
        group.append(svgNode('rect',{x:bucketX+(bucketWidth-barWidth)/2,y,width:barWidth,height,class:'usage-chart-bar '+colorClass(row)}));
      }
      const visibleModels=models.filter(row=>bucketValue(row,index)>0);
      const detail=bucketLabel(time,true)+' · '+(visibleModels.length?visibleModels.map(row=>modelSummary(row,index)).join(' · '):'此时段暂无用量');
      if(models.length){
        const hit=svgNode('rect',{x:bucketX,y:topY,width:bucketWidth,height:plotHeight,class:'usage-chart-hit',tabindex:0,role:'img','aria-label':detail});
        for(const event of ['pointerenter','focus'])hit.addEventListener(event,()=>showTooltip(index,models));
        for(const event of ['pointerleave','blur'])hit.addEventListener(event,hideTooltip);
        group.append(hit);
      }
      svg.append(group);
      if(labels.has(index))svg.append(svgNode('text',{x:bucketX+bucketWidth/2,y:234,'text-anchor':index===0?'start':index===data.buckets.length-1?'end':'middle',class:'usage-axis'},data.bucket_seconds===3600?hourLabel(time):bucketLabel(time)));
    });
    root.append(svg);hideTooltip();
    $('usage-chart-detail').textContent=models.length?'柱高表示对应时段内各模型用量之和；悬停或聚焦日期可查看每个模型的用量。':'时间范围内暂无模型用量。';
  }
  function compositionSummary(row,index){
    const bucket=bucketFor(row,index),parts=tokenPartsFor(bucket);
    return bucketLabel(data.buckets[index],true)+' · '+modelLabel(row)+' '+number(partsTotal(parts))+' Tokens（缓存命中 '+number(parts.cached_tokens)+'，未命中 '+number(parts.uncached_tokens)+'，输出 '+number(parts.output_tokens)+'）';
  }
  function compositionTooltip(row,index,tooltip){
    const bucket=bucketFor(row,index),parts=tokenPartsFor(bucket);
    tooltip.replaceChildren();
    const heading=el('div',undefined,'usage-composition-tooltip-heading');
    heading.append(el('strong',bucketLabel(data.buckets[index],true).replace(/ (?:UTC|本地时间)$/,'')),el('span',number(partsTotal(parts))));
    tooltip.append(heading);
    for(const [key,tone,label] of [['cached_tokens','cached','输入（命中缓存）'],['uncached_tokens','uncached','输入（未命中缓存）'],['output_tokens','output','输出']]){
      const rowNode=el('div',undefined,'usage-composition-tooltip-row');
      rowNode.append(el('span',undefined,'usage-composition-tooltip-swatch stack-'+tone),el('span',label),el('strong',number(parts[key])));
      tooltip.append(rowNode);
    }
  }
  function renderCompositionChart(row){
    const width=440,left=40,right=10,topY=18,plotHeight=94,baseline=topY+plotHeight,plotWidth=width-left-right;
    const stage=el('div',undefined,'usage-composition-chart-stage');
    const svg=svgNode('svg',{viewBox:'0 0 '+width+' 150',role:'group','aria-label':modelLabel(row)+'的 Token 构成趋势'});
    const tooltip=el('div',undefined,'usage-composition-tooltip');
    tooltip.hidden=true;tooltip.setAttribute('aria-hidden','true');
    const max=Math.max(1,...row.series.map(partTotal)),top=niceTop(max,2);
    for(let i=0;i<=2;i++){
      const y=topY+i*plotHeight/2;
      svg.append(svgNode('line',{x1:left,x2:width-right,y1:y,y2:y,class:'usage-grid'}),svgNode('text',{x:left-7,y:y+4,'text-anchor':'end',class:'usage-axis'},compact(top*(2-i)/2)));
    }
    const bucketWidth=plotWidth/data.buckets.length,barWidth=Math.min(20,bucketWidth*.6);
    const labels=new Set(data.buckets.length<=7?data.buckets.map((time,index)=>index):[0,.5,1].map(fraction=>Math.round((data.buckets.length-1)*fraction)));
    data.buckets.forEach((time,index)=>{
      const bucket=bucketFor(row,index),parts=tokenPartsFor(bucket),bucketX=left+index*bucketWidth,group=svgNode('g',{class:'usage-composition-bucket'});
      let y=baseline;
      for(const [key,tone] of tokenParts){
        const height=Math.max(parts[key]?0.8:0,parts[key]/top*plotHeight);
        if(!height)continue;
        y-=height;
        group.append(svgNode('rect',{x:bucketX+(bucketWidth-barWidth)/2,y,width:barWidth,height,class:'usage-composition-bar stack-'+tone}));
      }
      const detail=compositionSummary(row,index),hit=svgNode('rect',{x:bucketX,y:topY,width:bucketWidth,height:plotHeight,class:'usage-composition-hit',tabindex:0,role:'img','aria-label':detail});
      for(const event of ['pointerenter','focus'])hit.addEventListener(event,()=>{
        compositionTooltip(row,index,tooltip);tooltip.hidden=false;$('usage-composition-detail').textContent=detail;
      });
      for(const event of ['pointerleave','blur'])hit.addEventListener(event,()=>{tooltip.hidden=true;});
      group.append(hit);svg.append(group);
      if(labels.has(index))svg.append(svgNode('text',{x:bucketX+bucketWidth/2,y:140,'text-anchor':index===0?'start':index===data.buckets.length-1?'end':'middle',class:'usage-axis'},data.bucket_seconds===3600?hourLabel(time):bucketLabel(time)));
    });
    stage.append(svg,tooltip);
    return stage;
  }
  function renderComposition(models){
    const root=$('usage-composition-charts');root.replaceChildren();
    if(!models.length){root.append(el('p','暂无模型用量','diagnostic-empty'));$('usage-composition-detail').textContent='此时间范围内暂无可查看的 Token 构成。';return;}
    for(const row of models){
      const card=el('section',undefined,'usage-composition-card '+colorClass(row)),heading=el('div',undefined,'usage-composition-heading');
      const title=el('div'),summary=el('span',compact(partTotal(row))+' Tokens','usage-composition-total');
      title.append(el('h4',modelLabel(row)),summary);
      const key=el('div',undefined,'usage-composition-key'),swatch=el('span',undefined,'usage-composition-swatch');
      for(const [,tone] of tokenParts)swatch.append(el('span',undefined,'stack-'+tone));
      key.append(swatch,el('span','缓存命中 / 未命中 / 输出'));
      heading.append(title,key);card.append(heading,renderCompositionChart(row));root.append(card);
    }
    $('usage-composition-detail').textContent='悬停或聚焦任一时段，可查看该模型的缓存命中、未命中与输出用量。';
  }
  function render(){
    if(!data)return;
    const selected=$('usage-model').value;
    const models=data.models.filter(row=>!selected||row.model===selected);
    const totals={...empty(),uncached_tokens:0};
    for(const row of models){for(const key of fields)totals[key]+=row[key];totals.uncached_tokens+=uncached(row);}
    const metrics=$('usage-metrics');metrics.replaceChildren();
    for(const [title,key,note] of [['总用量','total_tokens','输入与输出合计'],['缓存命中','cached_tokens','包含在输入 Tokens 中'],['缓存未命中','uncached_tokens','按输入减去缓存命中'],['输出 Tokens','output_tokens','模型生成的 Token'],['请求数','requests','含失败及未返回用量的请求']]){
      const item=el('div',undefined,'usage-stat');item.append(el('span',title,'hint'),el('strong',number(totals[key])),el('small',note));metrics.append(item);
    }
    const warnings={missing:'尚无请求日志。',unavailable:'日志无法读取，请稍后重试。',partial:'部分日志无法读取，统计不完整。',available:''};
    const missing=totals.requests-totals.requests_with_usage;
    $('usage-status').textContent=periodLabel()+' · '+warnings[data.state]+(totals.requests?number(totals.requests)+' 次请求 · '+(missing?number(missing)+' 次未返回有效用量 · ':''):'当前范围暂无请求记录 · ')+'更新于 '+new Date(data.generated_at*1000).toLocaleTimeString('zh-CN');
    $('usage-content').hidden=data.state==='unavailable';
    renderTrend(models);renderLegend(models);renderComposition(models);
    const ranking=$('usage-ranking'),rows=$('usage-model-rows');ranking.replaceChildren();rows.replaceChildren();
    const max=Math.max(1,...models.map(partTotal));
    for(const row of models.slice(0,6)){
      const item=el('div',undefined,'usage-rank '+colorClass(row)),heading=el('div',undefined,'usage-rank-heading');heading.append(el('span',modelLabel(row)),el('strong',compact(partTotal(row))));
      const svg=svgNode('svg',{viewBox:'0 0 300 7','aria-hidden':'true',preserveAspectRatio:'none'});
      svg.append(svgNode('rect',{width:300,height:7,rx:3.5,class:'usage-rank-track'}),svgNode('rect',{width:partTotal(row)/max*300,height:7,rx:3.5,class:'usage-rank-bar'}));
      item.append(heading,svg);ranking.append(item);
    }
    for(const row of models){const tr=el('tr'),name=el('th',modelLabel(row),'usage-model-name '+colorClass(row));name.scope='row';tr.append(name);for(const key of ['requests','input_tokens','cached_tokens','uncached_tokens','output_tokens','total_tokens'])tr.append(el('td',number(key==='uncached_tokens'?uncached(row):row[key])));rows.append(tr);}
    if(!models.length){ranking.append(el('p','暂无模型用量','diagnostic-empty'));const tr=el('tr'),td=el('td','此时间范围内暂无数据');td.colSpan=7;tr.append(td);rows.append(tr);}
  }
  async function load(){
    const id=++requestId;$('usage-status').textContent='正在读取用量…';$('usage-content').hidden=true;
    try{
      const result=await api('usage?period='+period);if(id!==requestId)return;
      data=result;const select=$('usage-model'),previous=select.value;
      select.replaceChildren(el('option','全部模型'));select.firstChild.value='';
      for(const row of data.models){const option=el('option',modelLabel(row));option.value=row.model;select.append(option);}
      select.value=data.models.some(row=>row.model===previous)?previous:'';render();
    }catch{if(id!==requestId)return;data=null;$('usage-status').textContent='用量读取失败，请点击刷新重试。';$('usage-content').hidden=true;}
  }
  $('usage-model').onchange=render;
  for(const button of $('usage-period').querySelectorAll('button'))button.onclick=()=>{
    period=button.dataset.period;
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
