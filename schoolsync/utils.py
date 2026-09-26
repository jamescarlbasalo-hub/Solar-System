"""
utils.py
--------
Two kinds of helpers:
1. Decorators that protect routes (`login_required`, `role_required`) —
   these wrap a route function and run a check *before* it, redirecting
   away if the check fails.
2. Small validation functions for form input.
"""

import re
from datetime import datetime
from functools import wraps
from flask import session, redirect, url_for, flash, g

from models import get_user_by_id

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Where each role lands after logging in — used all over app.py.
ROLE_DASHBOARDS = {
    "admin": "admin_dashboard",
    "staff": "staff_dashboard",
    "student": "student_dashboard",
}


def current_user():
    """Loads the logged-in user's full database row, if any.
    Cached on `g` so it only queries the database once per request even
    if multiple things ask "who's logged in?" during the same request."""
    if "user" not in g:
        user_id = session.get("user_id")
        g.user = get_user_by_id(user_id) if user_id else None
    return g.user


def login_required(view):
    """Blocks a route unless someone is logged in."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(*allowed_roles):
    """
    Blocks a route unless the logged-in user's role is one of the
    roles listed. Usage:

        @app.route("/admin/users")
        @role_required("admin")
        def manage_users(): ...
    """
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                flash("Please log in to continue.", "error")
                return redirect(url_for("login"))
            if user["role"] not in allowed_roles:
                flash("You don't have permission to view that page.", "error")
                return redirect(url_for(ROLE_DASHBOARDS[user["role"]]))
            return view(*args, **kwargs)
        return wrapped
    return decorator


# ---------------------------------------------------------------------------
# FORM VALIDATION HELPERS
# ---------------------------------------------------------------------------
def validate_signup_fields(name, email, password, role):
    """Returns a list of error strings — empty list means everything's valid."""
    errors = []
    if not name or not name.strip():
        errors.append("Name is required.")
    elif len(name) > 100:
        errors.append("Name must be under 100 characters.")

    if not email or not EMAIL_PATTERN.match(email):
        errors.append("Please enter a valid email address.")

    if not password or len(password) < 6:
        errors.append("Password must be at least 6 characters.")

    if role not in ("admin", "staff", "student"):
        errors.append("Invalid role selected.")

    return errors


def validate_event_fields(title, date_str, start_time, end_time, location, description):
    """Returns a list of error strings — empty list means everything's valid."""
    errors = []

    if not title or not title.strip():
        errors.append("Title is required.")
    elif len(title) > 150:
        errors.append("Title must be under 150 characters.")

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        errors.append("Please choose a valid date.")

    # Staff/Admin can mark the time as "TBA" when it isn't set yet — both
    # fields come in as the "TBA" sentinel together (see event_form.html's
    # toggle), so skip the normal time-format / start-before-end checks
    # for that case entirely rather than rejecting "TBA" as a bad time.
    is_tba = start_time == "TBA" and end_time == "TBA"

    if not is_tba:
        start_dt = end_dt = None
        try:
            start_dt = datetime.strptime(start_time, "%H:%M")
        except (ValueError, TypeError):
            errors.append("Please choose a valid start time.")
        try:
            end_dt = datetime.strptime(end_time, "%H:%M")
        except (ValueError, TypeError):
            errors.append("Please choose a valid end time.")
        if start_dt and end_dt and end_dt <= start_dt:
            errors.append("End time must be after the start time.")

    if not location or not location.strip():
        errors.append("Location is required.")

    if description and len(description) > 1000:
        errors.append("Description must be under 1000 characters.")

    return errors