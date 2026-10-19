from datetime import datetime, timezone

from werkzeug.security import generate_password_hash, check_password_hash

from store import store

VALID_ROLES = ("admin", "staff", "student")


def create_user(name, email, password, role, must_change_password=False):
    if get_user_by_email(email):
        return None
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    row = store.add("users", {
        "name": name, "email": email, "password_hash": generate_password_hash(password),
        "role": role, "created_at": now, "is_active": 1, "deleted_at": None,
        "last_profile_update": None, "last_name_change": None,
        "must_change_password": int(bool(must_change_password)), "session_version": 0,
        "password_reset_pending": 0,
    })
    return row["id"]


def get_user_by_email(email):
    normalized = (email or "").casefold()
    return next((row for row in store.all("users")
                 if row["email"].casefold() == normalized), None)


def get_user_by_id(user_id):
    return store.get("users", user_id)


def get_all_users(role=None, include_deleted=True):
    rows = store.all("users")
    if not include_deleted:
        rows = [row for row in rows if row["deleted_at"] is None]
    if role:
        rows = [row for row in rows if row["role"] == role]
    return sorted(rows, key=lambda row: (row["role"], row["name"].casefold()))


def count_users_by_role(role):
    return sum(row["role"] == role and row["deleted_at"] is None
               for row in store.all("users"))


def delete_user(user_id):
    """Permanently remove the account, retaining authored event history."""
    target = get_user_by_id(user_id)
    if target is None:
        return False
    for event in store.all("events"):
        if event["created_by"] == user_id:
            store.update("events", event["id"], {
                "created_by_name": event.get("created_by_name") or target["name"],
                "created_by_role": event.get("created_by_role") or target["role"],
                "created_by": None,
            })
    for announcement in store.all("announcements"):
        if announcement.get("posted_by") == user_id:
            store.update("announcements", announcement["id"], {
                "posted_by_name": announcement.get("posted_by_name") or target["name"],
                "posted_by": None,
            })
    store.remove_where("password_resets", lambda row:
                       row.get("user_id") == user_id or row.get("created_by_admin_id") == user_id)
    store.remove_where("audit_logs", lambda row:
                       row.get("actor_id") == user_id or row.get("target_id") == user_id)
    store.update_where("audit_log", lambda row: row.get("admin_id") == user_id,
                       {"admin_id": None})
    store.update_where("audit_log", lambda row: row.get("target_user_id") == user_id,
                       {"target_user_id": None})
    store.remove_where("admin_password_recoveries", lambda row:
                       row.get("admin_email", "").casefold() == target["email"].casefold())
    store.remove_where("account_password_notices", lambda row:
                       row.get("email", "").casefold() == target["email"].casefold())
    return store.remove("users", user_id) is not None


def update_user_account(user_id, name, email, role):
    conflict = next((row for row in store.all("users")
                     if row["email"].casefold() == email.casefold()
                     and row["id"] != user_id), None)
    if conflict:
        return False
    return store.update("users", user_id, {"name": name, "email": email, "role": role}) is not None


def set_user_active(user_id, is_active):
    user = get_user_by_id(user_id)
    if user is None:
        return False
    return store.update("users", user_id, {
        "is_active": int(bool(is_active)),
        "deleted_at": None if is_active else user["deleted_at"],
    }) is not None


def update_own_profile(user_id, name, email):
    conflict = next((row for row in store.all("users")
                     if row["email"].casefold() == email.casefold()
                     and row["id"] != user_id), None)
    if conflict:
        return False
    return store.update("users", user_id, {"name": name, "email": email}) is not None


def set_last_profile_update(user_id, timestamp):
    store.update("users", user_id, {"last_profile_update": timestamp})


def set_last_name_change(user_id, timestamp):
    store.update("users", user_id, {"last_name_change": timestamp})


def update_password(user_id, new_password):
    store.update("users", user_id, {"password_hash": generate_password_hash(new_password)})


def admin_reset_password(admin_id, target_id, new_password):
    target = get_user_by_id(target_id)
    if target is None or target["role"] not in ("student", "staff"):
        return False
    store.update("users", target_id, {
        "password_hash": generate_password_hash(new_password),
        "must_change_password": 1,
        "password_reset_pending": 1,
        "session_version": target["session_version"] + 1,
    })
    store.add("audit_log", {
        "admin_id": admin_id, "target_user_id": target_id,
        "action": "admin_password_reset", "status": "success",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return True


def record_account_password_notice(email, temporary_password):
    """Keep the current temporary password in memory for the admin to retrieve."""
    normalized_email = (email or "").casefold()
    store.remove_where("account_password_notices", lambda row:
                       row.get("email", "").casefold() == normalized_email)
    store.add("account_password_notices", {
        "email": email,
        "temporary_password": temporary_password,
    })
    # Keep the dashboard notice list small and relevant for this temporary store.
    notices = store.all("account_password_notices")
    for notice in notices[:-50]:
        store.remove("account_password_notices", notice["id"])


def get_recent_account_password_notices(limit=20):
    return sorted(store.all("account_password_notices"),
                  key=lambda row: row["id"], reverse=True)[:limit]


def complete_forced_password_change(user_id, new_password):
    user = get_user_by_id(user_id)
    if user is not None:
        store.update("users", user_id, {
            "password_hash": generate_password_hash(new_password),
            "must_change_password": 0,
            "password_reset_pending": 0,
            "session_version": user["session_version"] + 1,
        })
        store.remove_where("account_password_notices", lambda row:
                           row.get("email", "").casefold() == user["email"].casefold())


def verify_password(user_row, password):
    return check_password_hash(user_row["password_hash"], password)
