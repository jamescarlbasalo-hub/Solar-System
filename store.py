"""Temporary in-memory storage for SchoolSync.

The project requirements specify Python lists rather than a database. This
store keeps each record as a dictionary inside an encapsulated collection.
All records are lost when this Python process stops or restarts.
"""
from copy import deepcopy
from datetime import datetime, timezone


class InMemoryStore:
    """Encapsulate the app's Python-list collections and CRUD operations."""

    def __init__(self):
        self.__collections = {
            "users": [],
            "events": [],
            "announcements": [],
            "password_resets": [],
            "audit_log": [],
            "audit_logs": [],
            "admin_password_recoveries": [],
            "account_password_notices": [],
        }
        self.__next_ids = {name: 1 for name in self.__collections}

    def all(self, collection):
        return deepcopy(self.__collection(collection))

    def get(self, collection, record_id):
        record = next((row for row in self.__collection(collection)
                       if row.get("id") == record_id), None)
        return deepcopy(record) if record is not None else None

    def add(self, collection, record):
        rows = self.__collection(collection)
        saved = deepcopy(record)
        if "id" not in saved:
            saved["id"] = self.__next_ids[collection]
            self.__next_ids[collection] += 1
        elif isinstance(saved["id"], int):
            self.__next_ids[collection] = max(self.__next_ids[collection], saved["id"] + 1)
        rows.append(saved)
        return deepcopy(saved)

    def update(self, collection, record_id, changes):
        for row in self.__collection(collection):
            if row.get("id") == record_id:
                row.update(deepcopy(changes))
                return deepcopy(row)
        return None

    def remove(self, collection, record_id):
        rows = self.__collection(collection)
        for index, row in enumerate(rows):
            if row.get("id") == record_id:
                return deepcopy(rows.pop(index))
        return None

    def remove_where(self, collection, predicate):
        rows = self.__collection(collection)
        removed = []
        remaining = []
        for row in rows:
            (removed if predicate(deepcopy(row)) else remaining).append(row)
        self.__collections[collection] = remaining
        return deepcopy(removed)

    def update_where(self, collection, predicate, changes):
        count = 0
        for row in self.__collection(collection):
            if predicate(deepcopy(row)):
                row.update(deepcopy(changes))
                count += 1
        return count

    def clear(self):
        """Clear temporary records; useful when restarting a demonstration."""
        for name in self.__collections:
            self.__collections[name].clear()
            self.__next_ids[name] = 1

    def __collection(self, name):
        if name not in self.__collections:
            raise KeyError(f"Unknown SchoolSync collection: {name}")
        return self.__collections[name]


store = InMemoryStore()


def timestamp_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
