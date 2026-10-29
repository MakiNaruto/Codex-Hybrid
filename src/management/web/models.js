'use strict';
// Membership and per-model settings are persisted by Hybrid, never by CC Switch.
let modelDialogSource;
let detailModel;
let modelSaving=false;
function modelName(model){
  return state.mode==='cc_switch'?(state.inventory.find(entry=>entry.provider_key===model.provider)?.models.find(entry=>entry.model_id===model.model_id)?.display_name||model.model_id):model.display_name;
}
function providerName(model){return state.inventory.find(entry=>entry.provider_key===model.provider)?.name||model.provider;}
function matchesModel(model,query){return [modelName(model),providerName(model),model.model_id].join(' ').toLowerCase().includes(query.toLowerCase());}
function modelIdentity(model){
  const identity=el('div',undefined,'model-list-identity');
  const avatar=el('span',providerName(model).slice(0,1).toUpperCase(),'model-list-avatar');avatar.setAttribute('aria-hidden','true');
  const copy=el('div');copy.append(el('h3',modelName(model)),el('p',providerName(model)+' · '+model.model_id,'hint'));
  identity.append(avatar,copy);return identity;
}
function renderModelList(){
  const list=$('enabled-models');if(!list||!state)return;
  $('add-models').disabled=!state.source_id;
  if(!state.source_id){
    list.replaceChildren(el('p','请重启 Hybrid 服务以加载新版模型管理。现有模型配置保持不变。','model-list-empty hint'));
    return;
  }
  const query=$('model-search').value.trim();
  const models=state.models.filter(model=>model.enabled&&matchesModel(model,query));
  list.replaceChildren();
  for(const model of models){
    const row=el('div',undefined,'model-list-row');
    row.append(modelIdentity(model));
    const mode=model.protocol==='openai_responses'?(model.responses_compatibility==='portable'?'兼容模式':'原生模式'):'Chat 转换';
    row.append(el('span',mode,'model-list-mode'));
    const details=button('查看详情',()=>openModelDetail(model),'secondary model-list-details');
    details.setAttribute('aria-label',modelName(model)+'，查看详情');
    const actions=el('div',undefined,'model-list-actions');
    const remove=button('删除',()=>removeListedModel(model,remove,state.source_id),'secondary text-danger model-list-delete');
    remove.setAttribute('aria-label',modelName(model)+'，从列表删除');
    remove.title='从启用列表移除，可重新添加';
    actions.append(details,remove);row.append(actions);list.append(row);
  }
  if(!models.length){
    const empty=el('div',undefined,'model-list-empty');
    empty.append(el('h3',state.source_error?'暂时无法读取模型':query?'没有匹配的模型':'添加你的第一个模型'),
      el('p',state.source_error?'检查配置来源后刷新重试。':query?'试试其他模型名称、厂商或 ID。':'连接厂商后，选择要在 Codex 中使用的模型。','hint'));
    if(!query&&!state.source_error)empty.append(button('＋ 添加模型',openAddModels,''));
    list.append(empty);
  }
  $('search-empty').hidden=true;
}
async function removeListedModel(model,control,sourceId){
  if(modelSaving)return;
  modelSaving=true;control.disabled=true;control.textContent='删除中…';
  try{
    await api('models',{source_id:sourceId,updates:[{key:model.key,added:false}]});
    await refresh();message('模型已从列表移除。列表变化请重启客户端加载。');
  }catch(error){message(errorMessage(error),true);}
  finally{modelSaving=false;control.disabled=false;control.textContent='删除';}
}
function renderAvailableModels(){
  const container=$('available-models');
  for(const row of container.children){
    const model=state.models.find(model=>model.key===row.dataset.key);
    row.hidden=!!model&&!matchesModel(model,$('available-search').value.trim());
  }
  const rows=[...container.querySelectorAll('.available-model-row')];
  $('available-empty').hidden=!rows.length||rows.some(row=>!row.hidden);
  updateAddCount();
}
function updateAddCount(){
  const count=$('available-models').querySelectorAll('input:checked').length;
  $('confirm-add-models').disabled=!count||modelSaving;
  $('confirm-add-models').textContent=count?'添加 '+count+' 个模型':'添加所选模型';
}
function openAddModels(){
  if(!state)return;
  modelDialogSource=state.source_id;
  $('available-search').value='';$('add-models-error').textContent='';$('available-empty').hidden=true;
  const list=$('available-models');list.replaceChildren();
  for(const model of state.models.filter(model=>!model.enabled)){
    const row=el('label',undefined,'available-model-row');row.dataset.key=model.key;
    const check=el('input');check.type='checkbox';check.value=model.key;
    check.disabled=model.source_enabled===false;check.addEventListener('change',updateAddCount);
    row.append(check,modelIdentity(model));
    if(check.disabled)row.append(el('span','来源中已停用','hint'));
    list.append(row);
  }
  if(!list.children.length){
    const empty=el('div',undefined,'model-list-empty');empty.append(el('h3',state.models.length?'所有模型均已添加':'还没有可添加的模型'),el('p','前往“管理连接”添加厂商，或在 CC Switch 中配置模型。','hint'),button('管理连接',()=>{$('add-models-dialog').close();$('connections-dialog').showModal();}));list.append(empty);
  }
  updateAddCount();$('add-models-dialog').showModal();
}
function openModelDetail(model){
  detailModel=model;modelDialogSource=state.source_id;
  $('model-detail-title').textContent=modelName(model);$('model-detail-provider').textContent=providerName(model)+' · '+(state.mode==='cc_switch'?'CC Switch':'独立管理');
  const meta=$('model-detail-meta');meta.replaceChildren();
  for(const [label,value] of [['模型 ID',model.model_id],['上下文窗口',model.context_window.toLocaleString()+' tokens'],['输出上限',model.max_output_tokens?model.max_output_tokens.toLocaleString()+' tokens':'未设置']]){
    meta.append(el('dt',label),el('dd',value));
  }
  $('model-compatibility-setting').hidden=model.protocol!=='openai_responses';
  $('model-compatibility').setAttribute('aria-checked',String(model.responses_compatibility==='portable'));
  $('model-detail-protocol').textContent=model.protocol==='openai_responses'?'接口协议 · Responses':'接口协议 · Chat Completions（已通过格式转换接入）';
  $('model-detail-test').replaceChildren(testButton(model));$('model-detail-error').textContent='';
  $('save-model-detail').disabled=false;$('remove-model').disabled=false;
  $('model-detail-dialog').showModal();
}
async function persistModelUpdates(updates,dialog,errorId){
  if(modelSaving)return;
  modelSaving=true;dialog.setAttribute('aria-busy','true');
  const controls=[...dialog.querySelectorAll('button,input')];
  const previous=controls.map(control=>control.disabled);controls.forEach(control=>control.disabled=true);
  $(errorId).textContent='';
  try{
    await api('models',{source_id:modelDialogSource,updates});
    dialog.close();await refresh();message('模型设置已保存。列表变化请重启客户端加载。');
  }catch(error){$(errorId).textContent=errorMessage(error);}
  finally{modelSaving=false;dialog.removeAttribute('aria-busy');controls.forEach((control,i)=>control.disabled=previous[i]);updateAddCount();}
}
$('add-models').onclick=openAddModels;
$('available-search').addEventListener('input',renderAvailableModels);
$('confirm-add-models').onclick=()=>persistModelUpdates([...$('available-models').querySelectorAll('input:checked')].map(input=>({key:input.value,added:true})),$('add-models-dialog'),'add-models-error');
$('model-compatibility').onclick=()=>{
  const control=$('model-compatibility');control.setAttribute('aria-checked',String(control.getAttribute('aria-checked')!=='true'));
};
$('save-model-detail').onclick=()=>{
  const update={key:detailModel.key};
  if(detailModel.protocol==='openai_responses')update.responses_compatibility=$('model-compatibility').getAttribute('aria-checked')==='true'?'portable':'native';
  persistModelUpdates([update],$('model-detail-dialog'),'model-detail-error');
};
$('remove-model').onclick=()=>persistModelUpdates([{key:detailModel.key,added:false}],$('model-detail-dialog'),'model-detail-error');
$('manage-connections').onclick=()=>$('connections-dialog').showModal();
for(const [trigger,dialog] of [['close-add-models','add-models-dialog'],['cancel-add-models','add-models-dialog'],['close-model-detail','model-detail-dialog'],['close-connections','connections-dialog']]){
  $(trigger).onclick=()=>$(dialog).close();
}
for(const id of ['add-models-dialog','model-detail-dialog'])$(id).addEventListener('cancel',event=>{if(modelSaving)event.preventDefault();});
$('connections-dialog').addEventListener('cancel',event=>{if(!discardDrafts())event.preventDefault();});
$('close-connections').onclick=()=>{if(discardDrafts())$('connections-dialog').close();};
$('connections-dialog').addEventListener('close',()=>action(refresh));
if(state)renderModelList();
