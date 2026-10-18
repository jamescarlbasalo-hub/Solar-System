# SchoolSync — School Event Calendar and Announcement System

SchoolSync is a Flask web app for school events with Admin, Staff, and Student
roles. Per the project assignment, app records are held in Python lists in
memory; this project does not connect to a database.

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000**. Local development starts with sample accounts
and events so you can demonstrate each role. Demo passwords are for local
demonstration only; never use them as personal passwords.

| Role | Email | Demo password |
|---|---|---|
| Admin | admin@schoolsync.edu | admin123 |
| Staff | staff@schoolsync.edu | staff123 |
| Student | student@schoolsync.edu | student123 |

Students can sign up at `/signup`; self-signup only creates Student accounts.
Admins create Staff and Admin accounts from Manage Accounts.

## Role features

| Feature | Admin | Staff | Student |
|---|---|---|---|
| View approved calendar | Yes | Yes | Yes |
| Create event | Published immediately | Submitted for review | No |
| Manage events | All events | Staff/Admin-submitted events | Approved events only |
| Approve or reject | Yes | No | No |
| Manage accounts | Yes | No | No |

## Event approval flow

1. Staff creates an event. It starts as Pending and is not shown to Students.
2. Admin reviews it and approves or rejects it.
3. Approved events appear on the calendar and student dashboard.
4. Editing an event does not silently change its review status.

## Project structure

```text
app.py          Flask routes, login, role dashboards, event and account actions
store.py        Encapsulated in-memory Python list collections and CRUD methods
models.py       User account creation, lookup, update, removal and password logic
events.py       Event CRUD, filtering and role-based permissions
auth_reset.py   In-memory password reset token helpers
utils.py        Flask decorators, CSRF, validation and password helpers
seed.py         Development sample accounts and events, initialized in app process
requirements.txt
templates/      HTML pages
static/         CSS and images
```

`store.py` defines an `InMemoryStore` class. It keeps lists of dictionaries for
users, events, announcements, reset tokens, and audit records. Its methods
provide add, retrieve, update, and remove operations. `models.py` and `events.py`
use these methods, so Flask routes and templates retain the same flow without
issuing SQL.

## Important temporary-storage limitation

All records exist only in the Python process's memory. They are cleared when
the process restarts, crashes, sleeps, or is redeployed. On a multi-worker web
service, each worker has its own separate lists, so users may see different
records depending on which worker handles a request. This is an expected
limitation of the assignment, but it makes the deployed service unsuitable for
reliable long-term use.

Existing records in the old local SQLite file or Render PostgreSQL service are
not loaded by this version. The old database files and cloud service are not
modified by this code change. The deployed Render web service will use lists
after you push and deploy this version; the separate Render database remains
separate until you choose to remove it in Render.

## Render deployment

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Set `SECRET_KEY` to a long random value.
- Set `SCHOOLSYNC_ADMIN_EMAIL` and `SCHOOLSYNC_ADMIN_PASSWORD` to initialize
  the Admin account in the running process. Optionally set
  `SCHOOLSYNC_ADMIN_NAME`.
- `DATABASE_URL` is not used by this version.

Announcements are reserved in the in-memory store but are not yet implemented
as a user-facing feature.
