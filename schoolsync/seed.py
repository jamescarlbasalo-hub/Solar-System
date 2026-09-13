"""
seed.py
-------
Run this ONCE to create schoolsync.db, add 3 demo accounts (one per
role), and a few sample events so the calendar has something to show
right away.

    python seed.py

Re-running it wipes and recreates the database from scratch (schema.sql
starts with DROP TABLE IF EXISTS) — handy while developing, but don't
run it again on a live system once real data exists!
"""

from datetime import date, timedelta

from app import app
import database
from models import create_user, get_user_by_email
from events import create_event

with app.app_context():
    database.init_db()
    print("Database schema created.")

    demo_accounts = [
        ("School Administrator", "admin@schoolsync.edu", "admin123", "admin"),
        ("Mr. Santos (Staff)", "staff@schoolsync.edu", "staff123", "staff"),
        ("Liza Fernandez (Student)", "student@schoolsync.edu", "student123", "student"),
    ]

    for name, email, password, role in demo_accounts:
        user_id = create_user(name, email, password, role)
        if user_id:
            print(f"  Created {role}: {email}")
        else:
            print(f"  Skipped {email} (already exists)")

    admin = get_user_by_email("admin@schoolsync.edu")
    staff = get_user_by_email("staff@schoolsync.edu")
    today = date.today()

    # A past event, so "keep past events" is demonstrable immediately.
    past_date = (today - timedelta(days=14)).isoformat()
    create_event(
        "First Day of School Assembly", past_date, "07:30", "09:00",
        "School Gym", "Welcome assembly for the new school year.",
        admin["id"], "Approved",
    )

    # A handful of future Approved events (admin-created, from the brief's examples)
    future_examples = [
        (30, "09:00", "15:00", "School Gym", "Valentine's-style celebration for students and staff."),
        (60, "08:00", "17:00", "School Grounds", "Annual school intramurals — all classes participate."),
        (90, "08:00", "12:00", "Main Hall", "School Foundation Day program and recognition rites."),
    ]
    titles = ["Valentine's Day Celebration", "School Intramurals", "School Foundation Day"]
    for (days_ahead, start, end, location, desc), title in zip(future_examples, titles):
        event_date = (today + timedelta(days=days_ahead)).isoformat()
        create_event(title, event_date, start, end, location, desc, admin["id"], "Approved")

    # A Staff-submitted event still waiting for review — demonstrates the
    # approval queue immediately after seeding.
    pending_date = (today + timedelta(days=10)).isoformat()
    create_event(
        "Student Council Meeting", pending_date, "13:00", "14:00",
        "Room 204", "Monthly student council meeting — open to all officers.",
        staff["id"], "Pending",
    )

    print("Sample events created (1 past, 3 upcoming approved, 1 pending review).")
    print("\nDone! You can now log in with any of the accounts above.")
