// Isolated event tests: no Tauri process, filesystem configuration, or network.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function fixture() {
  const nodes = new Map(), events = {}, calls = [];
  const node = id => {
    if (!nodes.has(id)) {
      const listeners = {};
      nodes.set(id, {disabled: false, textContent: '',
        addEventListener: (name, cb) => { listeners[name] = cb; },
        click() { if (!this.disabled) return listeners.click?.(); },
        scrollIntoView() { this.scrolled = true; }, replaceChildren() {}, focus() {}});
    }
    return nodes.get(id);
  };
  const context = vm.createContext({document: {getElementById: node, querySelectorAll: () => []},
    window: {__TAURI__: {core: {invoke: async command => {
      calls.push(command);
      if (command === 'desktop_exit') return {ok: false, error: 'EXIT_BLOCKED'};
      throw Error('No controller in event fixture');
    }}, event: {listen: (name, cb) => { events[name] = cb; }}}}, setInterval() {}});
  vm.runInContext(fs.readFileSync(__dirname + '/web/app.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync(__dirname + '/web/restart.js', 'utf8'), context);
  return {node, events, calls, context};
}
test('tray exit and keyboard quit use safe exit command', async () => {
  const f = fixture(); await new Promise(setImmediate);
  f.events['desktop-exit-requested'](); await new Promise(setImmediate);
  assert.equal(f.calls.filter(x => x === 'desktop_exit').length, 1);
  assert.match(f.node('status').textContent, /暂不能退出/);
});
test('tray exit preserves an unsaved draft', async () => {
  const f = fixture(); await new Promise(setImmediate);
  vm.runInContext('editing = true', f.context);
  f.events['desktop-exit-requested'](); await new Promise(setImmediate);
  assert.equal(f.calls.includes('desktop_exit'), false);
  assert.match(f.node('status').textContent, /保存或取消编辑/);
});


function connectedFixture({retained = false, failCommit = false} = {}) {
  const f = fixture();
  let routing = 'project';
  f.requests = [];
  vm.runInContext('window.__TAURI__.core.invoke = null', f.context);
  f.context.window.__TAURI__.core.invoke = async (command, args) => {
    f.calls.push(command);
    if (command === 'desktop_snapshot') return {status: 'not_configured'};
    if (command === 'desktop_exit') return routing === 'project' || retained ?
      {ok: false, error: 'EXIT_BLOCKED', restore_preview: true} : {ok: true};
    const request = args.request; f.requests.push(request);
    if (request.action === 'status') return {ok: true, result: {routing, configured: true, forwarding: {status: 'running'}}};
    if (request.action === 'preview_routing') return {ok: true, result: {
      mode: request.mode, revision: 'signed', activity: {active_requests: 0}, codex_process: {status: 'not_detected'},
      desktop: {available: false, running: false}, desktop_ticket: 'ticket'}};
    if (request.action === 'preview_restart') return {ok:true, result:{ticket:'restart-ticket', available:true, status:'running', activity:{active_requests:2}}};
    if (request.action === 'restart_codex') return {ok:true,result:{desktop_result:'started'}};
    if (request.action === 'set_routing') {
      if (failCommit) return {ok: false, error: 'CLIENT_CONFIG_CHANGED'};
      routing = 'openai'; return {ok: true, result: {desktop_result: 'manual', forwarding_retained: retained}};
    }
    return {ok: true, result: {}};
  };
  return f;
}
const settle = () => new Promise(setImmediate);
test('macOS exit previews restoration and requires confirmation before shutdown', async () => {
  const f = connectedFixture(); await settle();
  await f.node('exit-app').click();
  assert.equal(f.node('routing-preview').hidden, false);
  assert.match(f.node('preview-title').textContent, /退出/);
  assert.equal(f.requests.some(r => r.action === 'set_routing'), false);
  await f.node('confirm-routing').click();
  assert.equal(f.requests.some(r => r.action === 'set_routing'), false);
  f.node('ack-activity').checked = true;
  await f.node('confirm-routing').click();
  assert.equal(f.requests.find(r => r.action === 'set_routing').mode, 'openai');
  assert.equal(f.calls.filter(c => c === 'desktop_exit').length, 2);
});
test('cancelling exit restoration never commits or later exits on a normal switch', async () => {
  const f = connectedFixture(); await settle();
  await f.node('exit-app').click();
  await f.node('cancel-routing').click();
  assert.equal(f.requests.some(r => r.action === 'set_routing'), false);
  assert.match(f.node('status').textContent, /取消退出/);
  await f.node('routing-toggle').click();
  f.node('ack-activity').checked = true;
  await f.node('confirm-routing').click();
  assert.equal(f.calls.filter(c => c === 'desktop_exit').length, 1);
});
test('restored configuration with retained gateway keeps the app open', async () => {
  const f = connectedFixture({retained: true}); await settle();
  await f.node('exit-app').click(); f.node('ack-activity').checked = true;
  await f.node('confirm-routing').click();
  assert.match(f.node('status').textContent, /配置已关闭接入.*暂不能退出/);
});
test('failed restoration never retries a write or proceeds to shutdown', async () => {
  const f = connectedFixture({failCommit: true}); await settle();
  await f.node('exit-app').click(); f.node('ack-activity').checked = true;
  await f.node('confirm-routing').click();
  assert.equal(f.calls.filter(c => c === 'desktop_exit').length, 1);
  assert.equal(f.requests.filter(r => r.action === 'set_routing').length, 1);
  assert.match(f.node('status').textContent, /重新预览/);
});
test('blocked exit without macOS hint preserves the existing platform behavior', async () => {
  const f = connectedFixture(); await settle();
  const invoke = f.context.window.__TAURI__.core.invoke;
  f.context.window.__TAURI__.core.invoke = async (command, args) => command === 'desktop_exit' ?
    {ok: false, error: 'EXIT_BLOCKED'} : invoke(command, args);
  await f.node('exit-app').click();
  assert.equal(f.requests.some(r => r.action === 'preview_routing'), false);
  assert.match(f.node('status').textContent, /暂不能退出/);
});

test('tray routing directly opens a preview without writing configuration', async () => {
  const f = connectedFixture(); await settle();
  await f.events['desktop-routing-requested']();
  assert.equal(f.node('routing-preview').hidden, false);
  assert.equal(f.requests.filter(r => r.action === 'preview_routing').length, 1);
  assert.equal(f.requests.some(r => r.action === 'set_routing'), false);
});
test('tray restart requires activity acknowledgement and explicit confirmation', async () => {
  const f = connectedFixture(); await settle();
  await f.events['desktop-restart-requested']();
  assert.equal(f.node('restart-preview').hidden, false);
  assert.equal(f.requests.some(r => r.action === 'restart_codex'), false);
  await f.node('confirm-restart').click();
  assert.equal(f.requests.some(r => r.action === 'restart_codex'), false);
  f.node('ack-restart').checked = true;
  await f.node('confirm-restart').click();
  assert.equal(f.requests.find(r => r.action === 'restart_codex').ticket, 'restart-ticket');
  assert.match(f.node('status').textContent, /已尝试启动/);
});
test('restart preview blocks routing and exit, cancellation never restarts', async () => {
  const f = connectedFixture(); await settle();
  await f.events['desktop-restart-requested']();
  await f.events['desktop-routing-requested']();
  await f.node('exit-app').click();
  assert.equal(f.calls.includes('desktop_exit'), false);
  assert.equal(f.requests.some(r => r.action === 'preview_routing'), false);
  await f.node('cancel-restart').click();
  assert.equal(f.node('restart-preview').hidden, true);
  assert.equal(f.requests.some(r => r.action === 'restart_codex'), false);
});
test('tray actions preserve unsaved Key drafts', async () => {
  const f = connectedFixture(); await settle();
  vm.runInContext('editing = true', f.context);
  f.node('provider-key').value = 'fixture-unsaved-key';
  const before = f.requests.length;
  await f.events['desktop-restart-requested']();
  await f.events['desktop-routing-requested']();
  assert.equal(f.requests.length, before);
  assert.equal(f.node('provider-key').value, 'fixture-unsaved-key');
});
