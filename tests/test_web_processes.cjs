const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../src/management/web/app.js'), 'utf8');
const render = source.slice(source.indexOf('function renderClientProcesses('), source.indexOf('let processesRefreshing='));

function display(process) {
  const rows = [];
  const note = {};
  const context = vm.createContext({
    $: id => id === 'client-process-list' ? {replaceChildren() {}, append: row => rows.push(row)} : note,
    el: (tag, text, cls) => ({text, cls}), process,
  });
  vm.runInContext(render + '\nrenderClientProcesses(process);', context);
  return {rows, note};
}

test('shows each client and keeps unidentified processes visible', () => {
  const {rows} = display({status: 'running', clients: {desktop: 2, vscode: 1, cli: 0, unknown: 1}});
  assert.deepEqual(rows.map(row => row.text), ['桌面端 · 2 个进程', 'VS Code 端 · 1 个进程', 'CLI 端 · 未检测到', '来源未知 · 1 个进程']);
  assert.equal(rows[0].cls, 'client-process detected');
});

test('failed detection clears old counts and shows unknown for all clients', () => {
  const {rows, note} = display(null);
  assert.equal(rows.length, 3);
  assert.ok(rows.every(row => row.text.endsWith('状态未知')));
  assert.match(note.textContent, /检测不完整/);
});

test('partial detection retains positive evidence without claiming absent clients', () => {
  const {rows} = display({status: 'unknown', clients: {cli: 1}});
  assert.equal(rows[0].text, '桌面端 · 状态未知');
  assert.equal(rows[2].text, 'CLI 端 · 1 个进程');
});
