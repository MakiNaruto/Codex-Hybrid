'use strict';
const token = window.hybridDesktop ? '' : location.hash.slice(1) || sessionStorage.getItem('connectedNativeManagementToken') || '';
if (token) sessionStorage.setItem('connectedNativeManagementToken', token);
if(!window.hybridDesktop)history.replaceState(null, '', location.pathname);
let state;
let routingSaving=false;
const $ = id => document.getElementById(id);
const {el,help,field,copyText,syncDesktopSelect,initDesktopSelects,initHelp,closeHelp}=createManagementControls(message);
let messageTimer, fadeTimer;
function message(text,error=false){
  clearTimeout(messageTimer);clearTimeout(fadeTimer);
  $('notifications').classList.remove('is-hiding');
  $('message').textContent=text;$('message').className=error?'error':'';
  $('dismiss-message').hidden=!text;
  if(text&&!error)messageTimer=setTimeout(()=>{
    $('notifications').classList.add('is-hiding');
    fadeTimer=setTimeout(()=>{$('message').textContent='';$('dismiss-message').hidden=true;},250);
  },5000);
}
$('dismiss-message').onclick=()=>message('');
async function api(path,body){
  if(window.hybridDesktop){
    try{const result=await window.hybridDesktop.api(path,body);setConnection(true);return result;}
    catch(error){setConnection(error.message!=='SERVICE_UNREACHABLE'&&error.message!=='INVALID_SERVICE_RESPONSE');throw error;}
  }
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),path==='processes'?20000:body===undefined?8000:path==='test'?75000:120000);
  let response;
  try{
    try{response=await fetch('/manage/api/'+path,{method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal});}
    catch(error){setConnection(false);throw Error(error.name==='AbortError'?'OPERATION_TIMEOUT':'SERVICE_UNREACHABLE');}
    setConnection(true);
    let data;
    try{data=await response.json();}catch(error){throw Error(controller.signal.aborted?'OPERATION_TIMEOUT':'INVALID_SERVICE_RESPONSE');}
    if(!response.ok)throw Error(data.code||'请求失败');return data;
  }finally{clearTimeout(timer);}
}
function setConnection(connected){
  const indicator=$('connection-indicator');indicator.textContent=connected?'本地服务已连接':'本地服务连接中断';indicator.classList.toggle('offline',!connected);
}
function errorMessage(error){return managementErrorMessage(error,state?.mode);}
async function action(fn){try{await fn();}catch(error){message(errorMessage(error),true);}}
function button(text,fn,cls='secondary'){const b=el('button',text,cls);b.type='button';b.onclick=()=>action(async()=>{b.disabled=true;try{await fn();}finally{b.disabled=false;}});return b;}
const connectionResults=new Map();
let testingConnections=0;
function testButton(model,sourceOnly=false){
  const group=el('div',undefined,'connection-test');
  const result=el('span',undefined,'test-result');
  const saved=connectionResults.get(model?.key);
  if(saved){result.textContent=saved.text;result.className=saved.error?'test-result error':'test-result';}
  const b=button('测试连接',async()=>{
    testingConnections++;b.textContent='测试中…';b.setAttribute('aria-busy','true');
    result.textContent='正在连接 '+model.display_name+'…';result.className='test-result pending';
    try{
      const data=await api('test',{key:model.key});
      const text='连接成功，已调用模型：'+(data.model_id||'未提供')+(data.elapsed_ms===undefined?'':' · '+data.elapsed_ms+' ms');
      connectionResults.set(model.key,{text,error:false});
      result.textContent=text;result.className='test-result';message(text);
    }catch(error){
      const text=errorMessage(error);
      connectionResults.set(model.key,{text,error:true});
      result.textContent=text;result.className='test-result error';message(text,true);
    }finally{testingConnections--;b.textContent='测试连接';b.removeAttribute('aria-busy');}
  });
  b.disabled=!(sourceOnly?model?.source_enabled:model?.enabled);b.title=b.disabled?'请先保存并启用厂商及模型':sourceOnly?'测试 CC Switch 来源配置，无需加入模型列表':'测试已保存的模型配置';
  group.append(b,result);return group;
}
const {dirtyCards,updateUnsaved,markDirty,clearDirty,discardDrafts,installUnloadGuard}=createProviderDrafts($('providers'),$('unsaved-status'),el);
installUnloadGuard();
const {providerCard,ccCard}=createProviderViews({
  getState:()=>state,el,field,help,button,testButton,markDirty,clearDirty,applyFilters,
  api,refresh,message,clearConnectionResults:()=>connectionResults.clear()
});
function applyFilters(){
  if(typeof renderModelList==='function')renderModelList();
  const query=$('model-search').value.trim().toLowerCase(),filter=$('model-filter').value;
  let visible=0,total=0;
  for(const card of $('providers').children){
    if(!card.classList.contains('card'))continue;total++;
    const text=(card.textContent+' '+[...card.querySelectorAll('input:not([type=password]):not([type=checkbox])')].map(input=>input.value).join(' ')).toLowerCase();
    const models=(state?.models||[]).filter(model=>model.provider===card.dataset.providerId);
    const checks=[...card.querySelectorAll('.models-grid input[type=checkbox]')];
    const providerEnabled=card.querySelector('.provider-sidebar input[type=checkbox]')?.checked!==false;
    const flags=checks.length?checks.map(input=>providerEnabled&&input.checked):models.map(model=>model.enabled);
    const matches=filter==='all'||(filter==='enabled'?flags.some(Boolean):flags.some(value=>!value));
    card.hidden=!(text.includes(query)&&matches);if(!card.hidden)visible++;
  }
  $('search-empty').hidden=!(total>0&&visible===0);
}
$('model-search').addEventListener('input',applyFilters);$('model-filter').addEventListener('change',applyFilters);
let sourceSaving=false;
function changeSource(mode,path){return action(async()=>{
  if(sourceSaving||(state?.mode===mode&&path===undefined))return;
  if(dirtyCards().length&&!confirm('切换来源会放弃未保存的厂商修改，确定继续？'))return;
  sourceSaving=true;
  const buttons=[$('independent'),$('cc_switch'),$('save-path')];buttons.forEach(button=>button.disabled=true);
  try{await api('source',{mode,cc_db_path:path});for(const card of dirtyCards())clearDirty(card);connectionResults.clear();await refresh();message('配置来源已更新。');}
  finally{sourceSaving=false;buttons.forEach(button=>button.disabled=false);}
});}
function renderAccessSummary(){
  if(!state)return;
  const enabled=(state.models||[]).filter(model=>model.enabled).length;
  const official=Number.isFinite(state.official_model_count)?state.official_model_count:0;
  const open=state.routing_mode==='project';
  const external=state.routing_mode==='external';
  const switchable=['project','openai','external'].includes(state.routing_mode);
  const headline=!switchable?'当前 Codex 配置无法切换接入'
    :open?(enabled?'Codex 可使用 '+enabled+' 个第三方模型':'接入已开启，但还没有启用第三方模型')
    :external?(state.routing_interrupted?'接管已中断 · 当前使用第三方直连配置':'当前使用第三方直连配置')
    :(official?'Codex 正在使用 '+official+' 个官方模型':'Codex 正在使用官方模型');
  let note;
  if(state.source_error)note='配置来源需要检查：'+state.source_error;
  else if(state.catalog_pending)note='模型列表有变更，保存模型设置后请重启 Codex。';
  else if(external&&state.routing_interrupted)note='Codex 配置已在接管期间变化，请确认后重新开启接入。';
  else if(!enabled)note='先添加模型，再开启接入。';
  else note=open?'在 Codex 中选择第三方模型即可使用。':
    external?'开启后，Codex 可调用当前第三方直连配置和已添加的其他厂商模型。':
    '开启后，Codex 可调用你配置的第三方模型。';
  // role="status" regions re-announce on every write, so only change real text.
  const write=(id,text)=>{const node=$(id);if(node&&node.textContent!==text)node.textContent=text;};
  write('access-headline',headline);
  write('access-note',note);
}
let refreshing=false;
function renderSyncStatus(){
  const time=state?.last_synced_at?new Date(state.last_synced_at*1000).toLocaleTimeString():null;
  $('sync-status').textContent=state?.mode==='cc_switch'?
    (state.sync_mode==='watch'?'正在监听配置变化':'每 30 秒检查更新')+
    (time?' · 上次同步 '+time:' · 等待首次同步'):'';
}
async function refresh(automatic=false){
  if(refreshing||(automatic&&(testingConnections||routingSaving||sourceSaving||document.querySelector('dialog[open]'))))return;
  refreshing=true;
  try{
    const next=await api('state');
    if(window.hybridDesktop){
      $('desktop-setup').hidden=next.configured!==false;
      document.body.classList.toggle('desktop-unconfigured',next.configured===false);
      if(next.configured===false){state=undefined;$('access-note').textContent='请先初始化管理配置';return;}
    }
    const changed=state&&JSON.stringify(state.sync_revision)!==JSON.stringify(next.sync_revision);
    if(automatic&&document.querySelector('#providers input:focus,#providers textarea:focus,#providers .help-trigger:focus,#providers select:focus'))return;
    if(automatic&&state&&JSON.stringify(state)===JSON.stringify(next)){
      return;
    }
    const firstDesktopState=window.hybridDesktop&&!state;
    state=next;renderRouting();renderAccessSummary();
    if(automatic&&changed)message('CC Switch 配置已更新；后续调用使用最新配置。');
    for(const mode of ['independent','cc_switch']){
      $(mode).classList.toggle('active',mode===state.mode);$(mode).setAttribute('aria-pressed',String(mode===state.mode));
    }
    $('model-count').textContent=state.models.filter(model=>model.enabled).length+' 个模型';
    if(typeof renderModelList==='function')renderModelList();
    $('cc-path').hidden=state.mode!=='cc_switch';
    if(document.activeElement!==$('db-path'))$('db-path').value=state.cc_db_path;
    $('add-provider').hidden=state.mode!=='independent';
    $('source-note').textContent=state.mode==='independent'?'独立管理':'CC Switch · 只读同步';
    const drafts=dirtyCards();$('providers').replaceChildren();
    if(state.mode==='independent'){
      for(const [id,spec]of Object.entries(state.config.providers)){
        const draft=drafts.find(card=>card.dataset.providerId===id);$('providers').append(draft||providerCard(id,spec));
      }
      for(const draft of drafts)if(!draft.isConnected)$('providers').prepend(draft);
    }else{
      for(const entry of state.inventory)$('providers').append(ccCard(entry));
    }
    if(!$('providers').children.length)$('providers').append(el('p',state.mode==='cc_switch'?'CC Switch 中暂无可读取的第三方 OpenAI 配置。':'尚无厂商，请添加厂商和模型。','hint'));
    if(state.source_error)message('配置来源提示：'+state.source_error,true);
    updateUnsaved();applyFilters();
    $('catalog-status').textContent=state.catalog_pending?'模型列表有变更 · 保存模型设置后请重启 Codex':'客户端模型列表已更新';
    renderSyncStatus();
    if(firstDesktopState)window.dispatchEvent(new Event('hybrid-management-ready'));
    for(const mode of ['project','openai']){$('desktop-'+mode).value=state.desktop_preferences?.[mode]||'ask';syncDesktopSelect($('desktop-'+mode));}
  }catch(error){
    if(window.hybridDesktop&&!state)$('access-note').textContent='配置读取失败：'+errorMessage(error)+' 可点击刷新重试。';
    throw error;
  }finally{refreshing=false;}
}
for(const mode of ['independent','cc_switch'])$(mode).onclick=()=>changeSource(mode);
const {renderRouting,routingEnabled,refreshRoutingProgress,switchRouting,renderForwarding,
  renderGatewayActivity,renderClientProcesses,refreshClientProcesses,initRoutingControls}=createRoutingControls({
  getState:()=>state,isSaving:()=>routingSaving,setSaving:value=>{routingSaving=value;},
  $,el,api,action,refresh,message,errorMessage,syncDesktopSelect
});
initRoutingControls();
$('save-path').onclick=()=>changeSource('cc_switch',$('db-path').value);
$('refresh').onclick=()=>action(async()=>{if(!discardDrafts())return;message('');await refresh();});
$('add-provider').onclick=()=>{const card=providerCard('');$('providers').prepend(card);markDirty(card);$('model-search').value='';$('model-filter').value='all';applyFilters();card.querySelector('input').focus();};
action(refresh);

