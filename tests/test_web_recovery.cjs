const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../src/management/web/app.js'), 'utf8');
const render = source.slice(source.indexOf('function renderForwarding('), source.indexOf("$('restore-native').onclick="));
function display(forwarding, routing = 'project') {
  const elements = {};
  const context = vm.createContext({$: id => elements[id] ||= {}, state: {routing_mode: routing}, routingSaving: false, forwarding});
  vm.runInContext(render+'\nrenderForwarding(forwarding);', context);
  return elements;
}
test('startup recovery offers both explicit choices', () => {
  const view = display({status: 'recovery_required'});
  assert.equal(view['recover-forwarding'].textContent, '恢复接入');
  assert.equal(view['recover-forwarding'].hidden, false);
  assert.equal(view['restore-native'].hidden, false);
  assert.match(view['forwarding-status'].textContent, /等待恢复/);
});
test('backoff reports progress and avoids competing manual recovery', () => {
  const view = display({status: 'recovering', retry_attempt: 2, retry_limit: 3, retry_at: 100});
  assert.match(view['forwarding-status'].textContent, /第 2\/3 次/);
  assert.equal(view['recover-forwarding'].hidden, true);
  assert.equal(view['restore-native'].hidden, true);
});
test('exhausted retries leave manual recovery available', () => {
  const view = display({status: 'fault'});
  assert.equal(view['recover-forwarding'].hidden, false);
  assert.equal(view['restore-native'].hidden, false);
  assert.match(view['forwarding-status'].textContent, /自动恢复已停止/);
});
test('starting state remains connected and does not offer duplicate recovery', () => {
  const view = display({status: 'starting'});
  assert.match(view['forwarding-status'].textContent, /正在启动/);
  assert.equal(view['recover-forwarding'].hidden, true);
});
test('safe fault reasons explain recovery without exposing unknown text', () => {
  const known = display({status: 'fault', error_reason: 'port_in_use'});
  assert.match(known['forwarding-status'].textContent, /端口.*占用/);
  const unknown = display({status: 'fault', error_reason: 'secret-in-raw-exception'});
  assert.doesNotMatch(unknown['forwarding-status'].textContent, /secret/);
});

test('dropped logs remain visible after forwarding recovers', () => {
  const view = display({status: 'running', log_dropped_records: 12});
  assert.match(view['forwarding-status'].textContent, /已丢弃 12 条日志/);
});
