'use strict';
async function previewRestart() {
  if (busy || editing || routePreview || restartPreview) {
    message('请先完成当前操作，或保存、取消草稿和预览。'); return;
  }
  setBusy(true); message('正在检查 Codex 与网关活动…');
  try {
    restartPreview = await manage({action: 'preview_restart'});
    const active = restartPreview.activity.active_requests;
    const statuses = {running: '检测到运行', not_running: '未运行，本入口不会启动 Codex',
      unavailable: '无法识别安装，请手动操作 Codex', unknown: '运行状态未知，已阻止自动重启'};
    byId('restart-summary').textContent = 'Codex：' + (statuses[restartPreview.status] || '未知') +
      '；活动请求：' + (active == null ? '未知' : active) + '。预览两分钟内有效，执行前会重新核对进程身份。';
    byId('ack-restart').checked = false;
    byId('restart-preview').hidden = false;
    byId('restart-preview').scrollIntoView({block: 'start'});
    message('请核对重启影响并确认；取消不会操作 Codex。');
  } catch (error) { restartPreview = null; message(error instanceof Error ? error.message : '检查失败，请稍后重试。'); }
  finally { setBusy(false); }
  byId('confirm-restart').disabled = !restartPreview?.available;
  if (restartPreview) byId('ack-restart').focus();
}
window.__TAURI__.event.listen('desktop-restart-requested', previewRestart);
byId('restart-codex').addEventListener('click', previewRestart);
byId('cancel-restart').addEventListener('click', async () => {
  if (busy || !restartPreview) return;
  setBusy(true);
  try {
    await manage({action: 'cancel_restart'});
    restartPreview = null; byId('restart-preview').hidden = true;
    message('已取消重启，未操作 Codex。');
  } catch (_) { message('取消未确认完成，尚未发出重启请求，请重试取消。'); }
  finally { setBusy(false); }
});
byId('confirm-restart').addEventListener('click', async () => {
  if (busy || !restartPreview?.available) return;
  if (!byId('ack-restart').checked) { message('请先勾选确认重启影响，或取消重启。'); return; }
  const preview = restartPreview;
  setBusy(true); message('正在正常退出并重新打开 Codex，请等待…');
  try {
    const result = await manage({action: 'restart_codex', ticket: preview.ticket, confirm_activity: true});
    const outcomes = {started: '已尝试启动 Codex，不代表客户端已加载配置或恢复任务。',
      close_failed: 'Codex 正常退出未完成，未尝试启动，请手动检查；未强制结束进程。',
      launch_unconfirmed: 'Codex 已完成退出，但启动结果未确认，请手动检查。'};
    message(outcomes[result.desktop_result] || '操作结果未知，请手动检查 Codex。');
  } catch (error) { message(error instanceof Error ? error.message : '重启结果未确认，请手动检查；不会自动重试。'); }
  finally {
    restartPreview = null; byId('restart-preview').hidden = true; setBusy(false);
  }
});
