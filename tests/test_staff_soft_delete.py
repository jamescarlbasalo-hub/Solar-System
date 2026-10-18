"""Regression coverage for staff soft deletion using an isolated SQLite DB."""

import os
import sqlite3
import unittest
import gc
from datetime import timedelta
from pathlib import Path


_DB_PATH = Path(__file__).parent / ".staff-soft-delete-test.db"
if _DB_PATH.exists():
    _DB_PATH.unlink()

# Start with a pre-migration database containing an existing account. Importing
# app then exercises the same additive startup migration used by local SQLite.
os.environ["SCHOOLSYNC_DATABASE_PATH"] = str(_DB_PATH)
os.environ["DATABASE_URL"] = ""
for _name in (
    "SCHOOLSYNC_ADMIN_EMAIL", "SCHOOLSYNC_ADMIN_PASSWORD", "SCHOOLSYNC_ADMIN_NAME",
    "SCHOOLSYNC_ADMIN_RECOVERY_EMAIL", "SCHOOLSYNC_ADMIN_RECOVERY_PASSWORD",
    "SCHOOLSYNC_ADMIN_RECOVERY_TOKEN",
):
    os.environ.pop(_name, None)

with sqlite3.connect(_DB_PATH) as _legacy_db:
    _legacy_db.execute(
        """CREATE TABLE users (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT NOT NULL,
               email TEXT NOT NULL UNIQUE,
               password_hash TEXT NOT NULL,
               role TEXT NOT NULL,
               created_at TEXT NOT NULL DEFAULT (datetime('now'))
           )"""
    )
    _legacy_db.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
        ("Legacy Staff", "legacy-staff@example.test", "not-a-login-hash", "staff"),
    )

import database
from app import app
from events import create_event, school_today
from models import create_user, delete_user, get_user_by_id
from werkzeug.security import check_password_hash


class StaffSoftDeleteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True)

    def setUp(self):
        with app.app_context():
            db = database.get_db()
            for table in ("audit_logs", "password_resets", "audit_log", "events", "announcements"):
                db.execute(f"DELETE FROM {table}")
            db.execute("DELETE FROM users WHERE email <> ?", ("legacy-staff@example.test",))
            db.commit()
            suffix = os.urandom(6).hex()
            self.admin_id = create_user("Test Admin", f"admin-{suffix}@example.test", "admin-secret", "admin")
            self.other_admin_id = create_user("Other Admin", f"other-admin-{suffix}@example.test", "admin-secret", "admin")
            self.staff_id = create_user("Test Staff", f"staff-{suffix}@example.test", "staff-secret", "staff")
            self.other_staff_id = create_user("Other Staff", f"other-{suffix}@example.test", "staff-secret", "staff")
            self.student_id = create_user("Test Student", f"student-{suffix}@example.test", "student-secret", "student")

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            database.close_db()
        gc.collect()
        if _DB_PATH.exists():
            try:
                _DB_PATH.unlink()
            except PermissionError:
                # Windows/OneDrive scanners can briefly hold the just-closed
                # SQLite file. It is ignored by git and removed next run.
                pass

    def _client_as(self, user_id):
        client = app.test_client()
        with app.app_context():
            user = get_user_by_id(user_id)
            session_version = user["session_version"]
        with client.session_transaction() as session:
            session["user_id"] = user_id
            session["sv"] = session_version
            session["csrf_token"] = "test-csrf-token"
        return client

    def _delete(self, client, user_id):
        return client.post(
            f"/admin/accounts/{user_id}/delete",
            data={"csrf_token": "test-csrf-token"},
            follow_redirects=True,
        )

    def test_additive_migration_preserves_existing_account(self):
        with app.app_context():
            columns = database.table_columns(database.get_db(), "users")
            legacy = database.get_db().execute(
                "SELECT email, deleted_at, is_active FROM users WHERE email = ?",
                ("legacy-staff@example.test",),
            ).fetchone()
        self.assertIn("deleted_at", columns)
        self.assertEqual(legacy["email"], "legacy-staff@example.test")
        self.assertIsNone(legacy["deleted_at"])
        self.assertEqual(legacy["is_active"], 1)

    def test_admin_permanently_deletes_staff_and_preserves_creator_and_event_history(self):
        event_date = (school_today() + timedelta(days=10)).isoformat()
        expected = {"Approved Event": "Approved", "Pending Event": "Pending", "Rejected Event": "Rejected"}
        with app.app_context():
            for title, status in expected.items():
                create_event(title, event_date, "09:00", "10:00", "Hall", "Details", self.staff_id, status)
        response = self._delete(self._client_as(self.admin_id), self.staff_id)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"permanently deleted", response.data)

        with app.app_context():
            staff = get_user_by_id(self.staff_id)
            rows = database.get_db().execute(
                "SELECT title, status, created_by, created_by_name, created_by_role "
                "FROM events WHERE created_by_name = ? ORDER BY title",
                ("Test Staff",),
            ).fetchall()

        self.assertIsNone(staff)
        self.assertEqual({row["title"]: row["status"] for row in rows}, expected)
        self.assertTrue(all(row["created_by"] is None for row in rows))
        self.assertTrue(all(row["created_by_role"] == "staff" for row in rows))

    def test_deleted_staff_cannot_log_in_and_old_session_is_revoked(self):
        with app.app_context():
            staff = get_user_by_id(self.staff_id)
            password_hash = staff["password_hash"]
        staff_client = self._client_as(self.staff_id)

        self._delete(self._client_as(self.admin_id), self.staff_id)

        protected = staff_client.get("/staff/dashboard")
        self.assertEqual(protected.status_code, 302)
        self.assertTrue(protected.headers["Location"].endswith("/login"))

        login_client = app.test_client()
        login_client.get("/login")
        with login_client.session_transaction() as session:
            csrf = session["csrf_token"]
        login = login_client.post(
            "/login",
            data={"email": staff["email"], "password": "staff-secret", "csrf_token": csrf},
        )
        self.assertEqual(login.status_code, 200)
        self.assertIn(b"Invalid email or password", login.data)
        self.assertTrue(check_password_hash(password_hash, "staff-secret"))

    def test_admin_can_review_pending_and_students_still_see_approved_event(self):
        future = (school_today() + timedelta(days=3)).isoformat()
        with app.app_context():
            create_event("Visible Approved", future, "09:00", "10:00", "Hall", "", self.staff_id, "Approved")
            create_event("Review Pending", future, "11:00", "12:00", "Hall", "", self.staff_id, "Pending")
        self._delete(self._client_as(self.admin_id), self.staff_id)

        admin_page = self._client_as(self.admin_id).get("/events/pending")
        student_page = self._client_as(self.student_id).get("/student/dashboard")
        self.assertEqual(admin_page.status_code, 200)
        self.assertIn(b"Review Pending", admin_page.data)
        self.assertEqual(student_page.status_code, 200)
        self.assertIn(b"Visible Approved", student_page.data)

    def test_deleted_staff_is_removed_from_accounts_and_archive(self):
        admin = self._client_as(self.admin_id)
        self._delete(admin, self.staff_id)
        listing = admin.get("/admin/accounts")
        html = listing.data.decode("utf-8")
        self.assertNotIn("Deleted staff accounts", html)
        self.assertNotIn("Test Staff", html)
        self.assertIn("permanently deleted", html)
        with app.app_context():
            self.assertIsNone(get_user_by_id(self.staff_id))

    def test_repeat_delete_reports_missing_account_without_side_effects(self):
        admin = self._client_as(self.admin_id)
        self._delete(admin, self.staff_id)
        response = self._delete(admin, self.staff_id)
        self.assertIn(b"no longer exists", response.data)
        with app.app_context():
            self.assertIsNone(get_user_by_id(self.staff_id))

    def test_non_admin_and_non_staff_targets_are_rejected(self):
        staff_response = self._delete(self._client_as(self.other_staff_id), self.staff_id)
        student_response = self._delete(self._client_as(self.student_id), self.staff_id)
        admin_target_response = self._delete(self._client_as(self.admin_id), self.other_admin_id)
        self.assertEqual(staff_response.status_code, 200)
        self.assertEqual(student_response.status_code, 200)
        self.assertEqual(admin_target_response.status_code, 200)
        with app.app_context():
            self.assertEqual(get_user_by_id(self.staff_id)["is_active"], 1)
            self.assertEqual(get_user_by_id(self.other_admin_id)["is_active"], 1)

    def test_delete_error_rolls_back_account_and_event_reference_changes(self):
        with app.app_context():
            db = database.get_db()
            create_event("Still Linked", (school_today() + timedelta(days=2)).isoformat(),
                         "09:00", "10:00", "Hall", "", self.staff_id, "Approved")
            db.execute(
                """CREATE TRIGGER fail_account_delete BEFORE DELETE ON users
                   WHEN OLD.id = %d
                   BEGIN SELECT RAISE(ABORT, 'simulated delete failure'); END""" % self.staff_id
            )
            db.commit()
            with self.assertRaises(database.sqlite3.IntegrityError):
                delete_user(self.staff_id)
            staff = get_user_by_id(self.staff_id)
            event = db.execute("SELECT created_by FROM events WHERE title = 'Still Linked'").fetchone()
            db.execute("DROP TRIGGER fail_account_delete")
            db.commit()
        self.assertIsNotNone(staff)
        self.assertEqual(event["created_by"], self.staff_id)


if __name__ == "__main__":
    unittest.main()
