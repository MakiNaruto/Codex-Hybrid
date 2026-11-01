const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function fixture({draft=false,restored=true,hint=true,nativeChoice=0,restartAvailable=true,clientRunning=true,preference="ask",requestError=null,externalService=false}={}){
  const events={},calls=[],notes=[],nodes={};let exits=0;
  const node=id=>{
    if(!nodes[id]){const listeners={};nodes[id]={hidden:false,disabled:false,checked:false,open:false,
      addEventListener(name,cb){(listeners[name]??=[]).push(cb);},showModal(){this.open=true;},
      async submit(event){for(const cb of listeners.submit||[])await cb(event);},
      close(){this.open=false;for(const cb of listeners.close||[])cb();},focus(){}};}
    return nodes[id];
  };
  const desktop={pendingWrites:0,request:async r=>{calls.push(r);if(r.action===requestError)throw Error('SERVICE_UNREACHABLE');if(r.action==='preview_routing')return {revision:'rev',desktop_ticket:'route-ticket',desktop:{available:true,status:'known',running:clientRunning},activity:{active_requests:2}};if(r.action==='preview_restart')return {available:restartAvailable,ticket:'signed',activity:{active_requests:2},status:'running'};return {};}};
  const request=desktop.request;
  desktop.api=async(path,body)=>{calls.push({action:'api',path,body});return request({action:path==='routing/preview'?'preview_routing':'set_routing',...body});};
  if(externalService)desktop.request=async r=>{
    if(['preview_routing','set_routing'].includes(r.action))throw Error('SERVICE_ALREADY_RUNNING');
    return request(r);
  };
  const context=vm.createContext({window:{hybridDesktop:desktop,addEventListener:(name,fn)=>{events[name]=fn;},__TAURI__:{event:{listen:(name,cb)=>{events[name]=cb;return Promise.resolve();}},core:{invoke:async(command,args)=>{if(command==='desktop_alert'){calls.push({action:'alert',...args});return nativeChoice;}exits++;return {ok:false,error:'EXIT_BLOCKED',restore_preview:hint};}}}},
    document:{querySelector:()=>null},$:node,dirtyCards:()=>draft?[{}]:[],routingSaving:false,sourceSaving:false,modelSaving:false,
    renderRouting:()=>{},routingResultText:()=> '操作完成',state:{routing_mode:'project',desktop_preferences:{openai:preference}},refresh:async()=>{},routingEnabled:()=>true,switchRouting:async mode=>{calls.push({action:'switch',mode});return restored;},
    refreshClientProcesses:async()=>calls.push({action:'detect'}),
    message:(...args)=>notes.push(args[0]),errorMessage:e=>e.message,action:async fn=>{try{await fn();}catch(e){notes.push(e.message);}}});
  vm.runInContext(fs.readFileSync('src/management/web/desktop.js','utf8'),context);
  return {events,calls,notes,nodes,node,context,exits:()=>exits};
}
test('tray actions preserve unsaved drafts without sending native operations',async()=>{
  const f=fixture({draft:true});for(const name of ['desktop-exit-requested','desktop-routing-requested','desktop-restart-requested'])await f.events[name]();
  assert.equal(f.exits(),0);assert.equal(f.calls.length,0);assert.match(f.notes.join(' '),/保存/);
});
test('macOS exit restores through shared confirmation and exits only on success',async()=>{
  const f=fixture();await f.events['desktop-exit-requested']();assert.equal(f.calls[0].mode,'openai');assert.equal(f.exits(),2);
  const cancelled=fixture({restored:false});await cancelled.events['desktop-exit-requested']();assert.equal(cancelled.exits(),1);
});
test('platforms without the restoration hint keep the blocked exit behavior',async()=>{
  const f=fixture({hint:false});await f.events['desktop-exit-requested']();assert.equal(f.calls.length,0);assert.equal(f.exits(),1);
});
test('tray routing invokes shared preview and confirmation flow',async()=>{
  const f=fixture();await f.events['desktop-routing-requested']();assert.equal(f.calls[0].action,'switch');assert.equal(f.calls[0].mode,'openai');
});
test('desktop detects client and gateway status once configuration is ready',async()=>{
  const f=fixture();await f.events['hybrid-management-ready']();
  assert.equal(f.calls[0].action,'detect');
});
test('restart requires acknowledgement and a ticket, cancellation sends no restart',async()=>{
  const f=fixture();await f.events['desktop-restart-requested']();const dialog=f.node('desktop-restart-dialog');
  await dialog.submit({preventDefault(){},submitter:{value:'confirm'}});
  assert.equal(f.calls.some(r=>r.action==='restart_codex'),false);
  f.node('desktop-restart-ack').checked=true;
  await dialog.submit({preventDefault(){},submitter:{value:'confirm'}});
  assert.equal(f.calls.find(r=>r.action==='restart_codex').ticket,'signed');
});
test('shared desktop page leaves restart and exit in native menus',()=>{
  const html=fs.readFileSync('src/management/web/index.html','utf8');
  assert.doesNotMatch(html,/id="desktop-(?:controls|restart|exit)"/);
  const f=fixture();
  for(const id of ['desktop-controls','desktop-restart','desktop-exit'])assert.equal(f.nodes[id],undefined);
  assert.equal(typeof f.events['desktop-restart-requested'],'function');
  assert.equal(typeof f.events['desktop-exit-requested'],'function');
});

