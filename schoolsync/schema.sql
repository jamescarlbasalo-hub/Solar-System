-- schema.sql
-- --------------------------------------------------------------------
-- This file defines the shape of the database: 3 tables, matching the
-- ERD from the plan. It's applied once by database.py's init_db().
--
-- We create all 3 tables now (even though this step only builds the
-- Users feature) so the database structure is settled early and later
-- steps (Events, Announcements) just start using tables that already
-- exist.
-- --------------------------------------------------------------------

DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS announcements;

CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'staff', 'student')),
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    date        TEXT NOT NULL,      -- stored as 'YYYY-MM-DD'
    start_time  TEXT NOT NULL,      -- stored as 'HH:MM' (24-hour)
    end_time    TEXT NOT NULL,
    location    TEXT NOT NULL,
    description TEXT,
    created_by  INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending', 'Approved', 'Rejected')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (created_by) REFERENCES users (id)
);

CREATE TABLE announcements (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    content    TEXT NOT NULL,
    posted_by  INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (posted_by) REFERENCES users (id)
);
