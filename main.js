/* ==========================================================
   StudyGenie AI — main.js
   Handles: theme toggle, sidebar toggle, toast notifications
========================================================== */

// ---------- Theme (Dark / Light Mode) ----------
(function initTheme() {
  const saved = localStorage.getItem('studygenie-theme') || 'light';
  document.documentElement.setAttribute('data-theme', saved);
})();

function applyThemeIcon() {
  const theme = document.documentElement.getAttribute('data-theme');
  document.querySelectorAll('#themeToggle i, #landingThemeToggle i').forEach(icon => {
    icon.className = theme === 'dark' ? 'fa-solid fa-sun' : 'fa-solid fa-moon';
  });
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('studygenie-theme', next);
  applyThemeIcon();
  const setting = document.getElementById('darkModeSetting');
  if (setting) setting.checked = next === 'dark';
}

document.addEventListener('DOMContentLoaded', () => {
  applyThemeIcon();
  const themeBtn = document.getElementById('themeToggle');
  const landingThemeBtn = document.getElementById('landingThemeToggle');
  if (themeBtn) themeBtn.addEventListener('click', toggleTheme);
  if (landingThemeBtn) landingThemeBtn.addEventListener('click', toggleTheme);

  // Sidebar toggle (mobile)
  const sidebar = document.getElementById('sidebar');
  const sidebarToggle = document.getElementById('sidebarToggle');
  if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener('click', () => sidebar.classList.toggle('open'));
    document.addEventListener('click', (e) => {
      if (window.innerWidth <= 860 && sidebar.classList.contains('open') &&
          !sidebar.contains(e.target) && e.target !== sidebarToggle) {
        sidebar.classList.remove('open');
      }
    });
  }
});

// ---------- Toast Notifications ----------
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(120%)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3200);
}

// ---------- Gamification: badge unlock toasts ----------
// Call after any API response that may include a `new_badges` array,
// e.g. showBadgeToasts(data.new_badges)
function showBadgeToasts(badges) {
  if (!badges || !badges.length) return;
  badges.forEach((b, i) => {
    setTimeout(() => showToast(`🏅 Badge Unlocked: ${b.name}!`, 'success'), i * 500);
  });
}

// Simple markdown-ish formatter for AI text output (bold/headers/bullets)
function formatAIText(text) {
  if (!text) return '';
  let html = text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/^### (.*$)/gim, '<h4>$1</h4>')
    .replace(/^## (.*$)/gim, '<h3>$1</h3>')
    .replace(/^# (.*$)/gim, '<h2>$1</h2>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/^\* (.*$)/gim, '&bull; $1<br>')
    .replace(/^- (.*$)/gim, '&bull; $1<br>')
    .replace(/\n/g, '<br>');
  return html;
}
