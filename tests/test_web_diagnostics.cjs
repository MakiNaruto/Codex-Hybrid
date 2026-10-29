const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/management/web/diagnostics.js', 'utf8');

class Node {
  constructor(tag, text, cls) {
    this.tag = tag; this.textContent = text || ''; this.className = cls || '';
    this.children = []; this.dataset = {}; this.attributes = {};
    this.classList = {add() {}, remove() {}};
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(key, value) { this.attributes[key] = value; }
  querySelectorAll() { return this.children; }
  click() { this.clicked = true; return this.onclick?.(); }
  remove() { this.removed = true; }
}
function report(period, errors = []) {
  return {service: {uptime_seconds: 120}, generated_at: 1700000000, period_days: period,
    log: {errors, state: 'available', coverage: {}}};
}
function setup() {
  const nodes = {}, requests = [], jobs = [], failures = [], downloads = [], messages = [], timers = [];
  const $ = id => nodes[id] ||= new Node('div');
  for (const period of ['1','7','30','all']) {
    const button = new Node('button'); button.dataset.period = period;
    $('diagnostic-period').append(button);
  }
  const context = vm.createContext({
    $, el: (tag, text, cls) => new Node(tag, text, cls), help: () => new Node('button'),
    action: fn => {const job = fn(); jobs.push(job); job.catch(error => failures.push(error.message)); return job;},
    api: path => new Promise((resolve, reject) => requests.push({path, resolve, reject})),
    message: text => messages.push(text),
    document: {body: {append: node => downloads.push(node)}}, Blob,
    URL: {createObjectURL: () => 'blob:diagnostics', revokeObjectURL: url => messages.push(url)},
    setTimeout: fn => timers.push(fn),
  });
  vm.runInContext(source, context);
  return {$, requests, jobs, failures, downloads, messages, timers};
}

test('loads the initial period and renders its empty state', async () => {
  const env = setup();
  assert.equal(env.requests[0].path, 'diagnostics?days=1');
  env.requests[0].resolve(report(1)); await env.jobs[0];
  assert.match(env.$('service-status').textContent, /已运行 2 分钟/);
  assert.match(env.$('diagnostic-errors').children[0].textContent, /最近 24 小时未发现错误/);
});

test('a newer period wins even when an older request finishes last', async () => {
  const env = setup();
  env.$('diagnostic-period').children[1].click();
  assert.equal(env.requests[1].path, 'diagnostics?days=7');
  env.requests[1].resolve(report(7)); await env.jobs[1];
  env.requests[0].resolve(report(1)); await env.jobs[0];
  assert.match(env.$('diagnostic-errors').children[0].textContent, /最近 7 天未发现错误/);
  assert.equal(env.$('diagnostic-period').children[1].attributes['aria-pressed'], 'true');
});

test('a stale failure leaves the newest report visible', async () => {
  const env = setup(); env.$('diagnostic-period').children[2].click();
  env.requests[1].resolve(report(30)); await env.jobs[1];
  env.requests[0].reject(Error('stale')); await env.jobs[0].catch(() => {});
  assert.match(env.$('service-status').textContent, /运行中/);
  assert.match(env.$('diagnostic-errors').children[0].textContent, /最近 30 天/);
});

test('refresh recovers after failure and always restores its button', async () => {
  const env = setup();
  env.requests[0].reject(Error('offline')); await env.jobs[0].catch(() => {});
  assert.match(env.$('service-status').textContent, /诊断读取失败/);
  const refresh = env.$('refresh-diagnostics'); refresh.click();
  assert.equal(refresh.disabled, true);
  env.requests[1].resolve(report(1)); await env.jobs[1];
  assert.equal(refresh.disabled, false);
  assert.match(env.$('service-status').textContent, /运行中/);
});

test('export downloads the selected report and releases its object URL', async () => {
  const env = setup(); env.requests[0].resolve(report(1)); await env.jobs[0];
  const button = env.$('export-diagnostics'); button.click();
  env.requests[1].resolve(report(1)); await env.jobs[1];
  assert.equal(env.downloads[0].download, 'codex-hybrid-diagnostics.json');
  assert.equal(env.downloads[0].clicked, true);
  assert.equal(env.downloads[0].removed, true);
  assert.equal(button.disabled, false);
  env.timers[0](); assert.equal(env.messages.at(-1), 'blob:diagnostics');
});
