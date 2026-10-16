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


def get_all_users(role=None, include_deleted=False):
    """All non-deleted users, optionally filtered to one role.

    Soft-deleted staff are available separately for the admin archive.
    """
    db = get_db()
    conditions = []
    params = []
    if not include_deleted:
        conditions.append("deleted_at IS NULL")
    if role:
        conditions.append("role = ?")
        params.append(role)
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    return db.execute(
        f"SELECT * FROM users{where} ORDER BY role, name", params
    ).fetchall()


def get_deleted_staff():
    """Return soft-deleted staff for the admin's read-only archive."""
    db = get_db()
    return db.execute(
        "SELECT * FROM users WHERE role = 'staff' AND deleted_at IS NOT NULL "
        "ORDER BY deleted_at DESC, name"
    ).fetchall()


def count_users_by_role(role):
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) AS total FROM users WHERE role = ? AND deleted_at IS NULL",
        (role,),
    ).fetchone()
    return row["total"]


def soft_delete_staff(admin_id, staff_id):
    """Soft-delete one staff account and audit it in one transaction.

    Keeps the users row and all event relationships intact, revokes active
    sessions by incrementing session_version, and prevents repeat deletion.
    Returns one of: deleted, already_deleted, not_found, not_staff, conflict.
    Database errors are rolled back and re-raised for the route to handle.
    """
    db = get_db()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        cursor = db.execute(
            """UPDATE users
                  SET is_active = 0,
                      deleted_at = ?,
                      session_version = session_version + 1
                WHERE id = ? AND role = 'staff' AND deleted_at IS NULL""",
            (now, staff_id),
        )
        if cursor.rowcount != 1:
            target = db.execute(
                "SELECT role, deleted_at FROM users WHERE id = ?", (staff_id,)
            ).fetchone()
            db.rollback()
            if target is None:
                return "not_found"
            if target["role"] != "staff":
                return "not_staff"
            if target["deleted_at"] is not None:
                return "already_deleted"
            return "conflict"

        db.execute(
            """INSERT INTO audit_log
                   (admin_id, target_user_id, action, status, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (admin_id, staff_id, "staff_soft_deleted", "success", now),
        )
        db.commit()
        return "deleted"
    except database.DATABASE_ERRORS:
        db.rollback()
        raise


def delete_user(user_id):
    """Delete an account when nothing references it.

    Returns False when foreign-key history (such as submitted events or
    audit records) prevents deletion, leaving the caller to deactivate it
    instead so related records remain intact.
    """
    db = get_db()
    try:
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
        return True
    except database.INTEGRITY_ERRORS:
        db.rollback()
        return False


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
    if is_active:
        cursor = db.execute(
            "UPDATE users SET is_active = 1 WHERE id = ? AND deleted_at IS NULL",
            (user_id,),
        )
    else:
        cursor = db.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
    db.commit()
    return cursor.rowcount == 1


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
