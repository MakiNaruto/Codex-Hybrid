'use strict';
const token = location.hash.slice(1) || sessionStorage.getItem('connectedNativeManagementToken') || '';
if (token) sessionStorage.setItem('connectedNativeManagementToken', token);
history.replaceState(null, '', location.pathname);
let state;
let routingSaving=false;
let routingError='';
const $ = id => document.getElementById(id);
function el(tag, text, cls) { const node=document.createElement(tag); if(text!==undefined)node.textContent=text; if(cls)node.className=cls; return node; }
async function copyText(value){
  try{
    await navigator.clipboard.writeText(value);
    message('已复制到剪贴板。');return;
  }catch(error){/* Some browsers deny or do not expose the Clipboard API. */}
  const previousFocus=document.activeElement;
  const input=el('textarea');input.value=value;input.readOnly=true;input.className='clipboard-fallback';
  document.body.append(input);
  let copied=false;
  try{
    input.focus();input.select();input.setSelectionRange(0,input.value.length);
    copied=document.execCommand('copy');
  }catch(error){/* Offer manual copying if the compatibility path is also blocked. */}
  finally{input.remove();previousFocus?.focus({preventScroll:true});}
  if(copied)message('已复制到剪贴板。');
  else{
    message('无法自动复制，请在弹出的文本框中手动复制模型 key。',true);
    window.prompt('请复制模型 key（Ctrl+C / ⌘C）：',value);
  }
}
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
function errorMessage(error){const common={OPERATION_TIMEOUT:'操作等待超时，结果尚未确认。请刷新状态后检查，不要连续重复提交。',SERVICE_UNREACHABLE:'无法连接本地服务，请确认服务已启动后重试。',INVALID_SERVICE_RESPONSE:'服务返回了无法读取的响应，请刷新页面或检查服务日志。',CLIENT_RELOAD_STATE_CHANGED:'配置已更新，请刷新后重新确认手动重启。',CONCURRENCY_LIMIT:'当前请求数已达上限，请等待现有请求结束后重试。',CREDENTIALS_NOT_FOUND:'未找到 API Key，请填写并保存，或检查凭据环境变量。',CONFIG_INVALID_IDENTIFIER:'厂商标识和模型别名仅支持字母、数字、点、下划线和连字符，且须以字母或数字开头。',CONFIG_INVALID_BASE_URL:'API 地址需要有效的 HTTPS 基础地址，不要填写 /chat/completions 或 /responses。',CONFIG_INVALID_LIMIT:'上下文、输出上限或超时时间须为支持范围内的正整数。',CONFIG_RESERVED_PARAMETER:'高级参数包含模型、消息、认证或输出预算等保留字段，请使用对应表单设置。',CONFIG_INVALID_PARAMETERS:'高级参数必须是 JSON 对象。',CONFIG_MISSING_FIELD:'配置缺少必要字段，请检查厂商与模型信息。',UPSTREAM_STREAM_ENDED_EARLY:'上游连接已结束，但没有收到完成信号。请检查协议及模型是否匹配。',UPSTREAM_OUTPUT_BUDGET_EXHAUSTED:'连接测试达到输出预算，尚未完整完成，请检查模型输出设置。',UPSTREAM_INCOMPLETE:'上游返回未完成响应，请检查服务状态。'};if(common[error.message])return common[error.message];if(error instanceof SyntaxError)return '高级参数 JSON 格式有误，请检查逗号、引号和括号。';const routingErrors={SESSION_MIGRATION_PROCESS_CHECK_FAILED:'无法读取 Codex 进程状态。开启或关闭接入时可重新预览并确认影响后继续；恢复备份前请检查系统权限。',SESSION_MIGRATION_CODEX_RUNNING:'检测到相关 Codex 进程。开启或关闭接入时可重新预览并确认影响后继续；CLI 迁移前请先退出 Codex。',SESSION_MIGRATION_CHANGED:'会话在预览后发生变化，请重新预览并重试。',SESSION_INDEX_CODEX_UNAVAILABLE:'未找到可用的 Codex 程序，无法补齐会话索引。请安装 Codex，或在实例设置中指定 codex_executable。',SESSION_INDEX_REPAIR_FAILED:'Codex 无法补齐会话索引，接入配置尚未切换。请检查 Codex 版本和本地数据后重试。',SESSION_INDEX_REPAIR_INCOMPLETE:'Codex 尚未补齐全部会话索引，接入配置尚未切换。请检查会话是否能在 Codex 中读取。',SESSION_MODEL_LIST_EMPTY:'缺少可用的官方模型列表，无法替换第三方会话模型。请先更新模型列表。',SESSION_MIGRATION_RECOVERY_REQUIRED:'发现中断的会话迁移，请按使用文档恢复备份后重试。',CLIENT_CONFIG_CHANGED:'Codex 配置在预览后发生变化，或接入字段已被外部修改。未应用切换，请刷新并检查配置后重试。',CLIENT_BASELINE_UNAVAILABLE:'缺少可信的接入前配置备份，已停止自动恢复。请检查本地备份后修复。',CLIENT_CONFIG_REWRITE_UNSAFE:'无法安全修改 Codex 配置，已停止切换。请检查配置格式。',CLIENT_ROUTING_UNAVAILABLE:'当前 Codex 配置无法切换，请检查配置文件、厂商和 profile。',CLIENT_ROUTING_ALREADY_SET:'配置已处于目标状态，请刷新查看。'};if(routingErrors[error.message])return routingErrors[error.message];if(error.message==='LOCAL_AUTH_REQUIRED')return '已开启私密链接访问，请运行 codex-hybrid manage-url 获取管理链接。';if(error.message==='UPSTREAM_HTTP_401'){const source=state?.mode==='cc_switch'?'CC Switch':'独立管理';const next=state?.mode==='cc_switch'?'请在 CC Switch 更新该厂商的 API Key，然后重试。':'请在厂商配置中更新 API Key 并保存，然后重试。';return '厂商认证失败（401）。当前凭据来源：'+source+'。'+next+'无需重启网关，不会回退到其他 Key。';}return '操作未完成：'+error.message;}
async function action(fn){try{await fn();}catch(error){message(errorMessage(error),true);}}
function button(text,fn,cls='secondary'){const b=el('button',text,cls);b.type='button';b.onclick=()=>action(async()=>{b.disabled=true;try{await fn();}finally{b.disabled=false;}});return b;}
let fieldId=0;
function help(text, title='查看说明'){
  const trigger=el('button','?','help-trigger');
  trigger.type='button';trigger.dataset.help=text;trigger.setAttribute('aria-label',title);
  trigger.setAttribute('aria-expanded','false');return trigger;
}
function field(title,value='',type='text',description=''){
  const wrapper=el('div',undefined,'form-field');
  const caption=el('div',undefined,'field-caption');
  const label=el('label',title),input=el('input');
  input.id='field-'+(++fieldId);label.htmlFor=input.id;input.type=type;
  if(type==='checkbox')input.checked=value;else input.value=value;
  if(type==='checkbox'){label.className='check';label.append(input);wrapper.append(label);}
  else{caption.append(label);if(description)caption.append(help(description,title+'说明'));wrapper.append(caption,input);}
  return {label:wrapper,input};
}
const connectionResults=new Map();
let testingConnections=0;
function testButton(model){
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
  b.disabled=!model?.enabled;b.title=b.disabled?'请先保存并启用厂商及模型':'测试已保存的模型配置';
  group.append(b,result);return group;
}
function modelEditor(alias,model={},cc=false,savedModel){
  const row=el('div',undefined,'model-editor');
  const head=el('div',undefined,'model-card-head');
  const heading=el('strong',model.display_name||alias||'新模型');
  const enabled=field('启用',model.enabled!==false,'checkbox');head.append(heading,enabled.label);
  const fields=el('div',undefined,'model-fields');
  const a=field('模型别名',alias,'text','用于区分本厂商下的模型，不能重复。'),
    id=field('模型 ID',model.model_id||'','text',cc?'留空时跟随 CC Switch 的配置。':'填写厂商提供的准确模型 ID，例如 glm-5.3-flash。'),
    name=field('显示名称',model.display_name||'','text','在客户端模型列表中显示的名称。留空时使用模型别名。'),
    windowSize=field('上下文窗口',model.context_window??131072,'number','单位为 tokens。留空使用 131,072，应与厂商模型支持的窗口大小一致。'),
    limit=field('输出上限',model.max_output_tokens??'','number','单位为 tokens。留空不设上限，实际输出仍受厂商限制。');
  id.label.classList.add('wide-field');
  windowSize.input.min='1';windowSize.input.max='16777216';windowSize.input.step='1';
  limit.input.min='1';limit.input.max='1048576';limit.input.step='1';
  for(const f of [id,a,name,windowSize,limit])fields.append(f.label);
  const actions=el('div',undefined,'model-actions');
  actions.append(testButton(savedModel),button('移除',()=>{markDirty(row.closest('.card'));row.remove();applyFilters();},'text-danger'));
  row.append(head,fields,actions);
  name.input.addEventListener('input',()=>{heading.textContent=name.input.value||a.input.value||'新模型';});
  row.value=()=>{
    const output=limit.input.value.trim();
    const m={...model,model_id:id.input.value.trim()||null,display_name:name.input.value.trim()||a.input.value.trim(),max_output_tokens:output===''?null:Number(output),context_window:windowSize.input.value.trim()===''?131072:Number(windowSize.input.value),enabled:enabled.input.checked};
    if(!cc&&!m.model_id)throw Error('请填写模型 ID');
    if(!Number.isInteger(m.context_window)||m.context_window<1||m.context_window>16777216)throw Error('上下文窗口应为 1–16777216 的整数');
    if(m.max_output_tokens!==null&&(!Number.isInteger(m.max_output_tokens)||m.max_output_tokens<1||m.max_output_tokens>1048576))throw Error('输出上限应为 1–1048576 的整数');
    return [a.input.value.trim(),m];
  };row.alias=()=>a.input.value.trim();return row;
}
function collect(container){const result={};for(const row of container.children){const [alias,model]=row.value();if(Object.hasOwn(result,alias))throw Error('模型别名重复');result[alias]=model;}return result;}
function providerLayout(name,description){
  const card=el('article',undefined,'card provider-layout');
  const sidebar=el('div',undefined,'provider-sidebar');
  const heading=el('div',undefined,'provider-heading');
  heading.append(el('span',(name||'新').slice(0,1).toUpperCase(),'provider-avatar'));
  const title=el('div');title.append(el('h3',name||'新厂商'),el('p',description,'hint'));heading.append(title);
  sidebar.append(heading);
  const content=el('div',undefined,'provider-content');
  const head=el('div',undefined,'models-heading');head.append(el('h4','所属模型'));
  const tip=help('测试连接会使用已保存并启用的配置，向厂商发送一次真实请求并消耗少量额度。新增或修改模型后，请先保存厂商。','测试连接说明');
  const tools=el('div',undefined,'models-tools');tools.append(tip);head.append(tools);
  const rows=el('div',undefined,'models-grid');content.append(head,rows);card.append(sidebar,content);
  return {card,sidebar,content,rows,tools};
}
function providerCard(id,original={}){
  const {card,sidebar,content,rows,tools}=providerLayout(id,'连接与访问凭据');
  card.dataset.providerId=id;
  card.addEventListener('input',()=>markDirty(card));card.addEventListener('change',()=>markDirty(card));
  const fields=el('div',undefined,'fields');
  const pid=field('厂商标识',id,'text','厂商的唯一标识，保存后不可修改。'),
    base=field('API 地址',original.base_url||'','text','填写厂商的 API 基础地址，通常以 /v1 结尾；无需填写具体的聊天请求路径。'),
    key=field('API Key','','password','留空保留现有凭据。已有 Key 不会回显；新填入的 Key 在保存后生效。'),
    active=field('启用厂商',original.enabled!==false,'checkbox');
  pid.input.readOnly=!!id;key.input.autocomplete='new-password';
  if(id)sidebar.append(el('p',state.credential_status?.[id]==='available'?'已找到本地凭据 · 不代表连接已验证':'未找到可读取的凭据，请检查 Key 或环境变量','hint'));
  key.input.placeholder=original.credentials?'已配置 · 留空保留':'输入 API Key';
  const plabel=el('div',undefined,'form-field'),caption=el('div',undefined,'field-caption'),label=el('label','接口协议'),protocol=el('select');
  protocol.id='field-'+(++fieldId);label.htmlFor=protocol.id;
  caption.append(label,help('按厂商支持的接口选择 Chat Completions 或 Responses。','接口协议说明'));
  for(const [value,name]of[['openai_chat_completions','Chat Completions'],['openai_responses','Responses']]){const option=el('option',name);option.value=value;protocol.append(option);}
  protocol.value=original.protocol||'openai_chat_completions';plabel.append(caption,protocol);
  for(const f of [pid,base])fields.append(f.label);fields.append(plabel,key.label,active.label);sidebar.append(fields);
  for(const [alias,m]of Object.entries(original.models||{default:{model_id:'',enabled:true}}))rows.append(modelEditor(alias,m,false,state.models.find(model=>model.key===id+'/'+alias)));
  tools.append(button('＋ 添加模型',()=>{let index=1;while([...rows.children].some(row=>row.alias()==='model'+index))index++;const row=modelEditor('model'+index);rows.append(row);markDirty(card);row.querySelector('input:not([type=checkbox])').focus();}));
  const advanced=el('details');advanced.append(el('summary','高级参数'));
  const params=el('textarea');params.value=JSON.stringify(original.parameters||{},null,2);params.setAttribute('aria-label','厂商参数 JSON');
  const tokenField=el('select');tokenField.setAttribute('aria-label','输出预算字段');
  for(const t of ['max_tokens','max_completion_tokens']){const o=el('option',t);o.value=t;tokenField.append(o);}tokenField.value=original.token_limit_field||'max_tokens';
  const timeout=field('请求超时（秒）',original.timeout_seconds??180,'number','范围为 1–3600 秒，影响第三方模型请求；连接测试固定使用 60 秒。');
  timeout.input.min='1';timeout.input.max='3600';timeout.input.step='1';
  advanced.append(timeout.label,el('p','厂商参数（JSON）'),params,el('p','Chat Completions 输出预算字段'),tokenField,el('p','Responses 使用 max_output_tokens。','hint'));sidebar.append(advanced);
  const actions=el('div',undefined,'actions');
  actions.append(button('保存厂商',async()=>{
    if(!id&&Object.hasOwn(state.config.providers,pid.input.value.trim()))throw Error('厂商标识已存在，请使用其他标识，或直接编辑已有厂商。');
    const spec={...original,base_url:base.input.value.trim(),protocol:protocol.value,enabled:active.input.checked,models:collect(rows),parameters:JSON.parse(params.value),token_limit_field:tokenField.value,timeout_seconds:Number(timeout.input.value)};
    card.inert=true;
    try{await api('provider',{id:pid.input.value.trim(),spec,api_key:key.input.value||undefined});key.input.value='';clearDirty(card);connectionResults.clear();await refresh();message('厂商与模型已保存。Key / API 下一轮生效；模型列表变动请重启客户端。');}
    finally{card.inert=false;}
  },''));
  if(id)actions.append(button('删除厂商',async()=>{if(!confirm('删除此厂商及本工具中的模型配置？'))return;await api('provider',{id,delete:true});clearDirty(card);await refresh();},'text-danger'));
  const foot=el('div',undefined,'provider-footer');foot.append(el('span','修改后保存此厂商及其全部模型','hint'),actions);content.append(foot);
  return card;
}
function ccCard(entry){
  const {card,sidebar,rows}=providerLayout(entry.name,'同步自 CC Switch');
  card.dataset.providerId=entry.provider_key;
  const badges=el('div',undefined,'provider-badges');badges.append(el('span',entry.protocol==='openai_responses'?'Responses':'Chat Completions','badge'),el('span','只读','badge'));sidebar.append(badges);
  const address=el('div',undefined,'provider-address');address.append(el('span','API 地址','hint'),el('p',entry.base_url));sidebar.append(address);
  const note=el('div',undefined,'readonly-note');note.append(el('span','在 CC Switch 中编辑'),help('仅同步 OpenAI / Codex 第三方配置，不回写数据库、不切换其他工具的当前厂商。每轮调用读取最新 Key。','CC Switch 同步说明'));sidebar.append(note);
  for(const model of entry.models){
    const item=el('div',undefined,'cc-model');
    item.append(el('strong',model.display_name),el('code',model.model_id));
    const stats=el('div',undefined,'model-stats');
    for(const [title,value,description]of[
      ['上下文窗口',model.context_window?model.context_window.toLocaleString():'131,072',model.context_window?'单位为 tokens。':'CC Switch 未配置，使用默认 131,072 tokens。'],
      ['输出上限',model.max_output_tokens?model.max_output_tokens.toLocaleString():'不设上限',model.max_output_tokens?'单位为 tokens。':'CC Switch 未配置，实际输出受厂商限制。']
    ]){const stat=el('div'),caption=el('div',undefined,'field-caption');caption.append(el('span',title),help(description,title+'说明'));stat.append(caption,el('span',value,'stat-value'));stats.append(stat);}
    item.append(stats,testButton(state.models.find(saved=>saved.provider===entry.provider_key&&saved.model_id===model.model_id)));rows.append(item);
  }
  if(!entry.models.length)rows.append(el('p','暂无可同步的模型','hint'));return card;
}
function dirtyCards(){return [...$('providers').children].filter(card=>card.dataset.dirty==='true');}
function updateUnsaved(){
  const count=dirtyCards().length;
  $('unsaved-status').textContent=count?'有 '+count+' 个厂商尚未保存，刷新或离开前请保存':'';
}
function markDirty(card){
  if(!card)return;card.dataset.dirty='true';
  if(!card.querySelector('.dirty-badge'))card.querySelector('.provider-heading').append(el('span','未保存','dirty-badge'));
  updateUnsaved();
}
function clearDirty(card){card.dataset.dirty='false';card.querySelector('.dirty-badge')?.remove();updateUnsaved();}
function discardDrafts(){
  if(dirtyCards().length&&!confirm('有尚未保存的厂商修改，确定放弃这些修改并重新读取？'))return false;
  for(const card of dirtyCards())clearDirty(card);return true;
}
window.addEventListener('beforeunload',event=>{if(dirtyCards().length){event.preventDefault();event.returnValue='';}});
function applyFilters(){
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
function renderReadiness(){
  if(!state)return;
  const enabled=state.models.filter(model=>model.enabled),missing=enabled.filter(model=>state.credential_status?.[model.provider]!=='available');
  $('readiness-summary').textContent=state.source_error?'配置来源需要检查':enabled.length?enabled.length+' 个已启用模型 · '+state.official_model_count+' 个官方模型':'可先浏览管理页，稍后添加模型';
  const steps=$('readiness-steps');steps.replaceChildren();
  for(const [title,text] of [
    ['1 · 配置模型',state.source_error?'来源无法读取，请检查来源配置':enabled.length?(missing.length?'有 '+missing.length+' 个模型未找到可用凭据':'模型和凭据已就绪，可点击测试连接'):'添加厂商与模型，或选择 CC Switch 来源'],
    ['2 · Codex 接入',state.routing_mode==='project'?'接入配置已开启':state.routing_mode==='openai'?'准备好后开启下方 Codex 接入':'Codex 配置暂时无法切换'],
    ['3 · 重启并验证',state.catalog_pending?'模型目录有变更，请先更新客户端模型列表':state.reload?.required?'请手动完全退出并重新打开 Codex':state.routing_mode==='project'?'在 Codex 选择第三方模型，发送一条测试消息':'接入后重启 Codex，再选择模型验证']]){
    const item=el('li');item.append(el('strong',title),document.createTextNode(text));steps.append(item);
  }
  $('reload-notice').hidden=!state.reload?.required;
  $('reload-message').textContent='配置已更新，请重启需要使用新配置的 Codex。';
  $('acknowledge-reload').disabled=!!state.catalog_pending;
}
$('acknowledge-reload').onclick=()=>action(async()=>{
  if(!state?.reload?.revision)return;
  $('acknowledge-reload').disabled=true;
  try{const result=await api('reload/acknowledge',{revision:state.reload.revision});state.reload=result.reload;renderReadiness();renderRouting();message('已记录手动重启确认，请在 Codex 中验证模型。');}
  finally{$('acknowledge-reload').disabled=!!state?.catalog_pending;}
});
let refreshing=false;
function renderSyncStatus(){
  const time=state?.last_synced_at?new Date(state.last_synced_at*1000).toLocaleTimeString():null;
  $('sync-status').textContent=state?.mode==='cc_switch'?
    (state.sync_mode==='watch'?'正在监听配置变化':'每 30 秒检查更新')+
    (time?' · 上次同步 '+time:' · 等待首次同步'):'';
}
async function refresh(automatic=false){
  if(refreshing||(automatic&&(testingConnections||routingSaving||sourceSaving)))return;
  refreshing=true;
  try{
    const next=await api('state');
    const changed=state&&JSON.stringify(state.sync_revision)!==JSON.stringify(next.sync_revision);
    if(automatic&&document.querySelector('#providers input:focus,#providers textarea:focus,#providers .help-trigger:focus,#providers select:focus'))return;
    if(automatic&&state&&JSON.stringify(state)===JSON.stringify(next)){
      return;
    }
    state=next;renderRouting();renderReadiness();
    if(automatic&&changed)message('CC Switch 配置已更新；后续调用使用最新配置。');
    for(const mode of ['independent','cc_switch']){
      $(mode).classList.toggle('active',mode===state.mode);$(mode).setAttribute('aria-pressed',String(mode===state.mode));
    }
    $('model-count').textContent=state.models.length+' 个模型';
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
    $('catalog-status').textContent=state.catalog_pending?'模型列表有变更 · 更新列表后请重启客户端':'客户端模型列表已更新';
    renderSyncStatus();
  }finally{refreshing=false;}
}
for(const mode of ['independent','cc_switch'])$(mode).onclick=()=>changeSource(mode);
function renderRouting(){
  const toggle=$('routing-toggle');
  toggle.setAttribute('aria-checked',String(state?.routing_mode==='project'));
  toggle.disabled=routingSaving||!['project','openai'].includes(state?.routing_mode);
  toggle.setAttribute('aria-busy',String(routingSaving));
  $('routing-status').textContent=routingSaving?'正在准备或切换…':routingError||(
    state?.routing_mode==='project'?'已开启':state?.routing_mode==='openai'?'已关闭 · 使用原生路由':'无法切换：请检查 Codex 配置');
}
function confirmRouting(mode,preview){
  const dialog=$('routing-dialog'),verb=mode==='project'?'开启':'关闭';
  $('routing-dialog-title').textContent=verb+' Codex 接入？';
  $('routing-dialog-description').textContent=(mode==='project'?'将启用混合路由':'将恢复接入前的路由配置')+'，并备份、更新本地会话索引，保留历史内容和配置中的模型。';
  renderClientProcesses(preview.codex_process);
  renderGatewayActivity(preview.activity);
  const warnings=(preview.warnings||[]).map(warning=>warning.message+'（'+warning.code+'）');
  $('routing-dialog-warning').hidden=!warnings.length;
  $('routing-dialog-warning').textContent=warnings.join(' ');
  $('routing-dialog-details').textContent=[...(preview.changes||[]),mode==='openai'?'关闭后请选择官方模型。':''].filter(Boolean).join('\n\n');
  dialog.querySelector('details').open=false;
  $('routing-dialog-confirm').textContent='确认'+verb;
  dialog.returnValue='cancel';
  return new Promise(resolve=>{
    dialog.addEventListener('close',()=>resolve(dialog.returnValue==='confirm'),{once:true});
    dialog.showModal();
  });
}
$('routing-toggle').onclick=async()=>{
  if(routingSaving)return;
  const mode=state.routing_mode==='project'?'openai':'project';
  routingSaving=true;routingError='';renderRouting();
  try{
    const preview=await api('routing/preview',{mode});
    if(!await confirmRouting(mode,preview))return;
    const saved=await api('routing',{mode,revision:preview.revision,confirm_activity:true});
    state.routing_mode=saved.routing_mode;
    const warnings=saved.warnings||[];
    message((warnings.length?'接入配置已切换。'+warnings.map(warning=>warning.message+'（'+warning.code+'）').join(' ')+' 日志：'+(saved.warning_log||'日志写入失败，请保留此提示。'):'接入配置和会话索引已迁移，可以重新打开 Codex。')+' 备份：'+(saved.session_backup||'无需迁移'),warnings.length>0);
  }catch(error){
    routingError=errorMessage(error);message(routingError,true);
  }finally{
    try{await refresh();}catch(error){routingError=errorMessage(error);message(routingError,true);}
    routingSaving=false;renderRouting();
  }
};
$('save-path').onclick=()=>changeSource('cc_switch',$('db-path').value);
$('publish').onclick=()=>action(async()=>{await api('publish',{});await refresh();message('客户端模型列表已更新，请重启客户端加载最新列表。');});
$('refresh').onclick=()=>action(async()=>{if(!discardDrafts())return;message('');await refresh();});
$('add-provider').onclick=()=>{const card=providerCard('');$('providers').prepend(card);markDirty(card);$('model-search').value='';$('model-filter').value='all';applyFilters();card.querySelector('input').focus();};
action(refresh);

let syncTicks=0;
setInterval(()=>{syncTicks++;if(!document.hidden&&(state?.mode==='cc_switch'||syncTicks%5===0))action(()=>refresh(true));},1000);

function renderGatewayActivity(activity){
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
  }finally{processesRefreshing=false;trigger.disabled=false;trigger.textContent='检测状态';trigger.removeAttribute('aria-busy');}
}
$('detect-processes').onclick=refreshClientProcesses;

