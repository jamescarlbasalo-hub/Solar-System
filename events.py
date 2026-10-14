from datetime import date as date_cls, datetime
from database import get_db

VALID_STATUSES = ("Pending", "Approved", "Rejected")

# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------
def create_event(title, date, start_time, end_time, location, description, created_by, status):
    db = get_db()
    cursor = db.execute(
        """INSERT INTO events (title, date, start_time, end_time, location, description, created_by, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
        (title, date, start_time, end_time, location, description, created_by, status),
    )
    event_id = cursor.fetchone()["id"]
    db.commit()
    return event_id


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------
def get_event_by_id(event_id):
    db = get_db()
    return db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()


def get_events_by_month(year, month):
    """All events in a given month, any status — visibility filtering
    happens separately via filter_visible(), not here."""
    db = get_db()
    month_start = date_cls(year, month, 1).isoformat()
    if month == 12:
        month_end = date_cls(year + 1, 1, 1).isoformat()
    else:
        month_end = date_cls(year, month + 1, 1).isoformat()
    rows = db.execute(
        "SELECT * FROM events WHERE date >= ? AND date < ? ORDER BY date, start_time",
        (month_start, month_end),
    ).fetchall()
    return rows


def get_events_by_date(date_str):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM events WHERE date = ? ORDER BY start_time", (date_str,)
    ).fetchall()
    return rows


def get_all_events():
    """Every event, any status — newest dates first. Used by the Admin
    dashboard's "All Events" manager."""
    db = get_db()
    return db.execute(
        "SELECT * FROM events ORDER BY date DESC, start_time"
    ).fetchall()


def get_events_by_creator(user_id):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM events WHERE created_by = ? ORDER BY date DESC", (user_id,)
    ).fetchall()
    return rows


def get_events_by_creator_roles(roles):
    """Return events submitted by users with any of the supplied roles."""
    roles = tuple(roles)
    if not roles:
        return []

    placeholders = ", ".join("?" for _ in roles)
    db = get_db()
    return db.execute(
        f"""SELECT events.*, users.name AS creator_name, users.role AS creator_role
            FROM events
            JOIN users ON users.id = events.created_by
            WHERE users.role IN ({placeholders})
            ORDER BY events.date DESC, events.start_time""",
        roles,
    ).fetchall()


def get_events_by_status(status):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM events WHERE status = ? ORDER BY date", (status,)
    ).fetchall()
    return rows


def get_upcoming_approved_events(limit=5):
    db = get_db()
    today_str = date_cls.today().isoformat()
    rows = db.execute(
        """SELECT * FROM events WHERE status = 'Approved' AND date > ?
           ORDER BY date, start_time LIMIT ?""",
        (today_str, limit),
    ).fetchall()
    return rows


def get_todays_approved_events():
    db = get_db()
    today_str = date_cls.today().isoformat()
    rows = db.execute(
        "SELECT * FROM events WHERE status = 'Approved' AND date = ? ORDER BY start_time",
        (today_str,),
    ).fetchall()
    return rows


def count_all_events():
    db = get_db()
    return db.execute("SELECT COUNT(*) AS total FROM events").fetchone()["total"]


def count_events_by_status(status):
    db = get_db()
    return db.execute(
        "SELECT COUNT(*) AS total FROM events WHERE status = ?", (status,)
    ).fetchone()["total"]


# ---------------------------------------------------------------------------
# UPDATE
# ---------------------------------------------------------------------------
def update_event(event_id, title, date, start_time, end_time, location, description):
    db = get_db()
    db.execute(
        """UPDATE events SET title = ?, date = ?, start_time = ?, end_time = ?,
           location = ?, description = ? WHERE id = ?""",
        (title, date, start_time, end_time, location, description, event_id),
    )
    db.commit()


def set_event_status(event_id, status):
    if status not in VALID_STATUSES:
        raise ValueError(f"'{status}' is not a valid event status.")
    db = get_db()
    db.execute("UPDATE events SET status = ? WHERE id = ?", (status, event_id))
    db.commit()


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------
def delete_event(event_id):
    db = get_db()
    db.execute("DELETE FROM events WHERE id = ?", (event_id,))
    db.commit()


# ---------------------------------------------------------------------------
# DISPLAY HELPER
# ---------------------------------------------------------------------------
def event_time_display(event):
    """Human-readable time string for templates. Staff can mark an event's
    time as the "TBA" sentinel when it isn't decided yet — treat that as a
    special case here instead of letting every template re-check for it."""
    if event["start_time"] == "TBA" or event["end_time"] == "TBA":
        return "Time to be announced"

    def format_time(value):
        try:
            parsed = datetime.strptime(value, "%H:%M")
        except (TypeError, ValueError):
            return value
        return parsed.strftime("%I:%M %p").lstrip("0")

    return f"{format_time(event['start_time'])} – {format_time(event['end_time'])}"


# ---------------------------------------------------------------------------
# VISIBILITY + PERMISSION RULES
# (kept here in one place so every route enforces the same rule)
# ---------------------------------------------------------------------------
def is_visible(event, user):
    """Can this user see this event at all?
    - Admin: sees everything.
    - Staff: sees approved events and every staff/admin submission at any status.
    - Student: sees Approved events only.
    """
    if user["role"] == "admin":
        return True
    if event["status"] == "Approved":
        return True
    if user["role"] == "staff":
        creator = get_db().execute(
            "SELECT role FROM users WHERE id = ?", (event["created_by"],)
        ).fetchone()
        return creator is not None and creator["role"] in ("staff", "admin")
    return False


def filter_visible(events, user):
    return [e for e in events if is_visible(e, user)]


def staff_can_manage(event):
    """Staff can manage events created by any staff or admin account."""
    creator = get_db().execute(
        "SELECT role FROM users WHERE id = ?", (event["created_by"],)
    ).fetchone()
    return creator is not None and creator["role"] in ("staff", "admin")


def can_edit(event, user):
    """Admins can edit any event; staff can edit staff/admin events at any status."""
    if user["role"] == "admin":
        return True
    return user["role"] == "staff" and staff_can_manage(event)


def can_delete(event, user):
    """Admins can delete any event; staff can delete staff/admin events."""
    if user["role"] == "admin":
        return True
    return user["role"] == "staff" and staff_can_manage(event)

def can_moderate(event, user):
    """Admins moderate any event; staff moderate events created by staff/admin accounts."""
    if user["role"] == "admin":
        return True
    return user["role"] == "staff" and staff_can_manage(event)
