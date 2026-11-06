'use strict';
function createProviderViews({getState,el,field,help,button,testButton,markDirty,clearDirty,applyFilters,api,refresh,message,clearConnectionResults}){
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
  function providerLayout(name,description,cc=false){
    const card=el('article',undefined,'card provider-layout');
    const sidebar=el('div',undefined,'provider-sidebar');
    const heading=el('div',undefined,'provider-heading');
    heading.append(el('span',(name||'新').slice(0,1).toUpperCase(),'provider-avatar'));
    const title=el('div');title.append(el('h3',name||'新厂商'),el('p',description,'hint'));heading.append(title);
    sidebar.append(heading);
    const content=el('div',undefined,'provider-content');
    const head=el('div',undefined,'models-heading');head.append(el('h4','所属模型'));
    const tip=help(cc?'测试连接直接使用 CC Switch 来源配置，无需先在模型管理中添加模型，也不会将模型加入客户端列表。测试会向厂商发送一次真实请求并消耗少量额度。':'测试连接会使用已保存并启用的配置，向厂商发送一次真实请求并消耗少量额度。新增或修改模型后，请先保存厂商。','测试连接说明');
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
      base=field('API 地址',original.base_url||'','text','填写支持 Responses 的 API 基础地址，通常以 /v1 结尾；不要包含 /responses。'),
      key=field('API Key','','password','留空保留现有凭据。已有 Key 不会回显；新填入的 Key 在保存后生效。'),
      active=field('启用厂商',original.enabled!==false,'checkbox');
    pid.input.readOnly=!!id;key.input.autocomplete='new-password';
    if(id)sidebar.append(el('p',getState().credential_status?.[id]==='available'?'已找到本地凭据 · 不代表连接已验证':'未找到可读取的凭据，请检查 Key 或环境变量','hint'));
    key.input.placeholder=original.credentials?'已配置 · 留空保留':'输入 API Key';
    const plabel=el('div',undefined,'form-field'),caption=el('div',undefined,'field-caption');
    caption.append(el('span','接口协议'),help('仅支持 Responses API，供应商须提供 /responses 接口。','接口协议说明'));
    plabel.append(caption,el('span','Responses','badge'));
    for(const f of [pid,base])fields.append(f.label);fields.append(plabel,key.label,active.label);sidebar.append(fields);
    for(const [alias,m]of Object.entries(original.models||{default:{model_id:'',enabled:true}}))rows.append(modelEditor(alias,m,false,getState().models.find(model=>model.key===id+'/'+alias)));
    tools.append(button('＋ 添加模型',()=>{let index=1;while([...rows.children].some(row=>row.alias()==='model'+index))index++;const row=modelEditor('model'+index);rows.append(row);markDirty(card);row.querySelector('input:not([type=checkbox])').focus();}));
    const advanced=el('details');advanced.append(el('summary','高级参数'));
    const params=el('textarea');params.value=JSON.stringify(original.parameters||{},null,2);params.setAttribute('aria-label','厂商参数 JSON');
    const timeout=field('请求超时（秒）',original.timeout_seconds??180,'number','范围为 1–3600 秒，影响第三方模型请求；连接测试固定使用 60 秒。');
    timeout.input.min='1';timeout.input.max='3600';timeout.input.step='1';
    const compatibility=el('select');compatibility.setAttribute('aria-label','Responses 内容适配方式');
    for(const [value,name]of[['native','原生模式'],['portable','Responses · 内容兼容转换']]){const o=el('option',name);o.value=value;compatibility.append(o);}compatibility.value=original.responses_compatibility||'native';
    const migration=field('移除历史项 ID，按内容重放',original.history_migration===true,'checkbox','跨服务迁移时移除有完整内容的历史项 ID；不解密推理，不还原纯 ID 引用。');
    const protocolHint=el('div',undefined,'protocol-hint');plabel.append(protocolHint);
    const syncResponses=()=>{protocolHint.replaceChildren(protocolIndicator(compatibility.value));};compatibility.addEventListener('change',syncResponses);syncResponses();
    advanced.append(el('p','Responses 内容适配方式'),compatibility,migration.label,el('p','内容兼容转换将扩展消息、工具和历史改写为更基础的 Responses 结构，仍请求 /responses。原生模式保留协议结构；不支持时返回错误。','hint'));
    advanced.append(timeout.label,el('p','厂商参数（JSON）'),params,el('p','Responses 使用 max_output_tokens。','hint'));sidebar.append(advanced);
    const actions=el('div',undefined,'actions');
    actions.append(button('保存厂商',async()=>{
      if(!id&&Object.hasOwn(getState().config.providers,pid.input.value.trim()))throw Error('厂商标识已存在，请使用其他标识，或直接编辑已有厂商。');
      const spec={...original,base_url:base.input.value.trim(),protocol:'openai_responses',enabled:active.input.checked,models:collect(rows),parameters:JSON.parse(params.value),timeout_seconds:Number(timeout.input.value)};
      spec.responses_compatibility=compatibility.value;spec.history_migration=migration.input.checked;
      card.inert=true;
      try{await api('provider',{id:pid.input.value.trim(),spec,api_key:key.input.value||undefined});key.input.value='';clearDirty(card);clearConnectionResults();await refresh();message('厂商与模型已保存。Key、API 地址和兼容设置下一轮生效；模型列表变动后请重启 Codex，新列表才会在 Codex 中生效。');}
      finally{card.inert=false;}
    },''));
    if(id)actions.append(button('删除厂商',async()=>{if(!confirm('删除此厂商及本工具中的模型配置？'))return;await api('provider',{id,delete:true});clearDirty(card);await refresh();},'text-danger'));
    const foot=el('div',undefined,'provider-footer');foot.append(el('span','修改后保存此厂商及其全部模型','hint'),actions);content.append(foot);
    return card;
  }
  function protocolNotice(compatibility='native'){
    if(compatibility==='portable')return 'Responses · 内容兼容转换：将扩展消息、工具和历史改写为更基础的 Responses 结构，仍请求上游 /responses 接口。连接测试通过不代表所有桌面功能兼容。';
    return 'Responses 原生转发：保留 Codex 协议结构，供应商仍需支持实际使用的工具和历史特性。不支持时返回错误。';
  }
  function protocolIndicator(compatibility='native'){
    const warning=compatibility==='portable';
    const label=warning?'Responses · 内容兼容转换':'原生转发';
    const indicator=el('span',undefined,'protocol-indicator'+(warning?' is-warning':''));
    const trigger=help(protocolNotice(compatibility),label+'说明');
    trigger.textContent=warning?'!':'i';trigger.classList.add('protocol-info');
    trigger.dataset.helpTone=warning?'warning':'neutral';
    trigger.dataset.helpTitle=warning?'Responses · 内容兼容转换':'使用 Responses 原生转发';
    indicator.append(trigger,el('span',label));return indicator;
  }
  function ccCard(entry){
    const {card,sidebar,content,rows}=providerLayout(entry.name,'同步自 CC Switch · '+entry.models.length+' 个模型',true);
    card.classList.add('cc-provider');
    card.dataset.providerId=entry.provider_key;
    const badges=el('div',undefined,'provider-badges');badges.append(el('span','Responses','badge'),el('span','只读','badge'));sidebar.append(badges);
    badges.append(protocolIndicator(entry.responses_compatibility));
    const address=el('div',undefined,'provider-address');address.append(el('p',entry.base_url));sidebar.append(address);
    const note=el('div',undefined,'readonly-note');note.append(el('span','在 CC Switch 中编辑配置'),help('仅同步支持 Responses 的 OpenAI / Codex 第三方配置，不回写数据库、不切换其他工具的当前厂商。每轮调用读取最新 Key。','CC Switch 同步说明'));content.append(note);
    for(const model of entry.models){
      const item=el('div',undefined,'cc-model');
      const identity=el('div',undefined,'cc-model-identity');
      const displayName=(model.display_name||model.model_id||'未命名模型').trim();
      identity.append(el('strong',displayName));
      if(model.model_id&&model.model_id.trim()!==displayName)identity.append(el('code',model.model_id));
      const stats=el('div',undefined,'model-stats');
      for(const [title,value,description]of[
        ['上下文窗口',model.context_window?model.context_window.toLocaleString():'131,072',model.context_window?'单位为 tokens。':'CC Switch 未配置，使用默认 131,072 tokens。'],
        ['输出上限',model.max_output_tokens?model.max_output_tokens.toLocaleString():'不设上限',model.max_output_tokens?'单位为 tokens。':'CC Switch 未配置，实际输出受厂商限制。']
      ]){
        const stat=el('div',undefined,'model-stat'),caption=el('div',undefined,'field-caption');
        caption.append(el('span',title),help(description,title+'说明'));
        const metric=el('div',undefined,'stat-value');
        metric.append(el('span',value));
        if(value==='不设上限')metric.classList.add('is-unlimited');
        else metric.append(el('span','tokens','stat-unit'));
        stat.append(caption,metric);stats.append(stat);
      }
      item.append(identity,testButton(getState().models.find(saved=>saved.provider===entry.provider_key&&saved.model_id===model.model_id),true),stats);rows.append(item);
    }
    if(!entry.models.length)rows.append(el('p','暂无可同步的模型','hint'));return card;
  }
  return {providerCard,ccCard};
}
