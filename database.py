import os
import sqlite3
from abc import ABC, abstractmethod

import psycopg
from psycopg.rows import dict_row
from flask import g

DEFAULT_DATABASE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schoolsync.db")
DATABASE_PATH = os.environ.get("SCHOOLSYNC_DATABASE_PATH", DEFAULT_DATABASE_PATH)
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
POSTGRES = bool(DATABASE_URL)

DATABASE_ERRORS = (sqlite3.Error, psycopg.Error)
INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg.IntegrityError)


def _translate_qmark_placeholders(sql):
    """Translate SQLite-style ? parameters while leaving quoted text intact."""
    output = []
    quote = None
    index = 0
    while index < len(sql):
        char = sql[index]
        if quote:
            output.append(char)
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    output.append(sql[index + 1])
                    index += 1
                else:
                    quote = None
        elif char in ("'", '"'):
            quote = char
            output.append(char)
        elif char == "?":
            output.append("%s")
        else:
            output.append(char)
        index += 1
    return "".join(output)


class DatabaseConnection(ABC):
    """Common interface inherited by the SQLite and PostgreSQL adapters."""

    def __init__(self, raw):
        self.raw = raw

    @property
    @abstractmethod
    def is_postgres(self):
        """Identify the database type for existing application code."""

    @property
    @abstractmethod
    def IntegrityError(self):
        """Return the integrity-error class for this database driver."""

    @property
    @abstractmethod
    def Error(self):
        """Return the general error class for this database driver."""

    @abstractmethod
    def execute(self, sql, params=()):
        """Run one parameterized SQL statement."""

    @abstractmethod
    def executemany(self, sql, params):
        """Run one parameterized SQL statement for multiple rows."""

    @abstractmethod
    def begin_serialized(self, lock_id):
        """Start a transaction protected from concurrent schema setup."""

    @abstractmethod
    def table_columns(self, table):
        """Return the names of columns in a table."""

    def __getattr__(self, name):
        # Keep the rest of each driver's connection API available, including
        # commit(), rollback(), close(), and SQLite's executescript().
        return getattr(self.raw, name)


class SQLiteDatabaseConnection(DatabaseConnection):
    """SQLite implementation of the shared database connection interface."""

    @property
    def is_postgres(self):
        return False

    @property
    def IntegrityError(self):
        return sqlite3.IntegrityError

    @property
    def Error(self):
        return sqlite3.Error

    def execute(self, sql, params=()):
        return self.raw.execute(sql, params)

    def executemany(self, sql, params):
        return self.raw.executemany(sql, params)

    def begin_serialized(self, lock_id):
        self.execute("BEGIN IMMEDIATE")

    def table_columns(self, table):
        rows = self.execute(f"PRAGMA table_info({table})").fetchall()
        return {row["name"] for row in rows}


class PostgresDatabaseConnection(DatabaseConnection):
    """PostgreSQL implementation of the shared database connection interface."""

    @property
    def is_postgres(self):
        return True

    @property
    def IntegrityError(self):
        return psycopg.IntegrityError

    @property
    def Error(self):
        return psycopg.Error

    def execute(self, sql, params=()):
        sql = _translate_qmark_placeholders(sql)
        return self.raw.execute(sql, params)

    def executemany(self, sql, params):
        sql = _translate_qmark_placeholders(sql)
        # psycopg 3 exposes executemany on cursors, not connections.
        cursor = self.raw.cursor()
        cursor.executemany(sql, params)
        return cursor

    def begin_serialized(self, lock_id):
        self.execute("SELECT pg_advisory_xact_lock(?)", (lock_id,))

    def table_columns(self, table):
        rows = self.execute(
            """SELECT column_name AS name FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name = ?""",
            (table,),
        ).fetchall()
        return {row["name"] for row in rows}


def _connect():
    """Open a connection to DATABASE_URL, or local SQLite when unset."""
    if DATABASE_URL:
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        raw = psycopg.connect(url, row_factory=dict_row, connect_timeout=15)
        return PostgresDatabaseConnection(raw)

    parent = os.path.dirname(os.path.abspath(DATABASE_PATH))
    os.makedirs(parent, exist_ok=True)
    raw = sqlite3.connect(DATABASE_PATH, timeout=30)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    raw.execute("PRAGMA busy_timeout = 30000")
    return SQLiteDatabaseConnection(raw)


def get_db():
    """Return this request's connection, opening it on first use."""
    if "db" not in g:
        g.db = _connect()
    return g.db


def close_db(e=None):
    """Close the current request's database connection."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def begin_serialized(db, lock_id=734128):
    """Start a transaction serialized against other startup/recovery workers."""
    db.begin_serialized(lock_id)


def table_columns(conn, table):
    """Return a table's column names on either supported database."""
    return conn.table_columns(table)


def init_db():
    """Reset only a local SQLite database; safely initialize PostgreSQL."""
    db = get_db()
    if db.is_postgres:
        ensure_schema_migrations()
        return
    with open(SCHEMA_PATH, "r", encoding="utf-8") as schema_file:
        db.executescript(schema_file.read())
    db.commit()


def init_app(app):
    """Register request-scoped connection cleanup with Flask."""
    app.teardown_appcontext(close_db)


