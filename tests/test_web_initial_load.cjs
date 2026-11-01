const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('src/management/web/app.js','utf8');
const refresh=source.slice(source.indexOf('async function refresh(automatic='),source.indexOf("for(const mode of ['independent','cc_switch'])$(mode).onclick"));
function fixture(api){
  const nodes={};
  const context=vm.createContext({api,window:{hybridDesktop:{}},state:undefined,
    refreshing:false,$:id=>nodes[id]??={},errorMessage:e=>e.message,
    document:{body:{classList:{toggle(){}}}}});
  vm.runInContext(refresh,context);
  return {nodes,context};
}
test('failed first configuration read ends the loading state and permits retry',async()=>{
  const f=fixture(async()=>{throw Error('SERVICE_UNREACHABLE');});
  await assert.rejects(f.context.refresh(),/SERVICE_UNREACHABLE/);
  assert.match(f.nodes['readiness-summary'].textContent,/读取失败/);
  assert.match(f.nodes['readiness-summary'].textContent,/SERVICE_UNREACHABLE/);
  assert.equal(f.context.refreshing,false);
});
test('unconfigured desktop shows setup instead of an endless configuration read',async()=>{
  const f=fixture(async()=>({configured:false}));await f.context.refresh();
  assert.equal(f.nodes['desktop-setup'].hidden,false);
  assert.match(f.nodes['readiness-summary'].textContent,/初始化/);
});
