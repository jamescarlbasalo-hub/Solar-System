from datetime import datetime, timezone

from werkzeug.security import generate_password_hash, check_password_hash
import database
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
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?) RETURNING id",
            (name, email, password_hash, role),
        )
        user_id = cursor.fetchone()["id"]
        db.commit()
        return user_id
    except database.INTEGRITY_ERRORS:
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


def update_user_account(user_id, name, email, role):
    """Admin-side edit: change another account's name, email, and role.
    Returns True on success, False if that email is already taken by a
    *different* account (the UNIQUE constraint on email catches this —
    updating a user to the email they already have is not a conflict)."""
    db = get_db()
    try:
        db.execute(
            "UPDATE users SET name = ?, email = ?, role = ? WHERE id = ?",
            (name, email, role, user_id),
        )
        db.commit()
        return True
    except database.INTEGRITY_ERRORS:
        return False


def set_user_active(user_id, is_active):
    """Deactivate or reactivate an account without deleting it — their
    row and event history stay intact, they just can't log in while
    is_active is 0."""
    db = get_db()
    db.execute("UPDATE users SET is_active = ? WHERE id = ?", (1 if is_active else 0, user_id))
    db.commit()


def update_own_profile(user_id, name, email):
    """Self-service edit of your own name/email. Deliberately does not
    accept a role — only Admin can change roles, via update_user_account
    above. Same email-uniqueness handling as update_user_account."""
    db = get_db()
    try:
        db.execute(
            "UPDATE users SET name = ?, email = ? WHERE id = ?",
            (name, email, user_id),
        )
        db.commit()
        return True
    except database.INTEGRITY_ERRORS:
        return False


def set_last_profile_update(user_id, timestamp):
    """Stamps when a user last used the self-service Account Settings
    page — used to enforce the 30-day cooldown between self-edits."""
    db = get_db()
    db.execute("UPDATE users SET last_profile_update = ? WHERE id = ?", (timestamp, user_id))
    db.commit()


def set_last_name_change(user_id, timestamp):
    """Record the time a student last changed their own name."""
    db = get_db()
    db.execute("UPDATE users SET last_name_change = ? WHERE id = ?", (timestamp, user_id))
    db.commit()


def update_password(user_id, new_password):
    """Hashes and stores a new password the same way create_user() does."""
    db = get_db()
    password_hash = generate_password_hash(new_password)
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
    db.commit()


def admin_reset_password(admin_id, target_id, new_password):
    """Admin resets a Student's or Staff member's password.

    In ONE database transaction this:
      1. stores the new password's HASH (never the password itself),
      2. flags the account so its owner must choose a new password at
         their next login (must_change_password = 1),
      3. bumps session_version so any session that account already had
         open stops working (the Admin's own session is untouched — it
         belongs to a different row),
      4. writes an audit_log row: who, whom, when, what, outcome.
         The password and the hash are never written to the log.

    The `role IN ('student', 'staff')` condition is a second safety net:
    even if a route let an Admin id through by mistake, an Admin
    account's password can't be changed by this function.

    Returns True on success, False if no such resettable account exists.
    Raises a database driver error on failure (after rolling back)."""
    db = get_db()
    password_hash = generate_password_hash(new_password)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        cursor = db.execute(
            """UPDATE users
                  SET password_hash = ?,
                      must_change_password = 1,
                      session_version = session_version + 1
                WHERE id = ? AND role IN ('student', 'staff')""",
            (password_hash, target_id),
        )
        if cursor.rowcount != 1:
            db.rollback()
            return False
        db.execute(
            """INSERT INTO audit_log (admin_id, target_user_id, action, status, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (admin_id, target_id, "admin_password_reset", "success", now),
        )
        db.commit()
        return True
    except database.DATABASE_ERRORS:
        db.rollback()
        raise


def complete_forced_password_change(user_id, new_password):
    """The affected user has chosen their own permanent password: store
    its hash, clear the must-change flag, and bump session_version so
    any other session still using the temporary password is cut off."""
    db = get_db()
    password_hash = generate_password_hash(new_password)
    db.execute(
        """UPDATE users
              SET password_hash = ?,
                  must_change_password = 0,
                  session_version = session_version + 1
            WHERE id = ?""",
        (password_hash, user_id),
    )
    db.commit()


def verify_password(user_row, password):
    """Checks a plain-text password against the stored hash.
    Returns True/False — never compares raw passwords directly."""
    return check_password_hash(user_row["password_hash"], password)
