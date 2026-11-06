'use strict';
function createRoutingControls({getState,isSaving,setSaving,$,el,api,action,refresh,message,errorMessage,syncDesktopSelect}){
  let routingError='';
  function renderRouting(){
    renderForwarding(getState()?.forwarding);
    const operation=getState()?.routing_operation;
    const busy=isSaving()||!!operation;
    const phases={preparing:'正在准备切换…',closing:'正在请求 Codex 桌面端正常退出，请稍候…',applying:'正在应用接入配置和会话索引…',launching:'正在启动 Codex 桌面端，请稍候…'};
    const progress=operation&&Object.hasOwn(phases,operation.phase)?phases[operation.phase]:'';
    const toggle=$('routing-toggle');
    toggle.setAttribute('aria-checked',String(routingEnabled()));
    toggle.disabled=busy||!['project','openai','external'].includes(getState()?.routing_mode);
    toggle.setAttribute('aria-busy',String(busy));
    $('routing-status').textContent=progress||(isSaving()?'正在准备或切换…':routingError||(
      getState()?.routing_interrupted&&getState()?.routing_mode!=='project'?'接管已中断 · Codex 配置已变化，请重新开启接入':
      getState()?.routing_mode==='project'?({running:'已开启',starting:'已开启 · 正在启动…',recovering:'已开启 · 正在自动重试…',fault:'已开启 · 模型转发异常',stopped:'已开启 · 模型转发未运行'}[getState()?.forwarding?.status]||'已开启 · 正在检查状态…'):getState()?.routing_mode==='openai'?'已关闭 · 使用原生路由':getState()?.routing_mode==='external'?'已关闭 · 当前使用第三方直连配置':'无法切换：请检查 Codex 配置'));
    if(progress&&isSaving()&&$('routing-dialog').open&&$('routing-dialog-confirm').disabled){
      $('routing-dialog-description').textContent=progress;
    }
  }
  function routingEnabled(){
    return getState()?.routing_mode==='project';
  }
  let routingPolling=false;
  async function refreshRoutingProgress(){
    if(routingPolling)return;
    routingPolling=true;
    try{
      const activity=await api('activity');
      if(!isSaving())return;
      if(getState()){getState().routing_operation=activity.routing_operation;getState().forwarding=activity.forwarding;}
      renderRouting();
    }finally{routingPolling=false;}
  }
  function confirmRouting(mode,preview){
    const dialog=$('routing-dialog'),verb=mode==='project'?'开启':'关闭';
    const desktop=preview.desktop,preference=getState().desktop_preferences?.[mode]||'ask';
    const possible=desktop?.available&&desktop.status==='known'&&(mode==='project'||desktop.running);
    const checkbox=$('desktop-action');
    checkbox.checked=possible&&preference==='auto';
    checkbox.disabled=!possible||preference==='never';
    $('desktop-action-row').hidden=!possible||preference==='never';
    $('desktop-action-label').textContent=desktop?.running?'同时重启 Codex 桌面端':'完成后启动 Codex 桌面端';
    $('routing-dialog-title').textContent=verb+' Codex 接入？';
    $('routing-dialog-description').textContent=(mode==='project'?'将启用混合路由并保留当前厂商模型':'将恢复开启接入前的第三方或原生配置')+'，并备份、更新本地会话索引，保留历史内容和无关配置修改。';
    renderClientProcesses(preview.codex_process);renderGatewayActivity(preview.activity);
    const warnings=(preview.warnings||[]).map(warning=>warning.message+'（'+warning.code+'）');
    if((preview.activity?.active_requests||0)>0)warnings.push('当前仍有请求正在执行，重启桌面端可能中断任务。');
    if((preview.codex_process?.clients?.cli||0)+(preview.codex_process?.clients?.vscode||0)>0)warnings.push('CLI / VS Code 仍在运行，将更新共享配置和会话索引，建议先结束正在执行的任务。');
    warnings.push('自动操作仅针对本机 Codex 桌面端，重启可能影响所有桌面窗口的任务。其他客户端请自行重启。');
    if(!possible&&mode==='project')warnings.push('桌面端未识别、检测不完整或不支持自动操作，请自行打开或重启 Codex。');
    $('routing-dialog-warning').hidden=false;$('routing-dialog-warning').textContent=warnings.join(' ');
    $('routing-dialog-details').textContent=(preview.changes||[]).join('\n\n');
    dialog.querySelector('details').open=false;
    const confirm=$('routing-dialog-confirm');confirm.disabled=false;
    $('routing-dialog-cancel').hidden=false;
    const updateLabel=()=>{confirm.textContent=checkbox.checked?verb+'并'+(desktop?.running?'重启':'启动')+'桌面端':'确认'+verb;};
    checkbox.onchange=updateLabel;updateLabel();
    dialog.returnValue='cancel';
    return new Promise(resolve=>{
      const submit=event=>{
        if(event.submitter?.value!=='confirm')return;
        event.preventDefault();dialog.removeEventListener('submit',submit);
        resolve({desktop_action:checkbox.checked&&!checkbox.disabled,desktop_was_running:!!desktop?.running,desktop_ticket:preview.desktop_ticket});
      };
      dialog.addEventListener('submit',submit);
      dialog.addEventListener('close',()=>{dialog.removeEventListener('submit',submit);resolve(null);},{once:true});
      dialog.showModal();
    });
  }
  function finishRouting(text,error=false){
    $('routing-dialog-title').textContent=error?'接入切换失败':'操作结果';
    $('routing-dialog-description').textContent=text;
    $('routing-dialog-warning').hidden=true;$('desktop-action-row').hidden=true;
    $('routing-dialog').querySelector('details').open=false;
    $('routing-dialog-cancel').hidden=true;
    const confirm=$('routing-dialog-confirm');confirm.textContent='好的';confirm.disabled=false;
    message(text,error);
  }
  function routingResultText(mode,saved){
      const outcomes={started:'桌面端已启动。',already_running:'已检测到桌面端运行。',launch_unconfirmed:'未能确认桌面端启动成功，请自行打开 Codex 重试。',close_failed:'桌面端未能自动退出，请手动完全退出并重新打开 Codex。',unavailable:'未找到可用的桌面端安装，请自行打开或重启 Codex。',unknown:'无法确认桌面端状态，请自行打开或重启 Codex。',state_changed:'桌面端运行状态已变化，请自行重启 Codex。',not_running:'桌面端未运行，未启动。',manual:'请自行打开或重启需要使用新配置的 Codex。'};
      const reasons={quit_denied:'macOS 未允许退出操作，请检查自动化权限或手动退出 Codex。',window_enumeration_failed:'Windows 未允许读取桌面窗口。',restart_manager_identity_failed:'无法验证桌面端进程身份，未发送关闭请求。',restart_manager_identity_changed:'桌面端进程身份发生变化，未发送关闭请求。',restart_manager_start_failed:'无法创建 Windows 后台退出会话。',restart_manager_registration_failed:'Windows 未接受桌面端退出注册。',restart_manager_scope_changed:'Windows 返回的退出范围不符合本次桌面端目标，未发送关闭请求。',restart_manager_shutdown_failed:'Windows 后台正常退出请求未完成，应用可能拒绝退出或权限不足；未强制结束进程。',exit_timeout:'已请求正常退出，但桌面进程在等待期间仍未退出，请检查 Codex 是否弹出了退出确认。',process_reappeared:'原桌面进程退出后又检测到桌面进程，本次未重复操作。'};
      return ((mode==='project'?'接入配置已开启。':'接入前配置已恢复。')+(outcomes[saved.desktop_result]||outcomes.manual)+(reasons[saved.desktop_error]||'')+' 其他客户端请自行重启。'+(saved.forwarding_retained?' 为避免中断仍运行的客户端，模型转发暂时保留。':'')+(saved.warnings||[]).map(w=>w.message).join(' ')+' 首次基线：'+(saved.session_backup||'无需迁移'));
  }
  async function switchRouting(mode){
    if(isSaving()||getState()?.routing_operation)return;
    setSaving(true);routingError='';renderRouting();
    try{
      const preview=await api('routing/preview',{mode});
      const choice=await confirmRouting(mode,preview);if(!choice){
        if(window.hybridDesktop)await window.hybridDesktop.request({action:'cancel_preview'});
        return false;
      }
      $('routing-dialog-confirm').disabled=true;
      $('routing-dialog-confirm').textContent=choice.desktop_action?(choice.desktop_was_running?'正在切换并重启…':'正在切换并启动…'):'正在切换…';
      $('routing-dialog-cancel').hidden=true;$('desktop-action').disabled=true;
      if(choice.desktop_action&&choice.desktop_was_running){
        $('routing-dialog-description').textContent='正在请求 Codex 桌面端正常退出。退出完成后将应用配置并启动桌面端。';
        $('routing-dialog-warning').hidden=false;
        $('routing-dialog-warning').textContent='仅请求正常退出一次，不强制结束进程。若应用拒绝退出，将应用配置并提示手动处理。';
      }
      const saved=await api('routing',{mode,revision:preview.revision,confirm_activity:true,...choice});
      getState().routing_mode=saved.routing_mode;
      finishRouting(routingResultText(mode,saved));
      return true;
    }catch(error){
      routingError=errorMessage(error);
      if($('routing-dialog').open)finishRouting(routingError+(error.message==='OPERATION_TIMEOUT'||error.message==='SERVICE_UNREACHABLE'?' 请检查实际配置和桌面端状态后自行处理。':' 未继续启动桌面端。'),true);
      else message(routingError,true);
    }finally{
      try{await refresh();}catch(error){message(errorMessage(error),true);}
      setSaving(false);renderRouting();
    }
  };
  function renderForwarding(forwarding){
    if(!forwarding)return;
    const status=forwarding.status;
    const labels={starting:'正在启动',running:'运行中',fault:'故障，自动恢复已停止',stopped:'已停止',recovering:'意外退出，正在自动恢复'};
    let detail=status==='recovering'?'（第 '+forwarding.retry_attempt+'/'+forwarding.retry_limit+' 次，预计 '+new Date(forwarding.retry_at*1000).toLocaleTimeString()+' 重试）':'';
    const reasons={port_in_use:'转发端口已被占用，请关闭占用程序或修改端口后重试。',permission_denied:'系统拒绝启动或监听，请检查本机权限后重试。',startup_timeout:'网关未在规定时间内就绪，请查看日志后重试。',worker_exited:'网关在就绪前退出，请查看日志后重试。',invalid_configuration:'网关配置无法读取或格式无效，请检查配置后重试。',process_start_failed:'无法创建网关进程，请检查运行环境后重试。',worker_error:'网关启动发生异常，请查看日志后重试。'};
    if(status==='fault'&&Object.hasOwn(reasons,forwarding.error_reason))detail='：'+reasons[forwarding.error_reason];
    if(status==='running'&&['openai','external'].includes(getState()?.routing_mode))detail='（接入已关闭，暂保留供运行中的客户端使用）';
    if(Number.isSafeInteger(forwarding.log_dropped_records)&&forwarding.log_dropped_records>0)detail+=' · 已丢弃 '+forwarding.log_dropped_records+' 条日志（积压或写入失败）';
    $('forwarding-status').textContent='管理服务可用 · 模型转发'+(labels[status]||'状态未知')+detail;
    $('retry-forwarding').hidden=getState()?.routing_mode!=='project'||!['fault','stopped'].includes(status);
    $('retry-forwarding').disabled=isSaving()||!!getState()?.routing_operation;
  }
  function renderGatewayActivity(activity){
    if(getState()){getState().forwarding=activity?.forwarding;renderRouting();}
    const busy=activity?.gateway_status==='busy';
    const status=$('gateway-activity');
    status.hidden=false;
    status.textContent='网关 · '+(busy?activity.active_requests+' 个活动请求':activity?.gateway_status==='no_activity'?'无活动请求':'状态未知');
    status.classList.toggle('detected',busy);
  }
  function renderClientProcesses(process){
    const list=$('client-process-list');list.replaceChildren();
    const known=['running','not_detected'].includes(process?.status);
    for(const [kind,name] of [['desktop','桌面端'],['vscode','VS Code 端'],['cli','CLI 端'],['unknown','来源未知']]){
      const count=process?.clients?.[kind]||0;
      if(kind==='unknown'&&!count)continue;
      list.append(el('span',name+' · '+(count?count+' 个进程':known?'未检测到':'状态未知'),'client-process'+(count?' detected':'')+(kind==='unknown'?' unknown':'')));
    }
    $('client-process-note').textContent=(known?'':'检测不完整，部分进程可能无法读取。')+'进程数量不等于窗口数量或正在执行的任务。'+(process?.observed_at?' 检测于 '+new Date(process.observed_at*1000).toLocaleTimeString():'');

  }
  let processesRefreshing=false;
  async function refreshClientProcesses(){
    if(processesRefreshing)return;
    processesRefreshing=true;
    const trigger=$('detect-processes');
    trigger.disabled=true;trigger.textContent='检测中…';trigger.setAttribute('aria-busy','true');
    $('client-process-list').replaceChildren(...['桌面端','VS Code 端','CLI 端'].map(name=>el('span',name+' · 检测中…','client-process')));
    const gateway=$('gateway-activity');gateway.hidden=false;gateway.textContent='网关 · 检测中…';gateway.classList.remove('detected');
    $('client-process-note').textContent='检测可能需要几秒，请稍候。';
    try{
      const [process,activity]=await Promise.allSettled([api('processes'),api('activity')]);
      renderClientProcesses(process.status==='fulfilled'?process.value:null);
      renderGatewayActivity(activity.status==='fulfilled'?activity.value:null);
      const failures=[];
      if(process.status==='rejected')failures.push('客户端进程');
      if(activity.status==='rejected')failures.push('网关活动');
      if(failures.length)$('client-process-note').textContent+=' '+failures.join('、')+'检测失败，已显示为状态未知。';
    }finally{processesRefreshing=false;trigger.disabled=false;trigger.textContent='检测';trigger.removeAttribute('aria-busy');}
  }

  function initRoutingControls(){
    $('routing-dialog').addEventListener('cancel',event=>{if(isSaving()&&$('routing-dialog-confirm').disabled)event.preventDefault();});
    for(const mode of ['project','openai'])$('desktop-'+mode).onchange=()=>action(async()=>{
      try{const saved=await api('desktop/preferences',{mode,value:$('desktop-'+mode).value});getState().desktop_preferences=saved.desktop_preferences;message('桌面端操作设置已保存。');}
      catch(error){$('desktop-'+mode).value=getState().desktop_preferences?.[mode]||'ask';throw error;}
      finally{syncDesktopSelect($('desktop-'+mode));}
    });
    $('routing-toggle').onclick=()=>switchRouting(routingEnabled()?'openai':'project');
    $('retry-forwarding').onclick=()=>action(async()=>{await api('runtime/recover',{});await refresh();message('模型转发已启动。');});
    $('detect-processes').onclick=refreshClientProcesses;
  }
  return {renderRouting,routingEnabled,refreshRoutingProgress,switchRouting,renderForwarding,renderGatewayActivity,renderClientProcesses,refreshClientProcesses,initRoutingControls};
}
