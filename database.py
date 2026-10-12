import os
import sqlite3
from flask import g

DEFAULT_DATABASE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schoolsync.db")
DATABASE_PATH = os.environ.get("SCHOOLSYNC_DATABASE_PATH", DEFAULT_DATABASE_PATH)
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def _connect():
    """Open a configured SQLite connection and create its parent directory."""
    parent = os.path.dirname(os.path.abspath(DATABASE_PATH))
    os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def get_db():
    """Return this request's SQLite connection, creating it on first use."""
    if "db" not in g:
        g.db = _connect()
    return g.db


def close_db(e=None):
    """Close the current request's database connection."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Destructively recreate tables from schema.sql for explicit local resets only."""
    db = get_db()
    with open(SCHEMA_PATH, "r", encoding="utf-8") as schema_file:
        db.executescript(schema_file.read())
    db.commit()


def init_app(app):
    """Register request-scoped connection cleanup with Flask."""
    app.teardown_appcontext(close_db)


def _ensure_base_schema(conn):
    """Create base tables without dropping or overwriting existing data."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT NOT NULL,
               email TEXT NOT NULL UNIQUE,
               password_hash TEXT NOT NULL,
               role TEXT NOT NULL CHECK (role IN ('admin', 'staff', 'student')),
               created_at TEXT NOT NULL DEFAULT (datetime('now'))
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS events (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               title TEXT NOT NULL,
               date TEXT NOT NULL,
               start_time TEXT NOT NULL,
               end_time TEXT NOT NULL,
               location TEXT NOT NULL,
               description TEXT,
               created_by INTEGER NOT NULL,
               status TEXT NOT NULL DEFAULT 'Pending'
                   CHECK (status IN ('Pending', 'Approved', 'Rejected')),
               created_at TEXT NOT NULL DEFAULT (datetime('now')),
               FOREIGN KEY (created_by) REFERENCES users (id)
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS announcements (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               title TEXT NOT NULL,
               content TEXT NOT NULL,
               posted_by INTEGER NOT NULL,
               created_at TEXT NOT NULL DEFAULT (datetime('now')),
               FOREIGN KEY (posted_by) REFERENCES users (id)
           )"""
    )

def ensure_schema_migrations():
    """Safely create the schema and apply additive migrations on every startup.

    The transaction serializes concurrent Gunicorn workers so that only the
    first worker applies a missing-column migration. No existing rows are
    dropped or replaced.
    """
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_base_schema(conn)

        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        migrations = {
            "is_active": "INTEGER NOT NULL DEFAULT 1",
            "last_profile_update": "TEXT",
            "must_change_password": "INTEGER NOT NULL DEFAULT 0",
            "session_version": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, definition in migrations.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")

        # Used by the account-settings password-reset flow.
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

        # Used by the one-time reset-token flow. Keep these tables available
        # even when the app is started directly with Gunicorn (without seed.py).
        conn.execute(
            """CREATE TABLE IF NOT EXISTS password_resets (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   user_id INTEGER NOT NULL,
                   token_hash TEXT NOT NULL UNIQUE,
                   expires_at TEXT NOT NULL,
                   used_at TEXT,
                   created_at TEXT NOT NULL DEFAULT (datetime('now')),
                   created_by_admin_id INTEGER NOT NULL,
                   FOREIGN KEY (user_id) REFERENCES users (id),
                   FOREIGN KEY (created_by_admin_id) REFERENCES users (id)
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS audit_logs (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   actor_id INTEGER NOT NULL,
                   target_id INTEGER NOT NULL,
                   action TEXT NOT NULL,
                   status TEXT NOT NULL,
                   created_at TEXT NOT NULL DEFAULT (datetime('now')),
                   FOREIGN KEY (actor_id) REFERENCES users (id),
                   FOREIGN KEY (target_id) REFERENCES users (id)
               )"""
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()