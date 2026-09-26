"""
app.py
------
SchoolSync — School Event Calendar and Announcement System.

Built so far: project setup, database, Users table, login/signup/logout,
Events CRUD with the Pending -> Approved/Rejected approval workflow, the
month calendar, and Admin's Manage Accounts page. Announcements are the
one module from the original plan not yet built.

Run with:
    python app.py
Then open http://127.0.0.1:5000
"""

import os
import calendar as cal
from datetime import date as date_cls, datetime

from flask import Flask, render_template, request, redirect, url_for, session, flash

import database
from models import (
    get_user_by_email, get_user_by_id, verify_password, count_users_by_role,
    create_user, get_all_users, delete_user,
)
from events import (
    create_event, get_event_by_id, get_events_by_month, get_events_by_date,
    get_events_by_creator, get_events_by_status, get_upcoming_approved_events,
    get_todays_approved_events, count_all_events, count_events_by_status,
    update_event, set_event_status, delete_event,
    is_visible, filter_visible, can_edit, can_delete, event_time_display,
)
from utils import (
    login_required, role_required, current_user, validate_signup_fields,
    validate_event_fields, ROLE_DASHBOARDS,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-this-before-deploying")

database.init_app(app)  # makes sure the DB connection closes after each request


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


# Lets any template call event_time_display(event) to print "Time to be
# announced" for TBA events instead of a raw "TBA" string.
app.jinja_env.globals["event_time_display"] = event_time_display


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

        session["user_id"] = user["id"]
        flash(f"Welcome back, {user['name']}!", "success")
        return redirect(url_for(ROLE_DASHBOARDS[user["role"]]))

    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
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
    }
    recent_pending = get_events_by_status("Pending")[:5]
    return render_template("dashboard_admin.html", stats=stats, recent_pending=recent_pending)


@app.route("/staff/dashboard")
@role_required("staff")
def staff_dashboard():
    user = current_user()
    my_events = get_events_by_creator(user["id"])
    stats = {
        "pending": sum(1 for e in my_events if e["status"] == "Pending"),
        "approved": sum(1 for e in my_events if e["status"] == "Approved"),
        "rejected": sum(1 for e in my_events if e["status"] == "Rejected"),
    }
    return render_template("dashboard_staff.html", my_events=my_events[:5], stats=stats)


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
    today = date_cls.today()
    year = request.args.get("year", today.year, type=int)
    month = request.args.get("month", today.month, type=int)

    # Roll over cleanly if Prev/Next pushes us past Jan/Dec.
    if month < 1:
        month, year = 12, year - 1
    elif month > 12:
        month, year = 1, year + 1

    user = current_user()
    visible_events = filter_visible(get_events_by_month(year, month), user)

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
    events = filter_visible(get_events_by_date(date_str), user)
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
        # Admin-created events go live immediately — an Admin approving
        # their own submission would be a formality with no real check.
        status = "Approved" if user["role"] == "admin" else "Pending"

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
        can_approve=(user["role"] == "admin" and event["status"] != "Approved"),
        can_reject=(user["role"] == "admin" and event["status"] != "Rejected"),
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

        # If Staff edits a Rejected event, send it back to Pending so an
        # Admin reviews the corrected version.
        if user["role"] == "staff" and event["status"] == "Rejected":
            set_event_status(event_id, "Pending")
            flash("Event updated and resubmitted for approval.", "success")
        else:
            flash("Event updated.", "success")

        return redirect(url_for("event_detail", event_id=event_id))

    return render_template("event_form.html", form=event, mode="edit", event_id=event_id)


@app.route("/events/<int:event_id>/delete", methods=["POST"])
@role_required("admin")
def delete_event_route(event_id):
    event = get_event_by_id(event_id)
    if event is None:
        flash("That event doesn't exist.", "error")
    else:
        delete_event(event_id)
        flash(f"'{event['title']}' was deleted.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/events/<int:event_id>/approve", methods=["POST"])
@role_required("admin")
def approve_event(event_id):
    event = get_event_by_id(event_id)
    if event is None:
        flash("That event doesn't exist.", "error")
    else:
        set_event_status(event_id, "Approved")
        flash(f"'{event['title']}' approved — now visible on the student calendar.", "success")
    return redirect(request.referrer or url_for("admin_dashboard"))


@app.route("/events/<int:event_id>/reject", methods=["POST"])
@role_required("admin")
def reject_event(event_id):
    event = get_event_by_id(event_id)
    if event is None:
        flash("That event doesn't exist.", "error")
    else:
        set_event_status(event_id, "Rejected")
        flash(f"'{event['title']}' rejected.", "success")
    return redirect(request.referrer or url_for("admin_dashboard"))


@app.route("/events/pending")
@role_required("admin")
def pending_events():
    events = get_events_by_status("Pending")
    return render_template("pending_events.html", events=events)


@app.route("/events/mine")
@role_required("staff")
def my_events():
    events = get_events_by_creator(current_user()["id"])
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
        delete_user(user_id)
        if target:
            flash(f"Account '{target['email']}' deleted.", "success")
    return redirect(url_for("manage_accounts"))


# ---------------------------------------------------------------------------
# ERROR HANDLERS
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Page not found."), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", code=500, message="Something went wrong on our end."), 500


if __name__ == "__main__":
    app.run(debug=True)