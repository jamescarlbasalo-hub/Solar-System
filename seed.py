"""Seed preset demo accounts and local sample events into Python lists.

The records exist only for the lifetime of this Python process. Running this
script starts a fresh process. The preset demo Staff and Student accounts are
recreated on every app startup, including Render, to support demonstrations.
"""
import os
from datetime import date, timedelta

from events import create_event
from models import create_user, get_user_by_email
from store import store

DEMO_ACCOUNTS = [
    ("Demo Staff", "demo.staff@schoolsync.edu", "DemoStaff2026!", "staff"),
    ("Demo Student", "demo.student@schoolsync.edu", "DemoStudent2026!", "student"),
]


def seed_demo_accounts():
    """Ensure the preset demo Staff and Student exist in this process."""
    for name, email, password, role in DEMO_ACCOUNTS:
        if get_user_by_email(email) is None:
            create_user(name, email, password, role)


def create_event_once(title, date_value, start_time, end_time, location,
                      description, creator_id, status):
    exists = any(event["title"] == title and event["created_by"] == creator_id
                 for event in store.all("events"))
    if exists:
        return False
    create_event(title, date_value, start_time, end_time, location,
                 description, creator_id, status)
    return True


def seed_development_data():
    # These demo accounts are added in every environment. They are useful
    # after a Render restart because all in-memory records start empty.
    seed_demo_accounts()

    # Only the local development app gets the demo Admin and sample events.
    if os.environ.get("RENDER"):
        return
    demo_accounts = [
        ("School Administrator", "admin@schoolsync.edu", "admin123", "admin"),
    ]
    for name, email, password, role in demo_accounts:
        if get_user_by_email(email) is None:
            create_user(name, email, password, role)

    admin = get_user_by_email("admin@schoolsync.edu")
    staff = get_user_by_email("demo.staff@schoolsync.edu")
    today = date.today()
    if admin and staff:
        samples = [
            ("First Day of School Assembly", (today - timedelta(days=14)).isoformat(), "07:30", "09:00", "School Gym", "Welcome assembly for the new school year.", admin["id"], "Approved"),
            ("Valentine's Day Celebration", (today + timedelta(days=30)).isoformat(), "09:00", "15:00", "School Gym", "A celebration for students and staff.", admin["id"], "Approved"),
            ("School Intramurals", (today + timedelta(days=60)).isoformat(), "08:00", "17:00", "School Grounds", "Annual school intramurals.", admin["id"], "Approved"),
            ("Student Council Meeting", (today + timedelta(days=10)).isoformat(), "13:00", "14:00", "Room 204", "Monthly student council meeting.", staff["id"], "Pending"),
        ]
        for title, date_value, start, end, location, description, creator_id, status in samples:
            create_event_once(title, date_value, start, end, location,
                              description, creator_id, status)
    print("Temporary list-backed demo data is ready.")
