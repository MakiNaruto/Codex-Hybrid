'use strict';
// Page-local requests and period state; shared UI helpers come from app.js.
(() => {
  const diagnosticStatuses={rejected:'请求未完成',incompatible_request_or_stream:'请求或流处理异常',
    upstream_connection_failed:'上游连接失败',upstream_http_error:'上游返回错误',
    client_disconnected:'客户端连接中断',failed:'响应失败',incomplete:'响应未完成',
    stream_ended_without_completion:'流结束时缺少完成信号',
    forwarding_exited:'网关进程意外退出',forwarding_start_failed:'网关进程启动失败'};
  function diagnosticTime(seconds){
    const date=new Date(seconds*1000);
    const pad=value=>String(value).padStart(2,'0');
    const offset=-date.getTimezoneOffset();
    return date.getFullYear()+'-'+pad(date.getMonth()+1)+'-'+pad(date.getDate())+' '+
      pad(date.getHours())+':'+pad(date.getMinutes())+':'+pad(date.getSeconds())+
      ' UTC'+(offset>=0?'+':'-')+pad(Math.floor(Math.abs(offset)/60))+':'+pad(Math.abs(offset)%60);
  }
  function renderDiagnostics(report){
    const seconds=report.service.uptime_seconds;
    $('service-status').textContent='运行中'+(seconds===null?'':' · 已运行 '+Math.floor(seconds/60)+' 分钟');
    $('service-status').classList.add('diagnostic-running');
    const updated=el('span','更新于 '+diagnosticTime(report.generated_at).slice(11,19));
    updated.title=diagnosticTime(report.generated_at);$('diagnostic-updated').replaceChildren(updated);
    const list=$('diagnostic-errors');list.replaceChildren();
    const groups=[
      ['请求校验与格式错误',new Set(['rejected','incompatible_request_or_stream']),'请求未通过校验，或请求、响应流的格式无法被网关处理。'],
      ['上游服务错误',new Set(['upstream_connection_failed','upstream_http_error']),'网关无法连接模型服务，或模型服务返回错误状态。'],
      ['客户端连接中断',new Set(['client_disconnected']),'Codex 等客户端在请求处理期间断开了与网关的连接。'],
      ['响应失败或未完成',new Set(['failed','incomplete','stream_ended_without_completion']),'请求已开始处理，但模型响应失败，或未正常完成。'],
      ['其他运行异常',null,'服务运行或启动时出现的异常，以及暂时无法归入其他类别的错误。']
    ];
    const known=new Set(groups.flatMap(([,statuses])=>statuses?[...statuses]:[]));
    for(const [name,statuses,description] of groups){
      const entries=report.log.errors.filter(entry=>statuses?statuses.has(entry.status):!known.has(entry.status));
      if(!entries.length)continue;
      const group=el('li',undefined,'diagnostic-group');
      const heading=el('div',undefined,'diagnostic-group-heading');
      heading.append(el('strong',name),el('span',String(entries.reduce((total,entry)=>total+(entry.count||1),0)),'diagnostic-count'),help(description,name+'说明'));
      group.append(heading);
      const items=el('ul',undefined,'diagnostic-records');
      for(const entry of entries){
        const row=el('li',undefined,'diagnostic-record');
        const primary=el('div',undefined,'diagnostic-record-primary');
        const reference=entry.time_source==='file_modified';
        const fullTime=entry.time===undefined?'时间未知':diagnosticTime(entry.time);
        const time=el('span',entry.time===undefined?'时间未知':fullTime.slice(5,19),'diagnostic-time help-trigger');
        time.tabIndex=0;
        time.dataset.help=fullTime+(reference?' · 日志文件修改时间，非发生时间':'');
        time.setAttribute('aria-label',time.dataset.help);
        time.setAttribute('aria-expanded','false');
        primary.append(time);
        if(reference)primary.append(el('span','参考','diagnostic-reference'));
        primary.append(el('span',entry.exception_type||diagnosticStatuses[entry.status]||'其他异常','diagnostic-record-title'));
        row.append(primary);
        const meta=[];
        if(entry.count>1)meta.push(entry.count+' 条记录');
        if(entry.winerror!==undefined)meta.push('WinError '+entry.winerror);
        if(entry.errno!==undefined)meta.push('errno '+entry.errno);
        if(entry.http_status!==undefined)meta.push('HTTP '+entry.http_status);
        if(entry.elapsed_ms!==undefined)meta.push(entry.elapsed_ms+' ms');
        if(entry.error_code)meta.push(entry.error_code);
        if(entry.error_kind)meta.push(entry.error_kind);
        if(entry.request_ref)meta.push('请求 '+entry.request_ref);
        if(entry.source){
          const source=entry.source.startsWith('service.startup.stderr')?'启动日志':entry.source.startsWith('service.stderr')?'服务日志':'请求日志';
          meta.push(source+(/\.[123]$/.test(entry.source)?' · 历史记录':''));
        }
        if(meta.length){const detail=el('div',meta.join(' · '),'diagnostic-record-meta');row.append(detail);}
        items.append(row);
      }
      group.append(items);list.append(group);
    }
    if(!list.children.length&&report.log.state==='available'){
      const periodNames={1:'最近 24 小时',7:'最近 7 天',30:'最近 30 天',all:'现有日志中'};
      list.append(el('li',(periodNames[report.period_days??'all'])+'未发现错误','diagnostic-empty'));
    }
    $('diagnostic-coverage').textContent=
      (report.log.state==='missing'?'尚无日志文件':
       report.log.state==='unavailable'?'日志暂时无法读取':
       report.log.state==='partial'?'部分日志无法读取，以下结果不完整':'')+
      (report.log.coverage?.rotation_may_remove_history?' 仅包含保留日志，历史记录可能已被轮转清理。':'');
    $('diagnostic-coverage').hidden=!$('diagnostic-coverage').textContent;
  }
  let diagnosticRequest=0;
  let diagnosticPeriod='1';
  async function loadDiagnostics(){
    const request=++diagnosticRequest;
    const period=diagnosticPeriod;
    try{const report=await api('diagnostics?days='+period);if(request===diagnosticRequest)renderDiagnostics(report);return report;}
    catch(error){if(request!==diagnosticRequest)throw error;$('service-status').classList.remove('diagnostic-running');$('service-status').textContent='诊断读取失败，请重试';$('diagnostic-updated').replaceChildren();$('diagnostic-errors').replaceChildren(el('li','无法读取'));$('diagnostic-coverage').textContent='';throw error;}
  }
  for(const trigger of $('diagnostic-period').querySelectorAll('button'))trigger.onclick=()=>{
    if(diagnosticPeriod===trigger.dataset.period)return;
    diagnosticPeriod=trigger.dataset.period;
    for(const option of $('diagnostic-period').querySelectorAll('button'))option.setAttribute('aria-pressed',String(option===trigger));
    $('diagnostic-errors').replaceChildren(el('li','正在读取错误记录…','diagnostic-empty'));
    action(loadDiagnostics);
  };
  action(loadDiagnostics);
  for(const id of ['refresh-diagnostics','export-diagnostics'])$(id).onclick=()=>action(async()=>{
    $(id).disabled=true;
    try{
      const report=await loadDiagnostics();
      if(id==='export-diagnostics'){
        const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
        const link=el('a');link.href=url;link.download='codex-hybrid-diagnostics.json';
        document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
        message('脱敏诊断已生成并触发下载。');
      }
    }finally{$(id).disabled=false;}
  });

})();