const diagnosticStatuses={rejected:'请求未完成',incompatible_request_or_stream:'请求或流处理异常',
  upstream_connection_failed:'上游连接失败',upstream_http_error:'上游返回错误',
  client_disconnected:'客户端连接中断',failed:'响应失败',incomplete:'响应未完成',
  stream_ended_without_completion:'流结束时缺少完成信号'};
function renderDiagnostics(report){
  const seconds=report.service.uptime_seconds;
  $('service-status').textContent='管理服务运行中'+(seconds===null?'':' · 已运行 '+Math.floor(seconds/60)+' 分钟')+
    ' · 读取时间：'+new Date(report.generated_at*1000).toLocaleTimeString();
  const list=$('diagnostic-errors');list.replaceChildren();
  for(const entry of report.log.errors){
    const when=entry.time===undefined?'时间未知':new Date(entry.time*1000).toLocaleString();
    list.append(el('li',when+' · '+(diagnosticStatuses[entry.status]||'未知错误')+
      (entry.http_status===undefined?'':' · HTTP '+entry.http_status)+
      (entry.elapsed_ms===undefined?'':' · '+entry.elapsed_ms+' ms')));
  }
  if(!list.children.length)list.append(el('li',report.log.state==='missing'?'尚无日志文件（前台运行时日志可能输出到终端）':
    report.log.state==='unavailable'?'日志暂时无法读取':'读取范围内没有错误摘要'));
}
async function loadDiagnostics(){
  try{const report=await api('diagnostics');renderDiagnostics(report);return report;}
  catch(error){$('service-status').textContent='诊断读取失败，之前的结果已失效';$('diagnostic-errors').replaceChildren(el('li','无法读取'));throw error;}
}
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

