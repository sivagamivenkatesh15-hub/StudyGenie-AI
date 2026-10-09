/* ==========================================================
   StudyGenie AI — smart_revision.js
========================================================== */
document.querySelectorAll('.mark-revision-done').forEach(btn => {
  btn.addEventListener('click', () => {
    const item = btn.closest('.revision-item');
    const id = item.dataset.id;
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';

    fetch(`/api/revision-schedule/${id}/complete`, { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        if (!data.success) {
          showToast(data.error || 'Failed to update revision', 'error');
          btn.disabled = false;
          btn.innerHTML = '<i class="fa-solid fa-check"></i> Mark Done';
          return;
        }
        item.classList.add('done');
        item.querySelector('.revision-stage-dot').innerHTML = '<i class="fa-solid fa-check"></i>';
        btn.remove();
        showToast(
          data.next_stage_scheduled
            ? 'Revision completed! Next revision auto-scheduled 📅'
            : 'Final revision completed — topic fully mastered! 🎉',
          'success'
        );
        showBadgeToasts(data.new_badges);
        setTimeout(() => item.remove(), 1200);
      })
      .catch(() => {
        showToast('Network error — please try again.', 'error');
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-check"></i> Mark Done';
      });
  });
});
