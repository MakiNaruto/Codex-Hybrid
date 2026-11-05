'use strict';
// Only lifecycle controls live here; all management views and forms are shared.
(() => {
  const desktop=window.hybridDesktop;
  if(!desktop)return;
  const native=window.__TAURI__;
  window.addEventListener('hybrid-management-ready',()=>refreshClientProcesses());
  let busy=false,restartPreview=null;
  function blocked(){
    if(busy||routingSaving||sourceSaving||modelSaving||desktop.pendingWrites||dirtyCards().length||document.querySelector('dialog[open]')){
      message('请先完成当前操作，保存或取消草稿，并关闭当前弹窗。',true);return true;
    }
    return false;
  }
  async function guarded(fn){
    if(blocked())return;
    busy=true;
    try{await fn();}catch(error){message(errorMessage(error),true);}
    finally{busy=false;}
  }
  async function exitApp(){
    await guarded(async()=>{
      let result=await native.core.invoke('desktop_exit');
      if(result.ok||result.cancelled)return;
      if(result.error==='EXIT_BLOCKED'&&result.restore_preview){
        await refresh();
        if(state?.routing_mode==='project'){
          message('退出前需恢复原生接入配置，请确认以下切换；取消会保留应用运行。');
          if(!await switchRouting('openai'))return;
          $('routing-dialog').close();
          result=await native.core.invoke('desktop_exit');
          if(result.ok)return;
        }
      }
      message(result.error==='EXIT_BLOCKED'?'暂不能退出：接入仍开启，或客户端仍可能依赖网关。请关闭接入并检查客户端后重试。':'退出未完成，请检查状态后重试。',true);
    });
  }
  const alert=(title,detail,buttons=['好的'])=>native.core.invoke('desktop_alert',{title,detail,buttons});
  async function nativeAction(fn){
    if(blocked()){await alert('暂不能操作','请先完成当前操作，或保存、取消未完成的编辑。');return;}
    busy=true;
    try{await fn();}catch(error){message(errorMessage(error),true);await alert('操作未完成',errorMessage(error));}
    finally{busy=false;}
  }
  function activityNote(preview){
    const count=preview.activity?.active_requests;
    return count>0?'\n当前有 '+count+' 个请求正在进行。':count==null?'\n当前请求状态未知。':'';
  }
  function nativeRoutingResult(result){
    const outcomes={started:'已请求启动 Codex。',already_running:'Codex 已在运行。',
      close_failed:'Codex 未能退出，请手动重启。',launch_unconfirmed:'未能确认 Codex 启动，请手动打开。',
      unavailable:'未找到 Codex，请手动打开。',unknown:'无法确认 Codex 状态，请手动重启。',
      state_changed:'Codex 状态已变化，请手动重启。',not_running:'Codex 未运行，请手动打开。'};
    let text=outcomes[result.desktop_result]||'请重启 Codex 使更改生效。';
    if(result.warnings?.length)text+='\n'+result.warnings.map(warning=>warning.message).join('\n');
    return text;
  }
  async function nativeRouting(quietSuccess){
    await nativeAction(async()=>{
      await refresh();
      if(!state){await alert('尚未初始化','请先在管理窗口初始化配置。');return;}
      if(state.routing_operation){await alert('正在切换','请等待当前接入操作完成。');return;}
      const mode=routingEnabled()?'openai':'project',verb=mode==='project'?'开启':'关闭';
      routingSaving=true;renderRouting();
      try{
        const preview=await desktop.api('routing/preview',{mode});
        const client=preview.desktop;
        const possible=client?.available&&client.status==='known'&&(mode==='project'||client.running)&&state.desktop_preferences?.[mode]!=='never';
        const buttons=['取消','仅'+verb];
        if(possible)buttons.push(verb+'并'+(client.running?'重启':'启动')+' Codex');
        let committed=false;
        try{
          let detail=mode==='project'?'使用已配置的模型，保留现有会话。':'恢复 Codex 原生路由，保留现有会话。';
          detail+=possible&&client.running?'\n重启可能中断 Codex 所有窗口中的任务。':'\n请重新打开 Codex 使更改生效。';
          detail+=activityNote(preview);
          if(preview.missing_rollouts>0)detail+='\n部分历史文件缺失，请在管理页面检查。';
          const choice=await alert(verb+'混合路由？',detail,buttons);
          if(choice!==1&&!(choice===2&&possible))return;
          committed=true;
          const result=await desktop.api('routing',{mode,revision:preview.revision,confirm_activity:true,desktop_action:choice===2,desktop_was_running:!!client?.running,desktop_ticket:preview.desktop_ticket});
          const title='混合路由已'+verb,summary=nativeRoutingResult(result);
          const completed=choice===1||['started','already_running'].includes(result.desktop_result);
          if(quietSuccess&&completed&&!result.warnings?.length)message(title+'。'+summary);
          else await alert(title,summary);
        }finally{if(!committed)await desktop.request({action:'cancel_preview'});}
      }finally{routingSaving=false;await refresh();renderRouting();}
    });
  }
  async function nativeRestart(quietSuccess){
    await nativeAction(async()=>{
      message('正在检查 Codex 状态…');
      const preview=await desktop.request({action:'preview_restart'});
      let committed=false;
      try{
        if(!preview.available){
          const labels={not_running:'请先打开 Codex。',unavailable:'未找到 Codex，请手动打开。',unknown:'无法确认运行状态，请手动重启。'};
          await alert('无法重启 Codex',labels[preview.status]||'请检查 Codex 状态后重试。');return;
        }
        const choice=await alert('重启 Codex？','将退出并重新打开 Codex，可能中断所有窗口中的任务。'+activityNote(preview),['取消','重启 Codex']);
        if(choice!==1)return;
        committed=true;
        const result=await desktop.request({action:'restart_codex',ticket:preview.ticket,confirm_activity:true});
        const outcomes={started:'已请求重新打开 Codex。',close_failed:'Codex 未能退出，请手动重启。',launch_unconfirmed:'未能确认 Codex 启动，请手动打开。'};
        const summary=outcomes[result.desktop_result]||'请检查 Codex 是否已重新打开。';
        if(quietSuccess&&result.desktop_result==='started')message(summary);
        else await alert('重启 Codex',summary);
      }finally{if(!committed)await desktop.request({action:'cancel_restart'});}
    });
  }
  async function toggleRouting(){
    await guarded(async()=>{
      await refresh();
      if(!state){message('请先初始化管理配置。',true);return;}
      await switchRouting(routingEnabled()?'openai':'project');
    });
  }
  const dialog=$('desktop-restart-dialog');
  async function previewRestart(){
    await guarded(async()=>{
      restartPreview=await desktop.request({action:'preview_restart'});
      const labels={running:'检测到运行',not_running:'未运行，本入口不会启动 Codex',unavailable:'无法识别安装，请手动操作',unknown:'状态未知，已阻止自动重启'};
      $('desktop-restart-summary').textContent='Codex：'+(labels[restartPreview.status]||'未知')+'；活动请求：'+(restartPreview.activity?.active_requests??'未知')+'。仅请求正常退出，不强制结束进程。预览两分钟内有效，执行前会重新核对进程身份。';
      $('desktop-restart-ack').checked=false;
      $('desktop-restart-confirm').disabled=!restartPreview.available;
      dialog.showModal();
    });
  }
  dialog.addEventListener('submit',async event=>{
    if(event.submitter?.value!=='confirm')return;
    event.preventDefault();
    if(busy||!restartPreview?.available)return;
    if(!$('desktop-restart-ack').checked){message('请先勾选确认重启影响，或取消。',true);return;}
    busy=true;$('desktop-restart-confirm').disabled=true;
    try{
      const result=await desktop.request({action:'restart_codex',ticket:restartPreview.ticket,confirm_activity:true});
      restartPreview=null;dialog.close();
      const outcomes={started:'已尝试启动 Codex，不代表客户端已加载配置或恢复任务。',close_failed:'Codex 正常退出未完成，未尝试启动，请手动检查。',launch_unconfirmed:'未能确认 Codex 启动成功，请手动检查。'};
      message(outcomes[result.desktop_result]||'重启请求已结束，请检查 Codex 状态。');
    }catch(error){restartPreview=null;dialog.close();message(errorMessage(error),true);}
    finally{busy=false;}
  });
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  dialog.addEventListener('submit',event=>{if(busy&&event.submitter?.value!=='confirm')event.preventDefault();});
  dialog.addEventListener('close',()=>{
    if(restartPreview){restartPreview=null;desktop.request({action:'cancel_restart'}).catch(error=>message(errorMessage(error),true));}
  });
  $('desktop-initialize').onclick=()=>guarded(async()=>{
    $('desktop-initialize').disabled=true;
    try{await desktop.request({action:'initialize'});await refresh();message('管理配置已初始化。可添加模型，再预览开启接入。');}
    finally{$('desktop-initialize').disabled=false;}
  });
  for(const [name,handler] of [['desktop-exit-requested',exitApp],['desktop-routing-requested',toggleRouting],['desktop-restart-requested',previewRestart]]){
    native.event.listen(name,event=>{
      if(event?.payload?.native_confirmation){
        if(name==='desktop-routing-requested')return nativeRouting(event.payload.quiet_routing_success);
        if(name==='desktop-restart-requested')return nativeRestart(event.payload.quiet_restart_success);
      }
      return handler();
    }).catch(()=>message('桌面菜单连接失败，请重新打开应用后重试。',true));
  }
})();
