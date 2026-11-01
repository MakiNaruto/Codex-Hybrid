const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
class Node {
  constructor(tag,text){this.tag=tag;this.textContent=text||'';this.children=[];this.dataset={};this.attributes={};this.value='';}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  get firstChild(){return this.children[0];}
  querySelectorAll(){return this.children;}
  setAttribute(key,value){this.attributes[key]=value;}
  addEventListener(){}
}
function setup(desktop=false,hidden=false){
  const nodes={},events={},requests=[];
  const $=id=>nodes[id]??=new Node('div');
  $('page-usage').hidden=hidden;
  for(const days of ['1','7','30']){const button=new Node('button');button.dataset.days=days;$('usage-period').append(button);}
  for(const metric of ['total_tokens','requests']){const button=new Node('button');button.dataset.metric=metric;$('usage-metric').append(button);}
  vm.runInNewContext(fs.readFileSync('src/management/web/usage.js','utf8'),{
    $,el:(tag,text)=>new Node(tag,text),Intl,Date,
    window:{hybridDesktop:desktop,addEventListener:(event,fn)=>{events[event]=fn;}},
    document:{createElementNS:(ns,tag)=>new Node(tag)},
    api:path=>new Promise((resolve,reject)=>requests.push({path,resolve,reject}))
  });
  return {$,events,requests};
}
const report=(tokens=120)=>({generated_at:1700000000,bucket_seconds:86400,buckets:[1699920000],state:'available',models:[{model:'<model>',requests:2,requests_with_usage:1,input_tokens:100,output_tokens:20,cached_tokens:40,total_tokens:tokens,series:[{requests:2,requests_with_usage:1,input_tokens:100,output_tokens:20,cached_tokens:40,total_tokens:tokens}]}]});
const tick=()=>new Promise(setImmediate);
test('renders totals, missing usage and model names as text',async()=>{
  const env=setup();env.requests[0].resolve(report());await tick();
  assert.equal(env.$('usage-metrics').children[0].children[1].textContent,'120');
  assert.match(env.$('usage-status').textContent,/1 次未返回有效用量/);
  assert.equal(env.$('usage-model-rows').children[0].children[0].textContent,'<model>');
  env.$('usage-model').value='absent';env.$('usage-model').onchange();
  assert.equal(env.$('usage-metrics').children[0].children[1].textContent,'0');
});
test('latest period wins over stale successes and failures',async()=>{
  const env=setup();env.$('usage-period').children[2].onclick();
  assert.equal(env.requests[1].path,'usage?days=30');env.requests[1].resolve(report(500));await tick();
  env.requests[0].reject(Error('stale'));await tick();
  assert.equal(env.$('usage-metrics').children[0].children[1].textContent,'500');
  assert.equal(env.$('usage-content').hidden,false);
});
test('failure hides old figures and refresh recovers',async()=>{
  const env=setup();env.requests[0].reject(Error('offline'));await tick();
  assert.match(env.$('usage-status').textContent,/读取失败/);assert.equal(env.$('usage-content').hidden,true);
  env.$('refresh-usage').onclick();env.requests[1].resolve(report());await tick();
  assert.equal(env.$('usage-content').hidden,false);
});
test('desktop waits for readiness, hidden page loads on navigation',()=>{
  const env=setup(true,true);assert.equal(env.requests.length,0);env.events['hybrid-management-ready']();assert.equal(env.requests.length,0);
  env.$('page-usage').hidden=false;env.events.hashchange();assert.equal(env.requests[0].path,'usage?days=7');
});
