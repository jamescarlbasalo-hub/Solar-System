"""
events.py
---------
Functions for reading and writing the `events` table, plus two small
"who's allowed to see/edit this" helpers that centralize the approval
and permission rules in one place, so every route follows the same
logic instead of each route re-implementing it slightly differently.
"""

from datetime import date as date_cls
from database import get_db

VALID_STATUSES = ("Pending", "Approved", "Rejected")


# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------
def create_event(title, date, start_time, end_time, location, description, created_by, status):
    db = get_db()
    cursor = db.execute(
        """INSERT INTO events (title, date, start_time, end_time, location, description, created_by, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, date, start_time, end_time, location, description, created_by, status),
    )
    db.commit()
    return cursor.lastrowid


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
    month_str = f"{year:04d}-{month:02d}"
    rows = db.execute(
        "SELECT * FROM events WHERE strftime('%Y-%m', date) = ? ORDER BY date, start_time",
        (month_str,),
    ).fetchall()
    return rows


def get_events_by_date(date_str):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM events WHERE date = ? ORDER BY start_time", (date_str,)
    ).fetchall()
    return rows


def get_events_by_creator(user_id):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM events WHERE created_by = ? ORDER BY date DESC", (user_id,)
    ).fetchall()
    return rows


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
        """SELECT * FROM events WHERE status = 'Approved' AND date >= ?
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
    return f"{event['start_time']} – {event['end_time']}"


# ---------------------------------------------------------------------------
# VISIBILITY + PERMISSION RULES
# (kept here in one place so every route enforces the same rule)
# ---------------------------------------------------------------------------
def is_visible(event, user):
    """Can this user see this event at all?
    - Admin: sees everything.
    - Staff: sees every Approved event, plus their own regardless of status.
    - Student: sees Approved events only.
    """
    if user["role"] == "admin":
        return True
    if event["status"] == "Approved":
        return True
    if user["role"] == "staff" and event["created_by"] == user["id"]:
        return True
    return False


def filter_visible(events, user):
    return [e for e in events if is_visible(e, user)]


def can_edit(event, user):
    """Admin can edit anything. Staff can edit their own event, but only
    while it's still Pending or Rejected — once Admin approves it, only
    Admin can change it further (keeps the approved calendar trustworthy)."""
    if user["role"] == "admin":
        return True
    if user["role"] == "staff" and event["created_by"] == user["id"]:
        return event["status"] in ("Pending", "Rejected")
    return False


def can_delete(event, user):
    """Only Admin can delete events, per the brief."""
    return user["role"] == "admin"