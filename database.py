import sqlite3
import os
from flask import g

DATABASE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schoolsync.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def get_db():
    """
    Returns a connection to the database for the current request.

    Flask's `g` object is a little storage box that lives for exactly
    one request. The first time a route calls get_db(), we open a real
    connection and stash it in `g`. If the same route calls get_db()
    again later, we hand back the *same* connection instead of opening
    a second one.
    """
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE_PATH)
        # row_factory makes query results behave like dictionaries
        # (row["name"] instead of row[1]) which is much easier to read.
        g.db.row_factory = sqlite3.Row
        # Without this line, SQLite ignores FOREIGN KEY rules by default.
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    """Closes the database connection at the end of the request.
    Registered with app.teardown_appcontext() in app.py."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """
    Wipes and (re)creates all tables from schema.sql.
    Run this once via seed.py — NOT on every app startup, or you'd
    lose your data every time you restart the server.
    """
    db = get_db()
    with open(SCHEMA_PATH, "r") as f:
        db.executescript(f.read())
    db.commit()


def init_app(app):
    """Called once from app.py so Flask knows to clean up the database
    connection automatically after every request."""
    app.teardown_appcontext(close_db)


def ensure_schema_migrations():
    """One-time, additive schema fixes, safe to run every time the app
    starts up. Unlike init_db() (which wipes and recreates everything —
    only meant for first-time setup), this checks what's already there
    and only adds what's missing, so it never touches existing data.

    Columns added to `users`, each only if missing:
    - `is_active` for the account deactivate/reactivate feature — every
      existing account defaults to active (1) automatically.
    - `last_profile_update` for the self-service "edit your own name/
      email/password" page's 30-day cooldown — NULL by default, meaning
      "never self-edited yet", so everyone starts off eligible.
    - `must_change_password` — set to 1 when an Admin resets someone's
      password, forcing them to pick a new one at their next login.
      Everyone starts at 0, so no existing account is affected.
    - `session_version` — bumped each time an Admin resets a password so
      that any session the affected user already had open stops working.
      Everyone starts at 0, which matches sessions that already exist,
      so nobody gets logged out just because of this upgrade.

    Table created only if missing:
    - `audit_log` — one row per admin password reset (who, whom, when,
      what, outcome). It never stores any password or hash."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "is_active" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    if "last_profile_update" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN last_profile_update TEXT")
    if "must_change_password" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
    if "session_version" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0")

    # No FOREIGN KEY on purpose: the history should survive even if the
    # admin or the affected account is deleted later.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS audit_log (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               admin_id INTEGER,
               target_user_id INTEGER,
               action TEXT NOT NULL,
               status TEXT NOT NULL,
               created_at TEXT NOT NULL
           )"""
    )
    conn.commit()
    conn.close()