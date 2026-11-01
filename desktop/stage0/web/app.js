'use strict';
const byId = id => document.getElementById(id);
const protocolName = value => ({openai_chat_completions: 'Chat Completions', openai_responses: 'Responses'}[value] || value);
let state = null;
let busy = false;
let editing = false;
let modelIndex = 0;
let controlStatus = null;
let routePreview = null;
let restartPreview = null;
let exitAfterRestore = false;
const errors = {
  EXIT_BLOCKED: '暂不能退出：请先关闭 Codex 接入；仍有活动、Codex 进程或状态未知时会保留服务，请稍后重试。',
  CLIENT_CONFIG_CHANGED: 'Codex 配置或会话索引已变化，请重新预览。',
  INVALID_PREVIEW: '预览已失效，请重新预览。',
  FORWARDING_START_FAILED: '网关启动失败，Codex 配置未切换。请检查端口占用或配置后重试。',
  FORWARDING_UNAVAILABLE: '网关当前不可用，请刷新检查恢复状态。',
  CLIENT_BASELINE_UNAVAILABLE: '原生配置恢复基线不可用，已阻止覆盖。请检查已有配置和恢复文件。',
  CONFIG_CHANGED: '配置已被其他操作修改。请保留所需草稿，取消编辑后刷新，再重新编辑。',
  SERVICE_ALREADY_RUNNING: '已有管理服务正在运行，请先通过原入口正常停止后重试。',
  INSTANCE_BUSY: '配置正在被其他操作使用，请稍后重试。',
  CODEX_NOT_READY: '请先安装并运行官方 Codex，确保配置和官方模型缓存已生成。',
  ALREADY_CONFIGURED: '已有配置，未重复初始化。请刷新查看。',
  CC_MODE_IS_READ_ONLY: 'CC Switch 来源为只读，请在来源应用中编辑。',
  NOT_CONFIGURED: '请先初始化本地配置。',
  MODEL_DISABLED: '该模型未启用，请先检查厂商及模型配置。',
  INVALID_REQUEST: '提交内容无效，请检查字段。',
  OPERATION_FAILED: '操作失败。请检查 API 地址、标识、模型配置和本地文件权限；连接测试失败时请检查凭据、网络及供应商接口。'
};
function message(text) { byId('status').textContent = text; }
function setBusy(value) {
  busy = value;
  document.querySelectorAll('button').forEach(button => { button.disabled = value; });
  byId('editor-fields').disabled = value;
  document.querySelectorAll('#routing-preview input, #routing-preview select, #restart-preview input').forEach(input => { input.disabled = value; });
  if (!value && routePreview) byId('desktop-action').disabled = !routePreview.desktop.available || byId('desktop-preference').value !== 'ask';
  renderRouting();
}
async function manage(request) {
  const response = await window.__TAURI__.core.invoke('desktop_manage', {request});
  if (!response.ok) throw Error(errors[response.error] || '操作失败，请检查配置后重试。');
  return response.result;
}
function actionButton(text, action) {
  const button = document.createElement('button');
  button.type = 'button'; button.textContent = text;
  button.addEventListener('click', action);
  return button;
}
function render(data) {
  byId('models').replaceChildren();
  byId('provider-list').replaceChildren();
  byId('catalog').hidden = true;
  byId('initialize').hidden = data.status !== 'not_configured';
  byId('setup-help').hidden = data.status !== 'not_configured';
  if (data.status === 'not_configured') {
    message('尚未找到本机配置。点击初始化后才会创建管理文件。'); return;
  }
  if (data.status !== 'ready') {
    message('无法读取配置，请检查已有配置文件和来源是否可用，然后刷新。'); return;
  }
  byId('source').textContent = data.source === 'cc-switch' ? 'CC Switch（只读）' : '独立管理';
  byId('providers').textContent = String(data.providers.length);
  byId('count').textContent = String(data.models.length);
  byId('add-provider').hidden = data.source !== 'yaml';
  for (const provider of data.editable || []) {
    const row = document.createElement('div'); row.className = 'provider-row';
    const label = document.createElement('span'); label.textContent = provider.id + ' · ' + protocolName(provider.protocol);
    row.append(label, actionButton('编辑 ' + provider.id, () => openEditor(provider)));
    byId('provider-list').append(row);
  }
  for (const model of data.models) {
    const row = document.createElement('tr');
    for (const value of [model.display_name, model.provider, protocolName(model.protocol), model.enabled ? '已加入目录' : '未加入目录']) {
      const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
    }
    const cell = document.createElement('td');
    cell.append(actionButton('测试连接', () => testConnection(model.key))); row.append(cell);
    byId('models').append(row);
  }
  byId('empty').hidden = data.models.length !== 0;
  byId('catalog').hidden = false;
  message('配置已读取。目录状态不代表连接测试通过或 Codex 已加载。');
}
async function load() {
  state = await window.__TAURI__.core.invoke('desktop_snapshot');
  render(state);
  await loadRouting();
}
async function refresh() {
  if (busy) return;
  if (editing || routePreview || restartPreview) { message('请先保存或取消编辑，完成或取消切换预览，再刷新配置。'); return; }
  setBusy(true); message('正在读取配置…');
  try { await load(); } catch (_) { message('配置读取程序暂不可用，请重新打开应用后重试。'); }
  finally { setBusy(false); }
}
function modelField(labelText, value, type, row, key) {
  const label = document.createElement('label'); label.textContent = labelText;
  const input = document.createElement('input'); input.type = type; input.dataset.field = key;
  if (type === 'checkbox') { input.checked = value; label.className = 'check'; }
  else { input.value = value; input.required = true; }
  if (key === 'alias') input.pattern = '[A-Za-z0-9][A-Za-z0-9_.-]*';
  label.append(input); row.append(label);
}
function addModel(model = {}) {
  const row = document.createElement('div'); row.className = 'model-row';
  modelField('模型标识', model.alias || 'model' + (++modelIndex), 'text', row, 'alias');
  modelField('供应商模型 ID', model.model_id || '', 'text', row, 'model_id');
  modelField('显示名称', model.display_name || '', 'text', row, 'display_name');
  modelField('启用模型', model.enabled !== false, 'checkbox', row, 'enabled');
  row.append(actionButton('移除此模型', () => row.remove()));
  byId('model-fields').append(row);
}
function openEditor(provider = null) {
  if (busy) return;
  if (editing || routePreview || restartPreview) { message('请先保存或取消当前编辑，完成或取消切换预览，再打开其他厂商。'); return; }
  editing = true; modelIndex = 0;
  byId('provider-form').reset();
  byId('provider-id').value = provider?.id || '';
  byId('provider-id').readOnly = Boolean(provider);
  byId('provider-base').value = provider?.base_url || '';
  byId('provider-protocol').value = provider?.protocol || 'openai_chat_completions';
  byId('provider-timeout').value = provider?.timeout_seconds || 180;
  byId('provider-enabled').checked = provider?.enabled !== false;
  byId('model-fields').replaceChildren();
  for (const model of provider?.models || [{}]) addModel(model);
  byId('editor-title').textContent = provider ? '编辑 ' + provider.id : '添加厂商';
  byId('editor').hidden = false; renderRouting();
  byId('provider-id').focus();
  byId('editor').scrollIntoView({block: 'start', behavior: 'smooth'});
}
byId('provider-form').addEventListener('submit', async event => {
  event.preventDefault(); if (busy) return;
  const id = byId('provider-id').value.trim();
  if (!byId('provider-id').readOnly && state.providers.some(provider => provider.id === id)) {
    message('厂商标识已存在，请取消草稿并编辑已有厂商。'); return;
  }
  const models = [...byId('model-fields').children].map(row => Object.fromEntries(
    [...row.querySelectorAll('input')].map(input => [input.dataset.field, input.type === 'checkbox' ? input.checked : input.value.trim()])));
  if (!models.length) { message('请至少添加一个模型。'); return; }
  const request = {action: 'save_provider', revision: state.revision, id,
    base_url: byId('provider-base').value.trim(), protocol: byId('provider-protocol').value,
    enabled: byId('provider-enabled').checked, timeout_seconds: Number(byId('provider-timeout').value),
    api_key: byId('provider-key').value, models};
  setBusy(true); message('正在保存…');
  let saved = false;
  try {
    await manage(request); saved = true;
    byId('provider-key').value = ''; editing = false; byId('editor').hidden = true;
    await load(); message(state.status === 'ready' ? '厂商与模型已保存，未自动测试连接或改变接入状态；目录变动需要客户端重新加载。' : '配置已保存，但当前无法读取列表，请检查来源后刷新。');
  } catch (error) { message(saved ? '配置已保存，但回读失败，请刷新查看。' : (error instanceof Error ? error.message : '保存失败，草稿已保留。')); }
  finally { setBusy(false); }
});
async function testConnection(key) {
  if (busy) return;
  if (editing || routePreview || restartPreview) { message('请先保存或取消草稿，并完成或取消切换预览。连接测试使用已保存配置。'); return; }
  setBusy(true); message('正在测试 ' + key + '，最长等待约 60 秒…');
  try {
    const result = await manage({action: 'test_connection', key});
    message(key + ' 连接测试通过，耗时 ' + result.elapsed_ms + ' ms。此操作未改变接入状态。');
  } catch (error) { message(error instanceof Error ? error.message : '连接测试失败。'); }
  finally { setBusy(false); }
}
byId('initialize').addEventListener('click', async () => {
  if (busy) return;
  setBusy(true); message('正在初始化本地配置…');
  let initialized = false;
  try {
    await manage({action: 'initialize'}); initialized = true; await load();
    message(state.status === 'ready' ? '本地管理配置已初始化，Codex 配置未修改。可以添加厂商。' : '初始化已完成，但当前无法读取列表，请检查来源后刷新。');
  } catch (error) { message(initialized ? '初始化已完成，但回读失败，请刷新查看。' : (error instanceof Error ? error.message : '初始化失败。')); }
  finally { setBusy(false); }
});
byId('refresh').addEventListener('click', refresh);
byId('add-provider').addEventListener('click', () => openEditor());
byId('add-model').addEventListener('click', () => addModel());
byId('cancel-editor').addEventListener('click', () => {
  if (busy) return;
  editing = false; byId('provider-form').reset(); byId('editor').hidden = true;
  renderRouting(); message('已取消编辑，草稿已丢弃。'); byId('add-provider').focus();
});
byId('probe').addEventListener('click', async () => {
  if (busy) return;
  setBusy(true); byId('result').textContent = '正在检查…';
  try { byId('result').textContent = JSON.stringify(await window.__TAURI__.core.invoke('probe_report'), null, 2); }
  catch (_) { byId('result').textContent = '检查失败，请重新打开应用后重试。'; }
  finally { setBusy(false); }
});
function renderRouting() {
  const status = controlStatus;
  const mode = status?.routing;
  const forwarding = status?.forwarding?.status || 'stopped';
  const names = {stopped: '已停止', running: '运行中', starting: '启动中', recovering: '恢复中', fault: '故障'};
  byId('routing-state').textContent = status ?
    ((mode === 'project' ? '配置：已接入' : mode === 'openai' ? '配置：原生' : '配置：未准备或状态不可用') +
    ' · 网关：' + (names[forwarding] || '未知') +
    (status.recovery_required ? '。发现残留接入状态，请恢复接入服务或预览关闭接入。' : '')) : '接入状态不可用，请刷新。';
  byId('routing-toggle').textContent = mode === 'project' ? '预览关闭接入' : '预览开启接入';
  byId('routing-toggle').disabled = busy || editing || Boolean(routePreview || restartPreview) || !['project', 'openai'].includes(mode);
  byId('recover-forwarding').hidden = !status?.recovery_required;
  byId('recover-forwarding').disabled = busy || editing || Boolean(routePreview || restartPreview);
  byId('exit-app').disabled = busy;
  byId('restart-codex').hidden = !status?.restart_supported;
  byId('restart-codex').disabled = busy || editing || Boolean(routePreview || restartPreview);
  byId('confirm-restart').disabled = busy || !restartPreview?.available;
}
async function loadRouting() {
  try { controlStatus = await manage({action: 'status'}); }
  catch (error) { controlStatus = null; renderRouting(); throw error; }
  renderRouting();
}
function syncDesktopAction() {
  if (!routePreview) return;
  const preference = byId('desktop-preference').value;
  const available = routePreview.desktop.available;
  byId('desktop-action').checked = available && preference === 'auto';
  byId('desktop-action').disabled = !available || preference !== 'ask';
  byId('desktop-action-hint').textContent = available ? '仅尝试一次正常操作，不强制结束进程；操作失败仍分别报告配置结果。' : '未识别到可自动操作的 Codex，本次仅切换配置，请自行检查客户端。';
}
byId('desktop-preference').addEventListener('change', syncDesktopAction);
async function previewRouting(forExit = false) {
  if (busy || editing || routePreview || restartPreview || !controlStatus) return;
  exitAfterRestore = forExit;
  setBusy(true); message('正在预检配置与会话索引…');
  try {
    routePreview = await manage({action: 'preview_routing', mode: controlStatus.routing === 'project' ? 'openai' : 'project'});
    byId('preview-title').textContent = forExit ? '恢复原生配置并退出应用' : routePreview.mode === 'project' ? '确认开启 Codex 接入' : '确认关闭 Codex 接入';
    byId('confirm-routing').textContent = forExit ? '确认恢复并检查退出' : '确认切换';
    byId('cancel-routing').textContent = forExit ? '取消退出' : '取消切换';
    const active = routePreview.activity.active_requests;
    byId('preview-summary').textContent = '迁移会话索引 ' + routePreview.session_count + ' 个，模型变更 ' + routePreview.model_change_count +
      ' 个，待补齐/修复索引 ' + routePreview.index_repair_count + ' 个；缺少历史文件 ' + routePreview.missing_rollouts +
      ' 条。活动请求：' + (active === null ? '未知' : active) + '；Codex 进程：' + ({running: '检测到运行', not_detected: '未检测到', unknown: '检测未知'}[routePreview.codex_process.status] || '检测未知') + '。确认前不会改写 Codex 配置或迁移索引。';
    byId('ack-activity').checked = false;
    byId('desktop-preference').value = controlStatus.desktop_preferences?.[routePreview.mode] || 'ask';
    syncDesktopAction(); byId('routing-preview').hidden = false;
    message(forExit ? '退出前需恢复原生配置。确认后另行检查安全停服；仍有活动、Codex 进程或状态未知时保留应用。取消可继续使用，关闭窗口可留在托盘。' : '请核对预览并明确确认；可以取消。');
    byId('routing-preview').scrollIntoView({block: 'start'});
  } catch (error) { exitAfterRestore = false; message(error instanceof Error ? error.message : '预览失败，请检查配置。'); }
  finally { setBusy(false); }
  if (routePreview) byId('ack-activity').focus();
}
byId('routing-toggle').addEventListener('click', () => previewRouting());
byId('cancel-routing').addEventListener('click', async () => {
  if (busy) return;
  const cancellingExit = exitAfterRestore;
  exitAfterRestore = false;
  setBusy(true);
  try {
    await manage({action: 'cancel_preview'}); routePreview = null;
    byId('routing-preview').hidden = true; await load(); message(cancellingExit ? '已取消退出，Codex 配置与会话索引未改写。关闭窗口可留在托盘。' : '已取消切换，Codex 配置与会话索引未改写。');
  } catch (_) { message('取消未完成，请刷新检查；尚未发出确认切换请求。'); }
  finally { setBusy(false); }
  if (!routePreview) byId('exit-app').focus();
});
byId('confirm-routing').addEventListener('click', async () => {
  if (busy || !routePreview) return;
  if (!byId('ack-activity').checked) { message('请先勾选确认活动和索引影响，或取消切换。'); return; }
  const preview = routePreview;
  const shouldExit = exitAfterRestore;
  exitAfterRestore = false;
  const desktopAction = byId('desktop-action').checked;
  const preference = byId('desktop-preference').value;
  setBusy(true); message('正在切换接入，请等待配置事务和可选 Codex 操作完成…');
  let applied = false;
  try {
    await manage({action: 'save_desktop_preferences', mode: preview.mode, value: preference});
    const result = await manage({action: 'set_routing', mode: preview.mode, revision: preview.revision,
      confirm_activity: true, desktop_action: desktopAction,
      desktop_was_running: preview.desktop.running, desktop_ticket: preview.desktop_ticket});
    applied = true; routePreview = null; byId('routing-preview').hidden = true;
    await load();
    const outcomes = {manual: '未自动操作 Codex，请自行检查是否需要重启', not_running: 'Codex 未运行，未启动',
      started: '已尝试启动 Codex', close_failed: 'Codex 正常退出失败，请手动重启', unavailable: '无法自动操作 Codex，请手动检查',
      state_changed: 'Codex 运行状态已变化，请手动检查', launch_unconfirmed: 'Codex 启动结果未确认', unknown: 'Codex 操作结果未知'};
    message('配置已' + (preview.mode === 'project' ? '开启' : '关闭') + '接入；' +
      (outcomes[result.desktop_result] || 'Codex 操作结果：' + result.desktop_result) + '。不代表客户端已加载。' +
      (result.forwarding_retained ? '为保护仍在使用的客户端，网关暂时保留；退出前需再次检查。' : ''));
    if (shouldExit) {
      const feedback = byId('status').textContent;
      try {
        const response = await window.__TAURI__.core.invoke('desktop_exit');
        if (!response.ok) message(feedback + ' ' + (response.error === 'EXIT_BLOCKED' ?
          '暂不能退出：仍有活动、Codex 进程或状态未知，服务与应用已保留。关闭窗口可留在托盘，稍后可再次退出。' :
          errors[response.error] || '尚不能确认安全退出，应用已保留。'));
      } catch (_) { message(feedback + ' 退出未确认完成，请检查恢复状态；应用未主动退出。'); }
    }
  } catch (error) {
    routePreview = null; byId('routing-preview').hidden = true;
    message(applied ? '配置切换已完成，但回读失败，请刷新检查。' : (error instanceof Error ? error.message : '切换未确认完成，请刷新检查；不会自动重试。'));
    try { await loadRouting(); } catch (_) { /* Keep the original operation feedback. */ }
  } finally { setBusy(false); }
});
byId('recover-forwarding').addEventListener('click', async () => {
  if (busy || editing || routePreview || restartPreview) return;
  setBusy(true); message('正在恢复接入服务，不改写 Codex 配置…');
  try { await manage({action: 'recover_forwarding'}); await loadRouting(); message('接入服务已恢复，请自行检查客户端连接状态。'); }
  catch (error) { message(error instanceof Error ? error.message : '恢复失败，请刷新检查。'); }
  finally { setBusy(false); }
});
byId('exit-app').addEventListener('click', async () => {
  if (busy) return;
  if (editing || routePreview || restartPreview) { message('请先保存或取消编辑，完成或取消切换预览，再退出。'); return; }
  setBusy(true); message('正在检查是否可以安全退出…');
  let restore = false;
  try {
    const response = await window.__TAURI__.core.invoke('desktop_exit');
    if (!response.ok) {
      message(errors[response.error] || '尚不能确认安全退出，请关闭接入并检查活动状态。');
      if (response.restore_preview) {
        await loadRouting();
        restore = controlStatus.routing === 'project';
      }
    }
  } catch (_) { message('退出未确认完成，控制程序可能异常，请检查恢复状态。'); }
  finally { setBusy(false); }
  if (restore) await previewRouting(true);
});
window.__TAURI__.event.listen('desktop-exit-requested', () => {
  byId('exit-app').click();
});
window.__TAURI__.event.listen('desktop-routing-requested', async () => {
  if (busy || editing || routePreview || restartPreview) {
    message('请先完成当前操作，或保存、取消草稿和预览。'); return;
  }
  setBusy(true);
  try { await loadRouting(); }
  catch (_) { message('接入状态不可用，请刷新检查配置。'); return; }
  finally { setBusy(false); }
  if (['project', 'openai'].includes(controlStatus?.routing)) await previewRouting();
  else {
    byId('routing-toggle').scrollIntoView({block: 'center'});
    message('请先初始化并检查接入配置，再预览切换。');
  }
});
setInterval(async () => {
  if (busy || editing || routePreview || restartPreview || !controlStatus?.configured) return;
  try { await loadRouting(); } catch (_) { byId('routing-state').textContent = '控制程序状态不可用，请刷新检查恢复状态。'; }
}, 5000);
refresh();
