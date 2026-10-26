'use strict';
const button = document.getElementById('probe');
const result = document.getElementById('result');
button.addEventListener('click', async () => {
  button.disabled = true;
  result.textContent = '正在检查…';
  try {
    result.textContent = JSON.stringify(await window.__TAURI__.core.invoke('probe_report'), null, 2);
  } catch (error) {
    result.textContent = '检查失败：' + String(error);
  } finally {
    button.disabled = false;
  }
});