def _ensure_sqlite_schema(conn):
    """Create SQLite base tables without dropping or overwriting data."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT NOT NULL,
               email TEXT NOT NULL UNIQUE,
               password_hash TEXT NOT NULL,
               role TEXT NOT NULL CHECK (role IN ('admin', 'staff', 'student')),
               created_at TEXT NOT NULL DEFAULT (datetime('now'))
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS events (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               title TEXT NOT NULL,
               date TEXT NOT NULL,
               start_time TEXT NOT NULL,
               end_time TEXT NOT NULL,
               location TEXT NOT NULL,
               description TEXT,
               created_by INTEGER NOT NULL,
               status TEXT NOT NULL DEFAULT 'Pending'
                   CHECK (status IN ('Pending', 'Approved', 'Rejected')),
               created_at TEXT NOT NULL DEFAULT (datetime('now')),
               FOREIGN KEY (created_by) REFERENCES users (id)
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS announcements (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               title TEXT NOT NULL,
               content TEXT NOT NULL,
               posted_by INTEGER NOT NULL,
               created_at TEXT NOT NULL DEFAULT (datetime('now')),
               FOREIGN KEY (posted_by) REFERENCES users (id)
           )"""
    )


def _ensure_postgres_schema(conn):
    """Create the complete PostgreSQL schema idempotently; never drop data."""
    statements = [
        """CREATE TABLE IF NOT EXISTS users (
               id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
               name TEXT NOT NULL,
               email TEXT NOT NULL UNIQUE,
               password_hash TEXT NOT NULL,
               role TEXT NOT NULL CHECK (role IN ('admin', 'staff', 'student')),
               created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
               is_active INTEGER NOT NULL DEFAULT 1,
               last_profile_update TEXT,
               last_name_change TEXT,
               must_change_password INTEGER NOT NULL DEFAULT 0,
               session_version INTEGER NOT NULL DEFAULT 0
           )""",
        """CREATE TABLE IF NOT EXISTS events (
               id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
               title TEXT NOT NULL,
               date TEXT NOT NULL,
               start_time TEXT NOT NULL,
               end_time TEXT NOT NULL,
               location TEXT NOT NULL,
               description TEXT,
               created_by BIGINT NOT NULL REFERENCES users (id),
               status TEXT NOT NULL DEFAULT 'Pending'
                   CHECK (status IN ('Pending', 'Approved', 'Rejected')),
               created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
           )""",
        """CREATE TABLE IF NOT EXISTS announcements (
               id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
               title TEXT NOT NULL,
               content TEXT NOT NULL,
               posted_by BIGINT NOT NULL REFERENCES users (id),
               created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
           )""",
        """CREATE TABLE IF NOT EXISTS audit_log (
               id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
               admin_id BIGINT,
               target_user_id BIGINT,
               action TEXT NOT NULL,
               status TEXT NOT NULL,
               created_at TEXT NOT NULL
           )""",
        """CREATE TABLE IF NOT EXISTS password_resets (
               id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
               user_id BIGINT NOT NULL REFERENCES users (id),
               token_hash TEXT NOT NULL UNIQUE,
               expires_at TEXT NOT NULL,
               used_at TEXT,
               created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
               created_by_admin_id BIGINT NOT NULL REFERENCES users (id)
           )""",
        """CREATE TABLE IF NOT EXISTS audit_logs (
               id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
               actor_id BIGINT NOT NULL REFERENCES users (id),
               target_id BIGINT NOT NULL REFERENCES users (id),
               action TEXT NOT NULL,
               status TEXT NOT NULL,
               created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
           )""",
        """CREATE TABLE IF NOT EXISTS admin_password_recoveries (
               token_hash TEXT PRIMARY KEY,
               admin_email TEXT NOT NULL,
               used_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
           )""",
    ]
    for statement in statements:
        conn.execute(statement)
    conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active INTEGER NOT NULL DEFAULT 1")
    conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_profile_update TEXT")
    conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name_change TEXT")
    conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS session_version INTEGER NOT NULL DEFAULT 0")


def _ensure_sqlite_support_tables(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS audit_log (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               admin_id INTEGER,
               target_user_id INTEGER,
               action TEXT NOT NULL,
               status TEXT NOT NULL,
               created_at TEXT NOT NULL
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS password_resets (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               user_id INTEGER NOT NULL,
               token_hash TEXT NOT NULL UNIQUE,
               expires_at TEXT NOT NULL,
               used_at TEXT,
               created_at TEXT NOT NULL DEFAULT (datetime('now')),
               created_by_admin_id INTEGER NOT NULL,
               FOREIGN KEY (user_id) REFERENCES users (id),
               FOREIGN KEY (created_by_admin_id) REFERENCES users (id)
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS audit_logs (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               actor_id INTEGER NOT NULL,
               target_id INTEGER NOT NULL,
               action TEXT NOT NULL,
               status TEXT NOT NULL,
               created_at TEXT NOT NULL DEFAULT (datetime('now')),
               FOREIGN KEY (actor_id) REFERENCES users (id),
               FOREIGN KEY (target_id) REFERENCES users (id)
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS admin_password_recoveries (
               token_hash TEXT PRIMARY KEY,
               admin_email TEXT NOT NULL,
               used_at TEXT NOT NULL DEFAULT (datetime('now'))
           )"""
    )


def ensure_schema_migrations():
    """Safely create tables and apply additive migrations at startup."""
    conn = _connect()
    try:
        if conn.is_postgres:
            begin_serialized(conn)
            _ensure_postgres_schema(conn)
        else:
            begin_serialized(conn)
            _ensure_sqlite_schema(conn)
            columns = table_columns(conn, "users")
            migrations = {
                "is_active": "INTEGER NOT NULL DEFAULT 1",
                "last_profile_update": "TEXT",
                "last_name_change": "TEXT",
                "must_change_password": "INTEGER NOT NULL DEFAULT 0",
                "session_version": "INTEGER NOT NULL DEFAULT 0",
            }
            for column, definition in migrations.items():
                if column not in columns:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
            _ensure_sqlite_support_tables(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
