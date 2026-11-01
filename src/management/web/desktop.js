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
      if(result.ok)return;
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
    native.event.listen(name,handler).catch(()=>message('桌面菜单连接失败，请重新打开应用后重试。',true));
  }
})();
