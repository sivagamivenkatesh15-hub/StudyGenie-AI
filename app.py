"""
StudyGenie AI - Smart Study Planner with AI Assistant
Flask backend application.

Run with:  python app.py
"""

import os
import json
import sqlite3
import random
import string
import re
import secrets
from datetime import datetime, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()  # Loads variables from a .env file in the project root, if present
except ImportError:
    pass

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, flash, g
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import PyPDF2

# ----------------------------------------------------------------------------
# Gemini AI integration (server-side only - the API key never reaches the browser)
# ----------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-3.5-flash-lite"
GEMINI_TIMEOUT_SECONDS = 90

genai = None
try:
    import google.generativeai as genai
except Exception as _import_err:  # SDK not installed
    print(f"[Gemini] google-generativeai could not be imported: {_import_err}")

# True when both the SDK and an API key are available (used for the startup banner
# and for optional AI extras such as weak-topic recommendations).
GEMINI_ENABLED = bool(genai and GEMINI_API_KEY)
_configured_key = None


class GeminiError(Exception):
    """Raised when a Gemini request cannot produce a usable response.

    code       - short machine readable reason (shown to the frontend)
    http_status- status the API route should answer with
    retryable  - whether pressing "Retry" in the UI could plausibly succeed
    """

    def __init__(self, message, code="gemini_error", http_status=502, retryable=True):
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status
        self.retryable = retryable


def _classify_gemini_exception(exc):
    """Translate an SDK/network exception into a GeminiError with a clear message."""
    name = type(exc).__name__
    text = str(exc)
    low = text.lower()

    if name == "ResourceExhausted" or "429" in text or "quota" in low or "rate limit" in low:
        return GeminiError(
            "The Gemini API quota or rate limit has been reached. Please wait a minute and "
            "retry, or check your quota in Google AI Studio.",
            "quota_exceeded", 429, True)
    if name in ("InvalidArgument", "PermissionDenied", "Unauthenticated") and (
            "api key" in low or "api_key" in low or "permission" in low or "unauthenticated" in low):
        return GeminiError(
            "The Gemini API key was rejected. Check GEMINI_API_KEY in your .env file.",
            "invalid_api_key", 401, False)
    if "api key not valid" in low or "api_key_invalid" in low:
        return GeminiError(
            "The Gemini API key was rejected. Check GEMINI_API_KEY in your .env file.",
            "invalid_api_key", 401, False)
    if name == "NotFound" or "404" in text or "is not found" in low:
        return GeminiError(
            f"Gemini model '{GEMINI_MODEL_NAME}' was not found or is no longer available. "
            "Set GEMINI_MODEL in your .env file to a current model, e.g. gemini-2.5-flash.",
            "model_not_found", 502, False)
    if name in ("DeadlineExceeded", "ServiceUnavailable", "InternalServerError", "GatewayTimeout") \
            or "timed out" in low or "timeout" in low or "503" in text or "unavailable" in low:
        return GeminiError(
            "The Gemini service timed out or is temporarily unavailable. Please retry.",
            "gemini_unavailable", 503, True)
    if "connection" in low or "network" in low or "dns" in low:
        return GeminiError(
            "Could not reach the Gemini API. Check your internet connection and retry.",
            "network_error", 503, True)
    return GeminiError(f"Gemini API request failed ({name}). Please retry.", "gemini_error", 502, True)


def generate_with_gemini(prompt, system_instruction=None, json_output=False, temperature=None):
    """Strict Gemini call: returns the response text or raises GeminiError.

    Never returns fabricated/fallback content. The key is read from the
    environment at call time so a corrected .env is picked up after restart.
    """
    global _configured_key
    key = (GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", "")).strip()
    if genai is None:
        raise GeminiError(
            "The Gemini SDK is not installed. Run: pip install -r requirements.txt",
            "sdk_missing", 503, False)
    if not key:
        raise GeminiError(
            "GEMINI_API_KEY is not configured. Add it to your .env file and restart the app.",
            "missing_api_key", 503, False)

    try:
        if _configured_key != key:
            genai.configure(api_key=key)
            _configured_key = key
        gen_config = {}
        if json_output:
            gen_config["response_mime_type"] = "application/json"
        if temperature is not None:
            gen_config["temperature"] = temperature
        model = genai.GenerativeModel(
            GEMINI_MODEL_NAME,
            system_instruction=system_instruction,
            generation_config=gen_config or None,
        )
        response = model.generate_content(prompt, request_options={"timeout": GEMINI_TIMEOUT_SECONDS})
    except GeminiError:
        raise
    except Exception as exc:
        print(f"[Gemini Error] {type(exc).__name__}: {exc}")
        raise _classify_gemini_exception(exc)

    try:
        text = (response.text or "").strip()
    except Exception as exc:  # .text raises when the response was blocked / has no parts
        print(f"[Gemini Error] unreadable response: {exc}")
        raise GeminiError(
            "Gemini returned no usable content (the response may have been blocked). Please retry.",
            "empty_response", 502, True)
    if not text:
        raise GeminiError("Gemini returned an empty response. Please retry.", "empty_response", 502, True)
    return text


def call_gemini(prompt, system_instruction=None):
    """
    Lenient Gemini call used by AI Notes and other optional AI extras.
    Falls back to a generic message if Gemini is unavailable so those pages
    never crash. The AI Quiz does NOT use this - it uses generate_with_gemini()
    so that failures are reported instead of replaced by fake content.
    """
    try:
        return generate_with_gemini(prompt, system_instruction=system_instruction)
    except GeminiError as e:
        print(f"[Gemini Error] {e.code}: {e.message}")
        return _fallback_ai_response(prompt)


def _fallback_ai_response(prompt):
    """A safe, deterministic fallback used when Gemini is unavailable (Notes etc. only)."""
    return (
        "The AI service is currently unavailable (check GEMINI_API_KEY, model and quota).\n\n"
        f"You asked about: '{prompt[:200]}'.\n"
        "Please fix the Gemini configuration and try again."
    )


# ----------------------------------------------------------------------------
# Optional SMTP email integration (used by the Forgot Password flow).
# If no SMTP server is configured, reset links are surfaced directly in the
# UI/console instead of failing, so the flow stays fully testable locally.
# ----------------------------------------------------------------------------
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
MAIL_FROM = os.environ.get("MAIL_FROM", SMTP_USER)
MAIL_ENABLED = bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)
RESET_TOKEN_VALID_MINUTES = 30


def send_password_reset_email(to_email, name, reset_url):
    """Send a password reset email over SMTP. Silently logs failures so a
    misconfigured mail server never breaks the reset flow for the user."""
    import smtplib
    from email.mime.text import MIMEText

    subject = "Reset your StudyGenie AI password"
    body = (
        f"Hi {name},\n\n"
        "We received a request to reset your StudyGenie AI password. "
        f"Click the link below to choose a new password (valid for {RESET_TOKEN_VALID_MINUTES} minutes):\n\n"
        f"{reset_url}\n\n"
        "If you didn't request this, you can safely ignore this email.\n\n"
        "— StudyGenie AI"
    )
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = MAIL_FROM
    msg["To"] = to_email

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(MAIL_FROM, [to_email], msg.as_string())
    except Exception as e:
        print(f"[Email Error] Could not send password reset email: {e}")


# ----------------------------------------------------------------------------
# Flask app configuration
# ----------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "database.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"pdf"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "studygenie-super-secret-key-change-me")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max upload

