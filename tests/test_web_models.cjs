const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('src/management/web/models.js','utf8');
const persist=source.slice(source.indexOf('async function persistModelUpdates'),source.indexOf("$('add-models').onclick"));
const adaptations=source.slice(source.indexOf('const adaptationControls='),source.indexOf('function modelName'));
test('native settings and portable fallback retain per-model adaptations',()=>{
  const controls={
    'model-compatibility':{getAttribute:()=>portable?'true':'false'},
    'adapt-agent-messages':{checked:true},'adapt-standalone-outputs':{checked:false},'adapt-custom-tools':{checked:true},'adapt-discovered-tools':{checked:false}
  };
  let portable=false;
  const context=vm.createContext({$:id=>controls[id]});
  vm.runInContext(adaptations,context);
  const update=()=>JSON.parse(JSON.stringify(context.modelDetailUpdate({key:'p/m',protocol:'openai_responses'})));
  context.syncAdaptationControls();
  assert.equal(controls['adapt-custom-tools'].disabled,false);
  assert.deepEqual(update(),{key:'p/m',responses_compatibility:'native',responses_adaptations:['agent_messages','custom_tools']});
  portable=true;context.syncAdaptationControls();
  assert.equal(controls['adapt-custom-tools'].disabled,true);
  assert.deepEqual(update(),{key:'p/m',responses_compatibility:'portable',responses_adaptations:['agent_messages','custom_tools']});
  portable=false;controls['adapt-agent-messages'].checked=false;controls['adapt-custom-tools'].checked=false;
  assert.deepEqual(update().responses_adaptations,[]);
  assert.deepEqual(JSON.parse(JSON.stringify(context.modelDetailUpdate({key:'p/chat',protocol:'openai_chat_completions'}))),{key:'p/chat'});
});
function setup(failure){
  const events=[],messages=[],error={textContent:'old'},controls=[{disabled:false},{disabled:true}];
  const dialog={setAttribute(){},removeAttribute(){},querySelectorAll:()=>controls,close:()=>events.push('close')};
  const context=vm.createContext({modelSaving:false,modelDialogSource:'captured-source',
    $:()=>error,api:async(path,body)=>{events.push([path,JSON.parse(JSON.stringify(body))]);if(failure)throw Error('fixture');},
    refresh:async()=>events.push('refresh'),message:(text,isError)=>{events.push('message');messages.push([text,isError]);},
    errorMessage:()=> '保存失败',updateAddCount(){}});
  vm.runInContext(persist,context);
  return {context,events,messages,error,controls,dialog};
}
test('saving uses captured source and restores disabled controls',async()=>{
  const env=setup();
  await env.context.persistModelUpdates([{key:'p/m',added:true}],env.dialog,'error');
  assert.deepEqual(env.events[0],['models',{source_id:'captured-source',updates:[{key:'p/m',added:true}]}]);
  assert.deepEqual(env.events.slice(1),['close','refresh','message']);
  assert.deepEqual(env.controls.map(c=>c.disabled),[false,true]);
});
test('failed save keeps dialog open and displays recoverable error',async()=>{
  const env=setup(true);
  await env.context.persistModelUpdates([{key:'p/m',added:false}],env.dialog,'error');
  assert.equal(env.events.length,1);
  assert.equal(env.error.textContent,'保存失败');
  assert.equal(env.context.modelSaving,false);
  assert.deepEqual(env.controls.map(c=>c.disabled),[false,true]);
});
test('saving compatibility settings applies without requiring a client restart',async()=>{
  const env=setup();
  await env.context.persistModelUpdates([{key:'p/m',responses_compatibility:'portable'}],env.dialog,'error');
  assert.match(env.messages[0][0],/下一轮调用生效/);
  assert.match(env.messages[0][0],/无需重启 Codex/);
  assert.doesNotMatch(env.messages[0][0],/请重启|需要重启/);
});
test('changing model-list membership asks the user to restart Codex',async()=>{
  const env=setup();
  await env.context.persistModelUpdates([{key:'p/m',added:true}],env.dialog,'error');
  assert.match(env.messages[0][0],/重启 Codex/);
  assert.match(env.messages[0][0],/新模型才会在 Codex 中生效/);
});
test('in-flight save prevents duplicate requests',async()=>{
  const env=setup();env.context.modelSaving=true;
  await env.context.persistModelUpdates([{key:'p/m',added:true}],env.dialog,'error');
  assert.deepEqual(env.events,[]);
});
const removeListed=source.slice(source.indexOf('async function removeListedModel'),source.indexOf('function renderAvailableModels'));
test('row deletion removes membership and recovers control after failure',async()=>{
  for(const fail of [false,true]){
    const calls=[],control={disabled:false,textContent:'删除'};
    const context=vm.createContext({modelSaving:false,
      api:async(path,body)=>{calls.push(JSON.parse(JSON.stringify(body)));if(fail)throw Error('offline');},
      refresh:async()=>calls.push('refresh'),message:(text,error)=>calls.push(error?'error':'success'),errorMessage:()=> '保存失败'});
    vm.runInContext(removeListed,context);
    await context.removeListedModel({key:'p/m'},control,'source-a');
    assert.deepEqual(calls[0],{source_id:'source-a',updates:[{key:'p/m',added:false}]});
    assert.deepEqual(calls.slice(1),fail?['error']:['refresh','success']);
    assert.equal(control.disabled,false);assert.equal(control.textContent,'删除');assert.equal(context.modelSaving,false);
  }
});
