/* Restore appearance before the stylesheet loads to avoid a light flash. */
'use strict';
(() => {
  const key = 'codexHybridManagementTheme';
  let theme = 'light';
  try { if (localStorage.getItem(key) === 'dark') theme = 'dark'; } catch (_) { /* Storage may be disabled. */ }
  const apply = value => {
    theme = value;
    document.documentElement.dataset.theme = theme;
    const toggle = document.getElementById('theme-toggle');
    if (!toggle) return;
    const label = theme === 'dark' ? '切换到白天模式' : '切换到夜间模式';
    toggle.setAttribute('aria-label', label);
    toggle.setAttribute('title', label);
    toggle.setAttribute('aria-pressed', String(theme === 'dark'));
  };
  apply(theme);
  document.addEventListener('DOMContentLoaded', () => {
    apply(theme);
    document.getElementById('theme-toggle').addEventListener('click', () => {
      apply(theme === 'dark' ? 'light' : 'dark');
      try { localStorage.setItem(key, theme); } catch (_) { /* Switching still works without storage. */ }
    });
  });
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) apply(event.newValue === 'dark' ? 'dark' : 'light');
  });
})();
