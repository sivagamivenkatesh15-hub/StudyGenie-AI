/* ==========================================================
   StudyGenie AI — todo.js
========================================================== */
const todoForm = document.getElementById('todoForm');
const todoList = document.getElementById('todoList');

function bindTodoItem(li) {
  const id = li.dataset.id;
  const check = li.querySelector('.todo-check');
  const text = li.querySelector('.todo-text');
  const del = li.querySelector('.todo-delete');

  check.addEventListener('change', () => {
    li.classList.toggle('done', check.checked);
    updateTodo(id, { completed: check.checked });
  });

  text.addEventListener('blur', () => {
    updateTodo(id, { task: text.textContent.trim() });
  });
  text.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); text.blur(); }
  });

  del.addEventListener('click', () => {
    fetch(`/api/todos/${id}`, { method: 'DELETE' })
      .then(r => r.json())
      .then(() => { li.remove(); showToast('Task deleted', 'info'); });
  });
}

function updateTodo(id, payload) {
  fetch(`/api/todos/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => r.json()).then(() => showToast('Task updated', 'success'));
}

document.querySelectorAll('.todo-item').forEach(bindTodoItem);

if (todoForm) {
  todoForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const task = document.getElementById('taskInput').value.trim();
    const due_date = document.getElementById('dueDateInput').value;
    const priority = document.getElementById('priorityInput').value;
    if (!task) return;

    fetch('/api/todos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task, due_date, priority }),
    }).then(r => r.json()).then(data => {
      if (!data.success) { showToast(data.error || 'Failed to add task', 'error'); return; }
      document.getElementById('emptyTodo')?.remove();

      const li = document.createElement('li');
      li.className = 'todo-item';
      li.dataset.id = data.id;
      li.innerHTML = `
        <input type="checkbox" class="todo-check">
        <span class="todo-text" contenteditable="true">${escapeHtmlT(task)}</span>
        <span class="badge badge-${priority}">${priority.charAt(0).toUpperCase() + priority.slice(1)}</span>
        <span class="todo-date">${due_date || ''}</span>
        <button class="icon-btn danger todo-delete"><i class="fa-solid fa-trash"></i></button>
      `;
      todoList.appendChild(li);
      bindTodoItem(li);

      todoForm.reset();
      showToast('Task added!', 'success');
    });
  });
}

function escapeHtmlT(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