# --- Session security / "Remember Me" support -------------------------------
# When "Remember Me" is checked, session.permanent=True and the cookie lives
# for PERMANENT_SESSION_LIFETIME. When unchecked, the cookie is a normal
# (non-permanent) session cookie that expires when the browser closes.
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Only force secure cookies in production (HTTPS). Leave off for local http dev.
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FORCE_HTTPS", "false").lower() == "true"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ----------------------------------------------------------------------------
# Database helpers
# ----------------------------------------------------------------------------
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def init_db():
    """Create all tables if they do not already exist."""
    schema = """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        avatar TEXT DEFAULT 'default_avatar.png',
        study_streak INTEGER DEFAULT 0,
        last_study_date TEXT,
        reset_token TEXT,
        reset_token_expiry TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS syllabus (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        filename TEXT NOT NULL,
        extracted_text TEXT,
        uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        syllabus_id INTEGER,
        subject TEXT NOT NULL,
        topic_name TEXT NOT NULL,
        completed INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (syllabus_id) REFERENCES syllabus(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS study_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        exam_date TEXT NOT NULL,
        daily_hours REAL NOT NULL,
        difficulty TEXT,
        priority_subjects TEXT,
        plan_json TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS plan_days (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        day_date TEXT NOT NULL,
        subject TEXT NOT NULL,
        topic TEXT,
        hours REAL DEFAULT 1,
        session_type TEXT DEFAULT 'study',
        completed INTEGER DEFAULT 0,
        FOREIGN KEY (plan_id) REFERENCES study_plans(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS todos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        task TEXT NOT NULL,
        due_date TEXT,
        priority TEXT DEFAULT 'medium',
        completed INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        title TEXT NOT NULL,
        reminder_date TEXT NOT NULL,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS quiz_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        subject TEXT,
        score INTEGER NOT NULL,
        total INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS study_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        session_date TEXT NOT NULL,
        hours REAL NOT NULL,
        subject TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    -- ==========================================================
    -- NEW: Weak Topic Detection — per-question quiz attempt log
    -- ==========================================================
    CREATE TABLE IF NOT EXISTS quiz_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        chapter TEXT NOT NULL,
        question TEXT,
        is_correct INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    -- ==========================================================
    -- NEW: Smart Revision Planner — spaced repetition schedule
    -- ==========================================================
    CREATE TABLE IF NOT EXISTS revision_schedule (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        topic TEXT NOT NULL,
        study_date TEXT NOT NULL,
        stage INTEGER NOT NULL,
        revision_date TEXT NOT NULL,
        completed INTEGER DEFAULT 0,
        completed_at TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    -- ==========================================================
    -- NEW: Gamification — unlocked achievements / badges
    -- ==========================================================
    CREATE TABLE IF NOT EXISTS achievements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        badge_key TEXT NOT NULL,
        badge_name TEXT NOT NULL,
        description TEXT,
        icon TEXT,
        xp_reward INTEGER DEFAULT 0,
        unlocked_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, badge_key)
    );

    -- ==========================================================
    -- NEW: Gamification — XP / Level tracker (one row per user)
    -- ==========================================================
    CREATE TABLE IF NOT EXISTS user_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE,
        xp INTEGER DEFAULT 0,
        level INTEGER DEFAULT 1,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    -- ==========================================================
    -- NEW: Productivity Analytics — daily study stat cache
    -- ==========================================================
    CREATE TABLE IF NOT EXISTS study_statistics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        stat_date TEXT NOT NULL,
        hours REAL DEFAULT 0,
        sessions_completed INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, stat_date)
    );
    """
    conn = sqlite3.connect(DATABASE)
    conn.executescript(schema)
    conn.execute("DROP TABLE IF EXISTS chat_history")  # chatbot removed

    # --- Safe migration for pre-existing databases created before the ---
    # --- Forgot Password feature was added (adds columns if missing). ---
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "reset_token" not in existing_cols:
        conn.execute("ALTER TABLE users ADD COLUMN reset_token TEXT")
    if "reset_token_expiry" not in existing_cols:
        conn.execute("ALTER TABLE users ADD COLUMN reset_token_expiry TEXT")

    conn.commit()
    conn.close()


