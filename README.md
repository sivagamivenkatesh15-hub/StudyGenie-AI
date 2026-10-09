# 🧠 StudyGenie AI — Smart Study Planner with AI Assistant

A complete, modern, full-stack AI-powered study companion built with **Flask + SQLite + Google Gemini API**.
Glassmorphism UI, gradient colors, dark/light mode, animated dashboard, and 15+ AI-powered study tools.

---

## ✨ Features

| # | Feature | Description |
|---|---------|-------------|
| 1 | Landing Page | Hero, features, about, get started |
| 2 | Auth | Login / Register / Logout / Forgot & Reset Password (SQLite + hashed passwords + Remember Me) |
| 3 | Dashboard | Exams, today's plan, progress %, streak, hours, weekly graph, quote |
| 4 | Upload Syllabus | PDF upload, text extraction (PyPDF2), auto topic detection |
| 5 | AI Study Planner | Exam date + hours + difficulty + priority subjects → day-wise plan |
| 6 | Smart Timetable | Daily / Weekly views, inline editing, delete sessions |
| 8 | AI Notes Generator | Short notes / chapter summary / important points |
| 9 | AI Quiz Generator | 10 MCQs, 4 options, instant score, explanations |
| 10 | Progress Dashboard | Chapters completed, hours, weekly & monthly graphs, subject-wise % |
| 11 | AI Revision Planner | Auto revision timetable from remaining topics |
| 12 | Performance Prediction | Readiness %, weak/strong subjects, recommendations |
| 13 | To-Do List | Add / edit / delete / complete tasks |
| 14 | Reminders | Study / assignment / exam countdown reminders |
| 15 | Settings | Dark mode, profile update, change password |
| 16 | **Weak Topic Detection** | Analyzes quiz history to surface weak chapters, accuracy %, wrong-answer counts, priority levels & AI recommendations |
| 17 | **Smart Revision Planner** | Spaced-repetition schedule (1 → 3 → 7 → 14 → 30 days) auto-generated after every completed study session |
| 18 | **Productivity Analytics** | Bar / pie / line / doughnut charts with Today / Week / Month / Overall filters |
| 19 | **Gamification System** | XP points, levels, streaks, and auto-unlocking achievement badges |

### 🆕 New Module Details

**Weak Topic Detection** (`/weak-topics`)
Every quiz question you answer is logged with its chapter in `quiz_history`. This module aggregates
accuracy per chapter/subject, flags chapters with low accuracy or too few attempts, and produces
a sorted "Study Priority List" plus AI-generated (or fallback deterministic) recommendations.

**Smart Revision Planner** (`/smart-revision`)
Uses spaced repetition. The moment you mark a Timetable session complete, StudyGenie schedules
the 1st revision (+1 day). Each time you mark a revision "Done," the *next* stage is scheduled
automatically (+3, +7, +14, then a Final Revision at +30 days) — a real, adaptive spaced-repetition
chain rather than a fixed calendar.

**Productivity Analytics Dashboard** (`/analytics?range=today|week|month|all`)
Combines `study_sessions` and `quiz_results` into a bar chart (hours over time), pie chart
(subject-wise time), line chart (quiz score trend), and doughnut chart (topic completion),
plus stat cards for streak, average quiz score, and sessions completed.

**Gamification System** (`/achievements`)
Every completed study session, quiz, and revision awards XP (visible as a Level pill in the
topbar on every page). Badges unlock automatically — First Study Session, 7-Day Streak, Quiz
Master, Study Champion, Revision Expert, and XP milestones (100/500/1000) — with an achievement
history log.

> **Design note:** the new pages reuse StudyGenie's existing glassmorphism component library
> (`.panel-card`, `.stat-card`, `.badge`, `.progress-bar`, etc.) rather than introducing Bootstrap 5
> alongside it, so the whole app — old and new pages — stays visually and stylistically consistent,
> including full dark/light mode support.

---

## 🛠 Tech Stack

- **Frontend:** HTML5, CSS3 (glassmorphism + gradients), Vanilla JavaScript, Chart.js, Font Awesome
- **Backend:** Python Flask
- **Database:** SQLite
- **AI:** Google Gemini API (`google-generativeai`)
- **PDF Processing:** PyPDF2

---

## 📁 Project Structure

```
StudyGenieAI/
│── app.py                  # Flask backend — all routes, DB logic, AI integration
│── requirements.txt
│── .env.example             # Copy to .env and fill in your keys
│── database.db               # Auto-created on first run
│── static/
│   ├── css/style.css         # Glassmorphism + dark/light theme + responsive layout
│   ├── js/
│   │   ├── main.js           # Theme toggle, sidebar, toast notifications
││   │   ├── notes.js
│   │   ├── quiz.js
│   │   ├── todo.js
│   │   └── settings.js
│   └── images/
│── templates/
│   ├── index.html            # Landing page
│   ├── login.html / register.html
│   ├── base.html             # Shared dashboard layout (sidebar, topbar)
│   ├── dashboard.html
│   ├── upload.html
│   ├── planner.html
│   ├── timetable.html
│   ├── notes.html
│   ├── quiz.html
│   ├── progress.html         # Also used for Performance Prediction view
│   ├── todo.html
│   ├── reminders.html
│   ├── settings.html
│   └── 404.html
│── uploads/                  # Uploaded syllabus PDFs are stored here
```

