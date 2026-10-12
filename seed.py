"""Initialize SchoolSync safely and add development-only demo content.

This script is safe to run more than once. It never drops or clears tables.
On Render, it skips predictable demo accounts and sample events; the optional
SCHOOLSYNC_ADMIN_* environment variables bootstrap the first administrator.
"""
import os
from datetime import date, timedelta

from app import app
import database
from models import create_user, get_user_by_email
from events import create_event


def create_event_once(title, date_value, start_time, end_time, location, description, creator_id, status):
    db = database.get_db()
    existing = db.execute(
        "SELECT 1 FROM events WHERE title = ? AND created_by = ? LIMIT 1",
        (title, creator_id),
    ).fetchone()
    if existing:
        return False
    create_event(title, date_value, start_time, end_time, location, description, creator_id, status)
    return True


with app.app_context():
    database.ensure_schema_migrations()
    print("Database schema is ready.")

    if os.environ.get("RENDER"):
        print("Render detected; skipping development demo accounts and events.")
        if not os.environ.get("SCHOOLSYNC_ADMIN_EMAIL") or not os.environ.get("SCHOOLSYNC_ADMIN_PASSWORD"):
            print("Set SCHOOLSYNC_ADMIN_EMAIL and SCHOOLSYNC_ADMIN_PASSWORD in Render to create the first admin account.")
    else:
        demo_accounts = [
            ("School Administrator", "admin@schoolsync.edu", "admin123", "admin"),
            ("Mr. Santos (Staff)", "staff@schoolsync.edu", "staff123", "staff"),
            ("Liza Fernandez (Student)", "student@schoolsync.edu", "student123", "student"),
        ]

        for name, email, password, role in demo_accounts:
            if get_user_by_email(email) is None:
                create_user(name, email, password, role)
                print(f"Created demo {role} account: {email}")

        admin = get_user_by_email("admin@schoolsync.edu")
        staff = get_user_by_email("staff@schoolsync.edu")
        today = date.today()

        if admin and staff:
            samples = [
                ("First Day of School Assembly", (today - timedelta(days=14)).isoformat(), "07:30", "09:00", "School Gym", "Welcome assembly for the new school year.", admin["id"], "Approved"),
                ("Valentine's Day Celebration", (today + timedelta(days=30)).isoformat(), "09:00", "15:00", "School Gym", "A celebration for students and staff.", admin["id"], "Approved"),
                ("School Intramurals", (today + timedelta(days=60)).isoformat(), "08:00", "17:00", "School Grounds", "Annual school intramurals.", admin["id"], "Approved"),
                ("School Foundation Day", (today + timedelta(days=90)).isoformat(), "08:00", "12:00", "Main Hall", "School Foundation Day program.", admin["id"], "Approved"),
                ("Student Council Meeting", (today + timedelta(days=10)).isoformat(), "13:00", "14:00", "Room 204", "Monthly student council meeting.", staff["id"], "Pending"),
            ]
            for title, date_value, start, end, location, description, creator_id, status in samples:
                create_event_once(title, date_value, start, end, location, description, creator_id, status)

        print("Development demo data is ready (existing accounts and events were preserved).")