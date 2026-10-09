/* ==========================================================
   StudyGenie AI — auth.js
   Show/Hide password toggles for Login, Register, Reset Password
========================================================== */
function bindPasswordToggle(toggleBtnId, iconId, inputId) {
  const btn = document.getElementById(toggleBtnId);
  const icon = document.getElementById(iconId);
  const input = document.getElementById(inputId);
  if (!btn || !icon || !input) return;

  btn.addEventListener('click', () => {
    const isHidden = input.type === 'password';
    input.type = isHidden ? 'text' : 'password';
    icon.className = isHidden ? 'fa-solid fa-eye-slash' : 'fa-solid fa-eye';
  });
}

document.addEventListener('DOMContentLoaded', () => {
  bindPasswordToggle('togglePassword', 'togglePasswordIcon', 'loginPassword');
  bindPasswordToggle('toggleRegisterPassword', 'toggleRegisterPasswordIcon', 'registerPassword');
  bindPasswordToggle('toggleResetPassword', 'toggleResetPasswordIcon', 'resetPassword');
});
