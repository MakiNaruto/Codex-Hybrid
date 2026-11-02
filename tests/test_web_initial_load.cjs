const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('src/management/web/app.js','utf8');
const refresh=source.slice(source.indexOf('async function refresh(automatic='),source.indexOf("for(const mode of ['independent','cc_switch'])$(mode).onclick"));
const summary=source.slice(source.indexOf('function renderAccessSummary('),source.indexOf('let refreshing=false;'));
function fixture(api){
  const nodes={};
  const context=vm.createContext({api,window:{hybridDesktop:{}},state:undefined,
    refreshing:false,$:id=>nodes[id]??={},errorMessage:e=>e.message,
    document:{body:{classList:{toggle(){}}}}});
  vm.runInContext(refresh,context);
  return {nodes,context};
}
function summaryFixture(current){
  const nodes={};
  const context=vm.createContext({state:current,$:id=>nodes[id]??={}});
  vm.runInContext(summary+'\nrenderAccessSummary();',context);
  return nodes;
}
test('failed first configuration read ends the loading state and permits retry',async()=>{
  const f=fixture(async()=>{throw Error('SERVICE_UNREACHABLE');});
  await assert.rejects(f.context.refresh(),/SERVICE_UNREACHABLE/);
  assert.match(f.nodes['access-note'].textContent,/读取失败/);
  assert.match(f.nodes['access-note'].textContent,/SERVICE_UNREACHABLE/);
  assert.equal(f.context.refreshing,false);
});
test('unconfigured desktop shows setup instead of an endless configuration read',async()=>{
  const f=fixture(async()=>({configured:false}));await f.context.refresh();
  assert.equal(f.nodes['desktop-setup'].hidden,false);
  assert.match(f.nodes['access-note'].textContent,/初始化/);
});
test('access page leads with the switch and carries no readiness steps',()=>{
  const html=fs.readFileSync('src/management/web/index.html','utf8');
  assert.doesNotMatch(html,/readiness/);
  assert.doesNotMatch(html,/使用准备/);
  for(const id of ['access-headline','access-note','routing-status','routing-toggle','forwarding-status','detect-processes'])
    assert.match(html,new RegExp('id="'+id+'"'));
});
test('access headline reports the third-party models in use when routing is open',()=>{
  const nodes=summaryFixture({routing_mode:'project',models:Array.from({length:12},()=>({enabled:true})),
    official_model_count:5,catalog_pending:false,forwarding:{status:'running'}});
  assert.match(nodes['access-headline'].textContent,/12 个第三方模型/);
  assert.match(nodes['access-note'].textContent,/在 Codex 中选择/);
});
test('access headline reports official models when routing is closed',()=>{
  const nodes=summaryFixture({routing_mode:'openai',models:[],official_model_count:5,
    catalog_pending:false,forwarding:{status:'stopped'}});
  assert.match(nodes['access-headline'].textContent,/5 个官方模型/);
  assert.match(nodes['access-note'].textContent,/先添加模型/);
});
test('access summary surfaces source errors, pending catalog and an unusable config',()=>{
  const source_error=summaryFixture({routing_mode:'project',models:[{enabled:true}],official_model_count:1,
    catalog_pending:true,source_error:'SOURCE_UNAVAILABLE',forwarding:{status:'fault'}});
  assert.match(source_error['access-note'].textContent,/SOURCE_UNAVAILABLE/);
  const pending=summaryFixture({routing_mode:'project',models:[{enabled:true}],official_model_count:1,
    catalog_pending:true,forwarding:{status:'fault'}});
  assert.match(pending['access-note'].textContent,/模型列表有变更/);
  const blocked=summaryFixture({routing_mode:'unsupported',models:[{enabled:true}],official_model_count:1});
  assert.match(blocked['access-headline'].textContent,/无法切换/);
});
