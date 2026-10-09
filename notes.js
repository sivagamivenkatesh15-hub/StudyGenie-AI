/* ==========================================================
   StudyGenie AI — notes.js
========================================================== */
const generateNotesBtn = document.getElementById('generateNotesBtn');

if (generateNotesBtn) {
  generateNotesBtn.addEventListener('click', async () => {
    const syllabusId = document.getElementById('syllabusSelect').value;
    const noteType = document.getElementById('noteType').value;
    const loading = document.getElementById('notesLoading');
    const output = document.getElementById('notesOutput');

    output.innerHTML = '';
    loading.classList.remove('hidden');
    generateNotesBtn.disabled = true;

    try {
      const res = await fetch('/api/generate-notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ syllabus_id: syllabusId, note_type: noteType }),
      });
      const data = await res.json();
      loading.classList.add('hidden');
      generateNotesBtn.disabled = false;

      if (data.error) {
        showToast(data.error, 'error');
        return;
      }
      output.innerHTML = formatAIText(data.notes);
      showToast('Notes generated successfully!', 'success');
    } catch (err) {
      loading.classList.add('hidden');
      generateNotesBtn.disabled = false;
      showToast('Failed to generate notes. Please try again.', 'error');
    }
  });
}
