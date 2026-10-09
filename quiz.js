/* ==========================================================
   StudyGenie AI — quiz.js
========================================================== */
const generateQuizBtn = document.getElementById('generateQuizBtn');
let currentQuiz = [];
let currentSubject = '';
let userAnswers = [];

const QUIZ_SIZE = 10;

function setQuizState(state, message, retryable) {
  // state: 'loading' | 'success' | 'error' | 'idle'
  const loading = document.getElementById('quizLoading');
  const errorBox = document.getElementById('quizError');
  const errorText = document.getElementById('quizErrorText');
  const retryBtn = document.getElementById('quizRetryBtn');

  loading.classList.toggle('hidden', state !== 'loading');
  errorBox.classList.toggle('hidden', state !== 'error');
  generateQuizBtn.disabled = state === 'loading';
  if (state === 'error') {
    errorText.textContent = message || 'Failed to generate the quiz. Please try again.';
    retryBtn.classList.toggle('hidden', retryable === false);
  }
}

function isValidQuiz(quiz) {
  return Array.isArray(quiz) && quiz.length === QUIZ_SIZE && quiz.every(q =>
    q && typeof q.question === 'string' && q.question.trim() &&
    Array.isArray(q.options) && q.options.length === 4 &&
    q.options.every(o => typeof o === 'string' && o.trim()) &&
    Number.isInteger(q.correct_index) && q.correct_index >= 0 && q.correct_index < 4);
}

async function generateQuiz() {
  const select = document.getElementById('quizSyllabusSelect');
  const syllabusId = select.value;
  currentSubject = select.options[select.selectedIndex].dataset.subject || 'General';

  const container = document.getElementById('quizContainer');
  const resultBox = document.getElementById('quizResult');
  container.innerHTML = '';
  resultBox.classList.add('hidden');
  resultBox.innerHTML = '';
  currentQuiz = [];
  setQuizState('loading');

  try {
    const res = await fetch('/api/generate-quiz', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ syllabus_id: syllabusId }),
    });
    let data = null;
    try { data = await res.json(); } catch (e) { /* non-JSON body (e.g. server error page) */ }

    if (!res.ok || !data || data.error) {
      const msg = (data && data.error) || (res.status === 401 || res.redirected
        ? 'Your session has expired. Please log in again.'
        : 'The server returned an error while generating the quiz.');
      setQuizState('error', msg, data ? data.retryable !== false : true);
      return;
    }
    if (!isValidQuiz(data.quiz)) {
      setQuizState('error', 'The AI returned an incomplete quiz. Please retry.', true);
      return;
    }
    currentQuiz = data.quiz;
    userAnswers = new Array(currentQuiz.length).fill(null);
    setQuizState('success');
    renderQuiz();
    showToast('Quiz generated! Good luck 🍀', 'success');
  } catch (err) {
    setQuizState('error', 'Could not reach the server. Check your connection and retry.', true);
  }
}

if (generateQuizBtn) {
  generateQuizBtn.addEventListener('click', generateQuiz);
  const retryBtn = document.getElementById('quizRetryBtn');
  if (retryBtn) retryBtn.addEventListener('click', generateQuiz);
}

function renderQuiz() {
  const container = document.getElementById('quizContainer');
  container.innerHTML = currentQuiz.map((q, qi) => `
    <div class="quiz-question" data-qi="${qi}">
      <h4>${qi + 1}. ${escapeHtmlQ(q.question)}</h4>
      <div class="quiz-options">
        ${q.options.map((opt, oi) => `
          <div class="quiz-option" data-oi="${oi}" onclick="selectOption(${qi}, ${oi})">
            ${String.fromCharCode(65 + oi)}. ${escapeHtmlQ(opt)}
          </div>
        `).join('')}
      </div>
      <div class="quiz-explanation" id="explain-${qi}">
        <i class="fa-solid fa-lightbulb"></i> ${escapeHtmlQ(q.explanation || '')}
      </div>
    </div>
  `).join('') + `
    <button class="btn btn-primary btn-block" id="submitQuizBtn" onclick="submitQuiz()">
      <i class="fa-solid fa-paper-plane"></i> Submit Quiz
    </button>
  `;
}

function selectOption(qIndex, oIndex) {
  userAnswers[qIndex] = oIndex;
  const questionBlock = document.querySelector(`.quiz-question[data-qi="${qIndex}"]`);
  questionBlock.querySelectorAll('.quiz-option').forEach(el => el.classList.remove('selected'));
  questionBlock.querySelector(`.quiz-option[data-oi="${oIndex}"]`).classList.add('selected');
}

async function submitQuiz() {
  if (userAnswers.includes(null)) {
    showToast('Please answer all questions before submitting.', 'error');
    return;
  }

  let score = 0;
  currentQuiz.forEach((q, qi) => {
    const questionBlock = document.querySelector(`.quiz-question[data-qi="${qi}"]`);
    const options = questionBlock.querySelectorAll('.quiz-option');
    const correctIdx = q.correct_index;
    const chosenIdx = userAnswers[qi];

    options[correctIdx].classList.add('correct');
    if (chosenIdx !== correctIdx) {
      options[chosenIdx].classList.add('incorrect');
    } else {
      score++;
    }
    document.getElementById(`explain-${qi}`).classList.add('show');
    options.forEach(o => o.onclick = null);
  });

  document.getElementById('submitQuizBtn').remove();

  const resultBox = document.getElementById('quizResult');
  resultBox.classList.remove('hidden');
  resultBox.innerHTML = `
    <div class="quiz-score-banner">
      <h2>${score} / ${currentQuiz.length}</h2>
      <p>${score >= currentQuiz.length * 0.7 ? 'Great job! 🎉' : 'Keep practicing — you\'ll improve! 💪'}</p>
    </div>
  `;

  // Per-chapter breakdown feeds the Weak Topic Detection module
  const answers = currentQuiz.map((q, qi) => ({
    chapter: q.chapter || currentSubject,
    question: q.question,
    is_correct: userAnswers[qi] === q.correct_index,
  }));

  try {
    const res = await fetch('/api/submit-quiz', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subject: currentSubject, score, total: currentQuiz.length, answers }),
    });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error('save failed');
    showToast('Quiz submitted and score saved!', 'success');
    showBadgeToasts(data.new_badges);
  } catch (err) {
    showToast('Your score could not be saved. Please check your connection.', 'error');
  }
}

function escapeHtmlQ(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
