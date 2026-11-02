const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
class Node {
  constructor(tag,text){this.tag=tag;this.textContent=text||'';this.children=[];this.dataset={};this.attributes={};this.value='';this.events={};this.open=false;}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  get firstChild(){return this.children[0];}
  querySelectorAll(){return this.children;}
  setAttribute(key,value){this.attributes[key]=value;}
  addEventListener(event,fn){(this.events[event]??=[]).push(fn);}
  showModal(){this.open=true;}
  close(){this.open=false;for(const fn of this.events.close||[])fn();}
}
function setup(desktop=false,hidden=false){
  const nodes={},events={},requests=[],accessed=new Set();
  const $=id=>{
    accessed.add(id);
    return nodes[id]??=new Node('div');
  };
  $('page-usage').hidden=hidden;
  for(const period of ['yesterday','today','7','30']){const button=new Node('button');button.dataset.period=period;$('usage-period').append(button);}
  for(const metric of ['total_tokens','requests']){const button=new Node('button');button.dataset.metric=metric;$('usage-metric').append(button);}
  vm.runInNewContext(fs.readFileSync('src/management/web/usage.js','utf8'),{
    $,el:(tag,text,cls)=>{const node=new Node(tag,text);node.className=cls;return node;},Intl,Date,
    window:{hybridDesktop:desktop,addEventListener:(event,fn)=>{events[event]=fn;}},
    document:{createElementNS:(ns,tag)=>new Node(tag)},
    api:path=>new Promise((resolve,reject)=>requests.push({path,resolve,reject}))
  });
  return {$,events,requests,accessed};
}
const report=(tokens=120)=>({generated_at:1700000000,period:'7',period_days:7,period_start:1699833600,period_end:1700000000,bucket_seconds:86400,buckets:[1699920000],state:'available',models:[{model:'<model>',requests:2,requests_with_usage:1,input_tokens:100,output_tokens:20,cached_tokens:40,total_tokens:tokens,series:[{requests:2,requests_with_usage:1,input_tokens:100,output_tokens:20,cached_tokens:40,total_tokens:tokens}]}]});
const tick=()=>new Promise(setImmediate);
test('renders totals, missing usage and model names as text',async()=>{
  const env=setup();env.requests[0].resolve(report());await tick();
  assert.equal(env.$('usage-metrics').children[0].children[1].textContent,'120');
  assert.equal(env.$('usage-metrics').children[1].children[1].textContent,'40');
  assert.equal(env.$('usage-metrics').children[2].children[1].textContent,'60');
  assert.equal(env.$('usage-metrics').children[3].children[1].textContent,'20');
  assert.match(env.$('usage-status').textContent,/1 次未返回有效用量/);
  assert.equal(env.$('usage-model-rows').children[0].children[0].textContent,'<model>');
  assert.equal(env.$('usage-model-rows').children[0].children[4].textContent,'60');
  env.$('usage-model').value='absent';env.$('usage-model').onchange();
  assert.equal(env.$('usage-metrics').children[0].children[1].textContent,'0');
});
test('stacks models in the trend and separates token composition by model',async()=>{
  const env=setup(),data=report(140);
  data.models.push({model:'other',requests:1,requests_with_usage:1,input_tokens:30,output_tokens:10,cached_tokens:0,total_tokens:40,
    series:[{requests:1,requests_with_usage:1,input_tokens:30,output_tokens:10,cached_tokens:0,total_tokens:40}]});
  data.models.push({model:'zero',requests:1,requests_with_usage:0,input_tokens:0,output_tokens:0,cached_tokens:0,total_tokens:0,
    series:[{requests:1,requests_with_usage:0,input_tokens:0,output_tokens:0,cached_tokens:0,total_tokens:0}]});
  data.models[0].series[0].total_tokens=100;data.models[0].total_tokens=100;
  env.requests[0].resolve(data);await tick();
  const legend=env.$('usage-model-legend').children;
  assert.match(legend[0].className,/usage-color-0/);
  assert.match(legend[1].className,/usage-color-1/);
  assert.equal(legend[0].children[0].className,'usage-model-swatch');
  const trend=env.$('usage-trend').children[0],trendGroups=trend.children.filter(node=>node.tag==='g');
  const trendClasses=trendGroups[0].children.map(node=>node.attributes.class||'');
  assert.ok(trendClasses.some(name=>name.includes('usage-color-0')));
  assert.ok(trendClasses.some(name=>name.includes('usage-color-1')));
  assert.ok(trendClasses.every(name=>!name.includes('stack-')));
  const hit=trendGroups[0].children.at(-1);
  assert.equal(hit.children.length,0);
  hit.events.focus[0]();
  assert.equal(env.$('usage-chart-tooltip').hidden,false);
  assert.doesNotMatch(env.$('usage-chart-tooltip').children[0].children[1].textContent,/zero/);
  const cards=env.$('usage-composition-charts').children;
  assert.equal(cards.length,3);
  assert.match(cards[0].className,/usage-color-0/);
  const compositionStage=cards[0].children.find(node=>node.tag==='div'&&node.className.includes('usage-composition-chart-stage'));
  const compositionSvg=compositionStage.children.find(node=>node.tag==='svg');
  const compositionGroups=compositionSvg.children.filter(node=>node.tag==='g');
  const compositionClasses=compositionGroups[0].children.map(node=>node.attributes.class||'');
  assert.ok(compositionClasses.some(name=>name.includes('stack-cached')));
  assert.ok(compositionClasses.some(name=>name.includes('stack-uncached')));
  assert.ok(compositionClasses.some(name=>name.includes('stack-output')));
  const compositionBars=compositionGroups[0].children
    .filter(node=>node.attributes.class?.includes('usage-composition-bar'))
    .sort((left,right)=>Number(left.attributes.y)-Number(right.attributes.y));
  assert.deepEqual(
    compositionBars.map(node=>node.attributes.class.match(/stack-(\w+)/)[1]),
    ['cached','uncached','output']
  );
  compositionGroups[0].children.at(-1).events.focus[0]();
  const compositionTooltip=compositionStage.children.find(node=>node.tag==='div'&&node.className.includes('usage-composition-tooltip'));
  assert.equal(compositionTooltip.hidden,false);
  assert.equal(compositionTooltip.children[0].children[0].textContent,'2023-11-14');
  assert.equal(compositionTooltip.children[0].children[1].textContent,'120');
  assert.equal(compositionTooltip.children[1].children[1].textContent,'输入（命中缓存）');
  assert.equal(compositionTooltip.children[1].children[2].textContent,'40');
  assert.equal(compositionTooltip.children[2].children[2].textContent,'60');
  assert.equal(compositionTooltip.children[3].children[2].textContent,'20');
});
test('keeps the trend tooltip heading compact',async()=>{
  const env=setup(),data=report();
  data.period='today';data.period_days=1;data.bucket_seconds=3600;data.period_start=1699920000;
  env.requests[0].resolve(data);await tick();

  const trend=env.$('usage-trend').children[0],trendGroups=trend.children.filter(node=>node.tag==='g');
  const hit=trendGroups[0].children.find(node=>node.attributes.class==='usage-chart-hit');
  hit.events.focus[0]();

  const heading=env.$('usage-chart-tooltip').children[0];
  assert.doesNotMatch(heading.children[0].textContent,/(?:UTC|本地时间)$/);
  assert.equal(heading.children[1].textContent,'120');
});
test('replaces the token key with a button that opens an enlarged chart',async()=>{
  const env=setup(),data=report();
  env.requests[0].resolve(data);await tick();

  const card=env.$('usage-composition-charts').children[0];
  const heading=card.children[0];
  const expand=heading.children.at(-1);
  assert.equal(expand.tag,'button');
  assert.match(expand.className,/usage-composition-expand/);
  assert.equal(expand.textContent,'⤢');
  assert.equal(expand.attributes['aria-label'],'放大 <model> 的 Token 构成图');
  assert.doesNotMatch(JSON.stringify(card),/缓存命中 \/ 未命中 \/ 输出/);

  expand.onclick();
  const dialog=env.$('usage-composition-dialog');
  assert.equal(dialog.open,true);
  assert.equal(env.$('usage-composition-dialog-title').textContent,'Token 构成 · <model>');
  const content=env.$('usage-composition-dialog-body');
  assert.match(content.className,/usage-color-0/);
  const legend=content.children.find(node=>node.className?.includes('usage-composition-dialog-legend'));
  assert.deepEqual(
    legend.children.map(node=>node.textContent),
    ['缓存命中','缓存未命中','输出']
  );
  const stage=content.children.find(node=>node.className?.includes('usage-composition-chart-stage'));
  assert.match(stage.className,/usage-composition-chart-stage-expanded/);
});
test('does not render hover details below the usage trend',async()=>{
  const env=setup(),data=report();
  env.requests[0].resolve(data);await tick();

  const trend=env.$('usage-trend').children[0],trendGroups=trend.children.filter(node=>node.tag==='g');
  const hit=trendGroups[0].children.find(node=>node.attributes.class==='usage-chart-hit');
  hit.events.focus[0]();

  assert.equal(env.$('usage-chart-tooltip').hidden,false);
  assert.equal(env.accessed.has('usage-chart-detail'),false);
  assert.doesNotMatch(fs.readFileSync('src/management/web/index.html','utf8'),/id="usage-chart-detail"/);
});
test('does not open empty trend buckets',async()=>{
  const env=setup(),data=report();
  data.buckets.push(1699923600);
  data.models[0].series.push({requests:0,requests_with_usage:0,input_tokens:0,output_tokens:0,cached_tokens:0,total_tokens:0});
  env.requests[0].resolve(data);await tick();

  const trend=env.$('usage-trend').children[0],trendGroups=trend.children.filter(node=>node.tag==='g');
  const emptyHit=trendGroups[1].children.find(node=>node.attributes.class==='usage-chart-hit');

  assert.equal(emptyHit,undefined);
  assert.equal(env.$('usage-chart-tooltip').hidden,true);
});
test('does not render hover details below token composition charts',async()=>{
  const env=setup(),data=report();
  env.requests[0].resolve(data);await tick();

  const card=env.$('usage-composition-charts').children[0];
  const stage=card.children.find(node=>node.tag==='div'&&node.className.includes('usage-composition-chart-stage'));
  const svg=stage.children.find(node=>node.tag==='svg');
  const hit=svg.children.find(node=>node.tag==='g').children.find(node=>node.attributes.class==='usage-composition-hit');
  hit.events.focus[0]();

  const tooltip=stage.children.find(node=>node.tag==='div'&&node.className.includes('usage-composition-tooltip'));
  assert.equal(tooltip.hidden,false);
  assert.equal(env.accessed.has('usage-composition-detail'),false);
  assert.doesNotMatch(fs.readFileSync('src/management/web/index.html','utf8'),/id="usage-composition-detail"/);
});
test('does not open empty token composition buckets',async()=>{
  const env=setup(),data=report();
  data.buckets.push(1699923600);
  data.models[0].series.push({requests:0,requests_with_usage:0,input_tokens:0,output_tokens:0,cached_tokens:0,total_tokens:0});
  env.requests[0].resolve(data);await tick();

  const card=env.$('usage-composition-charts').children[0];
  const stage=card.children.find(node=>node.tag==='div'&&node.className.includes('usage-composition-chart-stage'));
  const svg=stage.children.find(node=>node.tag==='svg');
  const emptyGroup=svg.children.filter(node=>node.tag==='g')[1];
  const emptyHit=emptyGroup.children.find(node=>node.attributes.class==='usage-composition-hit');
  const tooltip=stage.children.find(node=>node.tag==='div'&&node.className.includes('usage-composition-tooltip'));

  assert.equal(emptyHit,undefined);
  assert.equal(tooltip.hidden,true);
});
test('renders list provider and model name instead of the raw key',async()=>{
  const env=setup(),data=report();
  data.models[0].provider_name='Vendor';data.models[0].model_name='Label model-a';
  env.requests[0].resolve(data);await tick();
  assert.equal(env.$('usage-model-rows').children[0].children[0].textContent,'Vendor · Label model-a');
  assert.equal(env.$('usage-ranking').children[0].children[0].children[0].textContent,'Vendor · Label model-a');
  assert.equal(env.$('usage-model').children[1].textContent,'Vendor · Label model-a');
  assert.equal(env.$('usage-model').children[1].value,'<model>');
});
test('latest period wins over stale successes and failures',async()=>{
  const env=setup();env.$('usage-period').children[3].onclick();
  assert.equal(env.requests[1].path,'usage?period=30');env.requests[1].resolve(report(500));await tick();
  env.requests[0].reject(Error('stale'));await tick();
  assert.equal(env.$('usage-metrics').children[0].children[1].textContent,'500');
  assert.equal(env.$('usage-content').hidden,false);
});
test('today and yesterday load calendar-day periods and expose the full-day window',async()=>{
  const env=setup();assert.equal(env.requests[0].path,'usage?period=7');
  env.$('usage-period').children[1].onclick();assert.equal(env.requests[1].path,'usage?period=today');
  const data=report();
  data.period='today';data.period_days=1;data.bucket_seconds=3600;data.period_start=1699920000;
  env.requests[1].resolve(data);await tick();
  assert.match(env.$('usage-status').textContent,/今天/);
  assert.match(env.$('usage-status').textContent,/00:00–24:00/);
  env.$('usage-period').children[0].onclick();assert.equal(env.requests[2].path,'usage?period=yesterday');
});
test('failure hides old figures and refresh recovers',async()=>{
  const env=setup();env.requests[0].reject(Error('offline'));await tick();
  assert.match(env.$('usage-status').textContent,/读取失败/);assert.equal(env.$('usage-content').hidden,true);
  env.$('refresh-usage').onclick();env.requests[1].resolve(report());await tick();
  assert.equal(env.$('usage-content').hidden,false);
});
test('desktop waits for readiness, hidden page loads on navigation',()=>{
  const env=setup(true,true);assert.equal(env.requests.length,0);env.events['hybrid-management-ready']();assert.equal(env.requests.length,0);
  env.$('page-usage').hidden=false;env.events.hashchange();assert.equal(env.requests[0].path,'usage?period=7');
});
