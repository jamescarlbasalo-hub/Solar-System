"""
models.py
---------
Functions for reading and writing the `users` table. Every route in
app.py that needs to touch user data calls a function from here instead
of writing raw SQL itself — that way, if you ever need to change how a
query works, you only change it in one place.

We're using plain functions here (not classes) since there's no
inheritance/polymorphism requirement for this project — just clear,
readable functions that each do one thing.
"""

from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db

VALID_ROLES = ("admin", "staff", "student")


def create_user(name, email, password, role):
    """
    Adds a new user. The password is hashed before it's stored — the
    real password is never saved anywhere, only a one-way scrambled
    version that can be checked against but not reversed.

    Returns the new user's id, or None if the email is already taken
    (emails must be unique).
    """
    db = get_db()
    password_hash = generate_password_hash(password)
    try:
        cursor = db.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (name, email, password_hash, role),
        )
        db.commit()
        return cursor.lastrowid
    except db.IntegrityError:
        # This fires if the UNIQUE constraint on `email` is violated.
        return None


def get_user_by_email(email):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return row


def get_user_by_id(user_id):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return row


def get_all_users(role=None):
    """All users, optionally filtered to one role (e.g. just 'student')."""
    db = get_db()
    if role:
        rows = db.execute(
            "SELECT * FROM users WHERE role = ? ORDER BY name", (role,)
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM users ORDER BY role, name").fetchall()
    return rows


def count_users_by_role(role):
    db = get_db()
    row = db.execute("SELECT COUNT(*) AS total FROM users WHERE role = ?", (role,)).fetchone()
    return row["total"]


def delete_user(user_id):
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()


def verify_password(user_row, password):
    """Checks a plain-text password against the stored hash.
    Returns True/False — never compares raw passwords directly."""
    return check_password_hash(user_row["password_hash"], password)