---

## 🚀 Installation & Setup

### 1. Clone / extract the project
```bash
cd StudyGenieAI
```

### 2. Create a virtual environment (recommended)
```bash
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure your Gemini API key (optional but recommended)
Get a free API key from **https://aistudio.google.com/app/apikey**, then either:

**Option A — .env file (recommended)**
```bash
cp .env.example .env
# then edit .env and set:
# GEMINI_API_KEY=your-key-here
```

**Option B — export as environment variable**
```bash
export GEMINI_API_KEY="your-key-here"      # Windows (PowerShell): $env:GEMINI_API_KEY="your-key-here"
```

> ⚠️ If no API key is set, the app still runs. The AI Quiz shows a clear error with a Retry button
> (it never shows fake questions); AI Notes shows an "AI unavailable" message.

### 5. Run the app
```bash
python app.py
```

The SQLite database (`database.db`) and all tables are created automatically on first run.

### 6. Open your browser
```
http://127.0.0.1:5000
```

---

## 🗄 SQLite Database Schema

```sql
users(id, name, email, password_hash, avatar, study_streak, last_study_date, created_at)
syllabus(id, user_id, subject, filename, extracted_text, uploaded_at)
topics(id, user_id, syllabus_id, subject, topic_name, completed, created_at)
study_plans(id, user_id, exam_date, daily_hours, difficulty, priority_subjects, plan_json, created_at)
plan_days(id, plan_id, user_id, day_date, subject, topic, hours, session_type, completed)
todos(id, user_id, task, due_date, priority, completed, created_at)
reminders(id, user_id, type, title, reminder_date, notes, created_at)
quiz_results(id, user_id, subject, score, total, created_at)
study_sessions(id, user_id, session_date, hours, subject)

-- New tables --
quiz_history(id, user_id, subject, chapter, question, is_correct, created_at)
revision_schedule(id, user_id, subject, topic, study_date, stage, revision_date, completed, completed_at, created_at)
achievements(id, user_id, badge_key, badge_name, description, icon, xp_reward, unlocked_at)
user_progress(id, user_id, xp, level, updated_at)
study_statistics(id, user_id, stat_date, hours, sessions_completed, created_at)
```

> Existing databases don't need manual migration — `init_db()` uses `CREATE TABLE IF NOT EXISTS`,
> so the new tables are added automatically the next time you run `python app.py`.

All tables are created automatically by `init_db()` in `app.py` — no manual migration needed.

---

## 🔌 Key Flask Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `/` | GET | Landing page |
| `/register`, `/login`, `/logout` | GET/POST | Authentication |
| `/dashboard` | GET | Main dashboard |
| `/upload` | GET/POST | Upload & parse syllabus PDF |
| `/planner` | GET/POST | Generate AI study plan |
| `/timetable` | GET | Daily/weekly timetable + editing |
| `/revision` | GET | AI-generated revision plan |
| `/notes` | GET | Notes generator UI |
| `/api/generate-notes` | POST | Gemini notes generation |
| `/quiz` | GET | Quiz generator UI |
| `/api/generate-quiz` | POST | Gemini MCQ generation |
| `/api/submit-quiz` | POST | Save quiz score |
| `/progress` | GET | Progress dashboard + charts |
| `/performance` | GET | Readiness % & recommendations |
| `/todo`, `/api/todos` | GET/POST/PUT/DELETE | To-do list CRUD |
| `/reminders`, `/api/reminders` | GET/POST/DELETE | Reminder CRUD |
| `/settings`, `/api/settings/*` | GET/POST | Profile & password updates |

---

## 🔐 Notes on Security & Production

- Passwords are hashed with Werkzeug's `generate_password_hash` / `check_password_hash`.
- Set a strong, random `SECRET_KEY` in `.env` before deploying.
- `debug=True` is enabled for local development in `app.py` — **turn this off in production**
  (`app.run(debug=False)`) and serve with a production WSGI server (e.g. Gunicorn) behind Nginx.
- Uploaded files are limited to PDF and 16 MB by default (`MAX_CONTENT_LENGTH`).

---

## 🧩 Extending the App

- Swap the rule-based `generate_study_plan()` in `app.py` for a Gemini-generated plan for even more
  personalized schedules.
- Add email/SMS delivery for reminders (e.g. via Flask-Mail or Twilio).
- Add OAuth login (Google) using `Flask-Dance` or `Authlib`.

Enjoy studying smarter with **StudyGenie AI**! 🚀
