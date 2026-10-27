// Run with: node --test tests/test_web_source.cjs
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../src/management/web/app.js'), 'utf8');
const helpers = source.slice(source.indexOf('let sourceSaving=false;'), source.indexOf('function renderReadiness()'));

function setup(mode) {
  const calls = [], controls = {};
  const context = vm.createContext({
    state: {mode}, action: async fn => fn(),
    $: id => controls[id] ||= {disabled: false},
    dirtyCards: () => { calls.push('draft-check'); return []; },
    confirm: () => assert.fail('unexpected prompt'),
    api: async (...args) => calls.push(args),
    connectionResults: {clear() {}}, refresh: async () => {}, message() {},
  });
  vm.runInContext(helpers, context);
  return {change: (...args) => context.changeSource(...args), calls, controls};
}

for (const mode of ['independent', 'cc_switch']) {
  test(`clicking selected ${mode} does not check drafts or send a request`, async () => {
    const env = setup(mode);
    await env.change(mode);
    assert.deepEqual(env.calls, []);
  });
}

test('switching to another mode sends a source request and restores controls', async () => {
  const env = setup('cc_switch');
  await env.change('independent');
  assert.equal(env.calls[1][0], 'source');
  assert.equal(env.calls[1][1].mode, 'independent');
  assert.equal(env.controls.independent.disabled, false);
  assert.equal(env.controls.cc_switch.disabled, false);
});

test('updating database path remains available when CC Switch is selected', async () => {
  const env = setup('cc_switch');
  await env.change('cc_switch', 'other.db');
  assert.equal(env.calls[1][1].cc_db_path, 'other.db');
});
