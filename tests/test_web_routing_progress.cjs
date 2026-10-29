const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../src/management/web/app.js'), 'utf8');
const helpers = source.slice(source.indexOf('function renderRouting(){'), source.indexOf('function confirmRouting('));
function setup(operation, saving = false, api = async () => ({})) {
  const elements = {};
  const context = vm.createContext({
    $: id => elements[id] ||= {setAttribute(name, value) { this[name] = value; }},
    state: {routing_mode: 'project', routing_operation: operation, forwarding: {status: 'running'}}, routingSaving: saving,
    routingError: '', renderForwarding() {}, api,
  });
  vm.runInContext(helpers, context);
  return {context, elements, render: () => context.renderRouting()};
}
test('another tab sees the current operation and cannot start a competing switch', () => {
  const view = setup({mode: 'project', phase: 'launching'});
  view.render();
  assert.equal(view.elements['routing-toggle'].disabled, true);
  assert.equal(view.elements['routing-toggle']['aria-busy'], 'true');
  assert.match(view.elements['routing-status'].textContent, /正在启动/);
});
test('the waiting dialog shows platform-neutral close progress', () => {
  const view = setup({mode: 'project', phase: 'closing'}, true);
  view.elements['routing-dialog'] = {open: true};
  view.elements['routing-dialog-confirm'] = {disabled: true};
  view.render();
  assert.match(view.elements['routing-dialog-description'].textContent, /正常退出/);
  assert.doesNotMatch(view.elements['routing-dialog-description'].textContent, /Windows/);
});
test('lightweight progress polling stays single flight and updates the active operation', async () => {
  let finish, calls = 0;
  const view = setup(null, true, async path => {
    assert.equal(path, 'activity'); calls++;
    return new Promise(resolve => { finish = resolve; });
  });
  const first = view.context.refreshRoutingProgress();
  await view.context.refreshRoutingProgress();
  assert.equal(calls, 1);
  finish({routing_operation: {mode: 'project', phase: 'launching'}, forwarding: {status: 'running'}});
  await first;
  assert.equal(view.context.state.routing_operation.phase, 'launching');
  assert.match(view.elements['routing-status'].textContent, /正在启动/);
});
test('finished operations restore the switch and normal routing status', () => {
  const view = setup(null);
  view.render();
  assert.equal(view.elements['routing-toggle'].disabled, false);
  assert.equal(view.elements['routing-status'].textContent, '已开启');
});

test('saved routing keeps the switch enabled across runtime states', () => {
  const view = setup(null);
  for(const status of ['stopped', 'fault', 'recovering', 'starting', undefined]) {
    view.context.state.forwarding = status ? {status} : undefined;
    view.render();
    assert.equal(view.elements['routing-toggle']['aria-checked'], 'true');
    assert.match(view.elements['routing-status'].textContent, /已开启/);
    assert.equal(view.context.routingEnabled(), true);
  }
  view.context.state.forwarding = {status: 'running'};
  view.render();
  assert.equal(view.elements['routing-toggle']['aria-checked'], 'true');
  view.context.state.routing_mode = 'openai';
  view.render();
  assert.equal(view.elements['routing-toggle']['aria-checked'], 'false');
});

test('a late progress response cannot overwrite the completed operation', async () => {
  let finish;
  const view = setup(null, true, () => new Promise(resolve => { finish = resolve; }));
  const pending = view.context.refreshRoutingProgress();
  view.context.routingSaving = false;
  finish({routing_operation: {mode: 'project', phase: 'closing'}});
  await pending;
  assert.equal(view.context.state.routing_operation, null);
});

test('backup timeout explains that routing was not switched and can be retried', () => {
  const errorHelpers = source.slice(source.indexOf('function errorMessage('), source.indexOf('async function action('));
  const context = vm.createContext({state: {}});
  vm.runInContext(errorHelpers, context);
  const text = context.errorMessage({message: 'SESSION_BACKUP_TIMEOUT'});
  assert.match(text, /备份.*超时/);
  assert.match(text, /尚未切换/);
  assert.match(text, /重试/);
});