let syncTicks=0;
setInterval(()=>{
  syncTicks++;
  if(document.hidden)return;
  if(routingSaving)action(refreshRoutingProgress);
  else if(state?.mode==='cc_switch'||syncTicks%5===0)action(()=>refresh(true));
},1000);

initHelp();
initDesktopSelects();

// URL fragments keep each settings page directly linkable and survive refresh.
function renderManagementPage(focusHeading=false){
  const pages={
    access:['接入与运行','配置 Codex 接入方式，查看客户端状态与启动偏好。'],
    models:['模型管理','选择要在 Codex 中使用的模型，连接与兼容设置集中管理。'],
    usage:['用量统计','查看模型调用趋势、Token 消耗与缓存命中情况。'],
    diagnostics:['运行与诊断','查看服务状态、请求错误与诊断信息。']
  };
  const requested=window.location.hash.slice(1);
  const current=Object.hasOwn(pages,requested)?requested:'access';
  for(const key of Object.keys(pages))$('page-'+key).hidden=key!==current;
  for(const link of document.querySelectorAll('.page-nav a')){
    if(link.dataset.page===current)link.setAttribute('aria-current','page');
    else link.removeAttribute('aria-current');
  }
  $('page-title').textContent=pages[current][0];
  $('page-intro').textContent=pages[current][1];
  document.title='Codex Hybrid · '+pages[current][0];
  if(focusHeading)$('page-title').focus();
}
window.addEventListener('hashchange',()=>{closeHelp();renderManagementPage(true);});
renderManagementPage();