const helpPanel=el('div',undefined,'help-panel');
helpPanel.id='help-panel';helpPanel.role='tooltip';helpPanel.hidden=true;document.body.append(helpPanel);
let activeHelp=null,helpPinned=false,helpTimer;
function closeHelp(){
  clearTimeout(helpTimer);
  if(activeHelp){activeHelp.removeAttribute('aria-describedby');activeHelp.setAttribute('aria-expanded','false');}
  activeHelp=null;helpPinned=false;helpPanel.hidden=true;
}
function positionHelp(){
  if(!activeHelp?.isConnected){closeHelp();return;}
  const rect=activeHelp.getBoundingClientRect(),box=helpPanel.getBoundingClientRect();
  const left=Math.max(12,Math.min(rect.left+rect.width/2-box.width/2,innerWidth-box.width-12));
  const below=rect.bottom+9;
  helpPanel.style.left=left+'px';helpPanel.style.top=Math.max(12,below+box.height<innerHeight-12?below:rect.top-box.height-9)+'px';
}
function openHelp(trigger){
  clearTimeout(helpTimer);
  if(activeHelp!==trigger){closeHelp();activeHelp=trigger;}
  trigger.setAttribute('aria-describedby',helpPanel.id);trigger.setAttribute('aria-expanded','true');
  helpPanel.textContent=trigger.dataset.help;helpPanel.hidden=false;positionHelp();
}
function delayCloseHelp(){if(!helpPinned)helpTimer=setTimeout(closeHelp,180);}
 document.addEventListener('pointerover',event=>{const trigger=event.target.closest('.help-trigger');if(trigger&&(!helpPinned||trigger===activeHelp))openHelp(trigger);});
 document.addEventListener('pointerout',event=>{if(event.target.closest('.help-trigger')&&!event.relatedTarget?.closest('.help-trigger'))delayCloseHelp();});
 document.addEventListener('focusin',event=>{const trigger=event.target.closest('.help-trigger');if(trigger)openHelp(trigger);else if(!helpPinned)closeHelp();});
 document.addEventListener('focusout',event=>{if(event.target.closest('.help-trigger'))delayCloseHelp();});
 document.addEventListener('click',event=>{
   const trigger=event.target.closest('.help-trigger');
   if(trigger){event.preventDefault();if(activeHelp===trigger&&helpPinned)closeHelp();else{openHelp(trigger);helpPinned=true;}}
   else if(!helpPanel.contains(event.target))closeHelp();
 });
 document.addEventListener('keydown',event=>{if(event.key==='Escape')closeHelp();});
 helpPanel.addEventListener('pointerenter',()=>clearTimeout(helpTimer));helpPanel.addEventListener('pointerleave',delayCloseHelp);
 window.addEventListener('resize',()=>{if(activeHelp)positionHelp();});
 window.addEventListener('scroll',()=>{if(activeHelp)positionHelp();},true);
