"""
utils.py
--------
Helpers shared across the app:
1. Decorators that protect routes (`login_required`, `role_required`) —
   these wrap a route function and run a check *before* it, redirecting
   away if the check fails. Plus the CSRF token helpers.
2. Small validation functions for form input.
3. Password helpers (temporary-password generator, validators).
"""

import hmac
import re
import secrets
from datetime import datetime
from functools import wraps
from flask import session, redirect, url_for, flash, g, request, render_template

from models import get_user_by_id

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Password rules. The 6-character minimum is the same rule signup and
# Account Settings already use. A temporary password an Admin types in
# by hand has to be a bit longer, since an Admin is handing it to
# someone else.
PASSWORD_MIN_LENGTH = 6
TEMP_PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128  # stops absurdly long input from burning CPU while hashing

# Letters and digits with look-alikes removed (no 0/O, 1/l/I), so a
# generated temporary password is easy to read out or type from a screen.
_TEMP_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"

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
        user = get_user_by_id(user_id) if user_id else None
        # An Admin can deactivate someone while they're mid-session — this
        # makes that take effect on their very next request, instead of
        # only blocking future logins. session.clear() ends that session
        # immediately; login_required/role_required will then redirect
        # them to the login page like anyone else who isn't logged in.
        if user is not None and not user["is_active"]:
            session.clear()
            user = None
        # Same idea for password resets: an Admin reset bumps the user's
        # session_version, so a session that was opened before the reset
        # (still carrying the old number) is ended here. Sessions that
        # predate this feature have no "sv" and count as 0, which matches
        # the column's default — so nobody is logged out by the upgrade.
        if user is not None and session.get("sv", 0) != user["session_version"]:
            session.clear()
            user = None
        g.user = user
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
# CSRF PROTECTION
# A CSRF attack is another website tricking a logged-in person's browser
# into submitting a form to SchoolSync without them knowing. The defence:
# every form carries a secret random token that only pages served by
# SchoolSync can contain, and the server rejects any POST whose token
# doesn't match the one stored in that person's session.
#
# How it fits together:
#   - base.html puts the token in a <meta> tag and a small script copies
#     it into every POST form on the page (so templates need no edits).
#   - app.py runs csrf_token_is_valid() before EVERY non-GET request.
# ---------------------------------------------------------------------------
CSRF_SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def get_csrf_token():
    """Returns this session's CSRF token, creating it the first time.
    Templates call it as {{ csrf_token() }} (registered in app.py)."""
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def csrf_token_is_valid():
    """True only if this request carries the token that belongs to this
    session — in the `csrf_token` form field (or an X-CSRFToken header)."""
    sent = request.form.get("csrf_token", "") or request.headers.get("X-CSRFToken", "")
    expected = session.get("csrf_token", "")
    if not sent or not expected:
        return False
    # compare_digest compares in constant time (so timing can't leak the
    # token); it needs bytes to accept non-ASCII input without crashing.
    return hmac.compare_digest(sent.encode("utf-8"), expected.encode("utf-8"))


def csrf_error_response():
    """What a visitor sees when the token is missing or wrong."""
    return render_template(
        "error.html", code=400,
        message="Your form expired or was invalid. Go back, refresh the page, and try again.",
    ), 400


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


def validate_profile_fields(name, email):
    """For the self-service 'edit my name/email' form — same rules as
    validate_signup_fields' name/email checks, minus password and role
    since this form doesn't touch either."""
    errors = []
    if not name or not name.strip():
        errors.append("Name is required.")
    elif len(name) > 100:
        errors.append("Name must be under 100 characters.")

    if not email or not EMAIL_PATTERN.match(email):
        errors.append("Please enter a valid email address.")

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


# ---------------------------------------------------------------------------
# PASSWORD HELPERS
# ---------------------------------------------------------------------------
def generate_temporary_password(length=12):
    """A random temporary password from Python's `secrets` module, which
    is built for security (unlike `random`, it can't be predicted).
    Retries until it contains an uppercase letter, a lowercase letter
    and a digit, so it always looks like a proper password."""
    while True:
        candidate = "".join(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(length))
        if (any(c.isupper() for c in candidate)
                and any(c.islower() for c in candidate)
                and any(c.isdigit() for c in candidate)):
            return candidate


def validate_temporary_password(password):
    """Rules for a temporary password an Admin types in by hand.
    Returns a list of error strings — empty list means it's valid."""
    errors = []
    if not password or not password.strip():
        errors.append("Please enter a temporary password.")
    elif len(password) < TEMP_PASSWORD_MIN_LENGTH:
        errors.append(f"The temporary password must be at least {TEMP_PASSWORD_MIN_LENGTH} characters.")
    elif len(password) > PASSWORD_MAX_LENGTH:
        errors.append(f"The temporary password must be under {PASSWORD_MAX_LENGTH} characters.")
    return errors


def validate_new_password(password, confirm):
    """Rules for the permanent password someone chooses on the forced
    Change Password page. Returns a list of error strings."""
    errors = []
    if not password:
        errors.append("Please enter a new password.")
    elif len(password) < PASSWORD_MIN_LENGTH:
        errors.append(f"Password must be at least {PASSWORD_MIN_LENGTH} characters.")
    elif len(password) > PASSWORD_MAX_LENGTH:
        errors.append(f"Password must be under {PASSWORD_MAX_LENGTH} characters.")
    if password != confirm:
        errors.append("The two passwords don't match.")
    return errors