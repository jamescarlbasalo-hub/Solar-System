import os
import calendar as cal
from datetime import datetime, timedelta

from flask import (
    Flask, render_template, request, redirect, url_for, session, flash, make_response,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash

from account_types import account_from_record
from store import store
from models import (
    get_user_by_email, get_user_by_id, verify_password, count_users_by_role,
    create_user, get_all_users, delete_user,
    update_user_account, set_user_active, update_own_profile, update_password,
    set_last_name_change, admin_reset_password, complete_forced_password_change,
)
from events import (
    create_event, get_event_by_id, get_events_by_month, get_events_by_date,
    get_events_by_creator, get_events_by_creator_roles, get_events_by_status, get_upcoming_approved_events,
    get_todays_approved_events, count_all_events, count_events_by_status,
    update_event, set_event_status, delete_event, school_today,
    is_visible, filter_visible, can_edit, can_delete, can_moderate, event_time_display,
)
from utils import (
    login_required, role_required, current_user, validate_signup_fields,
    validate_event_fields, validate_profile_fields, ROLE_DASHBOARDS,
    CSRF_SAFE_METHODS, get_csrf_token, csrf_token_is_valid, csrf_error_response,
    generate_temporary_password, validate_temporary_password, validate_new_password,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-this-before-deploying")

# Refuse any request whose body is bigger than this before it's even read
# into memory. Without a cap, Flask will happily try to load a multi-GB
# POST body in full — a handful of those at once is enough to exhaust
# server RAM. 1 MB is generous for anything this app's forms send.
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024

# Browsers won't attach the login cookie to a form posted from another
# website. A second layer on top of the CSRF tokens below.
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("RENDER"))

def bootstrap_admin_from_environment():
    """Create the first production admin from Render environment settings."""
    email = os.environ.get("SCHOOLSYNC_ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("SCHOOLSYNC_ADMIN_PASSWORD", "")
    if not email or not password:
        return

    with app.app_context():
        if get_user_by_email(email) is None:
            name = os.environ.get("SCHOOLSYNC_ADMIN_NAME", "School Administrator").strip()
            create_user(name or "School Administrator", email, password, "admin")


bootstrap_admin_from_environment()


def recover_admin_from_environment():
    """Apply an explicitly configured, one-time admin password recovery."""
    email = os.environ.get("SCHOOLSYNC_ADMIN_RECOVERY_EMAIL", "").strip().lower()
    password = os.environ.get("SCHOOLSYNC_ADMIN_RECOVERY_PASSWORD", "")
    token = os.environ.get("SCHOOLSYNC_ADMIN_RECOVERY_TOKEN", "").strip()
    if not email and not password and not token:
        return
    if not email or len(password) < 12 or len(password) > 128 or len(token) < 32:
        print(
            "Admin recovery skipped: set a valid recovery email, a password "
            "of 12-128 characters, and a unique token of at least 32 characters."
        )
        return

    import hashlib
    from datetime import datetime, timezone

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if any(row["token_hash"] == token_hash
           for row in store.all("admin_password_recoveries")):
        print("Admin recovery token was already used in this process; no password was changed.")
        return
    admin = get_user_by_email(email)
    if admin is None or admin["role"] != "admin":
        print("Admin recovery skipped: no admin account matches the recovery email.")
        return

    store.update("users", admin["id"], {
        "password_hash": generate_password_hash(password),
        "session_version": admin["session_version"] + 1,
        "must_change_password": 0,
    })
    store.add("admin_password_recoveries", {
        "token_hash": token_hash,
        "admin_email": email,
        "used_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    print("Admin password recovery completed for the configured account.")


recover_admin_from_environment()

# Populate predictable sample records only in local development. This runs
# in the same process as Flask so those records are available to its routes.
from seed import seed_development_data
seed_development_data()

# Limits how many requests one IP address can make in a given window.
# default_limits applies everywhere unless a route sets its own tighter
# limit (see login/signup below) — this stops one client from hammering
# any single endpoint fast enough to burn server CPU/DB connections.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per minute"],
    storage_uri="memory://",
)


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


# Lets any template call event_time_display(event) to print "Time to be
# announced" for TBA events instead of a raw "TBA" string.
app.jinja_env.globals["event_time_display"] = event_time_display

# Lets templates use {{ csrf_token() }} (base.html uses it to protect every form).
app.jinja_env.globals["csrf_token"] = get_csrf_token


@app.before_request
def check_csrf_token():
    """Runs before EVERY request. Any request that changes something
    (POST etc.) must carry this session's secret token, or it is refused
    before it reaches any route. This covers every form on the site."""
    if request.method not in CSRF_SAFE_METHODS and not csrf_token_is_valid():
        return csrf_error_response()


# While an Admin-reset password is still waiting to be replaced, these
# are the ONLY pages the account may open. Everything else — dashboards,
# calendar, events, account settings, typed-in URLs — is redirected to
# the Change Password page.
FORCED_CHANGE_ALLOWED_ENDPOINTS = {"change_password", "logout", "static"}


@app.before_request
def enforce_forced_password_change():
    """Runs before EVERY request, so the rule can't be dodged by typing a
    dashboard URL by hand."""
    user = current_user()
    if (user is not None and user["must_change_password"]
            and request.endpoint not in FORCED_CHANGE_ALLOWED_ENDPOINTS):
        return redirect(url_for("change_password"))


# ---------------------------------------------------------------------------
# AUTH ROUTES
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    user = current_user()
    if user:
        return redirect(url_for(ROLE_DASHBOARDS[user["role"]]))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("8 per minute")
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please enter both email and password.", "error")
            return render_template("login.html")

        user = get_user_by_email(email)
        if user is None or not verify_password(user, password):
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        if not user["is_active"] or user["deleted_at"] is not None:
            flash("This account has been deactivated. Contact an Administrator.", "error")
            return render_template("login.html")

        session["user_id"] = user["id"]
        session["sv"] = user["session_version"]  # see utils.current_user()

        # An Admin reset this account's password: the person must pick a
        # new one before they can use anything else.
        if user["must_change_password"]:
            flash("An administrator reset your password. Please choose a new one to continue.", "success")
            return redirect(url_for("change_password"))

        flash(f"Welcome back, {user['name']}!", "success")
        return redirect(url_for(ROLE_DASHBOARDS[user["role"]]))

    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
@limiter.limit("8 per minute")
def signup():
    if current_user():
        return redirect(url_for(ROLE_DASHBOARDS[current_user()["role"]]))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        # Self-signup always creates a Student account. Staff/Admin accounts
        # are created by an Admin from Manage Accounts.
        errors = validate_signup_fields(name, email, password, role="student")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("signup.html", name=name, email=email)

        user_id = create_user(name, email, password, "student")
        if user_id is None:
            flash("That email is already registered — try logging in instead.", "error")
            return render_template("signup.html", name=name, email=email)

        session["user_id"] = user_id
        session["sv"] = 0  # a brand-new account starts at session_version 0
        flash(f"Welcome to SchoolSync, {name}!", "success")
        return redirect(url_for("student_dashboard"))

    return render_template("signup.html", name="", email="")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# DASHBOARDS
# ---------------------------------------------------------------------------
@app.route("/admin/dashboard")
@role_required("admin")
def admin_dashboard():
    stats = {
        "total_students": count_users_by_role("student"),
        "total_staff": count_users_by_role("staff"),
        "total_events": count_all_events(),
        "pending_events": count_events_by_status("Pending"),
        "approved_events": count_events_by_status("Approved"),
        "rejected_events": count_events_by_status("Rejected"),
    }
    recent_pending = get_events_by_status("Pending")
    all_events = get_events_by_status("Approved")
    rejected_events = get_events_by_status("Rejected")
    return render_template("dashboard_admin.html", stats=stats,
                           recent_pending=recent_pending, all_events=all_events,
                           rejected_events=rejected_events)


@app.route("/staff/dashboard")
@role_required("staff")
def staff_dashboard():
    stats = {
        "total_events": count_all_events(),
        "pending_events": count_events_by_status("Pending"),
        "approved_events": count_events_by_status("Approved"),
        "rejected_events": count_events_by_status("Rejected"),
    }
    recent_pending = get_events_by_status("Pending")
    all_events = get_events_by_status("Approved")
    rejected_events = get_events_by_status("Rejected")
    return render_template(
        "dashboard_staff.html",
        stats=stats,
        recent_pending=recent_pending,
        all_events=all_events,
        rejected_events=rejected_events,
    )


@app.route("/student/dashboard")
@role_required("student")
def student_dashboard():
    upcoming = get_upcoming_approved_events(limit=5)
    todays = get_todays_approved_events()
    return render_template("dashboard_student.html", upcoming=upcoming, todays=todays)


# ---------------------------------------------------------------------------
# CALENDAR
# ---------------------------------------------------------------------------
@app.route("/calendar")
@login_required
def calendar_view():
    today = school_today()
    year = request.args.get("year", today.year, type=int)
    month = request.args.get("month", today.month, type=int)

    # Roll over cleanly if Prev/Next pushes us past Jan/Dec.
    if month < 1:
        month, year = 12, year - 1
    elif month > 12:
        month, year = 1, year + 1

    user = current_user()
    visible_events = [event for event in filter_visible(get_events_by_month(year, month), user) if event["status"] == "Approved"]

    events_by_day = {}
    for e in visible_events:
        events_by_day.setdefault(e["date"], []).append(e)

    calendar_obj = cal.Calendar(firstweekday=6)  # weeks start on Sunday
    weeks = calendar_obj.monthdayscalendar(year, month)  # 0 = day outside this month

    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    next_month, next_year = (1, year + 1) if month == 12 else (month + 1, year)

    return render_template(
        "calendar.html",
        year=year, month=month, month_name=cal.month_name[month],
        weeks=weeks, events_by_day=events_by_day, today=today,
        prev_year=prev_year, prev_month=prev_month,
        next_year=next_year, next_month=next_month,
        month_events=visible_events,
    )


@app.route("/calendar/day/<date_str>")
@login_required
def calendar_day(date_str):
    try:
        day_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        flash("That's not a valid date.", "error")
        return redirect(url_for("calendar_view"))

    user = current_user()
    events = [event for event in filter_visible(get_events_by_date(date_str), user) if event["status"] == "Approved"]
    return render_template("calendar_day.html", date_str=date_str, day_date=day_date, events=events)


# ---------------------------------------------------------------------------
# EVENTS: CREATE / READ / UPDATE / DELETE + APPROVAL
# ---------------------------------------------------------------------------
@app.route("/events/new", methods=["GET", "POST"])
@role_required("admin", "staff")
def new_event():
    prefill_date = request.args.get("date", "")

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        date_str = request.form.get("date", "")
        start_time = request.form.get("start_time", "")
        end_time = request.form.get("end_time", "")
        location = request.form.get("location", "").strip()
        description = request.form.get("description", "").strip()

        errors = validate_event_fields(title, date_str, start_time, end_time, location, description)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("event_form.html", form=request.form, mode="new")

        user = current_user()
        # The role-specific account class selects the initial status. Admin
        # and Staff override the same method with their own workflow behavior.
        status = account_from_record(user).initial_event_status()

        event_id = create_event(title, date_str, start_time, end_time, location,
                                 description, user["id"], status)
        flash(
            "Event created and published." if status == "Approved"
            else "Event submitted — an Admin will review it before it appears on the calendar.",
            "success",
        )
        return redirect(url_for("event_detail", event_id=event_id))

    return render_template("event_form.html", form={"date": prefill_date}, mode="new")


@app.route("/events/<int:event_id>")
@login_required
def event_detail(event_id):
    event = get_event_by_id(event_id)
    user = current_user()

    if event is None or not is_visible(event, user):
        flash("That event doesn't exist.", "error")
        return redirect(url_for("calendar_view"))

    creator = get_user_by_id(event["created_by"])
    return render_template(
        "event_detail.html",
        event=event, creator=creator,
        can_edit_event=can_edit(event, user),
        can_delete_event=can_delete(event, user),
        can_approve=(can_moderate(event, user) and event["status"] != "Approved"),
        can_reject=(can_moderate(event, user) and event["status"] != "Rejected"),
    )


@app.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
@login_required
def edit_event(event_id):
    event = get_event_by_id(event_id)
    user = current_user()

    if event is None:
        flash("That event doesn't exist.", "error")
        return redirect(url_for("calendar_view"))
    if not can_edit(event, user):
        flash("You can't edit this event.", "error")
        return redirect(url_for("event_detail", event_id=event_id))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        date_str = request.form.get("date", "")
        start_time = request.form.get("start_time", "")
        end_time = request.form.get("end_time", "")
        location = request.form.get("location", "").strip()
        description = request.form.get("description", "").strip()

        errors = validate_event_fields(title, date_str, start_time, end_time, location, description)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("event_form.html", form=request.form, mode="edit", event_id=event_id)

        update_event(event_id, title, date_str, start_time, end_time, location, description)
        # Editing event details does not change its review status. A rejected
        # event stays rejected until someone explicitly approves it.
        flash("Event updated.", "success")

        return redirect(url_for("event_detail", event_id=event_id))

    return render_template("event_form.html", form=event, mode="edit", event_id=event_id)


@app.route("/events/<int:event_id>/delete", methods=["POST"])
@login_required
def delete_event_route(event_id):
    event = get_event_by_id(event_id)
    user = current_user()
    if event is None:
        flash("That event doesn't exist.", "error")
    elif not can_delete(event, user):
        flash("You don't have permission to delete this event.", "error")
    else:
        delete_event(event_id)
        flash(f"'{event['title']}' was deleted.", "success")
    return redirect(request.referrer or url_for(ROLE_DASHBOARDS[user["role"]]))


@app.route("/events/<int:event_id>/approve", methods=["POST"])
@login_required
def approve_event(event_id):
    event = get_event_by_id(event_id)
    user = current_user()
    if event is None:
        flash("That event doesn't exist.", "error")
    elif not can_moderate(event, user):
        flash("You don't have permission to approve this event.", "error")
    else:
        set_event_status(event_id, "Approved")
        flash(f"'{event['title']}' approved — now visible on the student calendar.", "success")
    return redirect(request.referrer or url_for(ROLE_DASHBOARDS[user["role"]]))


@app.route("/events/<int:event_id>/reject", methods=["POST"])
@login_required
def reject_event(event_id):
    event = get_event_by_id(event_id)
    user = current_user()
    if event is None:
        flash("That event doesn't exist.", "error")
    elif not can_moderate(event, user):
        flash("You don't have permission to reject this event.", "error")
    else:
        set_event_status(event_id, "Rejected")
        flash(f"'{event['title']}' rejected.", "success")
    return redirect(request.referrer or url_for(ROLE_DASHBOARDS[user["role"]]))


@app.route("/events/pending")
@role_required("admin")
def pending_events():
    events = get_events_by_creator_roles(("staff", "admin"))
    return render_template("pending_events.html", events=events)

@app.route("/events/mine")
@role_required("staff")
def my_events():
    events = get_events_by_creator_roles(("staff", "admin"))
    return render_template("my_events.html", events=events)


# ---------------------------------------------------------------------------
# ADMIN: MANAGE ACCOUNTS
# ---------------------------------------------------------------------------
@app.route("/admin/accounts", methods=["GET", "POST"])
@role_required("admin")
def manage_accounts():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "")

        errors = validate_signup_fields(name, email, password, role)
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            user_id = create_user(name, email, password, role)
            if user_id is None:
                flash("That email is already registered.", "error")
            else:
                flash(f"{role.capitalize()} account created for {name}.", "success")
        return redirect(url_for("manage_accounts"))

    users = get_all_users()
    return render_template("manage_accounts.html", users=users)


@app.route("/admin/accounts/<int:user_id>/delete", methods=["POST"])
@role_required("admin")
def delete_account(user_id):
    if user_id == current_user()["id"]:
        flash("You can't delete your own account while logged in.", "error")
    else:
        target = get_user_by_id(user_id)
        if target is None:
            flash("That account no longer exists.", "error")
        elif target["role"] == "admin":
            flash("Admin accounts can't be deleted from Manage Accounts.", "error")
        else:
            deleted = delete_user(user_id)
            if deleted:
                flash(
                    f"Account '{target['email']}' was permanently deleted. "
                    "Its events and announcements were kept with the creator name saved for history.",
                    "success",
                )
            else:
                flash("That account no longer exists.", "error")
    return redirect(url_for("manage_accounts"))


@app.route("/admin/accounts/<int:user_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def edit_account(user_id):
    target = get_user_by_id(user_id)
    if target is None:
        flash("That account doesn't exist.", "error")
        return redirect(url_for("manage_accounts"))
    # An admin editing their own account can't change their own role —
    # same reasoning as the self-delete/self-deactivate guards: it's how
    # someone accidentally demotes themselves out of Admin with no way
    # back in except editing the database directly. This is enforced
    # here, server-side, not just hidden in the form — so it holds even
    # if a request is sent with a different role value in it.
    editing_self = (user_id == current_user()["id"])

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        role = target["role"] if editing_self else request.form.get("role", "")

        errors = validate_profile_fields(name, email)
        if not editing_self and role not in ("admin", "staff", "student"):
            errors.append("Invalid role selected.")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("edit_account.html", target=target, form=request.form,
                                   editing_self=editing_self)

        if not update_user_account(user_id, name, email, role):
            flash("That email is already used by another account.", "error")
            return render_template("edit_account.html", target=target, form=request.form,
                                   editing_self=editing_self)

        flash(f"Account '{email}' updated.", "success")
        return redirect(url_for("manage_accounts"))

    return render_template("edit_account.html", target=target, form=target, editing_self=editing_self)


@app.route("/admin/accounts/<int:user_id>/toggle-active", methods=["POST"])
@role_required("admin")
def toggle_active(user_id):
    if user_id == current_user()["id"]:
        flash("You can't deactivate your own account while logged in.", "error")
        return redirect(url_for("manage_accounts"))

    target = get_user_by_id(user_id)
    if target is None:
        flash("That account doesn't exist.", "error")
        return redirect(url_for("manage_accounts"))
    # Flip whatever it currently is — active becomes inactive, and vice
    # versa — so one button does both jobs depending on current state.
    new_state = not target["is_active"]
    set_user_active(user_id, new_state)
    flash(
        f"'{target['email']}' reactivated." if new_state
        else f"'{target['email']}' deactivated — they can no longer log in.",
        "success",
    )
    return redirect(url_for("manage_accounts"))


@app.route("/admin/accounts/<int:user_id>/reset-password", methods=["POST"])
@role_required("admin")
@limiter.limit("20 per minute")
def reset_account_password(user_id):
    """Admin resets a Student's or Staff member's password to a temporary
    one. The old password is never read or shown (only a hash is stored,
    and a hash can't be reversed). The new temporary password is shown
    once, on the response to this request, and is never saved anywhere
    in readable form."""
    admin = current_user()
    target = get_user_by_id(user_id)

    # The user id comes from the URL, which anyone could edit by hand — so
    # every rule is re-checked here on the server, never trusted from the form.
    if target is None:
        flash("That account doesn't exist.", "error")
        return redirect(url_for("manage_accounts"))
    if target["id"] == admin["id"]:
        flash("Use Account Settings to change your own password.", "error")
        return redirect(url_for("manage_accounts"))
    if target["role"] not in ("student", "staff"):
        flash("Admin passwords can't be reset from here.", "error")
        return redirect(url_for("manage_accounts"))

    mode = request.form.get("mode", "")
    if mode == "generate":
        temp_password = generate_temporary_password()
    elif mode == "manual":
        temp_password = request.form.get("temp_password", "")
        errors = validate_temporary_password(temp_password)
        if errors:
            for e in errors:
                flash(e, "error")
            return redirect(url_for("manage_accounts"))
    else:
        flash("Please choose how to set the temporary password.", "error")
        return redirect(url_for("manage_accounts"))

    reset_done = admin_reset_password(admin["id"], target["id"], temp_password)
    if not reset_done:
        flash("That account's password could not be reset.", "error")
        return redirect(url_for("manage_accounts"))

    # Rendered directly (not redirected) so the temporary password is
    # never placed in the session cookie. no-store tells browsers and
    # proxies not to keep a copy of this page.
    response = make_response(render_template(
        "password_reset_result.html",
        target=target,
        mode=mode,
        temp_password=temp_password if mode == "generate" else None,
    ))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/change-password", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per minute")
def change_password():
    """The page an account lands on after an Admin reset its password.
    It is the only page (besides Log out) that account can use until it
    chooses a new permanent password."""
    user = current_user()

    # Nobody else needs this page. Everyone else changes their password
    # on Account Settings, which has the 30-day limit — so this page
    # can't be used to get around it.
    if not user["must_change_password"]:
        return redirect(url_for("account_settings"))

    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        errors = validate_new_password(new_password, confirm_password)
        if not errors and verify_password(user, new_password):
            errors.append("Your new password must be different from the temporary one.")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("change_password.html")

        complete_forced_password_change(user["id"], new_password)
        # Keep THIS browser signed in: the version number changed, so
        # copy the new one into this session. Any other session that
        # still used the temporary password is now ended.
        session["sv"] = get_user_by_id(user["id"])["session_version"]

        flash("Password updated. Welcome back!", "success")
        return redirect(url_for(ROLE_DASHBOARDS[user["role"]]))

    return render_template("change_password.html")


# ---------------------------------------------------------------------------
# SELF-SERVICE ACCOUNT SETTINGS (every role: admin, staff, student)
# ---------------------------------------------------------------------------
ACCOUNT_EDIT_COOLDOWN_DAYS = 30


@app.route("/account", methods=["GET", "POST"])
@login_required
def account_settings():
    user = current_user()

    # Only students have a cooldown, and it applies only to their name.
    # Email and password changes remain available at any time for every role.
    on_name_cooldown = False
    next_name_eligible = None
    if user["role"] == "student" and user["last_name_change"]:
        next_name_eligible = datetime.fromisoformat(user["last_name_change"]) + \
            timedelta(days=ACCOUNT_EDIT_COOLDOWN_DAYS)
        on_name_cooldown = datetime.utcnow() < next_name_eligible

    if request.method == "POST":
        requested_name = request.form.get("name", user["name"]).strip()
        name_change_blocked = (
            on_name_cooldown and requested_name != user["name"]
        )
        # Enforce the student name cooldown on the server, while allowing
        # email/password changes in the same request to continue.
        name = user["name"] if name_change_blocked else requested_name
        email = request.form.get("email", "").strip().lower()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        errors = validate_profile_fields(name, email)

        # Changing the password is optional on this form — only validate
        # those fields at all if the user actually typed a new one.
        wants_password_change = bool(new_password or confirm_password)
        if wants_password_change:
            if not current_password or not verify_password(user, current_password):
                errors.append("Your current password is incorrect.")
            if len(new_password) < 6:
                errors.append("New password must be at least 6 characters.")
            if new_password != confirm_password:
                errors.append("New password and confirmation don't match.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("account_settings.html", form=request.form,
                                   on_name_cooldown=on_name_cooldown,
                                   next_name_eligible=next_name_eligible)

        if not update_own_profile(user["id"], name, email):
            flash("That email is already used by another account.", "error")
            return render_template("account_settings.html", form=request.form,
                                   on_name_cooldown=on_name_cooldown,
                                   next_name_eligible=next_name_eligible)

        if wants_password_change:
            update_password(user["id"], new_password)

        name_was_changed = name != user["name"]
        if user["role"] == "student" and name_was_changed:
            set_last_name_change(user["id"], datetime.utcnow().isoformat())
            next_name_eligible = datetime.utcnow() + timedelta(days=ACCOUNT_EDIT_COOLDOWN_DAYS)

        if name_change_blocked:
            flash(
                "Account changes were saved. Your name was left unchanged; you can "
                f"change it again on {next_name_eligible.strftime('%B %d, %Y')}.",
                "success",
            )
        elif user["role"] == "student" and name_was_changed:
            flash(
                "Account updated. You can change your name again on "
                f"{next_name_eligible.strftime('%B %d, %Y')}.",
                "success",
            )
        else:
            flash(
                "Account updated — your password was also changed." if wants_password_change
                else "Account updated.",
                "success",
            )
        return redirect(url_for("account_settings"))

    return render_template("account_settings.html", form=user,
                           on_name_cooldown=on_name_cooldown,
                           next_name_eligible=next_name_eligible)


# ---------------------------------------------------------------------------
# ERROR HANDLERS
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Page not found."), 404


@app.errorhandler(413)
def too_large(e):
    return render_template(
        "error.html", code=413,
        message="That request was too large. Please shorten your input and try again.",
    ), 413


@app.errorhandler(429)
def rate_limited(e):
    return render_template(
        "error.html", code=429,
        message="Too many attempts — please wait a minute and try again.",
    ), 429


@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", code=500, message="Something went wrong on our end."), 500


if __name__ == "__main__":
    app.run(debug=True)



