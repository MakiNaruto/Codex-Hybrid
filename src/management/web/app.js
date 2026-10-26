'use strict';
const token = location.hash.slice(1) || sessionStorage.getItem('connectedNativeManagementToken') || '';
if (token) sessionStorage.setItem('connectedNativeManagementToken', token);
history.replaceState(null, '', location.pathname);
let state;
let routingSaving=false;
const $ = id => document.getElementById(id);
function el(tag, text, cls) { const node=document.createElement(tag); if(text!==undefined)node.textContent=text; if(cls)node.className=cls; return node; }
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
async function api(path,body){const response=await fetch('/manage/api/'+path,{method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw Error(data.code||'请求失败');return data;}
function errorMessage(error){if(error.message==='LOCAL_AUTH_REQUIRED')return '已开启私密链接访问，请运行 codex-hybrid manage-url 获取管理链接。';if(error.message==='UPSTREAM_HTTP_401'){const source=state?.mode==='cc_switch'?'CC Switch':'独立管理';const next=state?.mode==='cc_switch'?'请在 CC Switch 更新该厂商的 API Key，然后重试。':'请在厂商配置中更新 API Key 并保存，然后重试。';return '厂商认证失败（401）。当前凭据来源：'+source+'。'+next+'无需重启网关，不会回退到其他 Key。';}return '操作未完成：'+error.message;}
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
      const text='连接成功，已调用模型：'+(data.model_id||'未提供');
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
  for(const f of [id,a,name,windowSize,limit])fields.append(f.label);
  const actions=el('div',undefined,'model-actions');
  actions.append(testButton(savedModel),button('移除',()=>{row.remove();},'text-danger'));
  row.append(head,fields,actions);
  name.input.addEventListener('input',()=>{heading.textContent=name.input.value||a.input.value||'新模型';});
  row.value=()=>{
    const output=limit.input.value.trim();
    const m={...model,model_id:id.input.value.trim()||null,display_name:name.input.value.trim()||a.input.value.trim(),max_output_tokens:output===''?null:Number(output),context_window:Number(windowSize.input.value)||131072,enabled:enabled.input.checked};
    if(!cc&&!m.model_id)throw Error('请填写模型 ID');return [a.input.value.trim(),m];
  };return row;
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
  const fields=el('div',undefined,'fields');
  const pid=field('厂商标识',id,'text','厂商的唯一标识，保存后不可修改。'),
    base=field('API 地址',original.base_url||'','text','填写厂商的 API 基础地址，通常以 /v1 结尾；无需填写具体的聊天请求路径。'),
    key=field('API Key','','password','留空保留现有凭据。已有 Key 不会回显；新填入的 Key 在保存后生效。'),
    active=field('启用厂商',original.enabled!==false,'checkbox');
  pid.input.readOnly=!!id;key.input.autocomplete='new-password';
  key.input.placeholder=original.credentials?'已配置 · 留空保留':'输入 API Key';
  const plabel=el('div',undefined,'form-field'),caption=el('div',undefined,'field-caption'),label=el('label','接口协议'),protocol=el('select');
  protocol.id='field-'+(++fieldId);label.htmlFor=protocol.id;
  caption.append(label,help('按厂商支持的接口选择 Chat Completions 或 Responses。','接口协议说明'));
  for(const [value,name]of[['openai_chat_completions','Chat Completions'],['openai_responses','Responses']]){const option=el('option',name);option.value=value;protocol.append(option);}
  protocol.value=original.protocol||'openai_chat_completions';plabel.append(caption,protocol);
  for(const f of [pid,base])fields.append(f.label);fields.append(plabel,key.label,active.label);sidebar.append(fields);
  for(const [alias,m]of Object.entries(original.models||{default:{model_id:'',enabled:true}}))rows.append(modelEditor(alias,m,false,state.models.find(model=>model.key===id+'/'+alias)));
  tools.append(button('＋ 添加模型',()=>{const row=modelEditor('model'+(rows.children.length+1));rows.append(row);row.querySelector('input:not([type=checkbox])').focus();}));
  const advanced=el('details');advanced.append(el('summary','高级参数'));
  const params=el('textarea');params.value=JSON.stringify(original.parameters||{},null,2);params.setAttribute('aria-label','厂商参数 JSON');
  const tokenField=el('select');tokenField.setAttribute('aria-label','输出预算字段');
  for(const t of ['max_tokens','max_completion_tokens']){const o=el('option',t);o.value=t;tokenField.append(o);}tokenField.value=original.token_limit_field||'max_tokens';
  advanced.append(el('p','厂商参数（JSON）'),params,el('p','Chat Completions 输出预算字段'),tokenField,el('p','Responses 使用 max_output_tokens。','hint'));sidebar.append(advanced);
  const actions=el('div',undefined,'actions');
  actions.append(button('保存厂商',async()=>{
    const spec={...original,base_url:base.input.value.trim(),protocol:protocol.value,enabled:active.input.checked,models:collect(rows),parameters:JSON.parse(params.value),token_limit_field:tokenField.value};
    await api('provider',{id:pid.input.value.trim(),spec,api_key:key.input.value||undefined});key.input.value='';await refresh();message('厂商与模型已保存。Key / API 下一轮生效；模型列表变动请重启客户端。');
  },''));
  if(id)actions.append(button('删除厂商',async()=>{if(!confirm('删除此厂商及本工具中的模型配置？'))return;await api('provider',{id,delete:true});await refresh();},'text-danger'));
  const foot=el('div',undefined,'provider-footer');foot.append(el('span','修改后保存此厂商及其全部模型','hint'),actions);content.append(foot);
  return card;
}
function ccCard(entry){
  const {card,sidebar,rows}=providerLayout(entry.name,'同步自 CC Switch');
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
let refreshing=false;
async function refresh(automatic=false){if(refreshing||(automatic&&testingConnections))return;refreshing=true;try{const next=await api('state');const changed=state&&JSON.stringify(state.sync_revision)!==JSON.stringify(next.sync_revision);if(automatic&&document.querySelector('#providers input:focus,#providers textarea:focus,#providers .help-trigger:focus,#providers select:focus'))return;if(automatic&&state&&JSON.stringify(state)===JSON.stringify(next)){$('sync-status').textContent='每 1 秒自动同步 · '+new Date().toLocaleTimeString();return;}state=next;$('routing-toggle').setAttribute('aria-checked',String(state.routing_mode==='project'));$('routing-toggle').disabled=routingSaving||!['project','openai'].includes(state.routing_mode);$('routing-status').textContent=state.routing_mode==='project'?'已保存配置：项目路由':state.routing_mode==='openai'?'已保存配置：OpenAI 原生':'无法切换：客户端配置不可用或使用了其他厂商／配置档案';if(automatic&&changed)message('CC Switch 配置已更新；后续调用使用最新配置。');for(const mode of ['independent','cc_switch']){$(mode).classList.toggle('active',mode===state.mode);$(mode).setAttribute('aria-pressed',String(mode===state.mode));}$('model-count').textContent=state.models.length+' 个模型';$('cc-path').hidden=state.mode!=='cc_switch';if(document.activeElement!==$('db-path'))$('db-path').value=state.cc_db_path;$('add-provider').hidden=state.mode!=='independent';$('source-note').textContent=state.mode==='independent'?'独立管理':'CC Switch · 只读同步';$('providers').replaceChildren();if(state.mode==='independent'){for(const [id,spec]of Object.entries(state.config.providers))$('providers').append(providerCard(id,spec));}else{for(const entry of state.inventory)$('providers').append(ccCard(entry));}if(!$('providers').children.length)$('providers').append(el('p',state.mode==='cc_switch'?'CC Switch 中暂无可读取的第三方 OpenAI 配置。':'尚无厂商，请添加厂商和模型。','hint'));if(state.source_error)message('配置来源提示：'+state.source_error,true);$('catalog-status').textContent=state.catalog_pending?'模型列表有变更 · 更新列表后请重启客户端':'客户端模型列表已更新';$('sync-status').textContent=state.mode==='cc_switch'?'每 1 秒自动同步 · '+new Date().toLocaleTimeString():'';}finally{refreshing=false;}}
for(const mode of ['independent','cc_switch'])$(mode).onclick=()=>action(async()=>{await api('source',{mode});message('');await refresh();});
$('routing-toggle').onclick=()=>action(async()=>{if(routingSaving)return;const toggle=$('routing-toggle');const mode=state.routing_mode==='project'?'openai':'project';routingSaving=true;toggle.disabled=true;toggle.setAttribute('aria-busy','true');try{await api('routing',{mode});state.routing_mode=mode;toggle.setAttribute('aria-checked',String(mode==='project'));await refresh();message('路由配置已保存，请重启客户端生效。');}finally{routingSaving=false;toggle.removeAttribute('aria-busy');toggle.disabled=!['project','openai'].includes(state?.routing_mode);}});
$('save-path').onclick=()=>action(async()=>{await api('source',{mode:'cc_switch',cc_db_path:$('db-path').value});message('');await refresh();});
$('publish').onclick=()=>action(async()=>{await api('publish',{});await refresh();message('客户端模型列表已更新，请重启客户端加载最新列表。');});
$('refresh').onclick=()=>action(async()=>{message('');await refresh();});
$('add-provider').onclick=()=>{const card=providerCard('');$('providers').prepend(card);card.querySelector('input').focus();};
action(refresh);

setInterval(()=>{if(state?.mode==='cc_switch'&&!document.hidden)action(()=>refresh(true));},1000);

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
