# SchoolSync — School Event Calendar and Announcement System

A Flask + SQLite school event system with 3 roles, hashed-password login
and signup, a full Events approval workflow, a month calendar, and
Admin account management. Announcements is the one module from the
original plan not yet built.

## 1. Run it locally

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python seed.py        # creates the database + demo accounts + sample events (run once)
python app.py
```

Open **http://127.0.0.1:5000**.

## 2. Demo accounts (created by seed.py)

| Role    | Email                     | Password    |
|---------|---------------------------|-------------|
| Admin   | admin@schoolsync.edu      | admin123    |
| Staff   | staff@schoolsync.edu      | staff123    |
| Student | student@schoolsync.edu    | student123  |

Students can also **sign themselves up** at `/signup` — self-signup
always creates a Student account. Staff and Admin accounts are created
by an Admin from **Manage Accounts**.

`seed.py` also creates 5 sample events: 1 past event, 3 upcoming
Approved events (the Valentine's/Intramurals/Foundation Day examples
from the brief), and 1 Staff-submitted event still **Pending** review —
so you can see the approval queue working immediately.

## 3. What each role can do

| Feature | Admin | Staff | Student |
|---|---|---|---|
| View calendar | ✅ | ✅ | ✅ |
| Create event | ✅ (auto-Approved) | ✅ (goes Pending) | ❌ |
| Edit event | ✅ any | ✅ own, only while Pending/Rejected | ❌ |
| Delete event | ✅ (with confirm) | ❌ | ❌ |
| Approve/Reject | ✅ | ❌ | ❌ |
| See Pending/Rejected events | ✅ all | ✅ own only | ❌ (Approved only) |
| Manage accounts | ✅ | ❌ | ❌ |

## 4. How the approval workflow works

1. Staff submits an event → status = `Pending`.
2. It's invisible to Students, and invisible to other Staff (each Staff
   member only sees their *own* Pending/Rejected events, plus everyone's
   Approved ones).
3. Admin reviews it from **Pending Approvals** (or the event's own page)
   and clicks Approve or Reject.
4. If Approved, it now shows up on everyone's calendar, including Students.
5. If Rejected, Staff can edit and resubmit it — editing a Rejected event
   automatically bumps it back to Pending for another review.

Events created directly by an Admin skip the queue and are Approved
immediately — an Admin approving their own submission would be a
formality with no real check behind it.

## 5. Project structure

```
schoolsync/
├── app.py            # Flask routes: auth, dashboards, calendar, events, accounts
├── database.py       # Opens/closes the SQLite connection per request
├── schema.sql         # users / events / announcements tables
├── models.py           # User functions (create/find/list/delete/verify password)
├── events.py            # Event functions (CRUD + is_visible/can_edit/can_delete rules)
├── utils.py              # login_required / role_required decorators + form validation
├── seed.py                # Run once: builds the DB + demo accounts + sample events
├── requirements.txt
├── templates/               # all pages — see below
└── static/css/style.css     # navy/gold school theme + calendar grid styles
```

**events.py** is where the permission logic actually lives:
`is_visible(event, user)`, `can_edit(event, user)`, and
`can_delete(event, user)` are each one small function, and every route
in `app.py` calls them instead of re-checking roles inline — so the
rule is defined once and enforced everywhere consistently.

## 6. What's still not built

**Announcements** — the last module from the original plan. Same pattern
as Events: a table already exists in `schema.sql`, so building it means
adding `announcements.py` (mirroring `events.py`) and a few templates —
no database changes needed.

Let me know when you're ready and we'll build that next.

