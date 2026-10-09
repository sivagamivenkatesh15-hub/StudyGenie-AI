/* ==========================================================
   StudyGenie AI — settings.js
========================================================== */
document.addEventListener('DOMContentLoaded', () => {
  const darkModeSetting = document.getElementById('darkModeSetting');
  if (darkModeSetting) {
    darkModeSetting.checked = document.documentElement.getAttribute('data-theme') === 'dark';
    darkModeSetting.addEventListener('change', () => toggleTheme());
  }
});

const profileForm = document.getElementById('profileForm');
if (profileForm) {
  profileForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('profileName').value.trim();
    const email = document.getElementById('profileEmail').value.trim();

    const res = await fetch('/api/settings/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email }),
    });
    const data = await res.json();
    if (data.success) showToast('Profile updated successfully!', 'success');
    else showToast(data.error || 'Failed to update profile', 'error');
  });
}

const passwordForm = document.getElementById('passwordForm');
if (passwordForm) {
  passwordForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const current_password = document.getElementById('currentPassword').value;
    const new_password = document.getElementById('newPassword').value;

    const res = await fetch('/api/settings/password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password, new_password }),
    });
    const data = await res.json();
    if (data.success) {
      showToast('Password changed successfully!', 'success');
      passwordForm.reset();
    } else {
      showToast(data.error || 'Failed to change password', 'error');
    }
  });
}
