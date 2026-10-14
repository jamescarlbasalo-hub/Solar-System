import argparse
from getpass import getpass
import os
import sqlite3
import sys

import database

TABLES_IN_COPY_ORDER = (
    "users",
    "events",
    "announcements",
    "audit_log",
    "password_resets",
    "audit_logs",
    "admin_password_recoveries",
)
IDENTITY_TABLES = (
    "users",
    "events",
    "announcements",
    "audit_log",
    "password_resets",
    "audit_logs",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "sqlite_file",
        nargs="?",
        default="schoolsync-backup-20261012.db",
        help="SQLite file to copy (defaults to the dated backup made earlier)",
    )
    args = parser.parse_args()

    if not database.POSTGRES:
        url = getpass("Paste the Render Postgres EXTERNAL URL (input is hidden): ").strip()
        if not url:
            raise SystemExit("No database URL entered; no data was copied.")
        database.DATABASE_URL = url
        database.POSTGRES = True
    if not os.path.isfile(args.sqlite_file):
        raise SystemExit(f"SQLite source file not found: {args.sqlite_file}")

    source = sqlite3.connect(f"file:{os.path.abspath(args.sqlite_file)}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    destination = None
    try:
        database.ensure_schema_migrations()
        destination = database._connect()

        # Refuse to merge blindly or overwrite a database that already has data.
        existing = {}
        for table in TABLES_IN_COPY_ORDER:
            row = destination.execute(f"SELECT COUNT(*) AS total FROM {table}").fetchone()
            existing[table] = row["total"]
        populated = {table: count for table, count in existing.items() if count}
        if populated:
            raise RuntimeError(
                "Destination database is not empty; no rows were copied. "
                f"Existing row counts: {populated}"
            )

        source_tables = {
            row["name"]
            for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        copied = {}
        for table in TABLES_IN_COPY_ORDER:
            if table not in source_tables:
                copied[table] = 0
                continue

            source_columns = [
                row["name"] for row in source.execute(f"PRAGMA table_info({table})").fetchall()
            ]
            target_columns = database.table_columns(destination, table)
            columns = [column for column in source_columns if column in target_columns]
            if not columns:
                copied[table] = 0
                continue

            rows = source.execute(
                f"SELECT {', '.join(columns)} FROM {table} ORDER BY rowid"
            ).fetchall()
            if rows:
                column_sql = ", ".join(columns)
                placeholders = ", ".join("?" for _ in columns)
                sql = f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})"
                values = [tuple(row[column] for column in columns) for row in rows]
                destination.executemany(sql, values)
            copied[table] = len(rows)

        # Explicitly copied IDs must advance PostgreSQL identity sequences.
        for table in IDENTITY_TABLES:
            destination.execute(
                f"""SELECT setval(
                         pg_get_serial_sequence('{table}', 'id'),
                         COALESCE(MAX(id), 1),
                         MAX(id) IS NOT NULL
                     ) FROM {table}"""
            )

        destination.commit()
        print("Migration completed. Rows copied:")
        for table, count in copied.items():
            print(f"  {table}: {count}")
        print("The SQLite source was opened read-only and was not changed.")
    except Exception:
        if destination is not None:
            destination.rollback()
        raise
    finally:
        source.close()
        if destination is not None:
            destination.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