const macEvent={payload:{native_confirmation:true}};
test('macOS tray routing uses native choice and cancels without changing configuration',async()=>{
  const f=fixture();await f.events['desktop-routing-requested'](macEvent);
  assert.equal(f.calls.some(r=>r.action==='alert'),true);
  assert.equal(f.calls.some(r=>r.action==='set_routing'||r.action==='switch'),false);
  assert.equal(f.calls.at(-1).action,'cancel_preview');
});
test('macOS native routing confirms activity and reuses the preview ticket',async()=>{
  for(const choice of [1,2]){
    const f=fixture({nativeChoice:choice});await f.events['desktop-routing-requested'](macEvent);
    const request=f.calls.find(r=>r.action==='set_routing');
    assert.equal(request.mode,'openai');assert.equal(request.desktop_ticket,'route-ticket');
    assert.equal(request.desktop_action,choice===2);assert.equal(request.confirm_activity,true);
  }
});
test('macOS native restart confirms ticket, cancellation never restarts',async()=>{
  for(const choice of [0,1]){
    const f=fixture({nativeChoice:choice});await f.events['desktop-restart-requested'](macEvent);
    assert.equal(f.node('desktop-restart-dialog').open,false);
    assert.equal(f.calls.some(r=>r.action==='restart_codex'),choice===1);
    if(choice===1)assert.equal(f.calls.find(r=>r.action==='restart_codex').ticket,'signed');
    else assert.equal(f.calls.at(-1).action,'cancel_restart');
  }
});
test('macOS unavailable restart gives visible native feedback without restarting',async()=>{
  const f=fixture({nativeChoice:1,restartAvailable:false});await f.events['desktop-restart-requested'](macEvent);
  assert.equal(f.calls.some(r=>r.action==='alert'),true);
  assert.equal(f.calls.some(r=>r.action==='restart_codex'),false);
});

test('macOS native actions show service errors instead of silently doing nothing',async()=>{
  const f=fixture({requestError:'preview_restart'});await f.events['desktop-restart-requested'](macEvent);
  assert.equal(f.calls.find(r=>r.action==='alert').title,'操作未完成');
  assert.equal(f.calls.some(r=>r.action==='restart_codex'),false);
});
test('macOS native route respects never preference and refuses unavailable restart choice',async()=>{
  for(const options of [{preference:'never'},{clientRunning:false}]){
    const f=fixture({...options,nativeChoice:2});await f.events['desktop-routing-requested'](macEvent);
    assert.equal(f.calls.find(r=>r.action==='alert').buttons.length,2);
    assert.equal(f.calls.some(r=>r.action==='set_routing'),false);
  }
});
test('macOS native tray preserves dirty drafts with visible feedback',async()=>{
  const f=fixture({draft:true});await f.events['desktop-restart-requested'](macEvent);
  assert.equal(f.calls.length,1);assert.equal(f.calls[0].title,'暂不能操作');
});

test('macOS tray routing shares the working web adapter when a web service owns the instance',async()=>{
  const f=fixture({externalService:true,nativeChoice:1});
  await f.events['desktop-routing-requested'](macEvent);
  assert.deepEqual(f.calls.filter(r=>r.action==='api').map(r=>r.path),['routing/preview','routing']);
  assert.equal(f.calls.some(r=>r.action==='set_routing'),true);
  assert.equal(f.calls.some(r=>r.title==='操作未完成'),false);
});