# ----------------------------------------------------------------------------
# Auth helpers / decorators
# ----------------------------------------------------------------------------
from functools import wraps


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Not authenticated"}), 401
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def current_user():
    if "user_id" not in session:
        return None
    db = get_db()
    return db.execute(
        "SELECT * FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(email):
    return bool(email) and bool(EMAIL_REGEX.match(email))


@app.context_processor
def inject_nav_progress():
    """Makes XP/Level available to base.html (topbar pill) on every page
    without every route needing to pass it explicitly."""
    if "user_id" in session:
        try:
            progress = get_or_create_progress(session["user_id"])
            return {"nav_xp": progress["xp"], "nav_level": progress["level"]}
        except Exception:
            return {"nav_xp": 0, "nav_level": 1}
    return {"nav_xp": 0, "nav_level": 1}


MOTIVATION_QUOTES = [
    "Success is the sum of small efforts repeated day in and day out.",
    "The expert in anything was once a beginner.",
    "Don't watch the clock; do what it does. Keep going.",
    "Believe you can and you're halfway there.",
    "Study while others are sleeping; work while others are loafing.",
    "Your future is created by what you do today, not tomorrow.",
    "Push yourself, because no one else is going to do it for you.",
    "Small daily improvements lead to stunning results.",
    "The pain of discipline is far less than the pain of regret.",
    "Dream big, study hard, stay focused.",
]


# ==============================================================================
# NEW FEATURE — Gamification System (XP, Levels, Badges)
# ==============================================================================
XP_PER_LEVEL = 100  # flat XP required per level


def get_or_create_progress(uid):
    """Fetch the user's XP/level row, creating one on first use."""
    db = get_db()
    row = db.execute("SELECT * FROM user_progress WHERE user_id = ?", (uid,)).fetchone()
    if not row:
        db.execute("INSERT INTO user_progress (user_id, xp, level) VALUES (?, 0, 1)", (uid,))
        db.commit()
        row = db.execute("SELECT * FROM user_progress WHERE user_id = ?", (uid,)).fetchone()
    return row


def get_xp(uid):
    return get_or_create_progress(uid)["xp"]


def award_xp(uid, amount):
    """Add XP to a user and recompute their level. Returns (new_level, leveled_up)."""
    db = get_db()
    progress = get_or_create_progress(uid)
    if amount <= 0:
        return progress["level"], False

    db.execute(
        "UPDATE user_progress SET xp = xp + ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
        (amount, uid),
    )
    db.commit()
    row = db.execute("SELECT * FROM user_progress WHERE user_id = ?", (uid,)).fetchone()
    new_level = (row["xp"] // XP_PER_LEVEL) + 1
    leveled_up = new_level > row["level"]
    if leveled_up:
        db.execute("UPDATE user_progress SET level = ? WHERE user_id = ?", (new_level, uid))
        db.commit()
    return new_level, leveled_up


def _badge_quiz_master(uid, db):
    rows = db.execute("SELECT score, total FROM quiz_results WHERE user_id=?", (uid,)).fetchall()
    if len(rows) < 5:
        return False
    avg = sum((r["score"] / r["total"] * 100) for r in rows if r["total"]) / len(rows)
    return avg >= 80


# Badge catalogue: key, display name, description, Font Awesome icon, XP reward,
# and a check(uid, db) function returning True once the badge should unlock.
BADGES = [
    {
        "key": "first_session", "name": "First Study Session",
        "desc": "Completed your very first study session.", "icon": "fa-seedling", "xp": 10,
        "check": lambda uid, db: db.execute(
            "SELECT COUNT(*) c FROM study_sessions WHERE user_id=?", (uid,)
        ).fetchone()["c"] >= 1,
    },
    {
        "key": "streak_7", "name": "7-Day Streak",
        "desc": "Studied 7 days in a row.", "icon": "fa-fire", "xp": 50,
        "check": lambda uid, db: (db.execute(
            "SELECT study_streak FROM users WHERE id=?", (uid,)
        ).fetchone()["study_streak"] or 0) >= 7,
    },
    {
        "key": "quiz_master", "name": "Quiz Master",
        "desc": "Averaged 80%+ across at least 5 quizzes.", "icon": "fa-crown", "xp": 60,
        "check": _badge_quiz_master,
    },
    {
        "key": "study_champion", "name": "Study Champion",
        "desc": "Studied for 50+ total hours.", "icon": "fa-trophy", "xp": 100,
        "check": lambda uid, db: (db.execute(
            "SELECT COALESCE(SUM(hours),0) h FROM study_sessions WHERE user_id=?", (uid,)
        ).fetchone()["h"] or 0) >= 50,
    },
    {
        "key": "revision_expert", "name": "Revision Expert",
        "desc": "Completed 10 spaced-repetition revisions.", "icon": "fa-rotate", "xp": 40,
        "check": lambda uid, db: db.execute(
            "SELECT COUNT(*) c FROM revision_schedule WHERE user_id=? AND completed=1", (uid,)
        ).fetchone()["c"] >= 10,
    },
    {
        "key": "xp_100", "name": "100 XP Club", "desc": "Earned 100 XP.", "icon": "fa-star", "xp": 0,
        "check": lambda uid, db: get_xp(uid) >= 100,
    },
    {
        "key": "xp_500", "name": "500 XP Club", "desc": "Earned 500 XP.", "icon": "fa-star-half-stroke", "xp": 0,
        "check": lambda uid, db: get_xp(uid) >= 500,
    },
    {
        "key": "xp_1000", "name": "1000 XP Club", "desc": "Earned 1000 XP.", "icon": "fa-meteor", "xp": 0,
        "check": lambda uid, db: get_xp(uid) >= 1000,
    },
]


def check_and_award_badges(uid):
    """Evaluate all badge conditions for a user and unlock any newly-earned ones.
    Returns a list of newly unlocked badge dicts (for toast notifications)."""
    db = get_db()
    get_or_create_progress(uid)
    existing = {r["badge_key"] for r in db.execute(
        "SELECT badge_key FROM achievements WHERE user_id=?", (uid,)
    ).fetchall()}

    newly_unlocked = []
    for badge in BADGES:
        if badge["key"] in existing:
            continue
        try:
            if badge["check"](uid, db):
                db.execute(
                    """INSERT INTO achievements (user_id, badge_key, badge_name, description, icon, xp_reward)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (uid, badge["key"], badge["name"], badge["desc"], badge["icon"], badge["xp"]),
                )
                db.commit()
                if badge["xp"] > 0:
                    award_xp(uid, badge["xp"])
                newly_unlocked.append(badge)
        except Exception as e:
            print(f"[Badge check error] {badge['key']}: {e}")
    return newly_unlocked


# ==============================================================================
# NEW FEATURE — Smart Revision Planner (Spaced Repetition)
# ==============================================================================
# Study Today -> +1 day -> +3 days -> +7 days -> +14 days -> Final Revision (+30 days)
# Each gap is counted from the date the *previous* stage was completed, so the
# schedule adapts automatically to when the learner actually revises.
REVISION_STAGES = {
    1: {"label": "1st Revision", "gap_days": 1},
    2: {"label": "2nd Revision", "gap_days": 3},
    3: {"label": "3rd Revision", "gap_days": 7},
    4: {"label": "4th Revision", "gap_days": 14},
    5: {"label": "Final Revision", "gap_days": 30},
}
MAX_REVISION_STAGE = 5


def schedule_next_revision(uid, subject, topic, stage, base_date):
    """Insert the next spaced-repetition revision row, gap_days after base_date."""
    stage_info = REVISION_STAGES.get(stage)
    if not stage_info:
        return
    db = get_db()
    revision_date = base_date + timedelta(days=stage_info["gap_days"])
    db.execute(
        """INSERT INTO revision_schedule (user_id, subject, topic, study_date, stage, revision_date)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (uid, subject, topic, base_date.strftime("%Y-%m-%d"), stage, revision_date.strftime("%Y-%m-%d")),
    )
    db.commit()


# ----------------------------------------------------------------------------
# Public pages
# ----------------------------------------------------------------------------
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    # Prevent already-authenticated users from landing back on auth pages
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        # --- Validation (Full Name, Email, Password only — no Confirm Password) ---
        if not name or not email or not password:
            flash("Full name, email and password are all required.", "danger")
            return redirect(url_for("register"))
        if not is_valid_email(email):
            flash("Please enter a valid email address.", "danger")
            return redirect(url_for("register"))
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return redirect(url_for("register"))

        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            flash("An account with this email already exists. Please sign in instead.", "danger")
            return redirect(url_for("register"))

        password_hash = generate_password_hash(password)
        db.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, password_hash),
        )
        db.commit()
        flash("Account created successfully! Please sign in to continue.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    # Prevent already-authenticated users from unnecessarily seeing the login page
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember_me = request.form.get("remember_me") == "on"

        if not email or not password:
            flash("Please enter both email and password.", "danger")
            return redirect(url_for("login"))

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        # Generic error message — never reveal whether the email exists or the
        # password was wrong, to avoid leaking account information.
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "danger")
            return redirect(url_for("login"))

        session.clear()
        session["user_id"] = user["id"]
        session["user_name"] = user["name"]

        # --- Remember Me: controls whether the session cookie persists ---
        # Checked   -> permanent session, lasts PERMANENT_SESSION_LIFETIME (30 days)
        # Unchecked -> normal session, cleared when the browser is closed
        session.permanent = remember_me

        flash(f"Welcome back, {user['name']}!", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out successfully.", "info")
    return redirect(url_for("login"))


# ----------------------------------------------------------------------------
# Forgot Password / Reset Password
# ----------------------------------------------------------------------------
@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    reset_link = None  # only populated in local/dev mode when no mail server is configured

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        if not is_valid_email(email):
            flash("Please enter a valid email address.", "danger")
            return redirect(url_for("forgot_password"))

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        # Always show the same confirmation message whether or not the email
        # exists, so we never reveal which emails are registered.
        if user:
            token = secrets.token_urlsafe(32)
            expiry = (datetime.now() + timedelta(minutes=RESET_TOKEN_VALID_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
            db.execute(
                "UPDATE users SET reset_token = ?, reset_token_expiry = ? WHERE id = ?",
                (token, expiry, user["id"]),
            )
            db.commit()

            reset_url = url_for("reset_password", token=token, _external=True)

            if MAIL_ENABLED:
                send_password_reset_email(user["email"], user["name"], reset_url)
            else:
                # No email server configured in this environment — surface the
                # link directly so the reset flow is still fully testable.
                reset_link = reset_url
                print(f"[Password Reset] No mail server configured. Reset link for {email}: {reset_url}")

        flash("If an account with that email exists, a password reset link has been sent.", "info")
        return render_template("forgot_password.html", reset_link=reset_link, submitted=True)

    return render_template("forgot_password.html", reset_link=None, submitted=False)


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE reset_token = ?", (token,)).fetchone()

    token_valid = bool(user) and user["reset_token_expiry"] and \
        datetime.strptime(user["reset_token_expiry"], "%Y-%m-%d %H:%M:%S") > datetime.now()

    if not token_valid:
        flash("This password reset link is invalid or has expired. Please request a new one.", "danger")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(new_password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return redirect(url_for("reset_password", token=token))
        if new_password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("reset_password", token=token))

        new_hash = generate_password_hash(new_password)
        db.execute(
            "UPDATE users SET password_hash = ?, reset_token = NULL, reset_token_expiry = NULL WHERE id = ?",
            (new_hash, user["id"]),
        )
        db.commit()
        flash("Your password has been reset successfully. Please sign in.", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html", token=token)


# ----------------------------------------------------------------------------
# Dashboard
# ----------------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    uid = session["user_id"]
    user = current_user()

    # Upcoming exams (from study plans)
    upcoming_exams = db.execute(
        """SELECT DISTINCT exam_date, priority_subjects FROM study_plans
           WHERE user_id = ? AND exam_date >= ? ORDER BY exam_date ASC LIMIT 5""",
        (uid, datetime.now().strftime("%Y-%m-%d")),
    ).fetchall()

    # Today's study plan
    today = datetime.now().strftime("%Y-%m-%d")
    todays_plan = db.execute(
        """SELECT * FROM plan_days WHERE user_id = ? AND day_date = ? ORDER BY id""",
        (uid, today),
    ).fetchall()

    # Progress percentage (topics completed / total topics)
    total_topics = db.execute(
        "SELECT COUNT(*) c FROM topics WHERE user_id = ?", (uid,)
    ).fetchone()["c"]
    completed_topics = db.execute(
        "SELECT COUNT(*) c FROM topics WHERE user_id = ? AND completed = 1", (uid,)
    ).fetchone()["c"]
    progress_pct = round((completed_topics / total_topics) * 100, 1) if total_topics else 0

    # Hours studied (total)
    total_hours = db.execute(
        "SELECT COALESCE(SUM(hours),0) h FROM study_sessions WHERE user_id = ?", (uid,)
    ).fetchone()["h"]

    # Weekly progress graph data (last 7 days)
    week_labels, week_hours = [], []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        label = (datetime.now() - timedelta(days=i)).strftime("%a")
        hrs = db.execute(
            "SELECT COALESCE(SUM(hours),0) h FROM study_sessions WHERE user_id = ? AND session_date = ?",
            (uid, d),
        ).fetchone()["h"]
        week_labels.append(label)
        week_hours.append(hrs)

    quote = random.choice(MOTIVATION_QUOTES)

    return render_template(
        "dashboard.html",
        user=user,
        upcoming_exams=upcoming_exams,
        todays_plan=todays_plan,
        progress_pct=progress_pct,
        total_hours=round(total_hours, 1),
        streak=user["study_streak"] if user else 0,
        week_labels=json.dumps(week_labels),
        week_hours=json.dumps(week_hours),
        quote=quote,
        total_topics=total_topics,
        completed_topics=completed_topics,
    )


# ----------------------------------------------------------------------------
# Syllabus Upload
# ----------------------------------------------------------------------------
@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        uid = session["user_id"]
        subject = request.form.get("subject", "General").strip()
        file = request.files.get("syllabus_file")

        if not file or file.filename == "":
            flash("Please choose a PDF file to upload.", "danger")
            return redirect(url_for("upload"))

        if not allowed_file(file.filename):
            flash("Only PDF files are supported.", "danger")
            return redirect(url_for("upload"))

        filename = secure_filename(f"{uid}_{int(datetime.now().timestamp())}_{file.filename}")
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        # Extract text with PyPDF2
        extracted_text = ""
        try:
            with open(filepath, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text = page.extract_text() or ""
                    extracted_text += text + "\n"
        except Exception as e:
            flash(f"Could not read PDF: {e}", "danger")
            return redirect(url_for("upload"))

        db = get_db()
        cur = db.execute(
            "INSERT INTO syllabus (user_id, subject, filename, extracted_text) VALUES (?, ?, ?, ?)",
            (uid, subject, filename, extracted_text),
        )
        syllabus_id = cur.lastrowid

        # Naive topic extraction: treat short, non-empty lines as topics/headings
        topics = extract_topics_from_text(extracted_text)
        for t in topics:
            db.execute(
                "INSERT INTO topics (user_id, syllabus_id, subject, topic_name) VALUES (?, ?, ?, ?)",
                (uid, syllabus_id, subject, t),
            )
        db.commit()

        flash(f"Syllabus uploaded! Extracted {len(topics)} topics for {subject}.", "success")
        return redirect(url_for("upload"))

    db = get_db()
    uploads = db.execute(
        "SELECT * FROM syllabus WHERE user_id = ? ORDER BY uploaded_at DESC",
        (session["user_id"],),
    ).fetchall()
    return render_template("upload.html", uploads=uploads)


def extract_topics_from_text(text, max_topics=60):
    """
    Very lightweight heuristic topic extractor.
    Picks lines that look like headings/topics (short lines, title-like,
    numbered, or bullet points) rather than full paragraphs.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    topics = []
    for line in lines:
        clean = line.strip("•-*.\t ")
        word_count = len(clean.split())
        if 1 <= word_count <= 10 and len(clean) > 2:
            # Skip lines that are just numbers or page markers
            if clean.replace(".", "").isdigit():
                continue
            topics.append(clean)
        if len(topics) >= max_topics:
            break
    # De-duplicate while preserving order
    seen = set()
    unique_topics = []
    for t in topics:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique_topics.append(t)
    return unique_topics if unique_topics else ["General Topic 1", "General Topic 2"]


@app.route("/api/topics/<int:topic_id>/toggle", methods=["POST"])
@login_required
def toggle_topic(topic_id):
    db = get_db()
    topic = db.execute(
        "SELECT * FROM topics WHERE id = ? AND user_id = ?", (topic_id, session["user_id"])
    ).fetchone()
    if not topic:
        return jsonify({"error": "Topic not found"}), 404
    new_status = 0 if topic["completed"] else 1
    db.execute("UPDATE topics SET completed = ? WHERE id = ?", (new_status, topic_id))
    db.commit()
    return jsonify({"success": True, "completed": new_status})


# ----------------------------------------------------------------------------
# AI Study Planner
# ----------------------------------------------------------------------------
@app.route("/planner", methods=["GET", "POST"])
@login_required
def planner():
    db = get_db()
    uid = session["user_id"]

    if request.method == "POST":
        exam_date_str = request.form.get("exam_date")
        daily_hours = float(request.form.get("daily_hours", 2))
        difficulty = request.form.get("difficulty", "medium")
        priority_subjects = request.form.get("priority_subjects", "").strip()

        try:
            exam_date = datetime.strptime(exam_date_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            flash("Please provide a valid exam date.", "danger")
            return redirect(url_for("planner"))

        today = datetime.now()
        days_left = max((exam_date - today).days, 1)

        subjects = [s.strip() for s in priority_subjects.split(",") if s.strip()]
        if not subjects:
            # Pull subjects from uploaded syllabus if user didn't type any
            rows = db.execute(
                "SELECT DISTINCT subject FROM topics WHERE user_id = ?", (uid,)
            ).fetchall()
            subjects = [r["subject"] for r in rows] or ["General Study"]

        # Gather topics per subject (not yet completed preferred)
        subject_topics = {}
        for s in subjects:
            rows = db.execute(
                "SELECT topic_name FROM topics WHERE user_id = ? AND subject = ? AND completed = 0",
                (uid, s),
            ).fetchall()
            subject_topics[s] = [r["topic_name"] for r in rows] or [f"{s} - Core Concepts"]

        plan = generate_study_plan(subjects, subject_topics, days_left, daily_hours, difficulty, today)

        cur = db.execute(
            """INSERT INTO study_plans (user_id, exam_date, daily_hours, difficulty, priority_subjects, plan_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (uid, exam_date_str, daily_hours, difficulty, priority_subjects, json.dumps(plan)),
        )
        plan_id = cur.lastrowid

        for day in plan:
            for item in day["items"]:
                db.execute(
                    """INSERT INTO plan_days (plan_id, user_id, day_date, subject, topic, hours, session_type)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (plan_id, uid, day["date"], item["subject"], item["topic"],
                     item["hours"], item["type"]),
                )
        db.commit()

        flash("Your personalized AI study plan has been generated!", "success")
        return redirect(url_for("timetable"))

    plans = db.execute(
        "SELECT * FROM study_plans WHERE user_id = ? ORDER BY created_at DESC", (uid,)
    ).fetchall()
    return render_template("planner.html", plans=plans)


def generate_study_plan(subjects, subject_topics, days_left, daily_hours, difficulty, start_date):
    """
    Rule based day-wise study schedule generator.
    Reserves the last ~15% of days for pure revision.
    Harder difficulty => more hours allocated per topic (fewer topics/day).
    """
    difficulty_factor = {"easy": 0.5, "medium": 1.0, "hard": 1.5}.get(difficulty, 1.0)
    revision_days = max(1, round(days_left * 0.15))
    study_days = max(1, days_left - revision_days)

    # Flatten topics round-robin across subjects for balanced coverage
    all_items = []
    max_len = max((len(v) for v in subject_topics.values()), default=1)
    for i in range(max_len):
        for s in subjects:
            topics = subject_topics[s]
            if i < len(topics):
                all_items.append({"subject": s, "topic": topics[i]})

    if not all_items:
        all_items = [{"subject": s, "topic": "Revision"} for s in subjects]

    topics_per_day = max(1, round(daily_hours / difficulty_factor))
    plan = []
    item_index = 0

    for d in range(study_days):
        date_str = (start_date + timedelta(days=d)).strftime("%Y-%m-%d")
        day_items = []
        hours_left = daily_hours
        count = 0
        while hours_left > 0 and count < topics_per_day and item_index < len(all_items):
            item = all_items[item_index]
            hrs = round(min(difficulty_factor, hours_left), 2)
            day_items.append({
                "subject": item["subject"],
                "topic": item["topic"],
                "hours": hrs,
                "type": "study",
            })
            hours_left -= hrs
            item_index += 1
            count += 1
        if not day_items:
            # Loop back topics if we ran out (keeps every day populated)
            item = all_items[item_index % len(all_items)]
            day_items.append({
                "subject": item["subject"], "topic": item["topic"],
                "hours": daily_hours, "type": "study",
            })
            item_index += 1
        plan.append({"date": date_str, "day_number": d + 1, "items": day_items})

    # Revision days at the end, cycling through all subjects
    for d in range(revision_days):
        date_str = (start_date + timedelta(days=study_days + d)).strftime("%Y-%m-%d")
        subj = subjects[d % len(subjects)]
        plan.append({
            "date": date_str,
            "day_number": study_days + d + 1,
            "items": [{
                "subject": subj,
                "topic": "Full Revision & Practice Questions",
                "hours": daily_hours,
                "type": "revision",
            }],
        })

    return plan


# ----------------------------------------------------------------------------
# Smart Timetable (daily / weekly / revision views + editing)
# ----------------------------------------------------------------------------
@app.route("/timetable")
@login_required
def timetable():
    db = get_db()
    uid = session["user_id"]
    latest_plan = db.execute(
        "SELECT * FROM study_plans WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (uid,)
    ).fetchone()

    plan_days = []
    if latest_plan:
        plan_days = db.execute(
            "SELECT * FROM plan_days WHERE plan_id = ? ORDER BY day_date", (latest_plan["id"],)
        ).fetchall()

    return render_template("timetable.html", plan=latest_plan, plan_days=plan_days)


@app.route("/api/plan-days/<int:day_id>", methods=["PUT", "DELETE"])
@login_required
def update_plan_day(day_id):
    db = get_db()
    uid = session["user_id"]
    row = db.execute(
        "SELECT * FROM plan_days WHERE id = ? AND user_id = ?", (day_id, uid)
    ).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404

    if request.method == "DELETE":
        db.execute("DELETE FROM plan_days WHERE id = ?", (day_id,))
        db.commit()
        return jsonify({"success": True})

    data = request.get_json(force=True)
    subject = data.get("subject", row["subject"])
    topic = data.get("topic", row["topic"])
    hours = data.get("hours", row["hours"])
    completed = data.get("completed", row["completed"])

    db.execute(
        "UPDATE plan_days SET subject=?, topic=?, hours=?, completed=? WHERE id=?",
        (subject, topic, hours, 1 if completed else 0, day_id),
    )

    # If marked completed, log a study session for hour/streak tracking.
    # This also kicks off the Smart Revision Planner spaced-repetition chain
    # and checks for newly unlocked gamification badges.
    new_badges = []
    if completed and not row["completed"]:
        new_badges = log_study_session(uid, row["day_date"], hours, subject, topic)

    db.commit()
    return jsonify({
        "success": True,
        "new_badges": [{"name": b["name"], "icon": b["icon"]} for b in new_badges],
    })


def log_study_session(uid, date_str, hours, subject, topic=None):
    db = get_db()
    db.execute(
        "INSERT INTO study_sessions (user_id, session_date, hours, subject) VALUES (?, ?, ?, ?)",
        (uid, date_str, hours, subject),
    )

    # NEW: daily study_statistics cache (Productivity Analytics Dashboard)
    db.execute(
        """INSERT INTO study_statistics (user_id, stat_date, hours, sessions_completed)
           VALUES (?, ?, ?, 1)
           ON CONFLICT(user_id, stat_date)
           DO UPDATE SET hours = hours + excluded.hours,
                         sessions_completed = sessions_completed + 1""",
        (uid, date_str, hours),
    )

    # Update streak
    user = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    last_date = user["last_study_date"]
    if last_date == today:
        new_streak = user["study_streak"]
    elif last_date == yesterday:
        new_streak = user["study_streak"] + 1
    else:
        new_streak = 1
    db.execute(
        "UPDATE users SET study_streak = ?, last_study_date = ? WHERE id = ?",
        (new_streak, today, uid),
    )
    db.commit()

    # NEW: award XP for completing a study session
    award_xp(uid, 10)

    # NEW: Smart Revision Planner — kick off the spaced-repetition chain (stage 1)
    schedule_next_revision(uid, subject, topic or subject, stage=1, base_date=datetime.now())

    # NEW: Gamification — check for newly unlocked badges
    return check_and_award_badges(uid)


# ----------------------------------------------------------------------------
# AI Notes Generator
# ----------------------------------------------------------------------------
@app.route("/notes")
@login_required
def notes():
    db = get_db()
    uploads = db.execute(
        "SELECT * FROM syllabus WHERE user_id = ? ORDER BY uploaded_at DESC",
        (session["user_id"],),
    ).fetchall()
    return render_template("notes.html", uploads=uploads)


@app.route("/api/generate-notes", methods=["POST"])
@login_required
def api_generate_notes():
    data = request.get_json(force=True)
    syllabus_id = data.get("syllabus_id")
    note_type = data.get("note_type", "short_notes")  # short_notes, summary, important_points

    db = get_db()
    syl = db.execute(
        "SELECT * FROM syllabus WHERE id = ? AND user_id = ?", (syllabus_id, session["user_id"])
    ).fetchone()
    if not syl:
        return jsonify({"error": "Syllabus not found"}), 404

    text_snippet = (syl["extracted_text"] or "")[:6000]

    prompts = {
        "short_notes": f"Create concise short study notes (bullet points) from this syllabus content:\n\n{text_snippet}",
        "summary": f"Write a clear chapter-wise summary of this syllabus content:\n\n{text_snippet}",
        "important_points": f"List the most important exam-relevant points from this syllabus content as a numbered list:\n\n{text_snippet}",
    }
    prompt = prompts.get(note_type, prompts["short_notes"])
    result = call_gemini(prompt, system_instruction="You are an expert study notes generator for students. Format output using markdown with headings and bullet points.")

    return jsonify({"notes": result, "note_type": note_type, "subject": syl["subject"]})


# ----------------------------------------------------------------------------
# AI Quiz Generator
# ----------------------------------------------------------------------------
@app.route("/quiz")
@login_required
def quiz():
    db = get_db()
    uploads = db.execute(
        "SELECT * FROM syllabus WHERE user_id = ? ORDER BY uploaded_at DESC",
        (session["user_id"],),
    ).fetchall()
    results = db.execute(
        "SELECT * FROM quiz_results WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
        (session["user_id"],),
    ).fetchall()
    return render_template("quiz.html", uploads=uploads, results=results)


QUIZ_QUESTION_COUNT = 10
QUIZ_SYSTEM_PROMPT = (
    "You are an expert exam-question writer. You output strict JSON only - no markdown, "
    "no commentary. Every question must be a genuine, factual, topic-specific multiple choice "
    "question with four plausible options, exactly one correct answer and a short explanation."
)
_PLACEHOLDER_RE = re.compile(
    r"(demo question|placeholder|lorem ipsum|sample question|dummy|your question here|"
    r"^\s*(option|choice)\s*[a-d1-4]?\s*$|^\s*[a-d]\s*[\.\):]?\s*$)", re.I)
_OPTION_PREFIX_RE = re.compile(r"^\s*(?:\(?[A-Da-d]\)|[A-Da-d][\.\):])\s+")


@app.route("/api/generate-quiz", methods=["POST"])
@login_required
def api_generate_quiz():
    data = request.get_json(silent=True) or {}
    syllabus_id = data.get("syllabus_id")

    db = get_db()
    syl = db.execute(
        "SELECT * FROM syllabus WHERE id = ? AND user_id = ?", (syllabus_id, session["user_id"])
    ).fetchone()
    if not syl:
        return jsonify({"error": "Syllabus not found", "code": "not_found", "retryable": False}), 404

    subject = syl["subject"] or "General"
    topic_rows = db.execute(
        "SELECT topic_name FROM topics WHERE syllabus_id = ? ORDER BY id LIMIT 25", (syl["id"],)
    ).fetchall()
    topic_names = [r["topic_name"] for r in topic_rows]
    text_snippet = (syl["extracted_text"] or "")[:6000]

    prompt = f"""Write exactly {QUIZ_QUESTION_COUNT} multiple choice questions that test real knowledge of the subject "{subject}".
Base them on the topics and syllabus content below. Test the actual concepts, facts, definitions and
applications of these topics - do NOT ask about the syllabus document itself.

Rules:
- Each question has exactly 4 meaningful options (no "Option A" style filler, no "all of the above" in every question).
- Exactly one option is correct; "correct_index" is its 0-based position (0=A, 1=B, 2=C, 3=D).
- Vary the position of the correct answer across questions.
- "explanation" is 1-2 sentences saying why the answer is correct.
- "chapter" is the specific topic/chapter the question tests (choose from the topic list when possible).
- Do not repeat questions.

Respond ONLY with valid JSON in exactly this structure:
{{
  "questions": [
    {{
      "question": "...",
      "chapter": "...",
      "options": ["...", "...", "...", "..."],
      "correct_index": 0,
      "explanation": "..."
    }}
  ]
}}

Topics: {", ".join(topic_names) if topic_names else "(none extracted - use the syllabus content / subject name)"}

Syllabus content:
{text_snippet if text_snippet.strip() else "(no text extracted - base the questions on the subject and topics above)"}
"""

    last_error = None
    for attempt in range(2):  # one automatic re-ask if Gemini returns malformed/invalid content
        try:
            raw = generate_with_gemini(
                prompt, system_instruction=QUIZ_SYSTEM_PROMPT, json_output=True, temperature=0.7)
            questions = _parse_quiz_json(raw)
            quiz_data = _validate_quiz(questions, subject)
            return jsonify({"quiz": quiz_data, "subject": subject})
        except GeminiError as e:
            last_error = e
            if not e.retryable or e.code in ("quota_exceeded", "gemini_unavailable", "network_error"):
                break  # retrying immediately will not help
        except ValueError as e:
            print(f"[Quiz validation] attempt {attempt + 1}: {e}")
            last_error = GeminiError(
                "The AI returned a quiz in an unexpected format. Please retry.",
                "invalid_quiz_format", 502, True)

    return jsonify({
        "error": last_error.message,
        "code": last_error.code,
        "retryable": last_error.retryable,
    }), last_error.http_status


def _parse_quiz_json(raw_text):
    """Extract the list of question dicts from Gemini's text. Raises ValueError on failure."""
    cleaned = (raw_text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I).strip()
    candidates = [cleaned]
    for open_c, close_c in (("{", "}"), ("[", "]")):
        i, j = cleaned.find(open_c), cleaned.rfind(close_c)
        if i != -1 and j > i:
            candidates.append(cleaned[i:j + 1])
    parsed = None
    for cand in candidates:
        try:
            parsed = json.loads(cand)
            break
        except (ValueError, TypeError):
            continue
    if parsed is None:
        raise ValueError("response is not valid JSON")
    if isinstance(parsed, dict):
        parsed = parsed.get("questions")
    if not isinstance(parsed, list) or not parsed:
        raise ValueError("JSON has no 'questions' list")
    return parsed


def _validate_quiz(questions, subject):
    """Validate and normalise Gemini's questions into the frontend structure:
    {question, chapter, options[4], correct_index, explanation}. Raises ValueError."""
    if not isinstance(questions, list):
        raise ValueError("questions is not a list")
    clean, seen = [], set()
    for n, q in enumerate(questions, 1):
        if not isinstance(q, dict):
            raise ValueError(f"question {n} is not an object")
        text = str(q.get("question") or "").strip()
        if len(text) < 10 or _PLACEHOLDER_RE.search(text):
            raise ValueError(f"question {n} is missing or a placeholder")
        if text.lower() in seen:
            raise ValueError(f"question {n} is a duplicate")
        seen.add(text.lower())

        options = q.get("options")
        if isinstance(options, dict):  # {"A": "...", "B": "..."} style
            options = [options.get(k) for k in ("A", "B", "C", "D")]
        if not isinstance(options, list) or len(options) != 4:
            raise ValueError(f"question {n} must have exactly 4 options")
        options = [_OPTION_PREFIX_RE.sub("", str(o if o is not None else "")).strip() for o in options]
        if any(not o or _PLACEHOLDER_RE.search(o) for o in options):
            raise ValueError(f"question {n} has empty or placeholder options")
        if len({o.lower() for o in options}) != 4:
            raise ValueError(f"question {n} has duplicate options")

        idx = q.get("correct_index")
        if idx is None:
            ans = q.get("correct_answer", q.get("answer"))
            if isinstance(ans, str) and ans.strip().upper()[:1] in "ABCD" and len(ans.strip()) <= 2:
                idx = "ABCD".index(ans.strip().upper()[:1])
            elif isinstance(ans, str) and ans.strip().lower() in [o.lower() for o in options]:
                idx = [o.lower() for o in options].index(ans.strip().lower())
        if isinstance(idx, bool) or isinstance(idx, str) and not idx.strip().isdigit():
            raise ValueError(f"question {n} has an invalid correct answer")
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            raise ValueError(f"question {n} has no correct answer")
        if idx not in (0, 1, 2, 3):
            raise ValueError(f"question {n} correct answer out of range")

        explanation = str(q.get("explanation") or "").strip()
        if len(explanation) < 5 or _PLACEHOLDER_RE.search(explanation):
            raise ValueError(f"question {n} has no explanation")

        clean.append({
            "question": text,
            "chapter": str(q.get("chapter") or "").strip() or subject,
            "options": options,
            "correct_index": idx,
            "explanation": explanation,
        })

    if len(clean) < QUIZ_QUESTION_COUNT:
        raise ValueError(f"only {len(clean)} valid questions (need {QUIZ_QUESTION_COUNT})")
    return clean[:QUIZ_QUESTION_COUNT]


@app.route("/api/submit-quiz", methods=["POST"])
@login_required
def api_submit_quiz():
    data = request.get_json(force=True)
    uid = session["user_id"]
    subject = data.get("subject", "General")
    score = int(data.get("score", 0))
    total = int(data.get("total", 10))
    # NEW: per-question breakdown for Weak Topic Detection
    # answers: [{ "chapter": str, "question": str, "is_correct": bool }, ...]
    answers = data.get("answers", [])

    db = get_db()
    db.execute(
        "INSERT INTO quiz_results (user_id, subject, score, total) VALUES (?, ?, ?, ?)",
        (uid, subject, score, total),
    )

    for a in answers:
        db.execute(
            """INSERT INTO quiz_history (user_id, subject, chapter, question, is_correct)
               VALUES (?, ?, ?, ?, ?)""",
            (uid, subject, a.get("chapter") or subject, a.get("question", ""),
             1 if a.get("is_correct") else 0),
        )
    db.commit()

    # NEW: award XP for completing a quiz (bonus XP for a strong score) + badge check
    award_xp(uid, 5 + round((score / total) * 10) if total else 5)
    new_badges = check_and_award_badges(uid)

    return jsonify({
        "success": True,
        "new_badges": [{"name": b["name"], "icon": b["icon"]} for b in new_badges],
    })


# ----------------------------------------------------------------------------
# Progress Dashboard
# ----------------------------------------------------------------------------
@app.route("/progress")
@login_required
def progress():
    db = get_db()
    uid = session["user_id"]

    total_topics = db.execute("SELECT COUNT(*) c FROM topics WHERE user_id=?", (uid,)).fetchone()["c"]
    completed_topics = db.execute(
        "SELECT COUNT(*) c FROM topics WHERE user_id=? AND completed=1", (uid,)
    ).fetchone()["c"]
    remaining_topics = total_topics - completed_topics

    total_hours = db.execute(
        "SELECT COALESCE(SUM(hours),0) h FROM study_sessions WHERE user_id=?", (uid,)
    ).fetchone()["h"]

    # Weekly graph (last 7 days)
    week_labels, week_hours = [], []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i))
        hrs = db.execute(
            "SELECT COALESCE(SUM(hours),0) h FROM study_sessions WHERE user_id=? AND session_date=?",
            (uid, d.strftime("%Y-%m-%d")),
        ).fetchone()["h"]
        week_labels.append(d.strftime("%a"))
        week_hours.append(hrs)

    # Monthly graph (last 30 days, grouped by week)
    month_labels, month_hours = [], []
    for w in range(3, -1, -1):
        start = datetime.now() - timedelta(days=(w + 1) * 7)
        end = datetime.now() - timedelta(days=w * 7)
        hrs = db.execute(
            "SELECT COALESCE(SUM(hours),0) h FROM study_sessions WHERE user_id=? AND session_date BETWEEN ? AND ?",
            (uid, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
        ).fetchone()["h"]
        month_labels.append(f"Week {4 - w}")
        month_hours.append(hrs)

    # Subject-wise progress
    subjects = db.execute(
        "SELECT DISTINCT subject FROM topics WHERE user_id=?", (uid,)
    ).fetchall()
    subject_progress = []
    for s in subjects:
        subj = s["subject"]
        tot = db.execute(
            "SELECT COUNT(*) c FROM topics WHERE user_id=? AND subject=?", (uid, subj)
        ).fetchone()["c"]
        comp = db.execute(
            "SELECT COUNT(*) c FROM topics WHERE user_id=? AND subject=? AND completed=1",
            (uid, subj),
        ).fetchone()["c"]
        pct = round((comp / tot) * 100, 1) if tot else 0
        subject_progress.append({"subject": subj, "total": tot, "completed": comp, "pct": pct})

    return render_template(
        "progress.html",
        total_topics=total_topics,
        completed_topics=completed_topics,
        remaining_topics=remaining_topics,
        total_hours=round(total_hours, 1),
        week_labels=json.dumps(week_labels),
        week_hours=json.dumps(week_hours),
        month_labels=json.dumps(month_labels),
        month_hours=json.dumps(month_hours),
        subject_progress=subject_progress,
    )


# ----------------------------------------------------------------------------
# AI Revision Planner
# ----------------------------------------------------------------------------
@app.route("/revision")
@login_required
def revision():
    db = get_db()
    uid = session["user_id"]

    latest_plan = db.execute(
        "SELECT * FROM study_plans WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (uid,)
    ).fetchone()

    remaining = db.execute(
        "SELECT * FROM topics WHERE user_id=? AND completed=0", (uid,)
    ).fetchall()

    revision_plan = []
    if latest_plan and remaining:
        exam_date = datetime.strptime(latest_plan["exam_date"], "%Y-%m-%d")
        days_left = max((exam_date - datetime.now()).days, 1)
        revision_days = min(days_left, max(3, len(remaining) // 3 + 1))
        topics_per_day = max(1, -(-len(remaining) // revision_days))  # ceil division

        idx = 0
        for d in range(revision_days):
            date_str = (datetime.now() + timedelta(days=d)).strftime("%Y-%m-%d")
            day_topics = remaining[idx: idx + topics_per_day]
            idx += topics_per_day
            if not day_topics:
                break
            revision_plan.append({
                "date": date_str,
                "topics": [{"subject": t["subject"], "topic": t["topic_name"]} for t in day_topics],
            })

    return render_template("timetable.html", plan=latest_plan, plan_days=None,
                            revision_plan=revision_plan, is_revision_view=True)


# ----------------------------------------------------------------------------
# Performance Prediction
# ----------------------------------------------------------------------------
@app.route("/performance")
@login_required
def performance():
    db = get_db()
    uid = session["user_id"]

    total_topics = db.execute("SELECT COUNT(*) c FROM topics WHERE user_id=?", (uid,)).fetchone()["c"]
    completed_topics = db.execute(
        "SELECT COUNT(*) c FROM topics WHERE user_id=? AND completed=1", (uid,)
    ).fetchone()["c"]
    topic_completion_pct = (completed_topics / total_topics * 100) if total_topics else 0

    quiz_rows = db.execute(
        "SELECT subject, score, total FROM quiz_results WHERE user_id=?", (uid,)
    ).fetchall()

    subject_scores = {}
    for r in quiz_rows:
        subj = r["subject"] or "General"
        pct = (r["score"] / r["total"] * 100) if r["total"] else 0
        subject_scores.setdefault(subj, []).append(pct)

    subject_avg = {s: round(sum(v) / len(v), 1) for s, v in subject_scores.items()}
    overall_quiz_avg = round(sum(subject_avg.values()) / len(subject_avg), 1) if subject_avg else 0

    # Readiness = weighted average of topic completion and quiz performance
    readiness = round((topic_completion_pct * 0.5) + (overall_quiz_avg * 0.5), 1)
    if not quiz_rows:
        readiness = round(topic_completion_pct, 1)  # no quiz data yet

    weak_subjects = sorted(
        [{"subject": s, "avg": a} for s, a in subject_avg.items() if a < 60],
        key=lambda x: x["avg"],
    )
    strong_subjects = sorted(
        [{"subject": s, "avg": a} for s, a in subject_avg.items() if a >= 75],
        key=lambda x: -x["avg"],
    )

    if readiness >= 80:
        estimated_performance = "Excellent — you are well prepared!"
        recommendations = [
            "Maintain your current pace and focus on revision.",
            "Practice previous year question papers under timed conditions.",
            "Get good sleep before the exam to stay sharp.",
        ]
    elif readiness >= 60:
        estimated_performance = "Good — a bit more focused effort will pay off."
        recommendations = [
            "Dedicate extra time to your weaker subjects.",
            "Use active recall and spaced repetition for retention.",
            "Take a full mock quiz every few days to track improvement.",
        ]
    elif readiness >= 40:
        estimated_performance = "Average — increase study intensity soon."
        recommendations = [
            "Revisit uncompleted topics using the Smart Timetable.",
            "Break large topics into smaller, manageable study sessions.",
            "Use AI Notes and the AI Quiz to clarify difficult concepts.",
        ]
    else:
        estimated_performance = "Needs Improvement — build a consistent routine now."
        recommendations = [
            "Start with a fresh AI-generated study plan today.",
            "Focus on covering syllabus topics before attempting quizzes.",
            "Set small daily goals to build momentum and confidence.",
        ]

    return render_template(
        "progress.html",
        performance_view=True,
        readiness=readiness,
        weak_subjects=weak_subjects,
        strong_subjects=strong_subjects,
        estimated_performance=estimated_performance,
        recommendations=recommendations,
        overall_quiz_avg=overall_quiz_avg,
        topic_completion_pct=round(topic_completion_pct, 1),
        total_topics=total_topics,
        completed_topics=completed_topics,
        remaining_topics=total_topics - completed_topics,
        total_hours=0,
        week_labels="[]", week_hours="[]",
        month_labels="[]", month_hours="[]",
        subject_progress=[],
    )


# ==============================================================================
# NEW FEATURE 1 — Weak Topic Detection
# ==============================================================================
@app.route("/weak-topics")
@login_required
def weak_topics():
    db = get_db()
    uid = session["user_id"]

    rows = db.execute(
        """SELECT subject, chapter,
                  COUNT(*) AS attempts,
                  SUM(is_correct) AS correct
           FROM quiz_history
           WHERE user_id = ?
           GROUP BY subject, chapter
           ORDER BY subject""",
        (uid,),
    ).fetchall()

    chapters = []
    for r in rows:
        attempts = r["attempts"]
        correct = r["correct"] or 0
        wrong = attempts - correct
        accuracy = round((correct / attempts) * 100, 1) if attempts else 0

        if accuracy < 40 or attempts < 2:
            level = "High"
        elif accuracy < 65:
            level = "Medium"
        else:
            level = "Low"

        chapters.append({
            "subject": r["subject"], "chapter": r["chapter"], "attempts": attempts,
            "correct": correct, "wrong": wrong, "accuracy": accuracy,
            "level": level, "is_weak": accuracy < 70 or attempts < 2,
        })

    # Weak chapters only, sorted worst-first — this is the "Study Priority List"
    priority_list = sorted([c for c in chapters if c["is_weak"]], key=lambda c: c["accuracy"])

    # Weak subjects = subjects whose average chapter accuracy is below 60%
    subject_acc = {}
    for c in chapters:
        subject_acc.setdefault(c["subject"], []).append(c["accuracy"])
    weak_subjects = sorted(
        [{"subject": s, "avg_accuracy": round(sum(v) / len(v), 1)}
         for s, v in subject_acc.items() if sum(v) / len(v) < 60],
        key=lambda x: x["avg_accuracy"],
    )

    recommendations = generate_weak_topic_recommendations(priority_list)

    return render_template(
        "weak_topics.html",
        chapters=chapters, priority_list=priority_list,
        weak_subjects=weak_subjects, recommendations=recommendations,
        has_data=len(chapters) > 0,
    )


def generate_weak_topic_recommendations(priority_list):
    """Generate short AI-style recommendations for the weakest chapters.
    Falls back to a deterministic template when Gemini isn't configured."""
    if not priority_list:
        return ["Attempt a few AI quizzes so we can analyze your weak areas."]

    top = priority_list[:5]
    if GEMINI_ENABLED:
        chapter_lines = "\n".join(
            f"- {c['chapter']} ({c['subject']}): {c['accuracy']}% accuracy, {c['wrong']} wrong answers"
            for c in top
        )
        prompt = (
            "A student has these weak chapters based on quiz performance:\n"
            f"{chapter_lines}\n\n"
            "Give 4-6 short, specific, actionable revision recommendations "
            "(one line each, no numbering prefix needed in the text)."
        )
        text = call_gemini(prompt, system_instruction="You are a study coach. Be concise and encouraging.")
        lines = [l.strip("-•* ").strip() for l in text.split("\n") if l.strip()]
        if lines:
            return lines[:6]

    # Deterministic fallback
    recs = [f"Revise '{c['chapter']}' in {c['subject']} — only {c['accuracy']}% accuracy so far." for c in top]
    recs.append("Do extra practice questions on your top 3 weakest chapters this week.")
    recs.append("Use the AI Notes Generator to re-summarize your weakest chapters.")
    return recs


# ==============================================================================
# NEW FEATURE 2 — Smart Revision Planner (Spaced Repetition)
# ==============================================================================
@app.route("/smart-revision")
@login_required
def smart_revision():
    db = get_db()
    uid = session["user_id"]
    today = datetime.now().strftime("%Y-%m-%d")

    due_today = db.execute(
        """SELECT * FROM revision_schedule
           WHERE user_id=? AND completed=0 AND revision_date <= ?
           ORDER BY revision_date ASC""",
        (uid, today),
    ).fetchall()

    upcoming = db.execute(
        """SELECT * FROM revision_schedule
           WHERE user_id=? AND completed=0 AND revision_date > ?
           ORDER BY revision_date ASC LIMIT 30""",
        (uid, today),
    ).fetchall()

    completed_recent = db.execute(
        """SELECT * FROM revision_schedule
           WHERE user_id=? AND completed=1
           ORDER BY completed_at DESC LIMIT 10""",
        (uid,),
    ).fetchall()

    stage_labels = {k: v["label"] for k, v in REVISION_STAGES.items()}

    return render_template(
        "smart_revision.html",
        due_today=due_today, upcoming=upcoming, completed_recent=completed_recent,
        stage_labels=stage_labels, max_stage=MAX_REVISION_STAGE,
    )


@app.route("/api/revision-schedule/<int:rid>/complete", methods=["POST"])
@login_required
def api_complete_revision(rid):
    db = get_db()
    uid = session["user_id"]
    row = db.execute(
        "SELECT * FROM revision_schedule WHERE id=? AND user_id=?", (rid, uid)
    ).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404

    db.execute(
        "UPDATE revision_schedule SET completed=1, completed_at=CURRENT_TIMESTAMP WHERE id=?",
        (rid,),
    )
    db.commit()

    # Automatically schedule the next stage in the spaced-repetition chain
    next_stage = row["stage"] + 1
    if next_stage <= MAX_REVISION_STAGE:
        schedule_next_revision(uid, row["subject"], row["topic"], next_stage, datetime.now())

    award_xp(uid, 8)
    new_badges = check_and_award_badges(uid)

    return jsonify({
        "success": True,
        "next_stage_scheduled": next_stage <= MAX_REVISION_STAGE,
        "new_badges": [{"name": b["name"], "icon": b["icon"]} for b in new_badges],
    })


# ==============================================================================
# NEW FEATURE 3 — Productivity Analytics Dashboard
# ==============================================================================
@app.route("/analytics")
@login_required
def analytics():
    db = get_db()
    uid = session["user_id"]
    range_key = request.args.get("range", "week")
    if range_key not in ("today", "week", "month", "all"):
        range_key = "week"

    today = datetime.now()
    date_filter_sql = ""
    params = [uid]

    if range_key == "today":
        start = today
        date_filter_sql = "AND session_date = ?"
        params.append(today.strftime("%Y-%m-%d"))
    elif range_key == "week":
        start = today - timedelta(days=6)
        date_filter_sql = "AND session_date BETWEEN ? AND ?"
        params += [start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")]
    elif range_key == "month":
        start = today - timedelta(days=29)
        date_filter_sql = "AND session_date BETWEEN ? AND ?"
        params += [start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")]
    else:  # all
        start = None
        date_filter_sql = ""

    # ---- Stat cards ----
    total_hours = db.execute(
        f"SELECT COALESCE(SUM(hours),0) h FROM study_sessions WHERE user_id=? {date_filter_sql}",
        params,
    ).fetchone()["h"]

    total_sessions = db.execute(
        f"SELECT COUNT(*) c FROM study_sessions WHERE user_id=? {date_filter_sql}",
        params,
    ).fetchone()["c"]

    total_topics = db.execute("SELECT COUNT(*) c FROM topics WHERE user_id=?", (uid,)).fetchone()["c"]
    completed_topics = db.execute(
        "SELECT COUNT(*) c FROM topics WHERE user_id=? AND completed=1", (uid,)
    ).fetchone()["c"]
    completion_pct = round((completed_topics / total_topics) * 100, 1) if total_topics else 0

    quiz_params = [uid]
    quiz_date_filter = ""
    if range_key == "today":
        quiz_date_filter = "AND date(created_at) = date(?)"
        quiz_params.append(today.strftime("%Y-%m-%d"))
    elif range_key in ("week", "month"):
        quiz_date_filter = "AND date(created_at) >= date(?)"
        quiz_params.append(start.strftime("%Y-%m-%d"))

    quiz_rows = db.execute(
        f"SELECT score, total, created_at FROM quiz_results WHERE user_id=? {quiz_date_filter} ORDER BY created_at ASC",
        quiz_params,
    ).fetchall()
    avg_quiz_score = round(
        sum((q["score"] / q["total"] * 100) for q in quiz_rows if q["total"]) / len(quiz_rows), 1
    ) if quiz_rows else 0

    user = current_user()
    study_streak = user["study_streak"] if user else 0

    # ---- Bar chart: study hours over time ----
    bar_labels, bar_data = [], []
    if range_key == "today":
        bar_labels = ["Today"]
        bar_data = [total_hours]
    elif range_key in ("week", "month"):
        span = 7 if range_key == "week" else 30
        for i in range(span - 1, -1, -1):
            d = today - timedelta(days=i)
            hrs = db.execute(
                "SELECT COALESCE(SUM(hours),0) h FROM study_sessions WHERE user_id=? AND session_date=?",
                (uid, d.strftime("%Y-%m-%d")),
            ).fetchone()["h"]
            bar_labels.append(d.strftime("%b %d"))
            bar_data.append(hrs)
    else:  # all -> last 6 months
        for i in range(5, -1, -1):
            month_start = (today.replace(day=1) - timedelta(days=1)).replace(day=1) if i else today.replace(day=1)
            # simpler: compute month boundaries via 30-day steps back
            ref = today - timedelta(days=i * 30)
            month_label = ref.strftime("%b %Y")
            month_prefix = ref.strftime("%Y-%m")
            hrs = db.execute(
                "SELECT COALESCE(SUM(hours),0) h FROM study_sessions WHERE user_id=? AND session_date LIKE ?",
                (uid, f"{month_prefix}%"),
            ).fetchone()["h"]
            bar_labels.append(month_label)
            bar_data.append(hrs)

    # ---- Pie/doughnut: subject-wise time distribution ----
    subject_rows = db.execute(
        f"""SELECT subject, COALESCE(SUM(hours),0) h FROM study_sessions
            WHERE user_id=? {date_filter_sql} GROUP BY subject""",
        params,
    ).fetchall()
    subject_labels = [r["subject"] or "General" for r in subject_rows]
    subject_data = [r["h"] for r in subject_rows]

    # ---- Line chart: quiz performance over time ----
    quiz_labels = [q["created_at"][:10] for q in quiz_rows]
    quiz_scores = [round((q["score"] / q["total"]) * 100, 1) if q["total"] else 0 for q in quiz_rows]

    return render_template(
        "analytics.html",
        range_key=range_key,
        total_hours=round(total_hours, 1), total_sessions=total_sessions,
        completion_pct=completion_pct, avg_quiz_score=avg_quiz_score, study_streak=study_streak,
        bar_labels=json.dumps(bar_labels), bar_data=json.dumps(bar_data),
        subject_labels=json.dumps(subject_labels), subject_data=json.dumps(subject_data),
        quiz_labels=json.dumps(quiz_labels), quiz_scores=json.dumps(quiz_scores),
        completed_topics=completed_topics, remaining_topics=total_topics - completed_topics,
    )


# ==============================================================================
# NEW FEATURE 4 — Gamification System
# ==============================================================================
@app.route("/achievements")
@login_required
def achievements():
    db = get_db()
    uid = session["user_id"]

    progress = get_or_create_progress(uid)
    xp = progress["xp"]
    level = progress["level"]
    xp_into_level = xp % XP_PER_LEVEL
    xp_progress_pct = xp_into_level  # XP_PER_LEVEL == 100, so this doubles as a %

    unlocked_rows = db.execute(
        "SELECT * FROM achievements WHERE user_id=? ORDER BY unlocked_at DESC", (uid,)
    ).fetchall()
    unlocked_keys = {r["badge_key"]: r for r in unlocked_rows}

    badge_display = []
    for badge in BADGES:
        unlocked_row = unlocked_keys.get(badge["key"])
        badge_display.append({
            **badge,
            "unlocked": unlocked_row is not None,
            "unlocked_at": unlocked_row["unlocked_at"] if unlocked_row else None,
        })

    return render_template(
        "achievements.html",
        xp=xp, level=level, xp_progress_pct=xp_progress_pct,
        xp_into_level=xp_into_level, xp_per_level=XP_PER_LEVEL,
        badges=badge_display, history=unlocked_rows,
    )


# ----------------------------------------------------------------------------
# To-Do List
# ----------------------------------------------------------------------------
@app.route("/todo")
@login_required
def todo():
    db = get_db()
    tasks = db.execute(
        "SELECT * FROM todos WHERE user_id=? ORDER BY completed ASC, due_date ASC",
        (session["user_id"],),
    ).fetchall()
    return render_template("todo.html", tasks=tasks)


@app.route("/api/todos", methods=["POST"])
@login_required
def api_add_todo():
    data = request.get_json(force=True)
    task = (data.get("task") or "").strip()
    if not task:
        return jsonify({"error": "Task text required"}), 400
    due_date = data.get("due_date") or None
    priority = data.get("priority", "medium")

    db = get_db()
    cur = db.execute(
        "INSERT INTO todos (user_id, task, due_date, priority) VALUES (?, ?, ?, ?)",
        (session["user_id"], task, due_date, priority),
    )
    db.commit()
    return jsonify({"success": True, "id": cur.lastrowid})


@app.route("/api/todos/<int:todo_id>", methods=["PUT", "DELETE"])
@login_required
def api_modify_todo(todo_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM todos WHERE id=? AND user_id=?", (todo_id, session["user_id"])
    ).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404

    if request.method == "DELETE":
        db.execute("DELETE FROM todos WHERE id=?", (todo_id,))
        db.commit()
        return jsonify({"success": True})

    data = request.get_json(force=True)
    task = data.get("task", row["task"])
    due_date = data.get("due_date", row["due_date"])
    priority = data.get("priority", row["priority"])
    completed = data.get("completed", row["completed"])

    db.execute(
        "UPDATE todos SET task=?, due_date=?, priority=?, completed=? WHERE id=?",
        (task, due_date, priority, 1 if completed else 0, todo_id),
    )
    db.commit()
    return jsonify({"success": True})


# ----------------------------------------------------------------------------
# Reminder System
# ----------------------------------------------------------------------------
@app.route("/reminders")
@login_required
def reminders_page():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM reminders WHERE user_id=? ORDER BY reminder_date ASC",
        (session["user_id"],),
    ).fetchall()

    # Compute countdown info for each reminder
    reminders_with_countdown = []
    for r in rows:
        try:
            rdate = datetime.strptime(r["reminder_date"], "%Y-%m-%d")
            days_left = (rdate - datetime.now()).days
        except ValueError:
            days_left = None
        reminders_with_countdown.append({**dict(r), "days_left": days_left})

    return render_template("reminders.html", reminders=reminders_with_countdown)


@app.route("/api/reminders", methods=["POST"])
@login_required
def api_add_reminder():
    data = request.get_json(force=True)
    title = (data.get("title") or "").strip()
    rtype = data.get("type", "study")
    rdate = data.get("reminder_date")
    notes = data.get("notes", "")

    if not title or not rdate:
        return jsonify({"error": "Title and date are required"}), 400

    db = get_db()
    cur = db.execute(
        "INSERT INTO reminders (user_id, type, title, reminder_date, notes) VALUES (?, ?, ?, ?, ?)",
        (session["user_id"], rtype, title, rdate, notes),
    )
    db.commit()
    return jsonify({"success": True, "id": cur.lastrowid})


@app.route("/api/reminders/<int:rid>", methods=["DELETE"])
@login_required
def api_delete_reminder(rid):
    db = get_db()
    row = db.execute(
        "SELECT * FROM reminders WHERE id=? AND user_id=?", (rid, session["user_id"])
    ).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    db.execute("DELETE FROM reminders WHERE id=?", (rid,))
    db.commit()
    return jsonify({"success": True})


# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
@app.route("/settings")
@login_required
def settings():
    return render_template("settings.html", user=current_user())


@app.route("/api/settings/profile", methods=["POST"])
@login_required
def api_update_profile():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()

    if not name or not email:
        return jsonify({"error": "Name and email are required"}), 400

    db = get_db()
    existing = db.execute(
        "SELECT id FROM users WHERE email=? AND id != ?", (email, session["user_id"])
    ).fetchone()
    if existing:
        return jsonify({"error": "Email already in use by another account"}), 400

    db.execute("UPDATE users SET name=?, email=? WHERE id=?", (name, email, session["user_id"]))
    db.commit()
    session["user_name"] = name
    return jsonify({"success": True})


@app.route("/api/settings/password", methods=["POST"])
@login_required
def api_change_password():
    data = request.get_json(force=True)
    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")

    if len(new_password) < 6:
        return jsonify({"error": "New password must be at least 6 characters"}), 400

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    if not check_password_hash(user["password_hash"], current_password):
        return jsonify({"error": "Current password is incorrect"}), 400

    new_hash = generate_password_hash(new_password)
    db.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, session["user_id"]))
    db.commit()
    return jsonify({"success": True})


# ----------------------------------------------------------------------------
# Error handlers
# ----------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404 if os.path.exists(
        os.path.join(BASE_DIR, "templates", "404.html")
    ) else (jsonify({"error": "Not found"}), 404)


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error. Please try again."}), 500


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    print("StudyGenie AI is starting...")

    app.run(
        debug=False,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        use_reloader=False
    )
else:
    init_db()