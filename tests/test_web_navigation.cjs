const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('src/management/web/app.js','utf8');
const navigation=source.slice(source.indexOf('function renderManagementPage'),source.indexOf("window.addEventListener('hashchange'"));
function setup(hash){
  const nodes=Object.fromEntries(['page-access','page-models','page-diagnostics','page-title','page-intro'].map(id=>[id,{hidden:false,focus(){this.focused=true;}}]));
  const links=['access','models','diagnostics'].map(page=>({dataset:{page},setAttribute(k,v){this[k]=v;},removeAttribute(k){delete this[k];}}));
  const context=vm.createContext({window:{location:{hash}},document:{querySelectorAll:()=>links},$:id=>nodes[id]});
  vm.runInContext(navigation,context);return {context,nodes,links};
}
test('default and unknown routes show only models',()=>{
  for(const hash of ['', '#unknown','#toString']){
    const {context,nodes,links}=setup(hash);context.renderManagementPage();
    assert.equal(nodes['page-models'].hidden,false);assert.equal(nodes['page-access'].hidden,true);assert.equal(nodes['page-diagnostics'].hidden,true);
    assert.equal(links[1]['aria-current'],'page');
  }
});
test('direct links and page changes update visibility, title and keyboard focus',()=>{
  const {context,nodes,links}=setup('#access');context.renderManagementPage();
  assert.equal(nodes['page-access'].hidden,false);assert.equal(nodes['page-title'].textContent,'接入与运行');
  assert.equal(nodes['page-title'].focused,undefined);
  context.window.location.hash='#diagnostics';context.renderManagementPage(true);
  assert.equal(nodes['page-access'].hidden,true);assert.equal(nodes['page-diagnostics'].hidden,false);
  assert.equal(links[0]['aria-current'],undefined);assert.equal(links[2]['aria-current'],'page');
  assert.equal(nodes['page-title'].focused,true);assert.equal(context.document.title,'Codex Hybrid · 运行与诊断');
});
test('remembered page survives a browser reload without fragment',()=>{
  const {context,nodes}=setup('');let saved='diagnostics';
  context.localStorage={getItem:()=>saved,setItem:(key,value)=>{saved=value;}};
  context.renderManagementPage();assert.equal(nodes['page-diagnostics'].hidden,false);
  context.window.location.hash='#access';context.renderManagementPage();assert.equal(saved,'access');
});
