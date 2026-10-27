// Run with: node --test tests/test_web_clipboard.cjs
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../src/management/web/app.js'), 'utf8');
const helpers = source.slice(source.indexOf('function el('), source.indexOf('let messageTimer'));
const key = 'example/model';

function setup(clipboard, command = () => true) {
  const messages = [], prompts = [], nodes = [];
  let restored = false, selected;
  const document = {
    activeElement: {focus() { restored = true; }},
    body: {append(node) { nodes.push(node); }},
    createElement() {
      return {
        focus() {},
        select() { selected = this.value; },
        setSelectionRange(start, end) { assert.equal(start, 0); assert.equal(end, key.length); },
        remove() { nodes.splice(nodes.indexOf(this), 1); },
      };
    },
    execCommand(name) {
      assert.equal(name, 'copy');
      assert.equal(selected, key);
      assert.equal(nodes[0].readOnly, true);
      return command();
    },
  };
  const context = vm.createContext({
    navigator: {clipboard}, document,
    message: (...args) => messages.push(args),
    window: {prompt: (...args) => prompts.push(args)},
  });
  vm.runInContext(helpers, context);
  return {copy: () => context.copyText(key), messages, prompts, nodes, restored: () => restored};
}

test('uses the Clipboard API when available', async () => {
  let written;
  const env = setup({writeText: async value => { written = value; }}, () => assert.fail('unexpected fallback'));
  await env.copy();
  assert.equal(written, key);
  assert.deepEqual(env.messages, [['已复制到剪贴板。']]);
  assert.equal(env.prompts.length, 0);
});

for (const [name, clipboard] of [
  ['unavailable', undefined],
  ['denied', {writeText: async () => { throw Error('NotAllowedError'); }}],
]) {
  test(`copies through selection when Clipboard API is ${name}`, async () => {
    const env = setup(clipboard);
    await env.copy();
    assert.deepEqual(env.messages, [['已复制到剪贴板。']]);
    assert.equal(env.prompts.length, 0);
    assert.equal(env.nodes.length, 0);
    assert.equal(env.restored(), true);
  });
}

for (const [name, command] of [
  ['returns false', () => false],
  ['throws', () => { throw Error('copy blocked'); }],
]) {
  test(`offers the exact key for manual copying when fallback ${name}`, async () => {
    const env = setup(undefined, command);
    await env.copy();
    assert.equal(env.prompts.length, 1);
    assert.equal(env.prompts[0][1], key);
    assert.equal(env.messages[0][1], true);
    assert.equal(env.nodes.length, 0);
    assert.equal(env.restored(), true);
  });
}
