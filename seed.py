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

    # A past event
    past_date = (today - timedelta(days=14)).isoformat()
    create_event(
        "First Day of School Assembly", past_date, "07:30", "09:00",
        "School Gym", "Welcome assembly for the new school year.",
        admin["id"], "Approved",
    )

    # Future Approved events
    future_examples = [
        (30, "09:00", "15:00", "School Gym", "Valentine's-style celebration for students and staff."),
        (60, "08:00", "17:00", "School Grounds", "Annual school intramurals — all classes participate."),
        (90, "08:00", "12:00", "Main Hall", "School Foundation Day program and recognition rites."),
    ]
    titles = ["Valentine's Day Celebration", "School Intramurals", "School Foundation Day"]
    for (days_ahead, start, end, location, desc), title in zip(future_examples, titles):
        event_date = (today + timedelta(days=days_ahead)).isoformat()
        create_event(title, event_date, start, end, location, desc, admin["id"], "Approved")

    # A Staff-submitted event still waiting for review
    pending_date = (today + timedelta(days=10)).isoformat()
    create_event(
        "Student Council Meeting", pending_date, "13:00", "14:00",
        "Room 204", "Monthly student council meeting — open to all officers.",
        staff["id"], "Pending",
    )

    print("Sample events created.")

    # -------------------------------------------------------------------------
    # AUTOMATIC DATABASE TABLE SETUP
    # -------------------------------------------------------------------------
    db = database.get_db()
    db.execute("""
    CREATE TABLE IF NOT EXISTS password_resets (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id             INTEGER NOT NULL,
        token_hash          TEXT NOT NULL UNIQUE,
        expires_at          TEXT NOT NULL,
        used_at             TEXT,
        created_at          TEXT NOT NULL DEFAULT (datetime('now')),
        created_by_admin_id INTEGER NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (created_by_admin_id) REFERENCES users (id)
    );
    """)
    db.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_id    INTEGER NOT NULL,
        target_id   INTEGER NOT NULL,
        action      TEXT NOT NULL,
        status      TEXT NOT NULL,
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (actor_id) REFERENCES users (id),
        FOREIGN KEY (target_id) REFERENCES users (id)
    );
    """)
    db.commit()
    print("Successfully initialized password_resets and audit_logs tables!")
