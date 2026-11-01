const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=()=>fs.readFileSync('src/management/web/transport.js','utf8');
function setup(invoke){const window=invoke?{__TAURI__:{core:{invoke}}}:{};vm.runInNewContext(source(),{window});return window.hybridDesktop;}
test('browser transport does not activate desktop IPC',()=>assert.equal(setup(),null));
test('desktop sends method, path and JSON body over private IPC without HTTP',async()=>{
  const calls=[];const desktop=setup(async(...args)=>{calls.push(args);return {ok:true,result:{saved:true}};});
  assert.equal((await desktop.api('provider',{id:'demo',api_key:'fixture-secret'})).saved,true);
  assert.equal(calls[0][0],'desktop_manage');
  assert.equal(calls[0][1].request.method,'POST');assert.equal(calls[0][1].request.path,'provider');
  assert.equal(calls[0][1].request.body.api_key,'fixture-secret');
  await desktop.api('state');assert.equal(calls[1][1].request.method,'GET');assert.equal(calls[1][1].request.body,null);
});
test('desktop business failures keep their code and do not retry writes',async()=>{
  let calls=0;const desktop=setup(async()=>{calls++;return {ok:false,error:'MODEL_SOURCE_CHANGED'};});
  await assert.rejects(desktop.api('models',{}),/MODEL_SOURCE_CHANGED/);assert.equal(calls,1);
  assert.equal(desktop.pendingWrites,0);
});
test('writes remain guarded until IPC settles and transport disconnects are not replayed',async()=>{
  let reject;const desktop=setup(()=>new Promise((_,r)=>{reject=r;}));
  const pending=desktop.api('publish',{});assert.equal(desktop.pendingWrites,1);
  reject(Error('native private failure'));await assert.rejects(pending,/SERVICE_UNREACHABLE/);
  assert.equal(desktop.pendingWrites,0);
});
