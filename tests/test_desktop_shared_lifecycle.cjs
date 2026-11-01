const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function fixture({draft=false,restored=true,hint=true}={}){
  const events={},calls=[],notes=[],nodes={};let exits=0;
  const node=id=>{
    if(!nodes[id]){const listeners={};nodes[id]={hidden:false,disabled:false,checked:false,open:false,
      addEventListener(name,cb){(listeners[name]??=[]).push(cb);},showModal(){this.open=true;},
      async submit(event){for(const cb of listeners.submit||[])await cb(event);},
      close(){this.open=false;for(const cb of listeners.close||[])cb();},focus(){}};}
    return nodes[id];
  };
  const desktop={pendingWrites:0,request:async r=>{calls.push(r);if(r.action==='preview_restart')return {available:true,ticket:'signed',activity:{active_requests:2},status:'running'};return {};}};
  const context=vm.createContext({window:{hybridDesktop:desktop,addEventListener:(name,fn)=>{events[name]=fn;},__TAURI__:{event:{listen:(name,cb)=>{events[name]=cb;return Promise.resolve();}},core:{invoke:async()=>{exits++;return {ok:false,error:'EXIT_BLOCKED',restore_preview:hint};}}}},
    document:{querySelector:()=>null},$:node,dirtyCards:()=>draft?[{}]:[],routingSaving:false,sourceSaving:false,modelSaving:false,
    state:{routing_mode:'project'},refresh:async()=>{},routingEnabled:()=>true,switchRouting:async mode=>{calls.push({action:'switch',mode});return restored;},
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
