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
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    
    # Check if the users table exists before trying to inspect its columns
    table_check = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
    
    if table_check:
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "is_active" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
            conn.commit()
        if "last_profile_update" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN last_profile_update TEXT")
            conn.commit()
            
    conn.close()